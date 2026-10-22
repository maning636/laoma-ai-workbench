"""只读模式守卫(D4):注册码过期且宽限期满 → 写操作拦截,读操作放行。

两套用法:

1. **路由级依赖**(单点精确拦截)

    from fastapi_app.api.v1.license.guard import require_write_allowed

    @router.post("/campaigns", ...)
    async def create_campaign(
        request: Request,
        _guard: None = Depends(require_write_allowed),
    ):
        ...

2. **全局中间件**(兜底,防绕过直调 API)—— 本文件主要提供这一套。
   拦截面由 `READ_ONLY_RULES` 一张表决定,**唯一真源**,改这里就够。

语义要点:
  - **从未有过注册码** → 不是只读(社区版照常用)。D4 的"到期只读"针对的是
    "曾经是 Pro、现在到期了"的用户,不是把社区版也锁成只读。
  - **宽限期内** → 仍可写(只是提示即将到期)。
  - **过期且宽限期满** → 写操作 403,读操作不受影响。

拦截原则(重要,别随手扩大):
  - 拦「**能产出新内容 / 推进新状态**」的写操作;
  - **放行「管理、清理、导出、停止、登录、改配置」**——
    否则到期用户会被锁死在:停不下正在跑的发布、删不掉自己的文件、导不出数据、
    甚至**没法输入新注册码**。
  - 因此 `/campaigns/{id}/pause`、`/tasks/cancel/*`、`/license/activate`、
    `/auth/*`、`/system/*`、`/data/*`、`/recovery/*` 一律**不在**拦截面内。
"""

from __future__ import annotations

import json
import os
import re
from typing import Iterable, Optional

from fastapi import HTTPException, Request, status

from fastapi_app.core.license import load_license

#: 视为"写"的方法
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: 紧急停用开关(设成 0/false/no/off 即关闭整个只读守卫)
DISABLE_ENV = "PRISM_LICENSE_READONLY_GUARD"

#: 403 响应体(与 HTTPException(detail=dict) 的形状保持一致)
_READ_ONLY_DETAIL = {
    "reason": "license_expired_read_only",
    "message": "注册码已过期,当前为只读模式(可查看,不能新增)",
    "readOnly": True,
    "upgrade": "请续费注册码以继续新增内容",
}


# ──────────────────────────────────────────────────────────────
# 拦截面 —— 唯一真源
# ──────────────────────────────────────────────────────────────
# 格式:(HTTP 方法, 路径模板)。路径模板里 `{xxx}` 匹配任意单段。
# 只登记**确属"产出新内容 / 推进新状态"**的端点。

READ_ONLY_RULES: tuple[tuple[str, str], ...] = (
    # ── A. AI / 生成(产出新内容) ────────────────────────────
    ("POST", "/api/v1/ai/chat"),
    ("POST", "/api/v1/ai/agent-chat"),
    ("POST", "/api/v1/ai/function-calling"),
    ("POST", "/api/v1/ai/generate-cover"),
    ("POST", "/api/v1/ai/generate-video"),
    ("POST", "/api/v1/ai/llm-proxy/chat/chat/completions"),
    ("POST", "/api/v1/ai/speech-recognition"),
    ("POST", "/api/v1/ai/scripts/run"),
    ("POST", "/api/v1/ai/threads/{thread_id}/messages"),
    ("POST", "/api/v1/ai/threads/{thread_id}/messages/batch"),
    ("POST", "/api/v1/ai-design/generate"),
    ("POST", "/api/v1/fusion/images/generate"),
    ("POST", "/api/v1/fusion/images/generate-batch"),
    ("POST", "/api/v1/fusion/breakdown"),
    ("POST", "/api/v1/fusion/cognition/audience"),
    ("POST", "/api/v1/fusion/cognition/dna"),
    ("POST", "/api/v1/fusion/cognition/gaps"),
    ("POST", "/api/v1/fusion/cognition/matrix"),
    ("POST", "/api/v1/fusion/cognition/persona"),
    ("POST", "/api/v1/files/upload"),
    ("POST", "/api/v1/files/upload-save"),
    ("POST", "/api/v1/files/{file_id}/ai-content"),
    ("POST", "/api/v1/files/{file_id}/ai-cover"),
    ("POST", "/api/v1/files/{file_id}/ai-cover-job"),
    ("POST", "/api/v1/video-pipeline/render"),
    ("POST", "/api/v1/video-pipeline/run"),
    ("POST", "/api/v1/workshop/run"),
    ("POST", "/api/v1/scripts/run"),
    ("POST", "/api/v1/agent/execute-script"),
    ("POST", "/api/v1/agent/hermes-run"),
    ("POST", "/api/v1/agent/openclaw-run"),
    ("POST", "/api/v1/agent/hermes-stream"),
    ("POST", "/api/v1/agent/openclaw-stream"),
    ("POST", "/api/v1/easel/drafts/{project}/import"),

    # ── B. 新建计划 / 任务 / 编排 ───────────────────────────
    ("POST", "/api/v1/campaigns/create"),
    ("POST", "/api/v1/campaigns/{campaign_id}/execute"),
    ("POST", "/api/v1/plans"),
    ("PUT", "/api/v1/plans/{plan_id}"),
    ("POST", "/api/v1/plans/{plan_id}/publish"),
    ("POST", "/api/v1/task-packages"),
    ("PUT", "/api/v1/task-packages/{package_id}"),
    ("POST", "/api/v1/task-packages/{package_id}/generate-tasks"),
    ("POST", "/api/v1/matrix/generate_tasks"),
    ("POST", "/api/v1/matrix/tasks/dispatch"),
    ("POST", "/api/v1/matrix/tasks/pop"),
    ("POST", "/api/v1/matrix-groups/"),
    ("POST", "/api/v1/matrix-groups/{group_id}/assign"),
    ("POST", "/api/v1/task-state/"),
    ("POST", "/api/v1/tasks/distribution"),

    # ── C. 发布 / 审核 / 产物流转 ───────────────────────────
    ("POST", "/api/v1/publish/single"),
    ("POST", "/api/v1/publish/batch"),
    ("POST", "/api/v1/publish/debug/capture"),
    ("POST", "/api/v1/publish/presets"),
    ("PUT", "/api/v1/publish/presets/{preset_id}"),
    ("POST", "/api/v1/review/items/{review_id}/approve"),
    ("POST", "/api/v1/review/items/{review_id}/reject"),
    ("POST", "/api/v1/review/items/{review_id}/edit"),
    ("POST", "/api/v1/review/batch-approve"),
    ("POST", "/api/v1/review/batch-reject"),
    ("POST", "/api/v1/artifacts"),
    ("POST", "/api/v1/artifacts/{artifact_id}/promote"),
    ("POST", "/api/v1/artifacts/{artifact_id}/submit-review"),
    ("POST", "/api/v1/content-variants/variants/"),
    ("PUT", "/api/v1/content-variants/variants/{variant_id}"),
    ("POST", "/api/v1/content-variants/variants/{variant_id}/submit"),
    ("POST", "/api/v1/content-variants/variants/{variant_id}/approve"),
    ("POST", "/api/v1/content-variants/variants/{variant_id}/reject"),
    ("POST", "/api/v1/content-variants/variants/{variant_id}/return"),
    ("POST", "/api/v1/content-library/ideas"),
    ("POST", "/api/v1/content-library/schedule"),
    ("POST", "/api/v1/content-library/profile/build"),

    # ── D. 生成结果的状态推进(approve/reject = 产出定稿) ────
    ("POST", "/api/v1/video-pipeline/run/{run_id}/approve"),
    ("POST", "/api/v1/video-pipeline/run/{run_id}/reject"),
)


