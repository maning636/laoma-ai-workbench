"""C14a:客户端 prompt 分层路由(双版本切换)。

设计(§2.2 双版本 prompt 分层):
  - `cloud tier` — 高价值 prompt,客户端**看不到模板**,只能按 `name` 触发:
      `GET /cloud/llm/prompts` 拿名字列表 → `POST /cloud/llm/chat` 让云端渲染 + 调 LLM。
  - `basic tier` — 基础模板,允许离线版复用:
      本地 `prompts_basic.py::BASIC_PROMPTS` 快照渲染。

切换策略(`pick_tier()`):
    ┌────────────────────────────────────────────────────────────────────┐
    │ 有订阅 + 云端可达   →  "cloud"  (cloud tier 走云端, basic 也走云端)│
    │ 有订阅 + 云端不可达 →  "basic"  (本地快照兜底)                      │
    │ 无订阅 / 未登录     →  "basic"  (只有本地基础功能可用)              │
    │ 离线模式(打包版)   →  "basic"  (云端永远不通,直接本地)            │
    └────────────────────────────────────────────────────────────────────┘

不启动真服务:所有云端交互都通过**可注入的 transport**(默认 `httpx`,测试用桩),
`pick_tier()` 本身是同步函数,不发起 I/O —— 由上层(如 `fusion_ai/router.py`)决定何时探测连通性。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


# ──────────────────────────────────────────────────────────────
# 依赖注入:云端可达性探测 & HTTP 客户端
# ──────────────────────────────────────────────────────────────

#: 云端可达性检查函数签名:`() -> bool`。默认实现是超时短(1.5s)的 `/cloud/llm/health` GET。
HealthCheckFn = Callable[[], bool]

#: Cloud LLM 调用函数签名:`(prompt_name: str, variables: dict) -> dict`。
CloudChatFn = Callable[[str, dict[str, Any]], dict[str, Any]]


# ──────────────────────────────────────────────────────────────
# 依赖(默认导入,但保留替换空间)
# ──────────────────────────────────────────────────────────────

from . import prompts_basic as _pb  # noqa: E402


# ──────────────────────────────────────────────────────────────
# 状态对象
# ──────────────────────────────────────────────────────────────

@dataclass
class TierContext:
    """tier 决策所需的运行时上下文。

    由调用方组装(例如从 auth state / config / feature flag 里读):
      - `subscribed`: 当前用户是否处于活跃订阅态
      - `cloud_base_url`: 云端 API 基址,如 `https://api.prism.local/cloud`
      - `cloud_reachable`: 上层探测过一次的连通性结果(可选;None 表示未探测)
      - `offline_packaged`: 是否打包为离线版(True 时永远走 basic)
      - `force_tier`: 强制覆盖("cloud" / "basic" / None),用于开发/测试
    """

    subscribed: bool = False
    cloud_base_url: str = ""
    cloud_reachable: bool | None = None
    offline_packaged: bool = False
    force_tier: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptRoute:
    """一次 prompt 触发的路由决策结果。"""

    tier: str  # "cloud" | "basic"
    prompt_name: str
    variables: dict[str, Any]
    #: 若 tier == "basic",这里给出**渲染后**的模板文本(可直接投给本地 LLM);
    #: 若 tier == "cloud",这里为 None,调用方需走 `POST /cloud/llm/chat`。
    rendered_local: str | None = None


# ──────────────────────────────────────────────────────────────
# tier 选择
# ──────────────────────────────────────────────────────────────

def pick_tier(ctx: TierContext) -> str:
    """根据运行时上下文返回 "cloud" 或 "basic"。

    决策顺序(短路):
      1. `force_tier` 显式指定 → 直接返回(仅允许 cloud/basic)
      2. `offline_packaged` → basic
      3. `subscribed` 且 `cloud_reachable` → cloud
      4. 其余 → basic
    """
    if ctx.force_tier in {"cloud", "basic"}:
        return ctx.force_tier
    if ctx.offline_packaged:
        return "basic"
    if ctx.subscribed and ctx.cloud_reachable:
        return "cloud"
    return "basic"


def should_use_cloud(prompt_name: str, ctx: TierContext) -> bool:
    """便捷查询:某个 prompt 名在当前上下文里是否走云端。"""
    return pick_tier(ctx) == "cloud"


# ──────────────────────────────────────────────────────────────
# 渲染 & 路由
# ──────────────────────────────────────────────────────────────

def render_local_basic(prompt_name: str, variables: dict[str, Any] | None = None) -> str | None:
    """从本地 `BASIC_PROMPTS` 快照渲染。找不到名字 → 返回 None。

    缺失变量不会抛异常 —— 会渲染为 `{{ key }}` 字面量(与云端语义一致)。
    """
    p = _pb.get_prompt(prompt_name)
    if p is None:
        return None
    return p.render(variables or {})


def route_prompt(
    prompt_name: str,
    variables: dict[str, Any] | None,
    ctx: TierContext,
) -> PromptRoute:
    """同步路由决策 + basic 场景下的本地渲染。

    返回 `PromptRoute`:
      - tier == "cloud" → `rendered_local=None`,由调用方决定如何 `POST /cloud/llm/chat`。
      - tier == "basic" 且名字在 `BASIC_PROMPTS` 里 → `rendered_local` 已渲染好。
      - tier == "basic" 但名字是 cloud tier(如 `cognition.matrix_evaluate`)
            → `rendered_local=None`,调用方需给出降级 UI 提示(离线版不提供该能力)。
    """
    variables = variables or {}
    tier = pick_tier(ctx)

    if tier == "cloud":
        return PromptRoute(tier="cloud", prompt_name=prompt_name, variables=variables, rendered_local=None)

    # tier == "basic"
    rendered = render_local_basic(prompt_name, variables)
    return PromptRoute(
        tier="basic",
        prompt_name=prompt_name,
        variables=variables,
        rendered_local=rendered,
    )


def list_available_names(ctx: TierContext, cloud_names: list[str] | None = None) -> list[str]:
    """列出当前上下文下**可用**的 prompt 名(供前端菜单展示)。

    - tier == "cloud": 返回云端 `cloud_names`(需要上层先 GET /cloud/llm/prompts 拿)。
    - tier == "basic": 返回本地快照里 basic tier 的所有名字。

    `cloud_names=None` 且 tier=="cloud" 时,返回空列表(未探测)—— 上层应触发一次
    `/cloud/llm/prompts` 请求后再传入结果。
    """
    tier = pick_tier(ctx)
    if tier == "cloud":
        return list(cloud_names or [])
    return _pb.list_names()


# ──────────────────────────────────────────────────────────────
# 云端可达性探测(默认实现,可注入替换)
# ──────────────────────────────────────────────────────────────

def _default_health_check(ctx: TierContext, timeout_sec: float = 1.5) -> bool:
    """默认探测:GET `{cloud_base_url}/llm/health`。

    - 网络错 / 非 200 / 超时 → False
    - 该函数**不**校验 JWT(health 端点公开)
    - 生产环境可用更轻量的 HTTP HEAD;此处用 GET 以兼容所有网关配置。
    """
    if not ctx.cloud_base_url:
        return False
    try:
        # httpx 是客户端已声明依赖,若未安装则视为不可达(离线场景常见)
        import httpx  # type: ignore
    except Exception:
        return False

    url = ctx.cloud_base_url.rstrip("/") + "/llm/health"
    try:
        r = httpx.get(url, timeout=timeout_sec)
        return r.status_code == 200
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# 便捷:一次性路由 + 云端调用(可选)
# ──────────────────────────────────────────────────────────────

def invoke(
    prompt_name: str,
    variables: dict[str, Any] | None,
    ctx: TierContext,
    *,
    health_check: HealthCheckFn | None = None,
    cloud_chat: CloudChatFn | None = None,
) -> dict[str, Any]:
    """端到端调用:自动探测云端、决定 tier、返回 `{tier, content?, error?}`。

    参数:
      - `health_check`: 可选,注入自定义连通性检查函数(默认 `_default_health_check`)。
      - `cloud_chat`: 可选,注入云端 LLM 调用函数(默认用 httpx 调 `POST /cloud/llm/chat`)。

    返回:
      - tier == "cloud" 且云端 OK  → `{"tier": "cloud", "content": "..."}`
      - tier == "basic" 且名字可用  → `{"tier": "basic", "rendered": "..."}`
      - 其它情况 → `{"tier": "...", "error": "..."}`
    """
    hc = health_check or (lambda: _default_health_check(ctx))
    reachable = bool(hc()) if callable(hc) else False
    ctx = TierContext(
        subscribed=ctx.subscribed,
        cloud_base_url=ctx.cloud_base_url,
        cloud_reachable=reachable,
        offline_packaged=ctx.offline_packaged,
        force_tier=ctx.force_tier,
        extra=ctx.extra,
    )

    route = route_prompt(prompt_name, variables or {}, ctx)

    if route.tier == "basic":
        if route.rendered_local is None:
            return {
                "tier": "basic",
                "error": f"prompt {prompt_name!r} not available in offline basic snapshot",
            }
        return {"tier": "basic", "rendered": route.rendered_local}

    # tier == "cloud"
    if cloud_chat is None:
        # 未注入云端调用 —— 只返回渲染信息,由调用方自己打 API
        return {"tier": "cloud", "prompt_name": prompt_name, "variables": variables or {}}
    try:
        result = cloud_chat(prompt_name, variables or {})
        return {"tier": "cloud", "content": result.get("content", ""), "meta": result}
    except Exception as exc:  # pragma: no cover - 上层调用方应捕获
        return {"tier": "cloud", "error": f"{exc.__class__.__name__}: {exc}"}


__all__ = [
    "TierContext",
    "PromptRoute",
    "HealthCheckFn",
    "CloudChatFn",
    "pick_tier",
    "should_use_cloud",
    "render_local_basic",
    "route_prompt",
    "list_available_names",
    "invoke",
]
