"""管理端路由 —— 线下人工充值模式下的运营入口。

背景
----
线上支付已下线(网站备案 / ICP 许可证未落地),商业闭环改为:
  用户加产品方微信 → 人工收款 → 产品方签发注册码 → 用户填入客户端同步云端。

这条链路上产品方需要**随时调整账户状态**,而不必每次都重新签发注册码:
  - 客户加购积分 → 直接给账户加积分(不用重发码);
  - 客户投诉/纠错 → 直接扣回积分;
  - 客户续费 → 直接延长订阅到期时间。

所以这里提供三个管理员端点,鉴权用 `X-Admin-Token` header + `CLOUD_ADMIN_TOKEN`
环境变量(常量时间比较,与既有 `POST /cloud/points/refund` 同一套路)。

⚠️ 安全边界
-----------
- `CLOUD_ADMIN_TOKEN` **不配置则全部端点 503**(fail-closed,不是 fail-open);
- token 用 `hmac.compare_digest` 比较,避免时序侧信道;
- 所有积分变动都写 `credit_ledger` 流水,留痕可审计。
"""

from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.models import User
from ..db import get_db
from .models import Subscription
from .points import get_account, recharge_credit, refund_credit


router = APIRouter()


_ZERO = Decimal("0")


def _dec(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _require_admin_token(x_admin_token: str) -> None:
    """校验管理员 token。**未配置则 503**(fail-closed)。"""
    expected = (os.getenv("CLOUD_ADMIN_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin token not configured (CLOUD_ADMIN_TOKEN)",
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=403, detail="invalid admin token")


def _get_user(db: Session, user_id: int) -> User:
    user = db.execute(
        select(User).where(User.id == user_id)
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
    return user


# ──────────────────────────────────────────────────────────────
# 用户查询
# ──────────────────────────────────────────────────────────────


@router.get("/admin/users")
def admin_list_users(
    q: Optional[str] = Query(default=None, description="按用户名/邮箱模糊匹配"),
    limit: int = Query(default=50, ge=1, le=200),
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """列出用户(便于运营按用户名/邮箱找到 user_id 再充值)。"""
    _require_admin_token(x_admin_token)

    stmt = select(User).order_by(User.id.desc()).limit(limit)
    if q:
        like = f"%{q}%"
        stmt = select(User).where(
            User.username.like(like) | User.email.like(like)
        ).order_by(User.id.desc()).limit(limit)

    users = db.execute(stmt).scalars().all()
    items = []
    for u in users:
        acct = get_account(db, u.id)
        sub = db.execute(
            select(Subscription).where(Subscription.user_id == u.id)
        ).scalar_one_or_none()
        items.append({
            **u.to_dict(),
            "availablePoints": acct["availablePoints"],
            "plan": sub.plan if sub else "free",
            "expireAt": sub.expire_at.isoformat() if sub and sub.expire_at else None,
        })
    return {"items": items, "count": len(items)}


# ──────────────────────────────────────────────────────────────
# 积分调整
# ──────────────────────────────────────────────────────────────


@router.post("/admin/points/adjust")
def admin_adjust_points(
    payload: dict,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """人工调整账户积分(**可加可减可设定**)。

    请求体:
      - `user_id`: 目标用户 id(必填)
      - `mode`: `add`(默认,按 delta 增减) | `set`(设为指定余额)
      - `amount`: `add` 模式下是增量(可正可负);`set` 模式下是目标余额
      - `note`: 备注(会写进积分流水,建议写明原因,如「微信充值 3000 积分」)

    语义:
      - `add` 且 amount > 0 → 走 `recharge_credit`(记为充值);
      - `add` 且 amount < 0 → 走 `refund_credit`(记为扣回);
      - `set` → 自动换算成差额后按上面两条走。

    每次调整都会写 `credit_ledger` 流水(`recharge_id` 形如 `admin-<时间戳>`),
    保证可审计、可追溯。
    """
    _require_admin_token(x_admin_token)

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="user_id must be an integer")

    mode = str(payload.get("mode") or "add").lower()
    if mode not in {"add", "set"}:
        raise HTTPException(status_code=422, detail="mode must be 'add' or 'set'")

    if "amount" not in payload or payload.get("amount") is None:
        raise HTTPException(status_code=422, detail="amount is required")
    try:
        amount = _dec(payload["amount"])
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="amount must be a number")

    note = str(payload.get("note") or "").strip() or "manual adjustment"

    user = _get_user(db, user_id)
    acct_before = get_account(db, user_id)
    current = _dec(acct_before["availablePoints"])

    if mode == "set":
        delta = amount - current
    else:
        delta = amount

    if delta == _ZERO:
        return {
            "ok": True,
            "changed": False,
            "userId": user_id,
            "username": user.username,
            "delta": 0,
            "points": acct_before,
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    recharge_id = f"admin-{stamp}"

    if delta > _ZERO:
        recharge_credit(
            db, user_id, points=delta, recharge_id=recharge_id, note=note,
        )
    else:
        refund_credit(
            db,
            user_id,
            amount=-delta,
            recharge_id=recharge_id,
            note=note,
        )

    acct_after = get_account(db, user_id)
    return {
        "ok": True,
        "changed": True,
        "userId": user_id,
        "username": user.username,
        "delta": float(delta),
        "rechargeId": recharge_id,
        "pointsBefore": acct_before,
        "points": acct_after,
    }


# ──────────────────────────────────────────────────────────────
# 订阅调整
# ──────────────────────────────────────────────────────────────


@router.post("/admin/subscription/extend")
def admin_extend_subscription(
    payload: dict,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """人工开通 / 延长用户订阅。

    请求体:
      - `user_id`: 目标用户 id(必填)
      - `days`: 从**当前到期时间**(或现在)起延长的天数;负数表示缩短(不推荐)
      - `plan`: `pro`(默认) | `free`
      - `note`: 备注

    说明:正常路径是用户用注册码开通(`POST /cloud/license/activate`),
    这里用于「客服补偿」「线下单独开通」等不需要重发注册码的场景。
    """
    _require_admin_token(x_admin_token)

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=422, detail="user_id is required")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="user_id must be an integer")

    try:
        days = int(payload.get("days", 30))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="days must be an integer")
    if not (-365 <= days <= 730):
        raise HTTPException(status_code=422, detail="days out of range: -365..730")

    plan = str(payload.get("plan") or "pro").lower()
    if plan not in {"pro", "free"}:
        raise HTTPException(status_code=422, detail="plan must be 'pro' or 'free'")

    user = _get_user(db, user_id)

    sub = db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if sub is None:
        sub = Subscription(
            user_id=user_id,
            plan=plan,
            status="active",
            quota=-1 if plan == "pro" else 0,
            expire_at=None if plan == "free" else now + timedelta(days=days),
        )
        db.add(sub)
    else:
        current = sub.expire_at
        if current is not None and current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        base = current if (current is not None and current > now) else now
        sub.plan = plan
        sub.status = "active"
        sub.quota = -1 if plan == "pro" else 0
        if plan != "free":
            sub.expire_at = base + timedelta(days=days)

    db.commit()
    db.refresh(sub)

    return {
        "ok": True,
        "userId": user_id,
        "username": user.username,
        "subscription": sub.to_dict(),
    }


__all__ = ["router"]