def _template_to_regex(template: str) -> re.Pattern[str]:
    """把 `/a/{id}/b` 编译成正则(`{id}` 匹配任意单段)。"""
    parts = re.split(r"(\{[^{}]+\})", template)
    out: list[str] = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            out.append(r"[^/]+")
        else:
            out.append(re.escape(part))
    return re.compile("^" + "".join(out) + r"/?$")


#: 预编译规则表(method → [(模板, 正则)])
_COMPILED: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {}
for _method, _template in READ_ONLY_RULES:
    _COMPILED.setdefault(_method, ())
    _COMPILED[_method] = _COMPILED[_method] + ((_template, _template_to_regex(_template)),)


def is_blocked_write(method: str, path: str) -> bool:
    """该 (方法, 路径) 是否落在只读拦截面内。

    只看**路径**匹配,不看业务参数 —— 避免"换个参数就绕过"。
    """
    method = (method or "").upper()
    if method not in WRITE_METHODS:
        return False
    candidates = _COMPILED.get(method)
    if not candidates:
        return False
    normalized = path or "/"
    for _tpl, rx in candidates:
        if rx.match(normalized):
            return True
    return False


def guard_enabled() -> bool:
    """紧急停用开关是否生效(默认启用)。"""
    raw = (os.getenv(DISABLE_ENV) or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def read_only_state() -> tuple[bool, str]:
    """返回 (是否只读, 原因说明)。"""
    state = load_license()
    if state.read_only:
        return True, state.message or "注册码已过期,当前为只读模式"
    return False, state.message


async def require_write_allowed(request: Request) -> None:
    """写操作守卫(路由级依赖)。只读模式下抛 403。"""
    read_only, message = read_only_state()
    if read_only:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "reason": "license_expired_read_only",
                "message": message,
                "readOnly": True,
                "upgrade": "请续费注册码以继续新增内容",
            },
        )


class ReadOnlyWriteGuard:
    """ASGI 中间件:只读模式下拦截"产出新内容"的写操作。

    刻意做成**中间件**而不是逐路由挂依赖:
      - 逐路由挂依赖必然漏挂(298 条写路由,漏一条就是一个绕过口子);
      - 中间件只在一处生效,且拦截面收敛到一张表,能审计。

    注意 middleware 的**嵌套顺序**:本中间件要看到**规范化之后**的路径
    (Next.js rewrite 可能把 `/api/v1/...` 写成 `/api/v1/v1/...`),
    所以注册位置必须**早于** `_normalize_duplicated_api_prefix`。
    Starlette 里 `add_middleware` 是"后注册 = 更外层",因此
    "先注册本中间件 → 后注册规范化中间件" 才能让规范化跑在前面。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        if method in WRITE_METHODS and is_blocked_write(method, path) and guard_enabled():
            # load_license(touch=False):只读判定不需要回写 lastSeenAt,
            # 避免每次被拦都写一次磁盘。
            state = load_license(touch=False)
            if state.read_only:
                detail = dict(_READ_ONLY_DETAIL)
                if state.message:
                    detail["message"] = state.message
                body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return

        await self.app(scope, receive, send)


__all__ = [
    "READ_ONLY_RULES",
    "WRITE_METHODS",
    "ReadOnlyWriteGuard",
    "guard_enabled",
    "is_blocked_write",
    "read_only_state",
    "require_write_allowed",
]
