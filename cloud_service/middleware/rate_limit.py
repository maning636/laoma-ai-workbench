"""cloud_service · Redis 请求级限流中间件。

设计要点
──────────
- 基于 Redis `INCR` + `EXPIRE` 实现滑动（其实是固定窗口）限流：
  每分钟最多 N 次；窗口内请求计数递增，达到上限返回 HTTP 429。
- 使用惰性 Redis 客户端：仅在实际调用限流逻辑时才 `import redis`，
  避免整个 cloud_service 启动时依赖 redis 包。
- **降级语义**：Redis 不可用时默认降级为"无限流"（打 warning），
  不阻塞业务；这既符合"限流只是二次防御"的定位，也避免 Redis
  短暂抖动让核心 API 全挂。可通过 `fallback_allow=True` 显式确认。
- 端点-维度映射：默认覆盖：
    - POST /cloud/points/freeze        → 每用户每分钟 20
    - POST /cloud/points/consume       → 每用户每分钟 20
    - POST /cloud/points/consume_by_pricing → 每用户每分钟 20
  M1 `/api/v1/ai-design/generate` 由 prism_backend 侧单独处理（该模块
  运行在另一个 FastAPI 应用下，不在 cloud_service 的 middleware 链）。
- user_id 解析：优先使用 request.state.user_id（由上游 auth 中间件设置）；
  否则从 Authorization Bearer 头取 token 的 "sub" 段作为**未校验的**
  限流维度 key（只用作分组，不做鉴权；真正的鉴权由 `get_current_user`
  依赖负责）。若都取不到，退化为 client IP。

契约
──────
    class RateLimitMiddleware:
        def __init__(self, app, *, rules, window_seconds, fallback_allow)
        async __call__(scope, receive, send)

    install_rate_limit_middleware(app, *, redis_url, rules=None, ...)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Tuple

from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Redis 客户端
# ──────────────────────────────────────────────────────────────


def _get_redis_url() -> str:
    return (
        os.getenv("CLOUD_REDIS_URL")
        or os.getenv("REDIS_URL")
        or "redis://localhost:6379/0"
    ).strip()


def _try_get_redis(redis_url: Optional[str] = None):
    """惰性获取 Redis 客户端；失败返回 None。

    不缓存实例以避免 Redis URL 变更（测试场景）导致 stale 连接；
    redis-py 自己会池化 socket。
    """
    url = redis_url or _get_redis_url()
    try:
        import redis  # type: ignore
    except ImportError:
        return None
    try:
        return redis.Redis.from_url(url, decode_responses=True,
                                    socket_connect_timeout=2)
    except Exception as exc:  # pragma: no cover
        logger.warning("[RateLimit] Redis init failed: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────
# user_id 解析
# ──────────────────────────────────────────────────────────────


def _extract_user_hint(request: Request) -> str:
    """从 request 提取"用于限流分组"的 user 标识。

    注意：这里只做**分组**用，不做鉴权。真正的身份校验由
    cloud_service.auth.router.get_current_user 负责。

    优先级：
      1. request.state.user_id（上游中间件可能已设置）
      2. Authorization Bearer token 的 sub claim（尝试用 cloud 密钥解）
      3. request.state.client_id 或 request.state.username
      4. client IP（request.client.host 或 X-Forwarded-For 首段）
      5. "anonymous"
    """
    st = getattr(request, "state", None)
    if st is not None:
        for attr in ("user_id", "client_id", "username"):
            val = getattr(st, attr, None)
            if val:
                return str(val)

    auth = (
        request.headers.get("authorization")
        or request.headers.get("Authorization")
        or ""
    ).strip()
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            sub = _try_decode_sub(token)
            if sub:
                return sub
            # 解不出 sub：仍把 token 前 32 字符当分组 key（比 IP 更精确）
            return "tok:" + token[:32]

    xff = request.headers.get("x-forwarded-for") or request.headers.get(
        "X-Forwarded-For"
    )
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return "ip:" + first
    client = getattr(request, "client", None)
    if client is not None and getattr(client, "host", None):
        return "ip:" + str(client.host)
    return "anonymous"


def _try_decode_sub(token: str) -> Optional[str]:
    """尝试解 JWT sub claim；失败返回 None。

    不 import cloud_service.auth.security 以避免循环依赖；这里只做
    best-effort 解码（HS256）。
    """
    try:
        import jwt as pyjwt  # PyJWT
    except Exception:
        return None
    try:
        from cloud_service.settings import get_settings
        secret = get_settings().get("jwt_secret") or ""
        alg = get_settings().get("jwt_algorithm") or "HS256"
        if not secret:
            return None
        payload = pyjwt.decode(token, secret, algorithms=[alg], options={"verify_exp": False})
        sub = payload.get("sub")
        if sub is None:
            return None
        return str(sub)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
# 限流规则
# ──────────────────────────────────────────────────────────────


Rule = Tuple[Tuple[str, str], int]  # ((method, path_glob), max_per_window)


DEFAULT_RULES: Tuple[Rule, ...] = (
    # M3 高频/敏感端点：每用户每分钟 N 次。
    (("POST", "/cloud/points/freeze"), 20),
    (("POST", "/cloud/points/consume"), 20),
    (("POST", "/cloud/points/consume_by_pricing"), 20),
    # M1 AI 生图：单次可能触发多次 provider 调用 + 冻结积分，严格一点。
    # 该路径通常由 prism_backend 自己的 FastAPI app 处理；此处保留规则以便
    # 未来若 cloud_service 承载 M1 转发，规则也自动生效。
    (("POST", "/api/v1/ai-design/generate"), 10),
    (("POST", "/ai-design/generate"), 10),
)


def _glob_match(pattern: str, path: str) -> bool:
    """极简 glob：支持 `*` 作为"任意字符串"（不跨越 `/`）。

    只用于限流规则的路径匹配，不需要完整 glob 语义。
    """
    if pattern == path:
        return True
    if "*" not in pattern:
        return False
    parts = pattern.split("*")
    if len(parts) == 2:
        return path.startswith(parts[0]) and path.endswith(parts[1])
    if len(parts) == 3:
        return (
            path.startswith(parts[0])
            and path.endswith(parts[2])
            and parts[1] in path
        )
    return False


def _match_rule(rules: Iterable[Rule], method: str, path: str) -> Optional[int]:
    for (rule_method, pattern), limit in rules:
        if method.upper() != rule_method.upper():
            continue
        if _glob_match(pattern, path):
            return int(limit)
    return None


# ──────────────────────────────────────────────────────────────
# Middleware
# ──────────────────────────────────────────────────────────────


class RateLimitMiddleware:
    """ASGI 中间件：按 (user, path_glob) 每分钟限流。"""

    def __init__(
        self,
        app: Any,
        *,
        rules: Iterable[Rule] = DEFAULT_RULES,
        window_seconds: int = 60,
        redis_url: Optional[str] = None,
        key_prefix: str = "cloud:rate:",
        fallback_allow: bool = True,
    ) -> None:
        self.app = app
        self.rules = tuple(rules)
        self.window = int(window_seconds)
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.fallback_allow = fallback_allow

    async def __call__(
        self,
        scope: Dict[str, Any],
        receive: Callable[[], Awaitable[Dict[str, Any]]],
        send: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        method = (scope.get("method") or "").upper()
        path = scope.get("path") or request.url.path

        limit = _match_rule(self.rules, method, path)
        if limit is None:
            await self.app(scope, receive, send)
            return

        user = _extract_user_hint(request)
        key = f"{self.key_prefix}{user}:{path}"

        allowed, retry_after = await asyncio.to_thread(
            self._check_rate, key, limit
        )
        if allowed:
            await self.app(scope, receive, send)
            return

        # 超过限额：返回 429
        response = JSONResponse(
            status_code=429,
            content={
                "detail": f"Too many requests: {limit} per {self.window}s",
                "retry_after": retry_after,
                "limit": limit,
                "window_seconds": self.window,
            },
            headers={"Retry-After": str(retry_after)},
        )
        await response(scope, receive, send)

    def _check_rate(self, key: str, limit: int) -> Tuple[bool, int]:
        """同步执行：返回 (allowed, retry_after_seconds)。"""
        r = _try_get_redis(self.redis_url)
        if r is None:
            if self.fallback_allow:
                logger.warning(
                    "[RateLimit] Redis unavailable; allowing request on %s", key
                )
                return True, 0
            return False, self.window

        try:
            count = int(r.incr(key) or 0)
            # 首次 INCR 后 TTL 未设置（或已过期）→ 立即补 TTL
            ttl_remaining = r.ttl(key)
            if ttl_remaining is None or ttl_remaining < 0:
                r.expire(key, self.window)
        except Exception as exc:
            if self.fallback_allow:
                logger.warning(
                    "[RateLimit] Redis error on %s: %s; allowing", key, exc
                )
                return True, 0
            return False, self.window

        if count > limit:
            retry_after = max(1, self.window)
            return False, retry_after
        return True, 0


# ──────────────────────────────────────────────────────────────
# 便捷安装
# ──────────────────────────────────────────────────────────────


def install_rate_limit_middleware(
    app: Any,
    *,
    rules: Optional[Iterable[Rule]] = None,
    window_seconds: int = 60,
    redis_url: Optional[str] = None,
    enabled: bool = True,
    fallback_allow: bool = True,
) -> None:
    """在 FastAPI/Starlette app 上安装 RateLimitMiddleware。

    `enabled=False` 时不安装（供测试或灰度使用）。
    """
    if not enabled:
        return
    from starlette.middleware import Middleware
    app.add_middleware(
        RateLimitMiddleware,
        rules=DEFAULT_RULES if rules is None else rules,
        window_seconds=window_seconds,
        redis_url=redis_url,
        fallback_allow=fallback_allow,
    )


__all__ = [
    "RateLimitMiddleware",
    "install_rate_limit_middleware",
    "DEFAULT_RULES",
]
