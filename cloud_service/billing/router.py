"""Billing 端点(C13)。

前缀:`/cloud`(在 `main.py` 中挂载)。
端点:
  GET  /cloud/subscription           → 当前订阅 + 用量(懒创建 free 订阅)
  POST /cloud/usage/consume          → 消耗额度;超限返回 402
  POST /cloud/license/verify         → 客户端心跳:订阅有效性 + 剩余额度 + is_pro
  POST /cloud/subscription/activate  → 模拟激活 pro(供 C19 支付接入前使用)

复用:
  - `..db.get_db`(SQLAlchemy session)
  - `..auth.router.get_current_user`(C12 的 JWT 依赖)
  - `..settings.get_settings()["billing"]`(额度可配)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.models import User
from ..auth.router import get_current_user  # C12 的 JWT 依赖(复用,不重造)
from ..db import get_db
from ..settings import get_settings
from .models import Subscription, Usage
from .schemas import (
    ConsumeRequest,
    ConsumeResponse,
    LicenseVerifyResponse,
    SubscriptionActivateRequest,
    SubscriptionResponse,
)

router = APIRouter()


# ──────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────

def _plan_quota(plan: str) -> int:
    billing = get_settings()["billing"]
    return int(billing.get("pro_quota", billing["free_quota"])) if plan == "pro" else int(
        billing["free_quota"]
    )


def _current_period(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _get_or_create_subscription(db: Session, user: User) -> Subscription:
    """获取当前订阅;不存在时懒创建 free 订阅(首次调用 `GET /subscription` 或 `consume`)。"""
    sub = db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    ).scalar_one_or_none()
    if sub is None:
        sub = Subscription(
            user_id=user.id,
            plan="free",
            status="active",
            quota=_plan_quota("free"),
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
    return sub


def activate_for_user(db: Session, user: User, plan: str, days: int) -> Subscription:
    """按 plan/days 激活(或续订)指定用户的订阅。

    语义与 `POST /cloud/subscription/activate` 端点一致,提取为函数以便
    C19 支付回调路径调用(回调时无 JWT,拿不到 current_user Depends)。

    行为:
      - plan='pro' : quota=pro_quota, expire_at = now + days, status='active',
                     本月 usage.used 清零(新额度周期)
      - plan='free': quota=free_quota, expire_at=None, status='active'

    **幂等提示**:本函数不判断"重复激活",调用方(如 C19 支付回调)
    应通过订单表 status 自行保证"同订单不重复激活"。
    """
    if plan not in {"pro", "free"}:
        raise ValueError(f"unsupported plan: {plan}")
    if not (1 <= days <= 730):
        raise ValueError(f"days out of range: {days}")

    sub = _get_or_create_subscription(db, user)
    sub.plan = plan
    sub.quota = _plan_quota(plan)
    if plan == "pro":
        sub.expire_at = datetime.now(timezone.utc) + timedelta(days=days)
        sub.status = "active"
        # 激活 pro 时清空本月已用额度,给一个"新的额度周期"体验
        period = _current_period()
        usage = db.execute(
            select(Usage).where(Usage.user_id == user.id, Usage.period == period)
        ).scalar_one_or_none()
        if usage is not None:
            usage.used = 0
    else:
        sub.expire_at = None
        sub.status = "active"
    db.commit()
    db.refresh(sub)
    return sub


def _get_usage(db: Session, user_id: int, period: str) -> int:
    row = db.execute(
        select(Usage.used).where(Usage.user_id == user_id, Usage.period == period)
    ).scalar_one_or_none()
    return int(row or 0)


class SubscriptionNotFoundError(LookupError):
    """用户不存在或订阅记录不存在(用于 `cancel_subscription` / `shorten_subscription`)。"""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _tzaware(dt: datetime) -> datetime:
    """SQLite 存回的 DateTime(timezone=True) 可能是 naive;统一补 UTC tzinfo。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def cancel_subscription(
    db: Session,
    user_id: int,
    *,
    reason: str = "",
) -> dict[str, Any]:
    """把指定用户的订阅置为 ``status='cancelled'``(立即失效)。

    语义:
      - **不**修改 ``plan`` / ``quota`` / ``expire_at``;下游 ``verify_license`` 会因
        ``sub.status != 'active'`` 判定 ``valid=False``;``consume`` 也会因 ``is_expired()``
        或 ``sub.status`` 分支被拒。
      - **幂等**:订阅已 ``cancelled`` / 已过期 → ``changed=False, reason='already-invalid'``
        (对 ``expire_at`` 保持不变)。
      - **行锁**:用 ``with_for_update()`` 锁住 ``Subscription`` 行,避免并发
        ``activate`` / 退款撤销的竞态覆盖(参考 ``_consume_quota`` / ``_rollback_quota``)。

    参数:
      - ``db``: SQLAlchemy Session。
      - ``user_id``: 用户主键。
      - ``reason``: 操作原因(仅用于响应回显,不落库;Subscription 模型无 audit 字段)。

    返回结构 ``dict[str, Any]``::

        {
          "ok": True,
          "changed": True/False,       # False 表示幂等 no-op
          "reason": "cancelled" | "already-invalid",
          "subscription": <_serialize_subscription(sub, used=0)>
        }

    错误:
      - ``SubscriptionNotFoundError``: ``user_id`` 对应用户不存在,或用户从未创建过
        订阅(Subscription 表无对应行)。调用方可映射为 HTTP 404。
    """
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None:
        raise SubscriptionNotFoundError(f"user {user_id} not found")

    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .with_for_update()
        .first()
    )
    if sub is None:
        raise SubscriptionNotFoundError(
            f"subscription for user {user_id} not found"
        )

    # 幂等:已取消 / 已过期 → 不再改字段
    already_invalid = sub.status == "cancelled" or sub.is_expired()
    if already_invalid:
        return {
            "ok": True,
            "changed": False,
            "reason": "already-invalid",
            "subscription": _serialize_subscription(sub, used=0),
        }

    # 只改 status;plan / quota / expire_at 均不动
    sub.status = "cancelled"
    db.commit()
    db.refresh(sub)
    return {
        "ok": True,
        "changed": True,
        "reason": "cancelled",
        "subscription": _serialize_subscription(sub, used=0),
    }


