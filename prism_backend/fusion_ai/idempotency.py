"""M1 · 幂等键缓存（Redis 优先 + 内存兜底）。

用于 `/api/v1/ai-design/generate` 的幂等性：
同一 (user_id, idempotency_key) 在 TTL 内重复请求时：
  - 已完成 → 返回缓存的响应（不重复 freeze/consume）
  - 处理中 → 返回 202，让前端轮询
  - 未处理 → 首次请求，正常执行

存储：Redis key `m1:gen_idem:{user_id}:{key}`，value 为 JSON：
  {"status": "processing" | "completed" | "failed",
   "result": {...}, "error": {...},
   "created_at": <float>}

TTL 默认 24 小时。Redis 不可用时降级到进程内 dict（内存兜底）。
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

_KEY_PREFIX = "m1:gen_idem:"
_DEFAULT_TTL = 86400  # 24 小时


# ──────────────────────────────────────────────────────────────
# Backends
# ──────────────────────────────────────────────────────────────


class _MemoryBackend:
    """进程内 dict 后端（Redis 不可用时的兜底）。

    所有操作都在同一把 `_lock` 内完成；`set_nx` 保证 get+set 组合原子。
    """

    def __init__(self) -> None:
        self._data: Dict[str, Tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, expires = item
            if expires and expires < time.time():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        with self._lock:
            expires = time.time() + ttl if ttl else 0.0
            self._data[key] = (value, expires)

    def set_nx(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """SET if Not eXists：key 不存在才写入。返回 True 表示抢占成功。"""
        with self._lock:
            item = self._data.get(key)
            if item is not None:
                expires = item[1]
                if expires and expires < time.time():
                    # 过期，视同不存在
                    self._data.pop(key, None)
                else:
                    return False
            expires_new = time.time() + ttl if ttl else 0.0
            self._data[key] = (value, expires_new)
            return True

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class _RedisBackend:
    """Redis 后端（默认首选）。所有异常吞掉，不阻塞主流程。

    新增 `set_nx`：使用 Redis `SET key value NX EX ttl` 保证 get+set 原子。
    """

    def __init__(self, client: Any) -> None:
        self._r = client

    def get(self, key: str) -> Optional[str]:
        try:
            return self._r.get(key)
        except Exception:
            return None

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        try:
            if ttl:
                self._r.set(key, value, ex=int(ttl))
            else:
                self._r.set(key, value)
        except Exception:
            pass

    def set_nx(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """SET key value NX EX ttl：原子抢占，只在 key 不存在时成功。

        返回 True 表示本次调用完成"写入"（首次请求）；False 表示 key 已存在
        （并发或重复请求），此时需要 GET 查询已存在的状态。
        任何 Redis 异常都返回 False（保守视为"已存在"），避免异常路径下
        两个请求都执行 provider 调用。
        """
        try:
            if ttl:
                ok = self._r.set(key, value, nx=True, ex=int(ttl))
            else:
                ok = self._r.set(key, value, nx=True)
            return bool(ok)
        except Exception:
            return False

    def delete(self, key: str) -> None:
        try:
            self._r.delete(key)
        except Exception:
            pass

    def clear(self) -> None:
        try:
            # 只清理 m1: 前缀，避免误伤其它 key
            keys = self._r.keys("m1:*") or []
            if keys:
                self._r.delete(*keys)
        except Exception:
            pass


_backend: Any = None
_backend_kind: str = ""


def _load_redis() -> Optional[Any]:
    try:
        from fastapi_app.cache.redis_client import get_redis  # type: ignore
    except Exception:
        return None
    try:
        client = get_redis()
        if client is None:
            return None
        client.ping()  # 主动探测
        return client
    except Exception:
        return None


def _get_backend() -> Any:
    global _backend, _backend_kind
    if _backend is None:
        r = _load_redis()
        if r is not None:
            _backend = _RedisBackend(r)
            _backend_kind = "redis"
        else:
            _backend = _MemoryBackend()
            _backend_kind = "memory"
    return _backend


# ──────────────────────────────────────────────────────────────
# 测试 / 运维用切换
# ──────────────────────────────────────────────────────────────


def backend_kind() -> str:
    _get_backend()
    return _backend_kind


def force_memory_backend() -> None:
    """测试用：强制切到内存后端。"""
    global _backend, _backend_kind
    _backend = _MemoryBackend()
    _backend_kind = "memory"


def force_redis_backend(client: Any) -> None:
    """测试用：注入自定义 Redis 客户端。"""
    global _backend, _backend_kind
    _backend = _RedisBackend(client)
    _backend_kind = "redis"


def reset_backend() -> None:
    global _backend, _backend_kind
    _backend = None
    _backend_kind = ""


def clear_cache() -> None:
    """测试用：清空当前后端。"""
    b = _get_backend()
    if hasattr(b, "clear"):
        b.clear()


def _key(user_id: str, idem_key: str) -> str:
    return f"{_KEY_PREFIX}{user_id}:{idem_key}"


# ──────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────


@dataclass
class AcquireResult:
    seen_before: bool
    in_flight: bool
    cached_result: Optional[Dict[str, Any]] = None
    cached_error: Optional[Dict[str, Any]] = None


def acquire(user_id: str, idem_key: str, *, ttl: int = _DEFAULT_TTL) -> AcquireResult:
    """首次访问：写入 processing 标记。已存在则返回缓存状态。

    并发安全（2026-10-19 medium-hardening）：
      原先是 `get` → `set`，两步之间没有原子性，并发同 key 请求可能都判断
      为"未见过"然后都执行 provider 调用与积分冻结。
      现在用后端 `set_nx`：Redis 用 `SET key value NX EX ttl` 原子抢占；
      内存后端在单一 lock 内完成 get+set。
      - 抢占成功 → 首次请求，返回 `AcquireResult(False, False, None, None)`
      - 抢占失败 → 读取已存在状态并返回对应分支
    """
    b = _get_backend()
    key = _key(user_id, idem_key)
    payload = json.dumps(
        {"status": "processing", "created_at": time.time()},
        ensure_ascii=False,
    )
    if b.set_nx(key, payload, ttl=ttl):
        # 抢占成功：首次请求
        return AcquireResult(False, False, None, None)

    # 抢占失败：key 已存在，读取状态
    raw = b.get(key)
    if raw is None:
        # 极少数场景：set_nx 失败但随后 GET 空（例如 TTL 边界）——
        # 保守视为首次请求，直接放行；下一次请求会通过 GET 拿到结果。
        return AcquireResult(False, False, None, None)
    try:
        obj = json.loads(raw)
    except Exception:
        obj = None
    if isinstance(obj, dict):
        st = obj.get("status")
        if st == "completed":
            return AcquireResult(True, False, obj.get("result"), None)
        if st in ("failed", "error"):
            return AcquireResult(True, False, None, obj.get("error"))
        if st == "processing":
            return AcquireResult(True, True, None, None)
    # 未识别状态：视为处理中，让调用方 202
    return AcquireResult(True, True, None, None)


def complete(user_id: str, idem_key: str, result: Dict[str, Any],
             *, ttl: int = _DEFAULT_TTL) -> None:
    b = _get_backend()
    key = _key(user_id, idem_key)
    payload = json.dumps(
        {"status": "completed", "result": result, "created_at": time.time()},
        ensure_ascii=False, default=str,
    )
    b.set(key, payload, ttl=ttl)


def fail(user_id: str, idem_key: str, error: Dict[str, Any],
         *, ttl: int = _DEFAULT_TTL) -> None:
    b = _get_backend()
    key = _key(user_id, idem_key)
    payload = json.dumps(
        {"status": "failed", "error": error, "created_at": time.time()},
        ensure_ascii=False, default=str,
    )
    b.set(key, payload, ttl=ttl)


def delete(user_id: str, idem_key: str) -> None:
    b = _get_backend()
    b.delete(_key(user_id, idem_key))


def get_cached(user_id: str, idem_key: str) -> Optional[Dict[str, Any]]:
    b = _get_backend()
    raw = b.get(_key(user_id, idem_key))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


__all__ = [
    "AcquireResult",
    "acquire", "complete", "fail", "delete", "get_cached",
    "backend_kind", "force_memory_backend", "force_redis_backend",
    "reset_backend", "clear_cache",
    "_DEFAULT_TTL",
]
