"""注册码激活 —— 线下人工充值模式下的云端开通入口。

背景
----
线上支付已下线,商业闭环改为「用户加微信 → 人工收款 → 签发注册码 → 用户填进客户端」。
客户端本地验签保证离线可用,但**云端能力**(云端 AI / 云端生图 / 云端 Prompt)需要
云端也认这份注册码,否则 D1=C 双轨交集会把云端侧压回 community 档。

所以本模块提供:用注册码 token 开通/延长该用户的云端订阅,并把注册码里带的
积分额度注入账户积分。

为什么订阅 expire_at 取「到期日 + 宽限期」
------------------------------------------
桌面端的只读切换点是 `expires_at + grace_days`(宽限期满才转只读)。
如果云端订阅只活到 `expires_at`,就会出现**本地还能写、云端已降级**的错位。
两者对齐到同一切换点才自洽。

为什么订阅 plan 直接置 `pro`
--------------------------
细粒度能力由**客户端本地注册码的 entitlements** 决定:云端给整档 pro,
客户端再按本地条目取子集(D1=C 双轨交集)。
这样无需给订阅表新增列存 entitlements,也避免两套授权口径打架。

积分注入为什么幂等
------------------
同一个注册码可以重复同步(用户点几次"同步到云端"、客户端重试)。
以 `license_id` 作为 `credit_ledger.recharge_id` 幂等键,已注入过就不再加。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.models import User
from . import license_verify as _lv
from .models import TX_RECHARGE, CreditLedger, Subscription
from .points import get_account, recharge_credit

logger = logging.getLogger(__name__)


class LicenseActivationError(ValueError):
    """注册码激活失败(验签失败 / 参数非法)。"""


def _license_already_recharged(db: Session, license_id: str) -> bool:
    """该注册码的积分额度是否已经注入过(幂等判定)。"""
    if not license_id:
        return False
    row = db.execute(
        select(CreditLedger.id).where(
            CreditLedger.recharge_id == license_id,
            CreditLedger.tx_type == TX_RECHARGE,
        ).limit(1)
    ).first()
    return row is not None


def _upsert_subscription(
    db: Session,
    user: User,
    *,
    expire_at: datetime,
    quota: int,
) -> Subscription:
    """开通或延长订阅。

    - 已有订阅且到期更晚 → **保留更晚的那个**(注册码不能缩短已购时长);
    - 已到期或不存在 → 按注册码给的期限开通;
    - 月度 LLM 用量**不清零**:注册码激活是「开通/续期」,不是「新的额度周期」,
      清零等于让续费用户白嫖一个月的已用额度。
    """
    sub = db.execute(
        select(Subscription).where(Subscription.user_id == user.id)
    ).scalar_one_or_none()

    if sub is None:
        sub = Subscription(
            user_id=user.id,
            plan="pro",
            status="active",
            quota=quota,
            expire_at=expire_at,
        )
        db.add(sub)
    else:
        current = sub.expire_at
        if current is not None and current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if current is None or expire_at > current:
            sub.expire_at = expire_at
        sub.plan = "pro"
        sub.status = "active"
        sub.quota = quota

    db.commit()
    db.refresh(sub)
    return sub


def activate_with_license(
    db: Session,
    user: User,
    token: str,
    *,
    quota: int = -1,
    now: Optional[datetime] = None,
    public_key_hex: Optional[str] = None,
) -> dict[str, Any]:
    """用注册码开通/延长云端订阅,并注入注册码携带的积分额度。

    参数:
      db: SQLAlchemy session
      user: 当前登录用户
      token: 注册码 token(PRISM1.xxx.yyy)
      quota: 订阅配额(LLM 调用次数);-1 = 无限。默认沿用 settings 的 pro_quota。
      now: 覆盖当前时间(测试用)
      public_key_hex: 验签公钥;默认用模块常量。测试可用临时密钥对。

    返回:激活结果摘要(含注册码声明、订阅状态、积分账户)。
    失败一律抛 `LicenseActivationError`(上层转 400)。
    """
    now = now or datetime.now(timezone.utc)
    try:
        claims = _lv.verify_token(
            token,
            public_key_hex=public_key_hex or _lv.PUBLIC_KEY_HEX,
            now=now,
        )
    except _lv.LicenseVerifyError as exc:
        raise LicenseActivationError(str(exc)) from exc

    # ── 1. 订阅 ──────────────────────────────────────────────
    sub = _upsert_subscription(
        db, user, expire_at=claims.effective_until, quota=quota
    )

    # ── 2. 积分额度(幂等) ────────────────────────────────────
    credits_added = 0
    credits_skipped = False
    if claims.credits > 0:
        if _license_already_recharged(db, claims.license_id):
            credits_skipped = True
        else:
            recharge_credit(
                db,
                user.id,
                points=claims.credits,
                recharge_id=claims.license_id,
                note=f"license {claims.license_id} credits",
            )
            credits_added = claims.credits
    elif claims.credits == 0:
        credits_skipped = True

    account = get_account(db, user.id)

    logger.info(
        "[license_activate] user=%s license=%s expire_at=%s credits_added=%s",
        user.id, claims.license_id, sub.expire_at, credits_added,
    )

    return {
        "license": claims.to_dict(),
        "subscription": sub.to_dict(),
        "creditsAdded": credits_added,
        "creditsSkipped": credits_skipped,
        "points": account,
    }


__all__ = ["LicenseActivationError", "activate_with_license"]
