"""Subscriptions + Usage 表(C13) + Credit Ledger 表(M3)。

设计参考 `docs/dev-reports/2026-10-13-saas-c-class-design.md` §3.3;
本迭代刻意保持简单 —— 无 `plans` / `invoices` 表(留待 C19 支付接入)。

  subscriptions (id, user_id, plan, status, expire_at, quota, created_at)
  usage         (id, user_id, period, used)        -- period 形如 "YYYY-MM"

M3(积分制,2026-10-16 追加;参考澜途 API 审计报告 §2):
  credit_balance (user_id, available_points, frozen_points,
                  total_consumed, total_recharged, version, updated_at)
  credit_ledger  (id, user_id, tx_type, amount, balance_after,
                  frozen_after, use_function, ref_id, recharge_id,
                  pricing_key, note, freeze_tx_id, status, created_at)
  credit_pricing (pricing_key, display_name, points, category,
                  enabled, sort_order, updated_at)

约定:
  - `plan`: "free" | "pro" | "credit"(可扩展;见 `settings.get_settings()["billing"]`)
  - `status`: "active" | "expired" | "cancelled"
  - `quota`: -1 表示无限;0 表示明确封禁;>=0 为月度上限
  - `expire_at`: `None` 表示永久(目前仅 free 使用);否则为有效截止时间
  - `Usage.period`: 单用户单期间聚合(唯一键),consume 时 upsert
  - `CreditLedger.tx_type`: RECHARGE | FREEZE | CONSUME | ROLLBACK | REFUND | BONUS
  - `CreditLedger.status` (仅 FREEZE 有意义): active | consumed | rolled_back
  - `CreditBalance.version`: 乐观锁版本号,每次积分变动 +1(并发超扣防护)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 用字符串 forward-ref "User" 避免与 auth.models 的循环导入
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    expire_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    quota: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # 单向 relationship;不调用 back_populates,避免 auth.models.User 反向绑定
    user = relationship("User", lazy="joined")

    def is_expired(self) -> bool:
        if self.expire_at is None:
            return False
        # SQLite 存回 DateTime(timezone=True) 后可能是 naive datetime;
        # 这里兜底补 UTC tzinfo,避免 `can't compare offset-naive and offset-aware`
        exp = self.expire_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= exp

    def to_dict(self, used: int = 0) -> dict:
        return {
            "plan": self.plan,
            "status": "expired" if self.is_expired() else self.status,
            "expire_at": self.expire_at.isoformat() if self.expire_at else None,
            "quota": self.quota,
            "used": used,
            "remaining": -1 if self.quota == -1 else max(0, self.quota - used),
            "is_pro": self.plan == "pro",
        }


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("user_id", "period", name="uq_usage_user_period"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "used": self.used,
        }


# ══════════════════════════════════════════════════════════════
# M3 · 积分制(Credit Ledger,2026-10-16 追加)
# ══════════════════════════════════════════════════════════════
#
# 设计参考:
#   - `docs/dev-reports/2026-10-16-lantyou-api-audit.md` §2(澜途 credit ledger)
#   - `docs/dev-reports/2026-10-16-module-replication-plan.md` §3.3(M3 方案)
#
# 语义(与澜途对齐):
#   - **双账户**:available_points(可用) + frozen_points(冻结,生成中)
#   - **预扣 → 实扣**:AI 任务开始前 `freeze`(available→frozen),成功 `consume`
#     (frozen→total_consumed),失败 `rollback`(frozen→available)。
#   - **积分金额单位**:积分(Decimal,允许 0.1/1.5 这样的分数,因为澜途价目表
#     `aiTitle=0.1`、`aiImageGeneration=1.5` 都是非整数)。
#   - **乐观锁**:`CreditBalance.version` 每次变动 +1,配合 `with_for_update`
#     行锁防并发超扣。


# 交易类型常量(避免散落字符串字面量)
TX_RECHARGE = "RECHARGE"      # 用户充值主积分
TX_BONUS = "BONUS"            # 充值赠送积分(满1000赠50%)
TX_FREEZE = "FREEZE"          # 预扣(生成前)
TX_CONSUME = "CONSUME"        # 实扣(生成成功后,来自 frozen)
TX_ROLLBACK = "ROLLBACK"      # 冻结回滚(生成失败,回到 available)
TX_REFUND = "REFUND"          # 退款扣减(负数)

TX_TYPES = {TX_RECHARGE, TX_BONUS, TX_FREEZE, TX_CONSUME, TX_ROLLBACK, TX_REFUND}

# 冻结交易状态(仅 FREEZE 行有意义)
FREEZE_ACTIVE = "active"
FREEZE_CONSUMED = "consumed"
FREEZE_ROLLED_BACK = "rolled_back"


class CreditBalance(Base):
    """用户积分余额(每用户唯一一行,冗余聚合视图)。

    权威数据来自 `CreditLedger`;本表用于快速读取当前余额,避免每次聚合扫描流水。
    所有写入都必须在事务内,并用 `with_for_update` 锁住本行 + 递增 `version`,
    防止并发扣减/冻结时出现负数或超扣。
    """

    __tablename__ = "credit_balance"
    __table_args__ = (UniqueConstraint("user_id", name="uq_credit_balance_user"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    available_points: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=Decimal("0"), nullable=False
    )
    frozen_points: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=Decimal("0"), nullable=False
    )
    total_consumed: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=Decimal("0"), nullable=False
    )
    total_recharged: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=Decimal("0"), nullable=False
    )
    # 乐观锁版本号:每次积分变动 +1
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def to_dict(self) -> dict:
        return {
            "userId": self.user_id,
            "availablePoints": float(self.available_points),
            "frozenPoints": float(self.frozen_points),
            "totalPoints": float(
                (self.available_points or Decimal("0"))
                + (self.frozen_points or Decimal("0"))
            ),
            "totalConsumed": float(self.total_consumed),
            "totalRecharged": float(self.total_recharged),
            "version": self.version,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CreditLedger(Base):
    """积分流水(唯一权威表)。

    所有积分变动(充值/赠送/冻结/实扣/回滚/退款)都必须在此落一条流水,
    便于审计、报表、退款溯源。
    """

    __tablename__ = "credit_ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tx_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )
    # 变动金额(正数充值/赠返,负数扣减/退款);对 FREEZE/CONSUME/ROLLBACK
    # 保持为正数,语义由 tx_type + status 决定。
    amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False
    )
    # 变动后可用余额
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=Decimal("0")
    )
    # 变动后冻结余额
    frozen_after: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=Decimal("0")
    )
    # 业务场景:"ai_design" / "collect" / "fission" / "recharge" 等
    use_function: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    # 关联业务 ID(如生图任务 ID);非空时用于对账
    ref_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )
    # 关联充值订单 ID(如 PF...)
    recharge_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    # 关联价目表项(如 aiImageGeneration);CONSUME 时填
    pricing_key: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    # 冻结交易的关联:CONSUME / ROLLBACK 记录回填原 FREEZE 的 tx id
    freeze_tx_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("credit_ledger.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 冻结状态:仅 tx_type='FREEZE' 时非空,取值 active | consumed | rolled_back
    status: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, index=True
    )
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "userId": self.user_id,
            "txType": self.tx_type,
            "amount": float(self.amount),
            "balanceAfter": float(self.balance_after),
            "frozenAfter": float(self.frozen_after),
            "useFunction": self.use_function,
            "refId": self.ref_id,
            "rechargeId": self.recharge_id,
            "pricingKey": self.pricing_key,
            "freezeTxId": self.freeze_tx_id,
            "status": self.status,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CreditPricing(Base):
    """AI 能力价目表(可配置;管理员可通过后台调整)。

    `pricing_key` 与澜途 `/system/config/ai-point-pricing` 对齐,便于客户端复用同一份枚举。
    """

    __tablename__ = "credit_pricing"

    pricing_key: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    points: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ai_design"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def to_dict(self) -> dict:
        return {
            "pricingKey": self.pricing_key,
            "displayName": self.display_name,
            "points": float(self.points),
            "category": self.category,
            "enabled": bool(self.enabled),
            "sortOrder": self.sort_order,
        }


__all__ = [
    "Subscription",
    "Usage",
    "CreditBalance",
    "CreditLedger",
    "CreditPricing",
    "TX_RECHARGE",
    "TX_BONUS",
    "TX_FREEZE",
    "TX_CONSUME",
    "TX_ROLLBACK",
    "TX_REFUND",
    "TX_TYPES",
    "FREEZE_ACTIVE",
    "FREEZE_CONSUMED",
    "FREEZE_ROLLED_BACK",
]
