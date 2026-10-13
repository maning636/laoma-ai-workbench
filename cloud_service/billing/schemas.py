"""Billing 端点的 Pydantic 请求/响应模型(C13)。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ConsumeRequest(BaseModel):
    """`POST /cloud/usage/consume` 请求体。

    - `amount` 默认 1,表示消费 1 个额度单位(如 1 次 LLM 调用)。
    - `period` 可选;不传时用当前 UTC `YYYY-MM` 期间。
    """

    amount: int = Field(1, ge=1, le=10000, description="本次消耗额度,默认 1")
    period: Optional[str] = Field(
        None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="计费期间,形如 '2026-10';缺省为当前 UTC 期间",
    )

    model_config = {"extra": "forbid"}


class SubscriptionActivateRequest(BaseModel):
    """`POST /cloud/subscription/activate` 请求体(模拟 C19 支付完成)。"""

    plan: str = Field("pro", description="目标套餐: pro | free")
    days: int = Field(30, ge=1, le=730, description="pro 订阅持续天数(1-730)")

    @model_validator(mode="after")
    def _check_plan(self) -> "SubscriptionActivateRequest":
        if self.plan not in {"pro", "free"}:
            raise ValueError("plan must be 'pro' or 'free'")
        return self

    model_config = {"extra": "forbid"}


class SubscriptionResponse(BaseModel):
    """订阅快照。`quota/remaining` 为 -1 表示无限。"""

    plan: str
    status: str  # active | expired | cancelled
    expire_at: Optional[str] = None  # ISO8601, None 表示永久
    quota: int
    used: int
    remaining: int  # -1 = 无限
    is_pro: bool

    model_config = {"extra": "forbid"}


class ConsumeResponse(BaseModel):
    """`POST /cloud/usage/consume` 响应。"""

    ok: bool
    period: str
    used: int
    remaining: int  # -1 = 无限;超限时为 0

    model_config = {"extra": "forbid"}


class LicenseVerifyResponse(BaseModel):
    """`POST /cloud/license/verify` 响应。

    - `valid=False`: 订阅失效/过期,客户端应回退到离线模式。
    - `is_pro=True`: 允许使用云端高价值 prompt(设计文档 §2.2)。
    """

    valid: bool
    reason: str  # free | active | expired | no-subscription | unknown
    plan: str
    status: str
    expire_at: Optional[str] = None
    quota: int
    used: int
    remaining: int
    is_pro: bool

    model_config = {"extra": "forbid"}


class ErrorResponse(BaseModel):
    detail: str

    model_config = {"extra": "forbid"}
