"""Orders 表(C19)。

字段参考 `docs/dev-reports/2026-10-13-saas-c-class-design.md` §3.3 `orders` 表:
  orders (id, user_id, amount, currency, channel, out_trade_no, status,
          created_at, paid_at)

本迭代扩展:
  - `plan` / `days` : 记录支付对应的订阅配置(回调时用于激活)
  - `pay_trade_no` : 第三方支付平台交易号(支付宝 trade_no / 微信 transaction_id)
  - `status` 状态机: `created` → `paid` / `closed`
    * `created`: 已生成订单号,等待用户付款
    * `paid`   : 渠道回调验签通过,订阅已激活(或幂等 no-op)
    * `closed` : 超时 / 取消(本迭代未实现定时关闭)

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
    days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

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

    def to_dict(self) -> dict:
        return {
            "order_no": self.order_no,
            "user_id": self.user_id,
            "amount": self.amount,
            "plan": self.plan,
            "days": self.days,
            "status": self.status,
            "channel": self.channel,
            "pay_trade_no": self.pay_trade_no,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
        }


__all__ = [
    "Order",
    "STATUS_CREATED",
    "STATUS_PAID",
    "STATUS_CLOSED",
    "CHANNEL_ALIPAY",
    "CHANNEL_WECHAT",
    "SUPPORTED_CHANNELS",
]