def shorten_subscription(
    db: Session,
    user_id: int,
    *,
    days_to_revoke: int,
) -> dict[str, Any]:
    """把订阅 ``expire_at`` 前移 ``days_to_revoke`` 天;若前移后已过期 → 等同取消。

    语义:
      - ``days_to_revoke > 0`` 且 ``expire_at`` 存在:
        - ``new_expire_at > now`` → ``expire_at = new_expire_at``(``status`` 不变,
          ``reason='shortened'``);
        - ``new_expire_at <= now`` → ``expire_at = new_expire_at`` 且
          ``status='cancelled'``(``reason='cancelled'``,订阅立即失效)。
      - ``expire_at is None``(如 free 永久订阅):**无法缩短**,返回 no-op
        (``changed=False, reason='no-expire-at'``),不视为错误。
      - ``status='cancelled'`` 或已过期:幂等 no-op(``reason='already-invalid'``)。
      - ``days_to_revoke <= 0``:非法,抛 ``HTTPException(422)``(与现有
        ``amount=0`` / ``plan=enterprise`` 的 422 语义一致,避免调用方误传 0 时被
        静默当 no-op 而没发现 bug)。

    **行锁**:同 ``cancel_subscription``,``with_for_update`` 锁行防止与
    ``activate_for_user`` / 并发退款撤销的竞态。

    返回结构与 ``cancel_subscription`` 一致;``reason`` 取值范围:
    ``shortened`` / ``cancelled`` / ``already-invalid`` / ``no-expire-at``。

    错误:
      - ``HTTPException(422)``: ``days_to_revoke <= 0``。
      - ``SubscriptionNotFoundError``: 用户或订阅不存在。
    """
    if days_to_revoke <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"days_to_revoke must be > 0, got {days_to_revoke}",
        )

    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None:
        raise SubscriptionNotFoundError(f"user {user_id} not found")

    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .with_for_update()
        .first()
    )
    if sub is None:
        raise SubscriptionNotFoundError(
            f"subscription for user {user_id} not found"
        )

    # 幂等:已取消 / 已过期 → 不动
    already_invalid = sub.status == "cancelled" or sub.is_expired()
    if already_invalid:
        return {
            "ok": True,
            "changed": False,
            "reason": "already-invalid",
            "subscription": _serialize_subscription(sub, used=0),
        }

    # 无 expire_at(通常是 free 永久订阅)→ 无法缩短,视为 no-op
    if sub.expire_at is None:
        return {
            "ok": True,
            "changed": False,
            "reason": "no-expire-at",
            "subscription": _serialize_subscription(sub, used=0),
        }

    now = _now_utc()
    exp = _tzaware(sub.expire_at)
    new_exp = exp - timedelta(days=days_to_revoke)

    if new_exp <= now:
        # 前移后已过期 → 等同取消:expire_at 前移 + status='cancelled'
        sub.expire_at = new_exp
        sub.status = "cancelled"
        db.commit()
        db.refresh(sub)
        return {
            "ok": True,
            "changed": True,
            "reason": "cancelled",
            "subscription": _serialize_subscription(sub, used=0),
        }

    sub.expire_at = new_exp
    db.commit()
    db.refresh(sub)
    return {
        "ok": True,
        "changed": True,
        "reason": "shortened",
        "subscription": _serialize_subscription(sub, used=0),
    }


