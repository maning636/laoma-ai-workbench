"""Orders 表(C19)。

字段参考 `docs/dev-reports/2026-10-13-saas-c-class-design.md` §3.3 `orders` 表:
  orders (id, user_id, amount, currency, channel, out_trade_no, status,
          created_at, paid_at)

本迭代扩展:
  - `plan` / `days` : 记录支付对应的订阅配置(回调时用于激活)
  - `pay_trade_no` : 第三方支付平台交易号(支付宝 trade_no / 微信 transaction_id)
  - `status` 状态机: `created` → `paid` / `refunded` / `closed`
    * `created`  : 已生成订单号,等待用户付款
    * `paid`     : 渠道回调验签通过,订阅已激活(或幂等 no-op)
    * `refunded` : 已发起退款(全额 / 部分;部分退款仍保持 paid 语义,由业务决定)
    * `closed`   : 超时未支付(由 `close_expired_orders` 定时任务置位)

约定:
  - `out_trade_no` 全局唯一(order_no),商户侧幂等键。
  - `pay_trade_no` 记录渠道交易号,用于对账 / 退款溯源。
  - `amount` 单位: 元(float),内部换算为渠道的最小单位由 adapter 完成。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


# 订单状态常量(避免散落字符串字面量)
STATUS_CREATED = "created"
STATUS_PAID = "paid"
STATUS_CLOSED = "closed"
STATUS_REFUNDED = "refunded"

# 支持渠道
CHANNEL_ALIPAY = "alipay"
CHANNEL_WECHAT = "wechat"
SUPPORTED_CHANNELS = {CHANNEL_ALIPAY, CHANNEL_WECHAT}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_no", name="uq_orders_order_no"),
        # 渠道交易号全局唯一;SQLite / Postgres 中多个 NULL 不视为冲突,
        # 因此 `created` 状态订单的 NULL pay_trade_no 不影响建表。
        UniqueConstraint("pay_trade_no", name="uq_orders_pay_trade_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 关联用户;订单归属,不建 relationship 反向(与 billing.models 保持一致)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # 商户侧订单号(时间戳 + 随机),全局唯一
    order_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # 金额(元,float);plan/days 冗余存储,方便后续审计
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default="pro", nullable=False)
    # M3 硬化:积分订单 plan='credit' 无有效期 → days 可为 NULL(仅订阅订单使用)。
    # 注意:此列**不设 column default**,避免 SQLAlchemy 在 INSERT 时用 default
    # 覆盖显式传入的 `days=None`(积分订单需要 days=NULL 表达"永久有效")。
    # 订阅订单的 30 天默认值由 CreateOrderRequest.days=30 在应用层保证。
    days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # M3 硬化:积分订单记录实际到账总积分(主积分 + 赠送积分)。
    #   - plan='pro'/'free' 时恒为 NULL;
    #   - plan='credit' 时 = recharge_credit() 到账总额,便于审计回调幂等与赠送追溯。
    # 说明:老库需执行 ALTER TABLE orders ADD COLUMN credit_points FLOAT;
    #       见 `docs/dev-reports/2026-10-16-m3-hardening.md`。
    credit_points: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    # 状态机
    status: Mapped[str] = mapped_column(
        String(16), default=STATUS_CREATED, nullable=False, index=True
    )

    # 支付渠道: alipay | wechat
    channel: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    # 第三方支付平台交易号(回调后填入)
    pay_trade_no: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 退款完成时间(仅当 status=refunded 时非空)
    refunded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def to_dict(self) -> dict:
        return {
            "order_no": self.order_no,
            "user_id": self.user_id,
            "amount": self.amount,
            "plan": self.plan,
            "days": self.days,
            "credit_points": self.credit_points,
            "status": self.status,
            "channel": self.channel,
            "pay_trade_no": self.pay_trade_no,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "refunded_at": self.refunded_at.isoformat() if self.refunded_at else None,
        }


__all__ = [
    "Order",
    "STATUS_CREATED",
    "STATUS_PAID",
    "STATUS_CLOSED",
    "STATUS_REFUNDED",
    "CHANNEL_ALIPAY",
    "CHANNEL_WECHAT",
    "SUPPORTED_CHANNELS",
]
