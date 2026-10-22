"""Billing 端点的 Pydantic 请求/响应模型(C13)。"""

from typing import Any, Optional

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


class LicenseActivateRequest(BaseModel):
    """`POST /cloud/license/activate` 请求体(用注册码开通云端能力)。

    线下人工充值模式下的核心入口:用户把产品方签发的注册码同步到云端,
    云端验签后开通订阅并注入注册码携带的积分额度。

    客户端应只传注册码原文;**不要**传任何期望的套餐/时长/积分数值——
    那些都以注册码签名内容为准,服务端不接受客户端自报。
    """

    token: str = Field(
        ...,
        min_length=16,
        max_length=4096,
        description="注册码 token(PRISM1.<payload>.<signature>)",
    )

    model_config = {"extra": "forbid"}


class LicenseActivateResponse(BaseModel):
    """`POST /cloud/license/activate` 响应。

    - `license`: 注册码声明(条目 / 到期 / 积分额度)
    - `subscription`: 激活后的订阅状态
    - `creditsAdded`: 本次实际注入的积分(重复同步时为 0)
    - `creditsSkipped`: 积分未注入(额度为 0,或该码已注入过)
    - `points`: 账户积分快照
    """

    ok: bool
    license: dict[str, Any]
    subscription: dict[str, Any]
    creditsAdded: float = 0
    creditsSkipped: bool = False
    points: dict[str, Any]

    model_config = {"extra": "forbid"}


class FeatureFlagsResponse(BaseModel):
    """`GET /cloud/feature-flags` 响应(Open Core feature gate 快照)。

    客户端订阅后缓存此响应;UI 根据 `flags` 隐藏/显示 Pro 功能入口,
    避免每次请求都打云端。详见 `cloud_service/billing/feature_gate.py`
    与 `docs/dev-reports/2026-10-16-open-core-implementation.md`。

    字段:
      - `plan`: "community" | "pro"
      - `flags`: 各 feature 的实际值(见 feature_gate.FEATURE_NAMES)
      - `upgrade_url`: 升级 Pro 的引导 URL;空字符串表示尚未配置
    """

    plan: str
    flags: dict[str, Any]
    upgrade_url: Optional[str] = None

    model_config = {"extra": "forbid"}


class ErrorResponse(BaseModel):
    detail: str

    model_config = {"extra": "forbid"}


# ══════════════════════════════════════════════════════════════
# M3 · 积分制 schemas(2026-10-16)
# 字段命名对齐澜途 API(availablePoints / frozenPoints 等 camelCase)。
# ══════════════════════════════════════════════════════════════


class PointsAccountResponse(BaseModel):
    """`GET /cloud/points/account` 响应(对齐澜途 `/points/account`)。"""

    primaryAccountId: int
    availablePoints: float
    frozenPoints: float
    totalPoints: float
    totalConsumed: float
    totalRecharged: float

    model_config = {"extra": "forbid"}


class PointsRechargePreset(BaseModel):
    """充值预设档位。"""

    points: float
    bonusPoints: float
    yuan: float
    enabled: bool

    model_config = {"extra": "forbid"}


class PointsRechargeOptionsResponse(BaseModel):
    """`GET /cloud/points/recharge/options` 响应。

    ⚠️ **2026-10-23:平台支付彻底删除** —— 本端点不再用于「在线下单」,
    只返回**档位与赠送规则**,供运营侧人工收款、人工签发注册码时对账。
    `channels` 恒为 `["manual_wechat"]`(唯一渠道:个人微信人工转账)。
    """

    enabled: bool
    pointsPerYuan: float
    bonusThreshold: float
    bonusRate: float
    minPoints: float
    maxPoints: float
    defaultPoints: float
    customEnabled: bool
    presets: list[PointsRechargePreset]
    channels: list[str]
    notice: str

    model_config = {"extra": "forbid"}


