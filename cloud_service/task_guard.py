"""跨 worker 任务互斥 + 每日计数限流(C-D / C-E)。

> **位置说明(2026-10-23)**:本模块原先位于 `cloud_service/payment/task_guard.py`。
> 平台支付彻底删除时,`payment/` 整包被移除,但本模块是**与支付无关的通用
> Redis 分布式锁工具**(原供「订单超时清理」与「日终对账」两个后台任务使用),
> 因此平移到 `cloud_service/task_guard.py` 保留,供后续任何多 worker 后台任务使用。
> 当前**没有调用方**,属于预留基础设施。

背景
----
`uvicorn --workers > 1` 时,每个 worker 的 lifespan 各起一份后台任务。清理任务
按 id + status 幂等,但对账任务会真的调商户 `fetch_bill()`,多份 worker 会重复
调用商户接口(浪费配额、可能触发限流)。

策略
----
- 用 Redis `SET key value NX PX <ttl>` 抢锁;抢到才执行本轮;抢不到则跳过本轮并
  debug 记录(不打 warning,避免日志噪音)。
- TTL 默认 `max(60, 2 * interval_seconds)`,大于单轮任务最长执行时间。每轮结束
  主动释放(CAS:值必须匹配 owner 才 DEL,防止误删别人的锁)。
- Redis 不可达时**降级为"无锁模式"**:记录 warning,仍执行本轮。理由:清理任务
  本身幂等,对账任务在 adapter 端可加每日限次作为兜底;因 Redis 挂而停摆整
  个后台任务比"可能重复执行"更危险。

依赖
----
`redis-py` 4.x,已与本仓库内置的 Redis 5 兼容。若模块未装,或首次连接失败,
本模块同样按"无锁"降级 —— 保证服务能起来。

设计约束
--------
- 本模块**不**在 import 时建立连接,`get_redis_client()` 惰性连接。
- 每次操作使用短连接/短命令,超时设置极短(`socket_connect_timeout=1s`,
  `socket_timeout=1s`),避免 Redis 抖动拖慢后台任务。
- 所有对外方法**吞掉** Redis 异常,只 warn/return fallback。
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Redis 客户端(惰性、独立实例,与 celery broker 不共享)
# ──────────────────────────────────────────────────────────────

_REDIS_URL_ENV = "CLOUD_REDIS_URL"
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"

_client_cache: Optional[Any] = None


def _parse_redis_url() -> str:
    url = (os.getenv(_REDIS_URL_ENV) or "").strip()
    if not url:
        url = _DEFAULT_REDIS_URL
    if not url.startswith(("redis://", "rediss://", "unix://")):
        url = f"redis://{url}"
    return url


def get_redis_client(*, force_new: bool = False) -> Optional[Any]:
    """惰性返回 redis.Redis 客户端;未安装或无法构造 → None。

    `force_new=True` 会丢弃缓存重新构造(测试用)。
    """
    global _client_cache
    if _client_cache is not None and not force_new:
        return _client_cache
    try:
        import redis  # type: ignore
    except ImportError:
        logger.warning("redis-py not installed; task guard runs lock-free")
        _client_cache = None
        return None
    try:
        client = redis.Redis.from_url(
            _parse_redis_url(),
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        # ping 一次探活;失败视为"暂不可用",返回 None 让调用方降级
        try:
            client.ping()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(
                "task_guard: redis ping failed at %s (%s); falling back to "
                "lock-free mode",
                _parse_redis_url(), e,
            )
            return None
        _client_cache = client
        return client
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("task_guard: redis client init failed: %s", e)
        return None


def reset_redis_client() -> None:
    """测试用:清缓存。"""
    global _client_cache
    _client_cache = None


# ──────────────────────────────────────────────────────────────
# 分布式锁(SET NX PX + Lua CAS 释放)
# ──────────────────────────────────────────────────────────────

_RELEASE_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def acquire_task_lock(
    *,
    key: str,
    owner: str,
    ttl_ms: int,
    redis_client: Optional[Any] = None,
) -> Optional[str]:
    """尝试抢锁;成功返回 owner 字符串,失败/不可达返回 None。

    调用方拿到非 None 返回值时,应在 finally 里调 `release_task_lock`。
    `None` 有两种含义:
      1. 没抢到锁(别的 worker 持有);
      2. Redis 不可达(降级为无锁模式由调用方决定)。
    两种情况的区分由调用方通过 `try_lock_or_none_reason` 拿到。
    """
    if ttl_ms <= 0:
        raise ValueError(f"ttl_ms must be > 0, got {ttl_ms}")
    client = redis_client if redis_client is not None else get_redis_client()
    if client is None:
        return None
    try:
        ok = client.set(key, owner, nx=True, px=ttl_ms)
        return owner if ok else None
    except Exception as e:
        logger.warning("task_guard.acquire failed key=%s err=%s", key, e)
        return None


def release_task_lock(
    *,
    key: str,
    owner: str,
    redis_client: Optional[Any] = None,
) -> bool:
    """释放锁(CAS,防止误删他人持有的锁)。任何异常都返回 False,不抛出。"""
    client = redis_client if redis_client is not None else get_redis_client()
    if client is None:
        return False
    try:
        # Lua 脚本在 Redis 里原子执行
        try:
            result = client.eval(_RELEASE_LOCK_LUA, 1, key, owner)
        except AttributeError:  # pragma: no cover - very old redis-py
            # 兼容:退化为 get+del(非原子,但功能等价)
            if client.get(key) == owner:
                client.delete(key)
                return True
            return False
        return bool(result)
    except Exception as e:
        logger.warning("task_guard.release failed key=%s err=%s", key, e)
        return False


@asynccontextmanager
async def task_lock(
    *,
    key: str,
    ttl_seconds: int = 7200,
    owner: Optional[str] = None,
    redis_client: Optional[Any] = None,
    log_label: str = "",
) -> AsyncIterator[str]:
    """异步 context manager 包装抢锁/释放。

    yield 值是"决策":
      - `"locked"`        : 抢到锁,正常执行;退出时自动 release。
      - `"skipped"`       : 抢不到锁,调用方应跳过本轮。
      - `"unlocked"`      : Redis 不可达(降级),调用方按无锁模式执行。

    使用示例::

        async with task_lock(key="cloud:lock:order_timeout", ttl_seconds=7200) as mode:
            if mode == "skipped":
                logger.debug("skip this round (other worker holds lock)")
                return
            # mode == "locked" 或 "unlocked" 都执行
            await do_work()
    """
    if ttl_seconds <= 0:
        raise ValueError(f"ttl_seconds must be > 0, got {ttl_seconds}")
    if owner is None:
        # 每个 worker 唯一 id;PID 在 uvicorn workers 里是独立的
        owner = f"pid-{os.getpid()}-{time.monotonic_ns()}"
    ttl_ms = int(ttl_seconds * 1000)

    acquired = acquire_task_lock(
        key=key, owner=owner, ttl_ms=ttl_ms, redis_client=redis_client,
    )

    if acquired is not None:
        yield "locked"
    else:
        # 抢不到,可能是"别人持有"或"Redis 挂了";区分两种情况
        client = redis_client if redis_client is not None else get_redis_client()
        if client is None:
            # Redis 不可达 → 降级
            if log_label:
                logger.warning(
                    "task_guard[%s]: redis unreachable, running lock-free",
                    log_label,
                )
            yield "unlocked"
        else:
            if log_label:
                logger.debug(
                    "task_guard[%s]: lock busy (another worker holds it)",
                    log_label,
                )
            yield "skipped"
        return

    # 释放(在 with 块退出时)
    release_task_lock(
        key=key, owner=owner, redis_client=redis_client,
    )


# ──────────────────────────────────────────────────────────────
# 每日调用次数上限(Redis INCR + EXPIRE)
# ──────────────────────────────────────────────────────────────


def daily_key(base_key: str, day_utc: Optional[str] = None) -> str:
    """按 UTC 日切构造每日计数 key。

    day_utc 默认取当前 UTC 日期(`YYYY-MM-DD`),便于测试注入固定日期。
    """
    if day_utc is None:
        day_utc = time.strftime("%Y-%m-%d", time.gmtime())
    return f"{base_key}:daily:{day_utc}"


def check_daily_limit(
    *,
    key: str,
    limit: int,
    ttl_seconds: int = 86400 * 2,
    redis_client: Optional[Any] = None,
    day_utc: Optional[str] = None,
) -> tuple[bool, int]:
    """判断当前 UTC 日是否还能调用一次。

    返回 `(allowed, used_after_call)`:
      - allowed=True  : 已 INCR,当前计数;
      - allowed=False : 已达上限,未 INCR,used 是当前累计值。

    Redis 不可达时 **fail-open**(返回 `(True, 0)`),避免限流组件本身把
    业务停摆;调用方应结合日志告警判断。
    """
    if limit <= 0:
        # limit <= 0 = 关闭限流
        return True, 0
    client = redis_client if redis_client is not None else get_redis_client()
    if client is None:
        logger.warning(
            "task_guard.daily_limit: redis unavailable key=%s, fail-open",
            key,
        )
        return True, 0
    dk = daily_key(key, day_utc=day_utc)
    try:
        used = client.incr(dk)
        # expire 保证 key 自动过期;失败无影响(下一天 key 名会切换)
        try:
            client.expire(dk, ttl_seconds)
        except Exception:  # pragma: no cover - defensive
            pass
    except Exception as e:
        logger.warning("task_guard.daily_limit failed key=%s err=%s", key, e)
        # 与"Redis 不可达"一致,fail-open
        return True, 0
    if used <= limit:
        return True, int(used)
    # 超限:回滚一次 INCR(避免虚高),并返回 False
    try:
        client.decr(dk)
    except Exception:  # pragma: no cover - defensive
        pass
    return False, int(used - 1)


def reset_daily_limit(
    *,
    key: str,
    redis_client: Optional[Any] = None,
    day_utc: Optional[str] = None,
) -> None:
    """测试用:清掉指定日期的计数 key。"""
    client = redis_client if redis_client is not None else get_redis_client()
    if client is None:
        return
    try:
        client.delete(daily_key(key, day_utc=day_utc))
    except Exception:  # pragma: no cover - defensive
        pass


__all__ = [
    "get_redis_client",
    "reset_redis_client",
    "acquire_task_lock",
    "release_task_lock",
    "task_lock",
    "daily_key",
    "check_daily_limit",
    "reset_daily_limit",
]
