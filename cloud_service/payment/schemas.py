"""Payment 端点的 Pydantic 请求/响应模型(C19)。"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


# 支持渠道(与 models.SUPPORTED_CHANNELS 保持一致)
_CHANNELS = {"alipay", "wechat"}


class CreateOrderRequest(BaseModel):
    """`POST /cloud/payment/create_order` 请求体。

    M3 硬化(2026-10-16):`plan` 新增 `'credit'` 允许积分充值订单走
    通用订单端点(可选,主入口仍是 `POST /points/recharge`);
    积分订单 `days` 可为 None(积分永久有效,无订阅延长)。
    """

    plan: str = Field("pro", description="目标套餐: pro | free | credit")
    days: Optional[int] = Field(
        30, ge=0, le=730,
        description="订阅持续天数(1-730);plan='credit' 时允许省略/None/0",
    )
    channel: str = Field(..., description="支付渠道: alipay | wechat")

    @model_validator(mode="after")
    def _check(self) -> "CreateOrderRequest":
        allowed_plans = {"pro", "free", "credit"}
        if self.plan not in allowed_plans:
            raise ValueError(f"plan must be one of {sorted(allowed_plans)}")
        if self.plan == "credit":
            # 积分订单无有效期;允许 days=None,把 days=0 归一为 None
            if self.days == 0:
                self.days = None
        else:
            if self.days is None or self.days < 1:
                raise ValueError("days must be >= 1 for pro/free plans")
        if self.channel not in _CHANNELS:
            raise ValueError(f"channel must be one of {sorted(_CHANNELS)}")
        return self

    model_config = {"extra": "forbid"}


class CreateOrderResponse(BaseModel):
    """`POST /cloud/payment/create_order` 响应。

    `pay_params` 结构随渠道不同:
      - alipay: `{pay_type:'form', form_html:'<form>...</form>', ...}`
      - wechat: `{pay_type:'qrcode', code_url:'weixin://...', ...}`
    """

    order_no: str
    amount: float
    plan: str
    days: Optional[int] = None
    channel: str
    pay_params: dict[str, Any]

    model_config = {"extra": "forbid"}


class OrderResponse(BaseModel):
    """`GET /cloud/payment/order/{order_no}` 响应。"""

    order_no: str
    status: str  # created | paid | refunded | closed
    plan: str
    days: Optional[int] = None
    amount: float
    channel: str
    pay_trade_no: Optional[str] = None
    created_at: Optional[str] = None
    paid_at: Optional[str] = None
    refunded_at: Optional[str] = None
    # M3 硬化:积分订单落 total points(主 + 赠送),用于审计
    credit_points: Optional[float] = None

    model_config = {"extra": "forbid"}


class CallbackResponse(BaseModel):
    """`POST /cloud/payment/callback/{channel}` 响应(第三方商户回调)。"""

    order_no: str
    ok: bool
    activated: bool  # False 表示幂等(已激活过,本次 no-op)
    subscription: Optional[dict[str, Any]] = None

    model_config = {"extra": "forbid"}


class RefundRequest(BaseModel):
    """`POST /cloud/payment/refund` 请求体(管理员)。"""

    order_no: str = Field(..., min_length=1, description="商户订单号")
    amount: Optional[float] = Field(
        None,
        ge=0.01,
        description="退款金额(元);不传则全额退款(= Order.amount)。",
    )
    reason: Optional[str] = Field(
        None, max_length=200, description="退款原因(仅供后台记录)。"
    )

    model_config = {"extra": "forbid"}


class RefundResponse(BaseModel):
    """`POST /cloud/payment/refund` 响应。

    - ``subscription_touched``: 本次退款是否**由端点自动**变更了 Subscription。
      当前迭代恒为 ``False``(业务规则未拍板,退款不自动撤销/缩短订阅),
      为保留前端契约 **不改变字段含义**;若未来业务决定"全额退款自动撤销订阅",
      该字段才会变 ``True``,前端可据此决定是否重新拉取订阅状态。
    - ``subscription_note``: 面向后台/客服的文字说明(新增,兼容旧客户端,
      因 ``Optional`` + 默认 ``None``,不改变旧字段结构)。
      当订阅被自动变更时(未来)可填入具体动作;当订阅未被变更但**值得留痕**时
      (如全额退款但订阅未自动撤销),也会说明原因,便于排查。
    - ``note``: 保留旧字段,含义/类型不变。
    """

    order_no: str
    refunded_amount: float
    order_status: str  # refunded | paid (部分退款语义可保留 paid)
    pay_trade_no: Optional[str] = None
    refund_trade_no: Optional[str] = None
    refunded_at: Optional[str] = None
    subscription_touched: bool = False  # 预留:退款是否撤销订阅(当前迭代不撤销)
    note: Optional[str] = None
    subscription_note: Optional[str] = None  # 新增:订阅侧动作/未动作的说明(规则待定)

    model_config = {"extra": "forbid"}


class ErrorResponse(BaseModel):
    detail: str

    model_config = {"extra": "forbid"}


__all__ = [
    "CreateOrderRequest",
    "CreateOrderResponse",
    "OrderResponse",
    "CallbackResponse",
    "RefundRequest",
    "RefundResponse",
    "ErrorResponse",
]