class PointsLedgerItem(BaseModel):
    """积分流水单条记录。"""

    id: int
    txType: str
    amount: float
    balanceAfter: float
    frozenAfter: float
    useFunction: Optional[str] = None
    refId: Optional[str] = None
    rechargeId: Optional[str] = None
    pricingKey: Optional[str] = None
    freezeTxId: Optional[int] = None
    status: Optional[str] = None
    note: Optional[str] = None
    createdAt: Optional[str] = None

    model_config = {"extra": "forbid"}


class PointsHistoryResponse(BaseModel):
    """`GET /cloud/points/history` 响应。"""

    current: int
    size: int
    total: int
    items: list[PointsLedgerItem]

    model_config = {"extra": "forbid"}


class PointsPricingItem(BaseModel):
    """价目表单项。"""

    pricingKey: str
    displayName: str
    points: float
    category: str
    enabled: bool
    sortOrder: int

    model_config = {"extra": "forbid"}


class PointsPricingResponse(BaseModel):
    """`GET /cloud/points/pricing` 响应。"""

    pricingVersion: str
    items: list[PointsPricingItem]

    model_config = {"extra": "forbid"}


class PointsFreezeRequest(BaseModel):
    """冻结/消耗/回滚共用请求体。

    - `amount`:冻结金额(仅 freeze 端点使用)。
    - `freezeTxId` / `freeze_tx_id`:消耗/回滚时指向要处理的冻结流水 ID(二者择一)。
    - `use_function` / `ref_id` / `pricing_key`:审计字段。
    - `note`:备注。
    """

    amount: Optional[float] = Field(None, gt=0, description="冻结金额(仅 freeze 使用)")
    freeze_tx_id: Optional[int] = Field(None, description="消耗/回滚时必填")
    use_function: Optional[str] = Field(None, max_length=64)
    ref_id: Optional[str] = Field(None, max_length=128)
    pricing_key: Optional[str] = Field(None, max_length=64)
    note: Optional[str] = Field(None, max_length=255)

    model_config = {"extra": "forbid"}


class PointsFreezeResponse(BaseModel):
    """`POST /cloud/points/freeze` 响应。"""

    freezeTxId: int
    amount: float
    useFunction: Optional[str] = None
    refId: Optional[str] = None
    pricingKey: Optional[str] = None
    status: str
    availablePoints: float
    frozenPoints: float
    createdAt: Optional[str] = None

    model_config = {"extra": "forbid"}


class PointsConsumeResponse(BaseModel):
    """`POST /cloud/points/consume` / `/rollback` 响应。"""

    freezeTxId: Optional[int] = None
    consumeTxId: int
    amount: float
    status: str  # 'consumed' | 'rolled_back' | 'refunded'
    availablePoints: float
    frozenPoints: float
    totalConsumed: float
    createdAt: Optional[str] = None

    model_config = {"extra": "forbid"}


class PointsConsumeByPricingRequest(BaseModel):
    """一次性按 pricing_key 扣积分。"""

    pricing_key: str = Field(..., min_length=1, max_length=64)
    amount: Optional[float] = Field(None, gt=0, description="覆盖价目表金额(可选)")
    use_function: Optional[str] = Field(None, max_length=64)
    ref_id: Optional[str] = Field(None, max_length=128)

    model_config = {"extra": "forbid"}


class PointsRefundAdminRequest(BaseModel):
    """管理员手动退积分请求体。"""

    user_id: int = Field(..., ge=1)
    amount: float = Field(..., gt=0)
    recharge_id: Optional[str] = Field(None, max_length=64)
    note: Optional[str] = Field(None, max_length=255)

    model_config = {"extra": "forbid"}


__all__ = [
    "ErrorResponse",
    "PointsAccountResponse",
    "PointsRechargePreset",
    "PointsRechargeOptionsResponse",
    "PointsRechargeCreateRequest",
    "PointsRechargeCreateResponse",
    "PointsLedgerItem",
    "PointsHistoryResponse",
    "PointsPricingItem",
    "PointsPricingResponse",
    "PointsFreezeRequest",
    "PointsFreezeResponse",
    "PointsConsumeResponse",
    "PointsConsumeByPricingRequest",
    "PointsRefundAdminRequest",
]
