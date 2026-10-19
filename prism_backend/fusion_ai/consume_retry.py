"""M1 · consume_pending 后台重试。

场景：生成成功、freeze 已生效，但 `POST /cloud/points/consume` 因云端不可达失败。
若只记日志就放弃，用户已经拿到图但云端仍显示"冻结中"，账本不一致。

设计：
- 失败时调用 `record_pending(freeze_tx_id, ...)` 写入 Redis key `m1:consume_pending:{tx_id}`，
  同时挂到 set `m1:consume_pending_index`，便于扫描。
- 后台每 5 分钟调一次 `retry_pending()`，遍历 index，对每条尝试重新 consume。
- 重试成功 → 清 pending + 从 index 移除；失败 → attempts+1；达上限（默认 5）→ 记告警，保留 pending 供人工介入。
- Redis 不可用时降级到进程内 dict（多进程不共享，但至少不会丢）。

状态机（Redis value）：
  {"freeze_tx_id": int, "user_id": str, "amount": float,
   "task_id": str, "model_key": str,
   "attempts": int, "last_error": str,
   "recorded_at": float, "last_attempt_at": float}

调度：
- Celery 定时任务（`@celery_app.on_after_finalize` 注册 Beat schedule），5 分钟一次。
- 若 Celery 未启动（例如本地只跑 FastAPI），提供 `start_background_loop()` 供 FastAPI startup 兜底。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

_KEY_PREFIX = "m1:consume_pending:"
_INDEX_KEY = "m1:consume_pending_index"

_DEFAULT_MAX_ATTEMPTS = int(os.getenv("M1_CONSUME_RETRY_MAX", "5"))
_DEFAULT_LOOP_INTERVAL = int(os.getenv("M1_CONSUME_RETRY_INTERVAL", "300"))

try:
    from fastapi_app.core.logger import logger  # type: ignore
    _log = logger
except Exception:
    _log = None

if _log is None:
    _log = logging.getLogger("m1.consume_retry")


# ──────────────────────────────────────────────────────────────
# Backend（Redis / 内存）
# ──────────────────────────────────────────────────────────────


class _MemoryPending:
    """Redis 不可用时的兜底：进程内 dict。"""

    def __init__(self) -> None:
        self._data: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def write(self, tx_id: int, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._data[int(tx_id)] = payload

    def read(self, tx_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._data.get(int(tx_id))

    def scan(self) -> List[int]:
        with self._lock:
            return list(self._data.keys())

    def delete(self, tx_id: int) -> None:
        with self._lock:
            self._data.pop(int(tx_id), None)

    def all(self) -> Dict[int, Dict[str, Any]]:
        with self._lock:
            return {int(k): dict(v) for k, v in self._data.items()}

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class _RedisPending:
    """Redis 后端。set 索引便于 SCAN。"""

    def __init__(self, client: Any) -> None:
        self._r = client

    def _key(self, tx_id: int) -> str:
        return f"{_KEY_PREFIX}{tx_id}"

    def write(self, tx_id: int, payload: Dict[str, Any]) -> None:
        key = self._key(tx_id)
        self._r.set(key, json.dumps(payload, ensure_ascii=False, default=str))
        self._r.sadd(_INDEX_KEY, str(tx_id))

    def read(self, tx_id: int) -> Optional[Dict[str, Any]]:
        raw = self._r.get(self._key(tx_id))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def scan(self) -> List[int]:
        members = self._r.smembers(_INDEX_KEY) or set()
        return [int(m) for m in members]

    def delete(self, tx_id: int) -> None:
        self._r.delete(self._key(tx_id))
        self._r.srem(_INDEX_KEY, str(tx_id))

    def all(self) -> Dict[int, Dict[str, Any]]:
        out: Dict[int, Dict[str, Any]] = {}
        for tx in self.scan():
            v = self.read(tx)
            if v is not None:
                out[tx] = v
        return out

    def clear(self) -> None:
        for tx in self.scan():
            self.delete(tx)
        self._r.delete(_INDEX_KEY)


_store: Any = None


def _load_redis() -> Optional[Any]:
    try:
        from fastapi_app.cache.redis_client import get_redis  # type: ignore
    except Exception:
        return None
    try:
        client = get_redis()
        if client is None:
            return None
        client.ping()
        return client
    except Exception:
        return None


def _get_store() -> Any:
    global _store
    if _store is None:
        r = _load_redis()
        if r is not None:
            _store = _RedisPending(r)
        else:
            _store = _MemoryPending()
    return _store


# ──────────────────────────────────────────────────────────────
# 测试用切换
# ──────────────────────────────────────────────────────────────


def force_memory_store() -> None:
    global _store
    _store = _MemoryPending()


def force_redis_store(client: Any) -> None:
    global _store
    _store = _RedisPending(client)


def reset_store() -> None:
    global _store
    _store = None


def clear_all_pending() -> None:
    s = _get_store()
    if hasattr(s, "clear"):
        s.clear()


# ──────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────


def record_pending(
    freeze_tx_id: int,
    *,
    user_id: str = "",
    amount: float = 0.0,
    task_id: str = "",
    model_key: str = "",
    note: str = "",
    last_error: str = "",
) -> None:
    """记录一条待重试的 consume 失败。多次调用会刷新状态（attempts 保持）。"""
    if not freeze_tx_id:
        return
    s = _get_store()
    existing = s.read(int(freeze_tx_id)) or {}
    attempts = int(existing.get("attempts") or 0)
    recorded_at = float(existing.get("recorded_at") or time.time())
    payload: Dict[str, Any] = {
        "freeze_tx_id": int(freeze_tx_id),
        "user_id": user_id or existing.get("user_id", ""),
        "amount": float(amount or existing.get("amount", 0.0) or 0.0),
        "task_id": task_id or existing.get("task_id", ""),
        "model_key": model_key or existing.get("model_key", ""),
        "note": note or existing.get("note", ""),
        "attempts": attempts,
        "last_error": last_error or existing.get("last_error", ""),
        "recorded_at": recorded_at,
        "last_attempt_at": float(existing.get("last_attempt_at") or 0.0),
    }
    try:
        s.write(int(freeze_tx_id), payload)
    except Exception as exc:
        _log.warning(f"[consume_retry] record_pending failed tx={freeze_tx_id}: {exc}")


def clear_pending(freeze_tx_id: int) -> None:
    s = _get_store()
    try:
        s.delete(int(freeze_tx_id))
    except Exception as exc:
        _log.warning(f"[consume_retry] clear_pending failed tx={freeze_tx_id}: {exc}")


def pending_list() -> List[Dict[str, Any]]:
    s = _get_store()
    return [v for _, v in sorted(s.all().items(), key=lambda kv: kv[0])]


def retry_pending(*, points_client: Optional[Any] = None,
                  max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
                  dry_run: bool = False) -> Dict[str, Any]:
    """扫描所有 pending 并逐条重试 consume。

    参数：
      - points_client：可选，用于测试注入 mock；默认使用 get_points_client()。
      - max_attempts：超过该次数后停止重试并告警（默认 5）。
      - dry_run：只扫描不调云端，用于测试。

    返回：{"success": [tx], "failed": [tx], "maxed": [tx]}
    """
    s = _get_store()
    tx_ids = s.scan()
    stats: Dict[str, List[int]] = {"success": [], "failed": [], "maxed": []}

    if points_client is None and not dry_run:
        try:
            from .points_client import get_points_client  # type: ignore
            points_client = get_points_client()
        except Exception:
            points_client = None

    for tx_id in tx_ids:
        entry = s.read(int(tx_id))
        if not entry:
            # 索引里残留，但数据已删 → 清理
            s.delete(int(tx_id))
            continue
        attempts = int(entry.get("attempts") or 0)
        if attempts >= max_attempts:
            stats["maxed"].append(int(tx_id))
            _log.warning(
                f"[consume_retry] tx={tx_id} 已达重试上限 {max_attempts}，保留 pending 待人工介入 "
                f"user={entry.get('user_id')} amount={entry.get('amount')}"
            )
            continue

        entry["attempts"] = attempts + 1
        entry["last_attempt_at"] = time.time()
        s.write(int(tx_id), entry)

        if dry_run:
            stats["failed"].append(int(tx_id))
            continue

        if points_client is None:
            stats["failed"].append(int(tx_id))
            continue

        try:
            res = points_client.consume(int(tx_id), note="AI生图 consume 重试")
        except Exception as exc:
            res = {"ok": False, "error": str(exc)}

        if res and res.get("ok"):
            stats["success"].append(int(tx_id))
            s.delete(int(tx_id))
            _log.info(f"[consume_retry] tx={tx_id} 重试成功")
        else:
            err = (res or {}).get("error", "unknown")
            entry["last_error"] = str(err)
            s.write(int(tx_id), entry)
            stats["failed"].append(int(tx_id))
            _log.warning(
                f"[consume_retry] tx={tx_id} 重试失败（第 {entry['attempts']} 次）：{err}"
            )

    return stats


# ──────────────────────────────────────────────────────────────
# 调度：Celery Beat + FastAPI 兜底后台 loop
# ──────────────────────────────────────────────────────────────


# Celery 任务定义。测试时可以 monkey-patch 直接调用。
def consume_retry_task() -> Dict[str, Any]:
    """Celery 任务体。5 分钟由 Beat schedule 触发一次。"""
    try:
        return retry_pending()
    except Exception as exc:
        _log.warning(f"[consume_retry] task error: {exc}")
        return {"success": [], "failed": [], "maxed": [], "error": str(exc)}


# FastAPI 端可启动的后台循环（无 Celery 场景兜底）。幂等；只启动一次。
_bg_loop_thread: Optional[threading.Thread] = None
_bg_loop_stop = threading.Event()


def start_background_loop(interval: int = _DEFAULT_LOOP_INTERVAL) -> bool:
    """启动后台线程，每 interval 秒调一次 retry_pending()。

    返回 True 表示新启动了线程；False 表示已在运行。
    测试时可以调用 stop_background_loop() 停止。
    """
    global _bg_loop_thread
    if _bg_loop_thread is not None and _bg_loop_thread.is_alive() and not _bg_loop_stop.is_set():
        return False
    _bg_loop_stop.clear()

    def _run() -> None:
        while not _bg_loop_stop.is_set():
            try:
                retry_pending()
            except Exception as exc:  # pragma: no cover
                _log.warning(f"[consume_retry] bg loop error: {exc}")
            _bg_loop_stop.wait(interval)

    _bg_loop_thread = threading.Thread(
        target=_run, name="m1-consume-retry-loop", daemon=True
    )
    _bg_loop_thread.start()
    return True


def stop_background_loop(timeout: float = 2.0) -> None:
    global _bg_loop_thread
    _bg_loop_stop.set()
    if _bg_loop_thread is not None:
        _bg_loop_thread.join(timeout)
        _bg_loop_thread = None


# ──────────────────────────────────────────────────────────────
# Celery Beat 注册（可选）
# ──────────────────────────────────────────────────────────────


def register_celery_schedule() -> bool:
    """把 consume_retry 注册到 Celery Beat（5 分钟一次）。

    延迟导入，避免顶层硬依赖 celery_app；导入失败返回 False 不影响主流程。
    返回 True 表示成功注册（可能已被先前的调用注册过）。
    """
    try:
        from fastapi_app.tasks.celery_app import celery_app  # type: ignore
    except Exception:
        return False

    try:
        celery_app.conf.beat_schedule.update({
            "m1-consume-retry-every-5m": {
                "task": "m1.consume_retry",
                "schedule": _DEFAULT_LOOP_INTERVAL,
                "options": {"queue": "default"},
            }
        })
    except Exception:
        return False

    # 把 consume_retry_task 以 name=m1.consume_retry 挂到 celery_app
    if celery_app.tasks.get("m1.consume_retry") is None:
        try:
            celery_app.task(name="m1.consume_retry")(consume_retry_task)
        except Exception:
            # 已被注册或不允许，忽略
            pass
    return True


__all__ = [
    "record_pending", "clear_pending", "pending_list",
    "retry_pending", "consume_retry_task",
    "start_background_loop", "stop_background_loop",
    "register_celery_schedule",
    "force_memory_store", "force_redis_store", "reset_store", "clear_all_pending",
    "_DEFAULT_MAX_ATTEMPTS", "_DEFAULT_LOOP_INTERVAL",
]
