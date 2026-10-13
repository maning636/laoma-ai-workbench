"""LLM Proxy 端点(C14)。

前缀:`/cloud`(在 `main.py` 中挂载 → 完整路径为 `/cloud/llm/*`)。

端点:
  POST /cloud/llm/chat      渲染 prompt + 调云端 LLM;不返回 prompt 源码。
  GET  /cloud/llm/prompts   列出可用 prompt 名(不含模板)。

复用:
  - `..auth.router.get_current_user`    C12 JWT 依赖
  - `..billing.router._consume_quota`   C13 额度累加(402 时回滚)
  - `..billing.router._get_or_create_subscription` 懒创建订阅
  - `..billing.router._get_usage`       查询本月已用
  - `..billing.router._plan_quota`      plan → quota 映射

防逆向关键:
  1. `POST /cloud/llm/chat` 只按 `prompt_name` 触发,`raw_prompt` 需 `allow_raw=True`,
     且 `allow_raw` 默认 False —— 客户端不能自由传任意 prompt 借用云端 LLM。
  2. 响应体**不含** `template` / `prompt` 字段,只回 `content` + 元信息。
  3. LLM key 只走 `CLOUD_LLM_API_KEY`,不出现在响应、日志(通过 `get_vault()` 屏蔽明文)。
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..auth.models import User
from ..auth.router import get_current_user
from ..billing import router as _billing_router
from ..billing.models import Subscription
from ..db import get_db
from . import llm_client as _llm
from . import prompts as _prompts
from .schemas import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    PromptExportItem,
    PromptExportPayload,
    PromptListItem,
    PromptListResponse,
    UsageSnapshot,
)

router = APIRouter()


# ──────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────

def _current_period(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _get_subscription_or_403(db: Session, user: User) -> Subscription:
    """订阅存在且未过期,否则 403。用于 chat:不允许无订阅调用。"""
    sub = _billing_router._get_or_create_subscription(db, user)
    if sub.is_expired():
        raise HTTPException(
            status_code=403,
            detail="subscription expired, please renew",
        )
    if sub.status != "active":
        raise HTTPException(
            status_code=403,
            detail=f"subscription not active (status={sub.status})",
        )
    return sub


def _check_quota_and_consume(
    db: Session, user: User, sub: Subscription, amount: int
) -> UsageSnapshot:
    """超额 → 402;成功则累加并返回新快照。

    复用 C13 `_consume_quota`,保持事务边界一致(超额时 rollback)。
    """
    period = _current_period()
    used = _billing_router._consume_quota(db, user, sub, amount, period)
    remaining = -1 if sub.quota == -1 else max(0, sub.quota - used)
    return UsageSnapshot(
        period=period,
        used=used,
        remaining=remaining,
        plan=sub.plan,
        is_pro=sub.plan == "pro",
    )


# 计费策略:1 次 chat = 1 个额度单位。raw 兜底加倍。
_COST_NORMAL = 1
_COST_RAW = 2  # 兜底路径限额度,防止绕过


# ──────────────────────────────────────────────────────────────
# 内部工具:prompt 解析(供 chat / stream 复用)
# ──────────────────────────────────────────────────────────────

@dataclass
class _ResolvedPrompt:
    """prompt 解析结果 —— chat / stream 共用,避免逻辑分叉。"""

    rendered: str
    prompt_name: str
    prompt_version: str
    prompt_tier: str
    cost: int


def _resolve_prompt(payload: ChatRequest) -> _ResolvedPrompt:
    """校验并渲染 prompt;失败抛 HTTPException(与既有 chat 行为一致)。"""
    if payload.prompt_name:
        pdef = _prompts.get_prompt(payload.prompt_name)
        if pdef is None:
            raise HTTPException(
                status_code=404,
                detail=f"prompt not found: {payload.prompt_name}",
            )
        missing = _prompts.validate_variables(payload.prompt_name, payload.variables)
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"missing variables: {', '.join(missing)}",
            )
        rendered = pdef.render(payload.variables or {})
        return _ResolvedPrompt(
            rendered=rendered,
            prompt_name=pdef.name,
            prompt_version=pdef.version,
            prompt_tier=pdef.tier,
            cost=_COST_NORMAL,
        )
    if not payload.allow_raw:
        raise HTTPException(
            status_code=400,
            detail="raw_prompt requires allow_raw=true (防逆向)",
        )
    rendered = (payload.raw_prompt or "").strip()
    if not rendered:
        raise HTTPException(
            status_code=422,
            detail="raw_prompt must not be empty",
        )
    return _ResolvedPrompt(
        rendered=rendered,
        prompt_name="__raw__",
        prompt_version="-",
        prompt_tier="raw",
        cost=_COST_RAW,
    )


def _precheck_quota(db: Session, user: User, sub: Subscription, cost: int) -> None:
    """前置额度检查(简单起见:检查 used + cost > quota 直接 402)。

    与既有 chat 策略一致:先检查再用,避免"发了一半才发现没额度"。
    流式场景下真正的 consume 发生在上游跑完之后(见 `/llm/stream`)。
    """
    period = _current_period()
    used_before = _billing_router._get_usage(db, user.id, period)
    if sub.quota != -1 and (used_before + cost) > sub.quota:
        raise HTTPException(
            status_code=402,
            detail=f"quota exceeded: {used_before + cost}/{sub.quota} in {period}",
        )


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────

@router.post(
    "/llm/chat",
    response_model=ChatResponse,
    responses={
        401: {"model": ErrorResponse},
        402: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    tags=["cloud-llm"],
)
async def llm_chat(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    """渲染 prompt + 调云端 LLM。

    流程:
      1. 订阅校验 + 未过期(403)
      2. 前置额度检查:不足直接 402(避免先调 LLM 再失败)
      3. 渲染 prompt(要么走 `prompt_name`,要么走 `raw_prompt`)
      4. 调 LLM(失败回滚额度?)—— 当前实现:先 consume 再调,失败时手动回退
      5. 返回 `content` + 元信息(**不含** template)
    """
    # 1. 订阅校验
    sub = _get_subscription_or_403(db, current_user)

    # 2. 决定 prompt 来源
    if payload.prompt_name:
        pdef = _prompts.get_prompt(payload.prompt_name)
        if pdef is None:
            raise HTTPException(
                status_code=404,
                detail=f"prompt not found: {payload.prompt_name}",
            )
        missing = _prompts.validate_variables(payload.prompt_name, payload.variables)
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"missing variables: {', '.join(missing)}",
            )
        rendered = pdef.render(payload.variables or {})
        prompt_tier = pdef.tier
        prompt_name = pdef.name
        prompt_version = pdef.version
        cost = _COST_NORMAL
    else:
        # raw 兜底路径
        if not payload.allow_raw:
            raise HTTPException(
                status_code=400,
                detail="raw_prompt requires allow_raw=true (防逆向)",
            )
        rendered = (payload.raw_prompt or "").strip()
        if not rendered:
            raise HTTPException(
                status_code=422,
                detail="raw_prompt must not be empty",
            )
        prompt_tier = "raw"
        prompt_name = "__raw__"
        prompt_version = "-"
        cost = _COST_RAW

    # 3. 前置额度检查(简单起见:检查 used + cost > quota 直接 402)
    period = _current_period()
    used_before = _billing_router._get_usage(db, current_user.id, period)
    if sub.quota != -1 and (used_before + cost) > sub.quota:
        raise HTTPException(
            status_code=402,
            detail=f"quota exceeded: {used_before + cost}/{sub.quota} in {period}",
        )

    # 4. 调 LLM(失败时不 consume,避免"钱花了没结果")
    try:
        result = await _llm.call_cloud_llm(
            messages=[{"role": "user", "content": rendered}],
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            model=payload.model,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )
    except _llm.LLMKeyNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail="cloud LLM not configured (server-side)",
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - 上游网络/模型错误
        # 保守起见:上游失败,不消费额度,让客户端重试
        raise HTTPException(
            status_code=502,
            detail=f"cloud LLM upstream error: {exc.__class__.__name__}: {exc}",
        )

    # 5. 调用成功后再消费额度;超限 → 402(事务回滚)
    usage_after = _check_quota_and_consume(db, current_user, sub, cost)

    # 6. 组装响应 —— 显式过滤掉 template / prompt 相关字段
    return ChatResponse(
        ok=True,
        prompt_name=result.prompt_name,
        prompt_version=result.prompt_version,
        prompt_tier=prompt_tier,
        model=result.model,
        content=result.content,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        usage_after=usage_after,
    )


# ──────────────────────────────────────────────────────────────
# C14c: /cloud/llm/stream — SSE 流式,与 /llm/chat 并列
# ──────────────────────────────────────────────────────────────
# 设计要点(与 /llm/chat 保持行为一致性,只改传输形态):
#   1. 请求体复用 `ChatRequest`,不新增字段 —— 客户端调用方式最小变更。
#   2. **不泄露 prompt 模板**:仍然只按 `prompt_name` 触发,响应体不含 template;
#      响应头只暴露 model/prompt_name/prompt_tier 等元信息,不含 prompt 内容。
#   3. **计量点**:
#      - 前置额度检查(不足 402,和 chat 一致,避免"钱花一半");
#      - 流结束后按累计 tokens 一次性 consume;失败时不 consume(见下方 try/except),
#        但记录日志,与 chat 的"调 LLM 失败不 consume"策略对齐。
#   4. SSE 帧格式(OpenAI 兼容,便于客户端复用解析逻辑):
#      event: message
#      data: {"id":"<req-id>","model":"...","delta":"<text>","usage":{"prompt_tokens":N,"completion_tokens":M}}
#
#      ...
#
#      event: message
#      data: [DONE]
#
#      - `data:` 每行 UTF-8 文本,以 `\n\n` 分帧;`[DONE]` 是终止标记。
#      - `delta` 只携带增量文本;`usage` 一般只在最后一帧给出(上游行为)。
#      - 客户端可通过 `AbortController` 中断 —— 后端不会回滚已 consume 的额度。
#   5. 前置错误(未鉴权、prompt 校验失败、超额度)在生成 SSE 之前抛出,
#      由 FastAPI 直接返回 JSON `{detail: ...}`,客户端可复用既有错误归一化。
# ──────────────────────────────────────────────────────────────

# SSE 帧编码:显式 UTF-8,避免某些代理层默认 latin-1 截断中文。
_SSE_MEDIA_TYPE = "text/event-stream; charset=utf-8"


def _sse_frame(data: str, event: str | None = None) -> str:
    """把 data 编码为一条 SSE 帧(支持多行 data)。"""
    parts: list[str] = []
    if event:
        parts.append(f"event: {event}")
    for line in data.split("\n"):
        parts.append(f"data: {line}")
    return "\n".join(parts) + "\n\n"


@router.post(
    "/llm/stream",
    tags=["cloud-llm"],
    responses={
        401: {"model": ErrorResponse},
        402: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    # 不设 response_model:StreamingResponse 不匹配 Pydantic 模型,故意留空。
)
async def llm_chat_stream(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """流式调用云端 LLM,返回 SSE(text/event-stream)。

    与 `/llm/chat` 语义对齐,只是把 `content` 拆成多帧 `delta` 输出。
    前置错误 → 直接抛 HTTPException(不进入 SSE);
    上游错误 → 以 `event: error` 帧发出后 `[DONE]` 终止(客户端仍可感知)。
    """
    # 1. 订阅校验(同 chat)
    sub = _get_subscription_or_403(db, current_user)

    # 2. 解析 & 渲染 prompt(同 chat,不返回模板源码)
    rp = _resolve_prompt(payload)

    # 3. 前置额度检查(避免"发了一半才发现没额度")
    _precheck_quota(db, current_user, sub, rp.cost)

    # 4. 模型选择
    vault = _llm.get_vault()
    model = payload.model or vault["model"]

    # 5. 定义 SSE 生成器 —— 关键点:generator 内部异常不影响已发送帧。
    async def _gen() -> AsyncIterator[str]:
        full_text = ""
        tokens_in = 0
        tokens_out = 0
        got_usage = False
        consumed_quota = False
        sent_meta = False

        try:
            async for ev in _llm.stream_cloud_llm(
                messages=[{"role": "user", "content": rp.rendered}],
                prompt_name=rp.prompt_name,
                prompt_version=rp.prompt_version,
                model=payload.model,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
            ):
                if ev.delta:
                    full_text += ev.delta
                if ev.usage:
                    tokens_in = int(ev.usage.get("prompt_tokens") or tokens_in)
                    tokens_out = int(ev.usage.get("completion_tokens") or tokens_out)
                    if tokens_in or tokens_out:
                        got_usage = True

                if not sent_meta:
                    meta = {
                        "model": model,
                        "prompt_name": rp.prompt_name,
                        "prompt_version": rp.prompt_version,
                        "prompt_tier": rp.prompt_tier,
                    }
                    frame_data = json.dumps(
                        {"meta": meta, "delta": ev.delta, "usage": {"prompt_tokens": 0, "completion_tokens": 0}},
                        ensure_ascii=False,
                    )
                    yield _sse_frame(frame_data, event="message")
                    sent_meta = True
                else:
                    frame_data = json.dumps(
                        {
                            "delta": ev.delta,
                            "usage": {
                                "prompt_tokens": tokens_in,
                                "completion_tokens": tokens_out,
                            },
                        },
                        ensure_ascii=False,
                    )
                    yield _sse_frame(frame_data, event="message")
        except _llm.LLMKeyNotConfiguredError:
            yield _sse_frame(
                json.dumps({"error": "cloud LLM not configured (server-side)", "code": "server"}),
                event="error",
            )
            yield _sse_frame("[DONE]")
            return
        except Exception as exc:  # pragma: no cover - 上游网络/模型错误
            # 与 chat 一致:上游失败不 consume 额度,让客户端可重试。
            yield _sse_frame(
                json.dumps(
                    {"error": f"cloud LLM upstream error: {exc.__class__.__name__}: {exc}", "code": "server"},
                    ensure_ascii=False,
                ),
                event="error",
            )
            yield _sse_frame("[DONE]")
            return

        # 6. 上游跑完:补上估算 tokens(部分模型不返回 usage)
        if not got_usage:
            if tokens_in == 0:
                tokens_in = max(1, len(rp.rendered) // 2)
            if tokens_out == 0:
                tokens_out = max(1, len(full_text) // 2)

        # 7. 发送终帧:带上 tokens 统计
        yield _sse_frame(
            json.dumps(
                {
                    "done": True,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
                },
                ensure_ascii=False,
            ),
            event="message",
        )

        # 8. 成功后消费额度 —— 若此时才发现超限,已经流完,记 warning 但不回滚。
        try:
            _check_quota_and_consume(db, current_user, sub, rp.cost)
            consumed_quota = True
        except HTTPException as exc:
            # 前置检查通过后此处几乎不会 402;但并发情况下可能出现。
            try:
                from loguru import logger

                logger.warning(
                    f"[llm-stream] post-stream consume failed user_id={current_user.id} "
                    f"err={exc.detail} prompt={rp.prompt_name}"
                )
            except Exception:  # pragma: no cover - loguru 可选
                pass
        finally:
            try:
                from loguru import logger

                logger.info(
                    f"[llm-stream] user_id={current_user.id} prompt={rp.prompt_name} "
                    f"tier={rp.prompt_tier} tokens={tokens_in}/{tokens_out} consumed={consumed_quota}"
                )
            except Exception:  # pragma: no cover
                pass

        # 9. [DONE] 终止标记 —— 客户端看到就停止解析。
        yield _sse_frame("[DONE]")

    headers = {
        # 让 SSE 流不被中间代理缓冲(nginx / CDN 常见配置)
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        # 只暴露 model / prompt_name / prompt_tier 等元信息,**不含** prompt 内容或模板
        "X-LLM-Model": model,
        "X-LLM-Prompt-Name": rp.prompt_name,
        "X-LLM-Prompt-Tier": rp.prompt_tier,
    }

    return StreamingResponse(
        _gen(),
        media_type=_SSE_MEDIA_TYPE,
        headers=headers,
    )


@router.get(
    "/llm/prompts",
    response_model=PromptListResponse,
    tags=["cloud-llm"],
)
def list_prompts(
    tier: str | None = Query(
        default=None,
        pattern=r"^(cloud|basic)$",
        description="过滤 cloud(高价值) / basic(基础);不传则全量。",
    ),
    current_user: User = Depends(get_current_user),
) -> PromptListResponse:
    """列出可用 prompt **名 + 描述 + 变量列表**(不含模板源码)。

    用途:客户端 UI 展示可选 prompt 列表,便于构建表单。
    """
    names = _prompts.list_prompt_names(tier)
    items: list[PromptListItem] = []
    for name in names:
        pdef = _prompts.get_prompt(name)
        if pdef is None:
            continue
        items.append(
            PromptListItem(
                name=pdef.name,
                tier=pdef.tier,
                version=pdef.version,
                variables=list(pdef.variables),
                description=pdef.description,
            )
        )
    return PromptListResponse(tier=tier, total=len(items), items=items)


@router.get(
    "/llm/health",
    tags=["cloud-llm"],
    response_model=dict[str, Any],
)
def llm_health() -> dict[str, Any]:
    """运维探针(不校验 JWT):只暴露配置状态,不泄露 key 明文。"""
    vault = _llm.get_vault()
    return {
        "api_key_configured": vault["api_key_configured"],
        "base_url": vault["base_url"],
        "model": vault["model"],
        "prompt_count": _prompts.prompt_count_by_tier(),
    }


# ──────────────────────────────────────────────────────────────
# C14a: /cloud/prompts-export — 给离线版打包脚本拉 basic tier 快照
# ──────────────────────────────────────────────────────────────
# 设计要点:
#   - 只允许导出 basic tier(高价值 prompt 绝不离开云端)
#   - 双重门禁:
#       1. JWT 用户必须有效(复用 C12 `get_current_user`)
#       2. 请求头 `X-Admin-Token` 必须匹配 env `CLOUD_ADMIN_TOKEN`
#   - 响应体携带 HMAC-SHA256 签名(用 `CLOUD_HMAC_SECRET`,默认回退到 JWT secret),
#     客户端在离线构建期用同一 secret 做完整性校验,防二次分发/篡改。
#   - 响应只包含模板 + 元数据,不含云端 LLM key。
# ──────────────────────────────────────────────────────────────

_PROMPT_EXPORT_SCHEMA_VERSION = "1.0"


def _get_admin_token_env() -> str:
    """读取 `CLOUD_ADMIN_TOKEN`。空/未设置时抛 503 —— 拒绝在无密钥状态下放行。"""
    token = (os.getenv("CLOUD_ADMIN_TOKEN") or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin token not configured (CLOUD_ADMIN_TOKEN)",
        )
    return token


def _get_hmac_secret() -> str:
    """HMAC 密钥:`CLOUD_HMAC_SECRET` 优先,否则回退到 JWT secret(仅开发环境)。"""
    explicit = (os.getenv("CLOUD_HMAC_SECRET") or "").strip()
    if explicit:
        return explicit
    return _settings().get("jwt_secret", "")


def _settings():
    from ..settings import get_settings

    return get_settings()


def _compute_export_hmac(payload: dict[str, Any]) -> str:
    """对响应体(不含 `hmac` 字段本身)做 canonical JSON + HMAC-SHA256。

    - `sort_keys=True` + `separators=(",", ":")` 保证序列化稳定
    - 客户端可用相同 secret 复算比对
    """
    secret = _get_hmac_secret()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HMAC secret not configured (CLOUD_HMAC_SECRET)",
        )
    body = {k: v for k, v in payload.items() if k != "hmac"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


@router.get(
    "/prompts-export",
    response_model=PromptExportPayload,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    tags=["cloud-llm"],
)
def export_prompts(
    tier: str = Query(
        default="basic",
        pattern=r"^(basic)$",
        description="目前仅允许 basic tier(高价值 cloud tier 不下发)。",
    ),
    current_user: User = Depends(get_current_user),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> PromptExportPayload:
    """导出 basic tier prompt 快照(带 HMAC 签名)。

    用途:
      - 离线版打包脚本(`scripts/build_offline_prompts.py` 等)定期拉取本端点,
        把 `prompts` 数组落盘为 `prism_backend/fusion_ai/prompts_basic.py`。
      - 客户端离线运行时无需连云即可渲染基础模板。

    安全:
      - JWT 有效 + `X-Admin-Token` 匹配 `CLOUD_ADMIN_TOKEN`,两者缺一不可。
      - 响应体 HMAC-SHA256 签名,防篡改/二次分发。
      - 硬限制:`tier` 只能是 `basic`;`cloud` 一律 422。
    """
    # 1. Admin token 校验
    expected = _get_admin_token_env()
    if not x_admin_token or not _hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid admin token",
        )

    # 2. tier 白名单(防御 `?tier=cloud` 或绕过)
    if tier != "basic":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"tier {tier!r} not allowed for export (only 'basic')",
        )

    # 3. 组装 payload
    items: list[PromptExportItem] = []
    for name in _prompts.list_prompt_names("basic"):
        pdef = _prompts.get_prompt(name)
        if pdef is None:
            continue
        items.append(
            PromptExportItem(
                name=pdef.name,
                version=pdef.version,
                variables=list(pdef.variables),
                description=pdef.description,
                template=pdef.template,
            )
        )

    payload = {
        "tier": "basic",
        "schema_version": _PROMPT_EXPORT_SCHEMA_VERSION,
        "total": len(items),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompts": [it.model_dump() for it in items],
    }
    payload["hmac"] = _compute_export_hmac(payload)

    # 审计日志(不含密钥,仅记录请求方 + 时间)
    try:
        from loguru import logger

        logger.info(
            f"[prompts-export] tier=basic requested by user_id={current_user.id} "
            f"username={current_user.username} total={len(items)}"
        )
    except Exception:  # pragma: no cover - loguru 可选
        pass

    return PromptExportPayload(**payload)


__all__ = ["router"]
