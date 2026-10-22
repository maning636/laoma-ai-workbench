"""Pydantic schemas for LLM Proxy endpoints (C14)."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


# ──────────────────────────────────────────────────────────────
# Request
# ──────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """`POST /cloud/llm/chat` 请求体。

    字段优先级与互斥规则:
      - `prompt_name`(推荐): 云端 prompt 库的名字,如 `platform_style.match`。
      - `raw_prompt`(兜底,`allow_raw=True` 时可用): 客户端自定义 prompt 全文。
        用途:调试、临时任务。会**消耗更多额度**且被标记 `source="raw"`。

    二者只能传其一(都不传 → 422,都传 → 422)。
    """

    prompt_name: Optional[str] = Field(
        None,
        max_length=128,
        description="云端 prompt 库中的名字(推荐)。",
    )
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="渲染 `prompt_name` 需要的变量;raw_prompt 下忽略。",
    )
    raw_prompt: Optional[str] = Field(
        None,
        min_length=1,
        max_length=8000,
        description="客户端传入的兜底 prompt(需 `allow_raw=True` 才生效)。",
    )
    model: Optional[str] = Field(
        None,
        max_length=128,
        description="显式覆盖云端默认模型;不传则用 CLOUD_LLM_MODEL。",
    )
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(1024, ge=1, le=8192)
    allow_raw: bool = Field(
        False,
        description="允许 `raw_prompt` 兜底;默认 False,防止客户端绕过 prompt 库。",
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> "ChatRequest":
        has_name = bool(self.prompt_name)
        has_raw = bool(self.raw_prompt)
        if has_name and has_raw:
            raise ValueError("prompt_name and raw_prompt are mutually exclusive")
        if not has_name and not has_raw:
            raise ValueError("either prompt_name or raw_prompt is required")
        return self


# ──────────────────────────────────────────────────────────────
# Response
# ──────────────────────────────────────────────────────────────

class UsageSnapshot(BaseModel):
    """调用后附带的用量快照。"""

    period: str
    used: int
    remaining: int  # -1 = 无限
    plan: str
    is_pro: bool

    model_config = {"extra": "forbid"}


class ChatResponse(BaseModel):
    """`POST /cloud/llm/chat` 响应。

    **绝不包含 `prompt` / `template` 字段** —— 防止客户端通过响应反推出源码。
    只暴露渲染结果 + 元信息(供日志 / 计费关联)。
    """

    ok: bool = True
    prompt_name: str
    prompt_version: str
    prompt_tier: str  # "cloud" | "basic" | "raw"
    model: str
    content: str
    tokens_in: int
    tokens_out: int
    usage_after: UsageSnapshot = Field(
        description="调用完成后的用量快照(用户友好)。",
    )

    model_config = {"extra": "forbid"}


class PromptListItem(BaseModel):
    """`GET /cloud/llm/prompts` 列表项 —— **只含 name 与描述,不含模板**。"""

    name: str
    tier: str  # "cloud" | "basic"
    version: str
    variables: list[str]
    description: str = ""
    available: bool = Field(
        default=True,
        description=(
            "当前部署是否拿得到模板正文。"
            "False = 该能力属于 Pro(开源仓不含云端模板正文)。"
        ),
    )

    model_config = {"extra": "forbid"}


class PromptListResponse(BaseModel):
    tier: Optional[str] = None  # 若过滤
    total: int
    items: list[PromptListItem]

    model_config = {"extra": "forbid"}


class PromptExportItem(BaseModel):
    """`GET /cloud/prompts-export` 单条 —— basic tier 才允许导出。"""

    name: str
    version: str
    variables: list[str]
    description: str = ""
    template: str

    model_config = {"extra": "forbid"}


class PromptExportPayload(BaseModel):
    """`GET /cloud/prompts-export` 响应体。

    - `tier`: 目前仅允许 `basic`(高价值 prompt 不下发)
    - `schema_version`: 快照 schema 版本,客户端据此升级
    - `generated_at`: 生成时间(UTC ISO)
    - `hmac`: `HMAC-SHA256(CLOUD_HMAC_SECRET, json.dumps(payload_minus_hmac, sort_keys=True))`
             客户端可用同一 secret(打包时下发)做完整性校验
    """

    tier: str
    schema_version: str
    total: int
    generated_at: str
    prompts: list[PromptExportItem]
    hmac: str

    model_config = {"extra": "forbid"}


class ErrorResponse(BaseModel):
    detail: str

    model_config = {"extra": "forbid"}