def _consume_quota(db: Session, user: User, sub: Subscription, amount: int, period: str) -> int:
    """原子累加用量并校验上限。

    超限抛 HTTPException(402);成功后返回更新后的 used。
    用 `with_for_update` 锁住 usage 行,防止并发覆盖。
    """
    usage = (
        db.query(Usage)
        .filter(Usage.user_id == user.id, Usage.period == period)
        .with_for_update()
        .first()
    )
    if usage is None:
        usage = Usage(user_id=user.id, period=period, used=0)
        db.add(usage)
        db.flush()
        usage = (
            db.query(Usage)
            .filter(Usage.user_id == user.id, Usage.period == period)
            .with_for_update()
            .first()
        )

    new_used = int(usage.used or 0) + amount
    if sub.quota != -1 and new_used > sub.quota:
        db.rollback()
        raise HTTPException(
            status_code=402,
            detail=f"quota exceeded: {new_used}/{sub.quota} in {period}",
        )

    usage.used = new_used
    db.commit()
    return new_used


def _rollback_quota(db: Session, user: User, amount: int, period: str) -> int:
    """`_consume_quota` 的对称反向操作:扣回 amount 个额度单位。

    用于流式 LLM 中断场景 —— 预消费额度后,客户端 AbortController/断网 触发
    `GeneratorExit`,绕过 `except Exception`,导致"内容已发但未扣额度"的
    计费漏洞。修复策略是"预消费 + 补偿回滚":在生成器进入前先 consume,
    然后在 `finally` 里根据 `cancelled` 标记调用本函数回滚。

    语义:
      - amount > 0 时执行;amount <= 0 直接 no-op;
      - 用 `with_for_update` 锁住 usage 行,防并发覆盖;
      - 下限截断到 0,不允许出现负数 usage;
      - 事务失败抛 `SQLAlchemyError`(调用方 `finally` 里应 catch 后 log)。
    """
    if amount <= 0:
        return 0
    usage = (
        db.query(Usage)
        .filter(Usage.user_id == user.id, Usage.period == period)
        .with_for_update()
        .first()
    )
    if usage is None:
        # 极端边界:consume 从未落库就触发 rollback —— 无操作
        return 0
    new_used = max(0, int(usage.used or 0) - amount)
    usage.used = new_used
    db.commit()
    return new_used


