"""云端 LLM 调用封装(C14)。

设计要点:
  1. **LLM key vault**:所有 key / endpoint 只从 `os.environ` 读,不写文件、不进日志、不进响应。
     - `CLOUD_LLM_API_KEY`    —— 必填;缺失时 `call_cloud_llm()` 抛 `LLMKeyNotConfiguredError`。
     - `CLOUD_LLM_BASE_URL`   —— 可选,默认 `https://api.siliconflow.cn/v1`(兼容 OpenAI API)。
     - `CLOUD_LLM_MODEL`      —— 可选,默认 `deepseek-ai/DeepSeek-V3`。
  2. **懒加载 client**:每次调用才建 `AsyncOpenAI`,避免启动期缺 key 影响其他模块。
  3. **可 monkey-patch**:`_build_client()` 与 `call_cloud_llm()` 独立,测试可以直接替换
     `call_cloud_llm`,不必真的发 HTTP。

不做的:
  - key 版本 / 轮转 / 多 key 池(C14b 或独立 key-vault 服务)。
  - 流式响应(C14b,当前客户端不需要)。
  - token 精确计费(仅返回 `tokens_in / tokens_out` 估计;严格计费走计费系统)。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

_DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
_DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3"


class LLMKeyNotConfiguredError(RuntimeError):
    """`CLOUD_LLM_API_KEY` 未配置。"""


@dataclass
class LLMCallResult:
    """`call_cloud_llm()` 的返回值。"""

    content: str
    model: str
    prompt_name: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "model": self.model,
            "prompt_name": self.prompt_name,
            "prompt_version": self.prompt_version,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
        }


@dataclass
class LLMStreamEvent:
    """`stream_cloud_llm()` 的一帧增量。

    - `delta`: 上游给出的文本增量(可能为空,例如首帧仅带 usage)。
    - `usage`: 上游返回的 token 用量(OpenAI 兼容:prompt_tokens / completion_tokens)。
      部分上游仅在最后一帧给出 `usage`;若全程未给出,调用方需要按估算兜底。
    """

    delta: str = ""
    usage: dict[str, int] = field(default_factory=dict)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def get_vault() -> dict[str, str]:
    """返回当前 LLM 配置的快照(不含 api_key 明文,防止被 log 误打出)。"""
    return {
        "api_key_configured": bool(_env("CLOUD_LLM_API_KEY")),
        "base_url": _env("CLOUD_LLM_BASE_URL", _DEFAULT_BASE_URL) or _DEFAULT_BASE_URL,
        "model": _env("CLOUD_LLM_MODEL", _DEFAULT_MODEL) or _DEFAULT_MODEL,
    }


def get_api_key() -> str:
    key = _env("CLOUD_LLM_API_KEY")
    if not key:
        raise LLMKeyNotConfiguredError(
            "CLOUD_LLM_API_KEY is not configured. "
            "Set it in the cloud service runtime env before enabling /cloud/llm/chat."
        )
    return key


def _build_client() -> Any:
    """延迟导入 openai,避免测试/离线场景依赖未安装。"""
    try:
        from openai import AsyncOpenAI  # type: ignore[import-not-found]
    except ImportError as e:  # pragma: no cover - 依赖缺失时才会走
        raise RuntimeError("openai package is required for cloud LLM calls") from e
    return AsyncOpenAI(api_key=get_api_key(), base_url=get_vault()["base_url"])


# 允许测试 monkey-patch 的入口点。签名保持稳定的 async callable。
AsyncLlmCaller = Callable[..., Awaitable[str]]


async def call_cloud_llm(
    *,
    messages: list[dict[str, Any]],
    prompt_name: str,
    prompt_version: str,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> LLMCallResult:
    """调用云端 LLM(OpenAI 兼容接口)。

    - `messages`: 已经渲染好的 messages 列表。
    - `model`: 显式覆盖;不传则用 `CLOUD_LLM_MODEL`。
    - 返回 `LLMCallResult`,不返回 `prompt` 源 —— 客户端永远拿不到模板。
    """
    client = _build_client()
    use_model = model or get_vault()["model"]
    resp = await client.chat.completions.create(
        model=use_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
    )
    content = resp.choices[0].message.content or ""

    # token 估算:有 usage 字段就取,否则粗估(字符数 / 2)
    usage = getattr(resp, "usage", None)
    tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
    tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
    if tokens_in == 0:
        tokens_in = max(1, len(str(messages)) // 2)
    if tokens_out == 0:
        tokens_out = max(1, len(content) // 2)

    return LLMCallResult(
        content=content,
        model=use_model,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )


async def stream_cloud_llm(
    *,
    messages: list[dict[str, Any]],
    prompt_name: str,
    prompt_version: str,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> AsyncIterator[LLMStreamEvent]:
    """流式调用云端 LLM(OpenAI 兼容接口,`stream=True`)。

    - 每一帧产出 `LLMStreamEvent(delta=..., usage=...)`。
    - 上游通常只在最后一帧给出 `usage`;若最后一帧未给,调用方可自行估算。
    - **不返回 `prompt` 源**:渲染发生在 router 层,这里只接收 messages。

    与 `call_cloud_llm` 共享 key / base_url / model 解析。测试可用 monkey-patch
    替换本函数,避免真发 HTTP。
    """
    client = _build_client()
    use_model = model or get_vault()["model"]
    stream = await client.chat.completions.create(
        model=use_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        delta = ""
        choices = getattr(chunk, "choices", None) or []
        if choices:
            try:
                delta = getattr(choices[0], "delta", None) and getattr(
                    choices[0].delta, "content", None
                ) or ""
            except Exception:  # pragma: no cover - 防御性:不同 SDK 版本字段差异
                delta = ""
        usage = getattr(chunk, "usage", None)
        usage_dict: dict[str, int] = {}
        if usage is not None:
            usage_dict = {
                "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            }
        yield LLMStreamEvent(delta=str(delta or ""), usage=usage_dict)


__all__ = [
    "LLMKeyNotConfiguredError",
    "LLMCallResult",
    "LLMStreamEvent",
    "get_vault",
    "get_api_key",
    "call_cloud_llm",
    "stream_cloud_llm",
]
