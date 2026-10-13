"""Payment 端点的 Pydantic 请求/响应模型(C19)。"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


# 支持渠道(与 models.SUPPORTED_CHANNELS 保持一致)
_CHANNELS = {"alipay", "wechat"}


class CreateOrderRequest(BaseModel):
    """`POST /cloud/payment/create_order` 请求体。"""

    plan: str = Field("pro", description="目标套餐: pro | free")
    days: int = Field(30, ge=1, le=730, description="订阅持续天数(1-730)")
    channel: str = Field(..., description="支付渠道: alipay | wechat")

    @model_validator(mode="after")
    def _check(self) -> "CreateOrderRequest":
        if self.plan not in {"pro", "free"}:
            raise ValueError("plan must be 'pro' or 'free'")
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
    days: int
    channel: str
    pay_params: dict[str, Any]

    model_config = {"extra": "forbid"}


class OrderResponse(BaseModel):
    """`GET /cloud/payment/order/{order_no}` 响应。"""

    order_no: str
    status: str  # created | paid | refunded | closed
    plan: str
    days: int
    amount: float
    channel: str
    pay_trade_no: Optional[str] = None
    created_at: Optional[str] = None
    paid_at: Optional[str] = None
    refunded_at: Optional[str] = None

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
    """`POST /cloud/payment/refund` 响应。"""

    order_no: str
    refunded_amount: float
    order_status: str  # refunded | paid (部分退款语义可保留 paid)
    pay_trade_no: Optional[str] = None
    refund_trade_no: Optional[str] = None
    refunded_at: Optional[str] = None
    subscription_touched: bool = False  # 预留:退款是否撤销订阅(当前迭代不撤销)
    note: Optional[str] = None

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
