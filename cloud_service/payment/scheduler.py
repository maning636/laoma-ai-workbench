"""订单超时关闭任务(C19 遗留补齐)。

场景:
  - 用户在 `create_order` 后放弃支付,`Order.status` 一直停在 `created`;
  - 24 小时后应自动关闭,释放前端展示,避免"僵尸订单"堆积。

提供:
  - `close_expired_orders(db, *, hours=24) -> int` : 纯函数,由外部调度。
  - `close_expired_orders_task(interval_seconds=3600) -> asyncio.Task` :
    基于 asyncio 的循环调度器;返回一个可 cancel 的 Task,不启动全局事件循环。

调度模式参考:
  - FastAPI 里可挂 `asyncio.create_task(close_expired_orders_task(...))`
    在 lifespan 启动时启动、shutdown 时 cancel;
  - 或用 APScheduler / Celery Beat 等外部调度器直接调 `close_expired_orders`。

本模块不主动 create_task,避免导入即产生副作用 —— 由调用方决定何时启动。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import SessionLocal
from .models import STATUS_CLOSED, STATUS_CREATED, Order

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def close_expired_orders(
    db: Session, *, hours: int = 24
) -> int:
    """把 `status='created'` 且 `created_at < now - hours` 的订单置为 `closed`。

    参数:
      - `db`    : SQLAlchemy Session。
      - `hours` : 超时小时数,默认 24。

    返回:
      被关闭的订单数量(int)。

    说明:
      - 只处理 `created`;`paid` / `refunded` / `closed` 一律不动。
      - SQLite / SQLAlchemy 返回的 DateTime(timezone=True) 在读取时可能是 naive
        UTC,这里统一按 UTC 语义处理;SQL 层比较由数据库完成,不受读回时区影响。
    """
    if hours <= 0:
        raise ValueError(f"hours must be > 0, got {hours}")

    cutoff = _utcnow() - timedelta(hours=hours)

    # 先用 select 抓一次(便于返回 id 列表 / 日志);再用 update 批量提交。
    ids = [
        row[0]
        for row in db.execute(
            select(Order.id).where(
                Order.status == STATUS_CREATED,
                Order.created_at < cutoff,
            )
        ).all()
    ]
    if not ids:
        return 0

    db.execute(
        update(Order)
        .where(Order.id.in_(ids), Order.status == STATUS_CREATED)
        .values(status=STATUS_CLOSED)
    )
    db.commit()
    logger.info("close_expired_orders: closed %d order(s) older than %dh", len(ids), hours)
    return len(ids)


async def close_expired_orders_task(
    *,
    interval_seconds: float = 3600.0,
    hours: int = 24,
    db_factory: Any = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """循环执行 `close_expired_orders` 的后台任务(asyncio)。

    参数:
      - `interval_seconds` : 两次执行的间隔(秒),默认 1 小时。
      - `hours`            : 传给 `close_expired_orders` 的超时小时数。
      - `db_factory`       : 可选的 session 工厂(callable → Session);默认用
                             `cloud_service.db.SessionLocal`。
      - `stop_event`       : 若给定,`stop_event.set()` 时立即退出循环。

    调用方示例(挂在 FastAPI lifespan 里):
        stop = asyncio.Event()
        task = asyncio.create_task(
            close_expired_orders_task(interval_seconds=3600, stop_event=stop)
        )
        ... # yield 生命周期
        stop.set()
        await task

    注意:
      - 本函数**不会**自己 create_task;由调用方调度。
      - 单次失败不会终止任务,仅记录日志,等下一次间隔重试。
    """
    if interval_seconds <= 0:
        raise ValueError(f"interval_seconds must be > 0, got {interval_seconds}")

    while True:
        if stop_event is not None and stop_event.is_set():
            break
        try:
            if db_factory is None:
                session = SessionLocal()
            else:
                session = db_factory()
            try:
                closed = close_expired_orders(session, hours=hours)
                if closed:
                    logger.info("closed %d expired order(s)", closed)
            finally:
                session.close()
        except Exception:
            logger.exception("close_expired_orders_task iteration failed")

        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            else:
                await asyncio.sleep(interval_seconds)
        except asyncio.TimeoutError:
            pass  # 正常走下一轮
        except asyncio.CancelledError:
            raise


__all__ = ["close_expired_orders", "close_expired_orders_task"]