def _serialize_subscription(sub: Subscription, used: int = 0) -> dict:
    """把 ORM Subscription 序列化为 API 载荷(与 `to_dict` 一致,但集中管理)。"""
    expired = sub.is_expired()
    effective_status = "expired" if expired else sub.status
    return {
        "plan": sub.plan,
        "status": effective_status,
        "expire_at": sub.expire_at.isoformat() if sub.expire_at else None,
        "quota": sub.quota,
        "used": used,
        "remaining": -1 if sub.quota == -1 else max(0, sub.quota - used),
        "is_pro": sub.plan == "pro",
    }


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────

@router.get("/subscription", response_model=SubscriptionResponse)
def get_subscription(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    """返回当前用户订阅状态 + 本月已用量。"""
    sub = _get_or_create_subscription(db, current_user)
    period = _current_period()
    used = _get_usage(db, current_user.id, period)
    return SubscriptionResponse(**_serialize_subscription(sub, used=used))


@router.post("/usage/consume", response_model=ConsumeResponse)
def consume_usage(
    payload: ConsumeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConsumeResponse:
    """消耗额度;超限 402,订阅过期 403。

    典型调用方:LLM 代理(B3)、云端 prompt 服务。
    """
    sub = _get_or_create_subscription(db, current_user)
    period = payload.period or _current_period()

    # 过期订阅不允许消费;free 订阅过期视为永久(实际 free 不会有 expire_at)
    if sub.is_expired():
        raise HTTPException(
            status_code=403,
            detail="subscription expired, please renew",
        )

    used = _consume_quota(db, current_user, sub, payload.amount, period)
    remaining = -1 if sub.quota == -1 else max(0, sub.quota - used)
    return ConsumeResponse(
        ok=True,
        period=period,
        used=used,
        remaining=remaining,
    )


@router.post("/license/verify", response_model=LicenseVerifyResponse)
def verify_license(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LicenseVerifyResponse:
    """客户端心跳:返回订阅有效性 + 剩余额度 + 是否 pro。

    行为:
      - 无订阅记录  → 视为 free 状态(不下架)
      - 订阅已过期 → valid=False, status='expired'
      - 订阅有效   → valid=True, 返回 quota/used/remaining/is_pro
    """
    sub = db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id)
    ).scalar_one_or_none()

    if sub is None:
        # 懒创建 free 订阅,避免每次心跳都返回 no-subscription
        sub = Subscription(
            user_id=current_user.id,
            plan="free",
            status="active",
            quota=_plan_quota("free"),
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)

    period = _current_period()
    used = _get_usage(db, current_user.id, period)
    expired = sub.is_expired()
    if expired:
        valid = False
        reason = "expired"
    elif sub.status != "active":
        valid = False
        reason = sub.status  # cancelled 等
    else:
        valid = True
        reason = "active" if sub.plan == "pro" else "free"

    data = _serialize_subscription(sub, used=used)
    return LicenseVerifyResponse(
        valid=valid,
        reason=reason,
        plan=data["plan"],
        status=data["status"],
        expire_at=data["expire_at"],
        quota=data["quota"],
        used=data["used"],
        remaining=data["remaining"],
        is_pro=data["is_pro"],
    )


@router.post("/subscription/activate", response_model=SubscriptionResponse)
def activate_subscription(
    payload: SubscriptionActivateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubscriptionResponse:
    """模拟激活订阅(仅供开发 / 支付集成前使用)。

    - plan='pro':  quota 取 settings['billing']['pro_quota'](默认无限), expire_at = 现在 + days。
    - plan='free': quota 取 free_quota, expire_at = None(永久)。
    激活 pro 后重置本月用量(避免遗留超量)。
    """
    try:
        sub = activate_for_user(db, current_user, plan=payload.plan, days=payload.days)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    used = _get_usage(db, current_user.id, _current_period())
    return SubscriptionResponse(**_serialize_subscription(sub, used=used))


__all__ = ["router"]
