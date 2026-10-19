"""客户端 Open Core Feature Gate 消费模块。

职责
────
    1. 拉取云端 feature flags：HTTP GET <CLOUD_URL>/cloud/feature-flags
       （云端实现见 `cloud_service/billing/feature_gate.py` +
        `cloud_service/billing/router.py::get_feature_flags`）。
    2. 用 Redis + 内存双层缓存（TTL 5 分钟），减少云端调用次数。
    3. 云端不可达 / 未登录 / 未知用户 → **回落 Community 默认 flag**
       （不阻断基本体验，仅记 warning 日志）。
    4. 提供三个业务侧 helper：
       - `get_feature_flags(user_id)`       → `{plan, flags}`
       - `check_feature(user_id, feature)`  → `{"allowed": bool, ...}`
       - `check_quota(user_id, feature, current_count)` → `{"allowed", "limit", ...}`
    5. 提供两个便捷 gate（业务 API 内直接调用）：
       - `require_feature(user_id, feature)`  → 未授权时抛 HTTPException(403)
       - `require_quota(user_id, feature, current_count)` → 超额时抛 403

设计原则
────────
    - **不修改任何云端订阅状态**：本模块只做只读拉取。
    - **不阻断离线体验**：云端不可达 → 默认 Community flag（含 max_accounts=3、
      ai_mode='local_key' 等），本地基础功能（自配 key 的 LLM、Cookie 上传、
      平台自动化）不受影响。
    - **向后兼容**：无 JWT / 匿名调用 → 回落 Community，不影响未改造的老接口。
    - **测试友好**：`BillingClient` 允许注入 transport（httpx 替身）、cache
      backend、base_url，便于 mock 云端响应。

端点契约（与云端 `feature_gate.py` 一致）
────────────────────────
    GET <CLOUD_URL>/cloud/feature-flags
      Header:  Authorization: Bearer <user_access_token>
      Response 200:
        {
          "plan": "community" | "pro",
          "flags": {
            "max_accounts": 3 | -1,
            "max_platforms": 3 | 8,
            "ai_mode": "local_key" | "cloud",
            "image_gen": "local_key" | "cloud",
            "agent_quota": 0 | 2,
            "data_recovery": false | true,
            "persona": false | true,
            "proxy_management": false | true,
            "stream_chat": false | true,
            "team_members": 1
          }
        }

Flag 语义（与云端 FEATURE_NAMES 对齐）
    - **布尔型** (data_recovery / persona / proxy_management / stream_chat):
      `allowed = (flag is True)`；False → 403 `upgrade_required`。
    - **数值型** (max_accounts / max_platforms / agent_quota / team_members):
      `allowed = (flag != 0)`；`-1` 表示无限。
      配额超限由业务 API 用 `check_quota` / `require_quota` 判定。
    - **模式型** (ai_mode / image_gen):
      `allowed` 恒为 True，业务方按 limit ("local_key" | "cloud") 切换路径；
      Community 用户请求"云端模式"由业务侧拦截（本模块不主动拦截）。

环境变量
    - `CLOUD_URL`                 云端根 URL（如 `https://api.prism.local`）
    - `LAOMA_CLOUD_BASE_URL`      备选根 URL（与 `points_client.py` /
                                  `cloud_gateway.py` 保持一致）
    - `FEATURE_FLAGS_CACHE_TTL`   Redis 缓存 TTL（秒），默认 300
    - `FEATURE_FLAGS_DISABLED`    设为 `1` / `true` / `yes` 时**完全跳过云端**
                                  （离线开发 / 单元调试用），全走 Community flag
    - `FEATURE_FLAGS_TIMEOUT`     HTTP 超时（秒），默认 5.0

修改记录
    - 2026-10-19 新建：`M3 feature gate 消费`（对应
      `docs/dev-reports/2026-10-16-feature-flag-client.md`）。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Dict, Optional

try:
    from fastapi_app.core.logger import logger  # type: ignore
except Exception:  # pragma: no cover - 独立运行时降级
    try:
        import logging

        logger = logging.getLogger(__name__)
    except Exception:
        logger = None


# ──────────────────────────────────────────────────────────────
# 常量 & 默认值
# ──────────────────────────────────────────────────────────────

# 云端 base URL 环境变量（与 `fusion_ai/points_client.py` 一致）
_ENV_CLOUD_BASE_URL = "CLOUD_URL"
_ENV_CLOUD_BASE_URL_ALT = "LAOMA_CLOUD_BASE_URL"
_DEFAULT_CLOUD_BASE_URL = "https://api.prism.local"

# Redis 缓存 TTL（秒）
_FLAGS_CACHE_TTL_DEFAULT = 300  # 5 分钟
_FLAGS_CACHE_KEY_PREFIX = "billing:flags:"

# HTTP 超时（秒）
_FLAGS_HTTP_TIMEOUT_DEFAULT = 5.0

# 内存缓存（Redis 不可达时的二级缓存）
_IN_MEMORY_CACHE_TTL_DEFAULT = 30

# Feature 名称清单（与云端 FEATURE_NAMES 对齐，用于校验 & 类型分发）
FEATURE_NAMES: tuple = (
    "max_accounts",
    "max_platforms",
    "ai_mode",
    "image_gen",
    "agent_quota",
    "data_recovery",
    "persona",
    "proxy_management",
    "stream_chat",
    "team_members",
)

# 三类 flag 分组
_BOOL_FEATURES = frozenset({
    "data_recovery",
    "persona",
    "proxy_management",
    "stream_chat",
})
_NUMERIC_FEATURES = frozenset({
    "max_accounts",
    "max_platforms",
    "agent_quota",
    "team_members",
})
_MODE_FEATURES = frozenset({
    "ai_mode",
    "image_gen",
})

# Community 默认 flag（云端不可达时回落，与云端 COMMUNITY_FLAGS 一致）
COMMUNITY_FLAGS: Dict[str, Any] = {
    "max_accounts": 3,
    "max_platforms": 3,
    "ai_mode": "local_key",
    "image_gen": "local_key",
    "agent_quota": 0,
    "data_recovery": False,
    "persona": False,
    "proxy_management": False,
    "stream_chat": False,
    "team_members": 1,
}

# Pro 默认 flag（仅作为参考，实际由云端下发；本地不硬编码使用）
PRO_FLAGS: Dict[str, Any] = {
    "max_accounts": -1,
    "max_platforms": 8,
    "ai_mode": "cloud",
    "image_gen": "cloud",
    "agent_quota": 2,
    "data_recovery": True,
    "persona": True,
    "proxy_management": True,
    "stream_chat": True,
    "team_members": 1,
}


def _log(msg: str, *args: Any) -> None:
    """安全的 warning 日志（logger 不存在时静默）。"""
    if logger is None:
        return
    try:
        logger.warning(msg, *args)
    except Exception:
        pass


def _truthy(raw: Any) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _default_base_url() -> str:
    """优先 CLOUD_URL，其次 LAOMA_CLOUD_BASE_URL，最后默认值。

    与 `points_client.py` / `cloud_gateway.py` 的 base_url 解析保持一致，
    方便运维在同一环境变量下配置多个客户端。
    """
    raw = (
        os.getenv(_ENV_CLOUD_BASE_URL)
        or os.getenv(_ENV_CLOUD_BASE_URL_ALT)
        or _DEFAULT_CLOUD_BASE_URL
    )
    return raw.rstrip("/")


def _flags_path() -> str:
    return "/cloud/feature-flags"


def _cache_key(user_id: str) -> str:
    """Redis 缓存 key。"""
    return f"{_FLAGS_CACHE_KEY_PREFIX}{user_id}"


# ──────────────────────────────────────────────────────────────
# 内存缓存（Redis 不可用时的二级缓存）
# ──────────────────────────────────────────────────────────────

class _InMemoryFlagsCache:
    """进程内 dict 缓存。多 worker 部署时会不共享，但对 5 分钟 TTL 的
    flag 快照完全够用；比"永远 miss"性能好，且完全不引入 Redis 依赖。
    """

    def __init__(self, ttl_seconds: int = _IN_MEMORY_CACHE_TTL_DEFAULT) -> None:
        self._ttl = ttl_seconds
        self._data: Dict[str, tuple] = {}  # key → (expire_at_ms, payload)
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expire_at, payload = entry
            if now >= expire_at:
                del self._data[key]
                return None
            return dict(payload)  # 拷贝避免外部修改

    def set(self, key: str, payload: Dict[str, Any]) -> None:
        now = time.time()
        with self._lock:
            self._data[key] = (now + self._ttl, dict(payload))

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_IN_MEMORY_CACHE = _InMemoryFlagsCache()


# ──────────────────────────────────────────────────────────────
# 客户端主类
# ──────────────────────────────────────────────────────────────

TransportFn = Callable[..., Dict[str, Any]]


class BillingClient:
    """拉取并缓存云端 feature flags 的客户端。

    典型使用::

        client = BillingClient()
        snapshot = client.get_feature_flags(user_id="42")
        # → {"plan": "pro", "flags": {...}}

        if not client.check_feature("42", "data_recovery")["allowed"]:
            raise HTTPException(403, ...)
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        transport: Optional[TransportFn] = None,
        cache_backend: Optional[Any] = None,
        cache_ttl_seconds: Optional[int] = None,
        timeout: Optional[float] = None,
        features_disabled: Optional[bool] = None,
        in_memory_cache: Optional[_InMemoryFlagsCache] = None,
    ) -> None:
        self._base_url = (
            (base_url or _default_base_url()).rstrip("/")
            if base_url is not None
            else _default_base_url().rstrip("/")
        )
        # features_disabled：完全跳过云端（离线开发 / 单测用）
        if features_disabled is None:
            features_disabled = _truthy(os.getenv("FEATURE_FLAGS_DISABLED", ""))
        self._features_disabled = bool(features_disabled)

        self._transport = transport or self._default_transport
        self._cache = cache_backend
        self._cache_ttl = int(cache_ttl_seconds if cache_ttl_seconds is not None
                              else _env_int("FEATURE_FLAGS_CACHE_TTL", _FLAGS_CACHE_TTL_DEFAULT))
        self._timeout = float(timeout if timeout is not None
                              else _env_float("FEATURE_FLAGS_TIMEOUT", _FLAGS_HTTP_TIMEOUT_DEFAULT))
        self._in_memory_cache = in_memory_cache or _IN_MEMORY_CACHE

    # ── 内部：默认 transport ────────────────────────────────

    def _default_transport(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        """httpx 同步调用；异常时抛 RuntimeError，由上层捕获回落 Community。"""
        import httpx

        with httpx.Client(timeout=timeout or self._timeout) as client:
            r = client.request(
                method.upper(),
                url,
                headers=headers or {},
                json=json,
                timeout=timeout or self._timeout,
            )
            try:
                data: Any = r.json() if r.content else {}
            except Exception:
                data = {}
            return {"status_code": r.status_code, "data": data}

    # ── 内部：缓存 I/O ──────────────────────────────────────

    def _cache_get(self, user_id: str) -> Optional[Dict[str, Any]]:
        key = _cache_key(user_id)
        # 1. Redis
        if self._cache is not None:
            try:
                raw = self._cache.get(key)
                if raw:
                    import json as _json
                    return _json.loads(raw)
            except Exception:
                pass
        # 2. 内存
        return self._in_memory_cache.get(user_id)

    def _cache_set(self, user_id: str, payload: Dict[str, Any]) -> None:
        key = _cache_key(user_id)
        # Redis（写失败静默降级）
        if self._cache is not None:
            try:
                import json as _json
                self._cache.setex(
                    key,
                    self._cache_ttl,
                    _json.dumps(payload, ensure_ascii=False),
                )
            except Exception:
                pass
        # 内存（永远写入，即使 Redis 不可用）
        try:
            self._in_memory_cache.set(user_id, payload)
        except Exception:
            pass

    # ── 内部：默认 token provider（无 token → 不发送）───────

    @staticmethod
    def _default_token_provider(headers: Optional[Dict[str, str]]) -> str:
        if headers is None:
            return ""
        for k, v in headers.items():
            if k.lower() == "authorization":
                val = (v or "").strip()
                if val.lower().startswith("bearer "):
                    return val.split(" ", 1)[1].strip()
                return val
        return ""

    # ── 内部：拉取云端 flags ────────────────────────────────

    def _fetch_remote_flags(self, token: str) -> Dict[str, Any]:
        """GET /cloud/feature-flags；失败抛 RuntimeError。"""
        url = f"{self._base_url}{_flags_path()}"
        headers = {
            "Accept": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        resp = self._transport(
            "GET", url,
            headers=headers,
            timeout=self._timeout,
        )
        status_code = int(resp.get("status_code") or 0)
        if status_code == 200:
            data = resp.get("data") or {}
            return self._normalize_snapshot(data)
        raise RuntimeError(
            f"cloud billing /feature-flags returned status {status_code}: "
            f"{resp.get('data')!r}"
        )

    @staticmethod
    def _normalize_snapshot(data: Any) -> Dict[str, Any]:
        """把云端返回标准化为 {plan, flags}。

        兼容两种响应形态：
          - 云端 `feature-flags` 端点：`{"plan": ..., "flags": {...}}`
          - 云端旧版 `feature_flags`：`{"plan": ..., "allowed": [...], "denied": [...], "limit": {...}}`
            （合并 allowed/denied/limit 为 flags）
        """
        if not isinstance(data, dict):
            raise ValueError(f"unexpected flags payload: {type(data).__name__}")
        plan = data.get("plan") or "community"
        if "flags" in data and isinstance(data["flags"], dict):
            flags = dict(data["flags"])
        else:
            # 兼容旧形态
            flags: Dict[str, Any] = {}
            for name in FEATURE_NAMES:
                if name in data.get("denied", []):
                    flags[name] = COMMUNITY_FLAGS.get(name)
                elif name in data.get("allowed", []):
                    if name in _NUMERIC_FEATURES and name in data.get("limit", {}):
                        flags[name] = data["limit"][name]
                    elif name in _BOOL_FEATURES:
                        flags[name] = True
                    elif name in _MODE_FEATURES:
                        flags[name] = data.get(name) or "cloud"
                    else:
                        flags[name] = True
        return {"plan": plan, "flags": flags}

    # ── 公开 API ─────────────────────────────────────────────

    def get_feature_flags(
        self,
        user_id: Optional[str],
        token: str = "",
        *,
        headers: Optional[Dict[str, str]] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """返回 `{plan, flags}`。

        优先级：
          1. `features_disabled=True`  → 直接返回 Community 默认 flag
          2. 缓存命中                  → 直接返回缓存
          3. HTTP GET /feature-flags   → 命中则写缓存后返回
          4. 任何异常                  → 回落 Community（记 warning）

        Args:
          user_id: 用户 ID（从 JWT `sub` 或业务逻辑获取）；None/空 → 直接 Community
          token:   云端 access token；空字符串 → 云端返回 Community（未登录）
          headers: 用于从 Authorization header 兜底提取 token
        """
        # features_disabled 短路（离线模式）
        if self._features_disabled:
            return {"plan": "community", "flags": dict(COMMUNITY_FLAGS)}

        uid = (user_id or "").strip()
        if not uid:
            # 无用户 → 直接 Community（不写缓存，避免污染）
            return {"plan": "community", "flags": dict(COMMUNITY_FLAGS)}

        # 1. 缓存
        if not force_refresh:
            cached = self._cache_get(uid)
            if cached is not None:
                return cached

        # 2. 云端拉取
        token = token or self._default_token_provider(headers)
        try:
            snapshot = self._fetch_remote_flags(token)
            # 校验 plan / flags 字段
            plan = snapshot.get("plan")
            flags = snapshot.get("flags")
            if plan not in {"community", "pro"} or not isinstance(flags, dict):
                raise ValueError(
                    f"invalid flags payload: plan={plan!r} flags_type={type(flags).__name__}"
                )
            self._cache_set(uid, snapshot)
            return snapshot
        except Exception as exc:  # noqa: BLE001
            _log(
                "billing_client: failed to fetch flags for user=%s, "
                "fallback to Community default: %s",
                uid, exc,
            )
            return {"plan": "community", "flags": dict(COMMUNITY_FLAGS)}

    def get_flag(self, user_id: Optional[str], feature_name: str, **kwargs: Any) -> Any:
        """便捷方法：直接取单个 flag 值。未知 feature 抛 ValueError。"""
        if feature_name not in FEATURE_NAMES:
            raise ValueError(
                f"unknown feature: {feature_name!r}; supported: {sorted(FEATURE_NAMES)}"
            )
        snap = self.get_feature_flags(user_id, **kwargs)
        return snap["flags"].get(feature_name)

    def check_feature(
        self,
        user_id: Optional[str],
        feature_name: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """检查单个 feature；返回结构对齐云端 `FeatureCheckResult`。

        返回::

            {
              "feature": "data_recovery",
              "allowed": True,
              "plan": "pro",
              "limit": None,     # 布尔型为 None；数值型为 flag 值；模式型为字符串
              "reason": "ok",    # "ok" | "upgrade_required"
            }
        """
        if feature_name not in FEATURE_NAMES:
            raise ValueError(
                f"unknown feature: {feature_name!r}; supported: {sorted(FEATURE_NAMES)}"
            )
        snap = self.get_feature_flags(user_id, **kwargs)
        plan = snap["plan"]
        value = snap["flags"].get(feature_name, COMMUNITY_FLAGS.get(feature_name))

        if feature_name in _BOOL_FEATURES:
            allowed = bool(value)
            return {
                "feature": feature_name,
                "allowed": allowed,
                "plan": plan,
                "limit": None,
                "reason": "ok" if allowed else "upgrade_required",
            }
        if feature_name in _MODE_FEATURES:
            return {
                "feature": feature_name,
                "allowed": True,  # 模式型总是可用
                "plan": plan,
                "limit": value,   # "local_key" | "cloud"
                "reason": "ok",
            }
        # 数值型
        try:
            limit = int(value)
        except (TypeError, ValueError):
            limit = 0
        allowed = limit != 0  # 0 = 明确禁用
        return {
            "feature": feature_name,
            "allowed": allowed,
            "plan": plan,
            "limit": limit,
            "reason": "ok" if allowed else "upgrade_required",
        }

    def check_quota(
        self,
        user_id: Optional[str],
        feature_name: str,
        current_count: int = 0,
        *,
        increment: int = 1,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """配额检查。返回::

            {
              "allowed": bool,       # 是否允许再增加 increment 个
              "limit": int,          # -1 表示无限
              "current": int,        # current_count
              "requested": int,      # increment
              "plan": str,
              "reason": str,         # "ok" | "quota_exceeded" | "upgrade_required"
            }
        """
        if feature_name not in _NUMERIC_FEATURES:
            raise ValueError(
                f"check_quota only supports numeric quota features; got {feature_name!r}"
            )
        info = self.check_feature(user_id, feature_name, **kwargs)
        limit = info["limit"]
        plan = info["plan"]

        if limit == -1:
            return {
                "allowed": True,
                "limit": -1,
                "current": current_count,
                "requested": increment,
                "plan": plan,
                "reason": "ok",
            }
        if current_count < 0:
            current_count = 0
        new_count = current_count + max(0, increment)
        if new_count > limit:
            return {
                "allowed": False,
                "limit": limit,
                "current": current_count,
                "requested": increment,
                "plan": plan,
                "reason": "quota_exceeded",
            }
        return {
            "allowed": True,
            "limit": limit,
            "current": current_count,
            "requested": increment,
            "plan": plan,
            "reason": "ok",
        }

    def clear_cache(self, user_id: Optional[str] = None) -> None:
        """清空缓存（测试或订阅状态变更后调用）。"""
        if user_id:
            key = _cache_key(user_id)
            if self._cache is not None:
                try:
                    self._cache.delete(key)
                except Exception:
                    pass
        self._in_memory_cache.clear()


# ──────────────────────────────────────────────────────────────
# 全局单例 & 便捷 API
# ──────────────────────────────────────────────────────────────

_DEFAULT_CLIENT: Optional[BillingClient] = None
_DEFAULT_CLIENT_LOCK = threading.Lock()


def _get_default_redis() -> Optional[Any]:
    """延迟导入 fastapi_app 的 Redis 客户端；失败时返回 None（跳过 Redis 缓存）。"""
    try:
        from fastapi_app.cache.redis_client import get_redis  # type: ignore
        return get_redis()
    except Exception:
        return None


def get_default_client() -> BillingClient:
    """返回全局共享的 BillingClient（懒加载）。

    线程安全；首次调用时才构造 Redis 客户端，避免 import 时连 Redis。
    """
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        with _DEFAULT_CLIENT_LOCK:
            if _DEFAULT_CLIENT is None:
                _DEFAULT_CLIENT = BillingClient(cache_backend=_get_default_redis())
    return _DEFAULT_CLIENT


def set_default_client(client: Optional[BillingClient]) -> None:
    """测试注入：替换全局客户端；传 None 清除。"""
    global _DEFAULT_CLIENT
    _DEFAULT_CLIENT = client


def get_feature_flags(
    user_id: Optional[str],
    token: str = "",
    *,
    headers: Optional[Dict[str, str]] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    return get_default_client().get_feature_flags(
        user_id, token, headers=headers, force_refresh=force_refresh
    )


def get_flag(user_id: Optional[str], feature_name: str, **kwargs: Any) -> Any:
    return get_default_client().get_flag(user_id, feature_name, **kwargs)


def clear_cache(user_id: Optional[str] = None) -> None:
    get_default_client().clear_cache(user_id)


def check_feature(
    user_id: Optional[str],
    feature_name: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    return get_default_client().check_feature(user_id, feature_name, **kwargs)


def check_quota(
    user_id: Optional[str],
    feature_name: str,
    current_count: int = 0,
    *,
    increment: int = 1,
    **kwargs: Any,
) -> Dict[str, Any]:
    return get_default_client().check_quota(
        user_id, feature_name, current_count, increment=increment, **kwargs
    )


# ──────────────────────────────────────────────────────────────
# 便捷 gate：业务 API 直接调用，未授权 / 超额时抛 403
# ──────────────────────────────────────────────────────────────

def _upgrade_detail(feature_name: str, plan: str, *, reason: str,
                    limit: Any = None, current: Any = None) -> Dict[str, Any]:
    """统一的 403 detail 结构（Open Core 契约：仅 reason/required_plan/feature）。

    保留 `plan`/`limit`/`current` 参数以兼容调用方，但不写入 response，
    避免暴露内部字段。
    """
    return {
        "reason": reason,
        "required_plan": "pro",
        "feature": feature_name,
    }


def require_feature(
    user_id: Optional[str],
    feature_name: str,
    *,
    token: str = "",
    headers: Optional[Dict[str, str]] = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """未授权时抛 `HTTPException(403)`。

    使用场景：布尔型 flag（data_recovery / persona / stream_chat …）或
    明确禁用的数值型 flag（agent_quota=0 时创建智能体）。
    """
    # 延迟导入 HTTPException，避免模块 import 时依赖 FastAPI
    from fastapi import HTTPException, status as http_status

    info = check_feature(user_id, feature_name, token=token, headers=headers)
    if info["allowed"]:
        return info
    # Open Core 契约：所有 403 均使用 "upgrade_required"（覆盖内部 check_feature
    # 返回的 reason，例如 "feature_denied" 等）。
    detail = _upgrade_detail(
        feature_name, info["plan"], reason="upgrade_required", limit=info.get("limit"),
    )
    if message:
        detail["message"] = message
    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def require_quota(
    user_id: Optional[str],
    feature_name: str,
    current_count: int = 0,
    *,
    token: str = "",
    headers: Optional[Dict[str, str]] = None,
    increment: int = 1,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """超额时抛 `HTTPException(403)`。

    使用场景：max_accounts / max_platforms / agent_quota / team_members
    创建前的额度检查。
    """
    from fastapi import HTTPException, status as http_status

    info = check_quota(
        user_id, feature_name, current_count,
        increment=increment, token=token, headers=headers,
    )
    if info["allowed"]:
        return info
    # Open Core 契约：所有 403 均使用 "upgrade_required"（覆盖 check_quota 返回的
    # "quota_exceeded" 等内部原因）。
    detail = _upgrade_detail(
        feature_name, info["plan"],
        reason="upgrade_required",
        limit=info.get("limit"),
        current=info.get("current"),
    )
    if message:
        detail["message"] = message
    raise HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


__all__ = [
    "BillingClient",
    "FEATURE_NAMES",
    "COMMUNITY_FLAGS",
    "PRO_FLAGS",
    "get_default_client",
    "set_default_client",
    "get_feature_flags",
    "get_flag",
    "check_feature",
    "check_quota",
    "require_feature",
    "require_quota",
    "clear_cache",
]
