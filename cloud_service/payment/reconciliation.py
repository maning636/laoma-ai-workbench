"""日终对账(C19 遗留补齐)。

目的:
  - 每天结束时把本地 `orders.status='paid'` 的订单与支付平台账单做比对,
    找出以下差异:
      1. `local_only` : 本地有 paid 订单,平台账单无对应记录(可能未真正到账);
      2. `amount_mismatch` : 两边都有,但金额不一致(可能中间被改/汇率误差);
      3. `platform_only` : 平台有,本地无(可能漏回调)。
  - 生成一份 `ReconciliationReport`(纯 dict,便于序列化到日志或后台报表)。

数据源:
  - 本地:`cloud_service.payment.models.Order`,过滤 `status='paid'`。
  - 平台账单:调 `PaymentAdapter.fetch_bill(start_date, end_date)`。
    - mock 阶段默认返回 `[]`,测试或联调时可通过 `platform_bills` 参数注入。
    - 真实环境应由 alipay / wechat 子类覆盖 `fetch_bill`,拉商户账户账单下载。

不启动任何服务、不落库、不通知 —— 纯函数,由运维脚本或定时任务调用即可:

    from cloud_service.payment.reconciliation import reconcile_day
    report = reconcile_day(db, start_date="2026-10-13", end_date="2026-10-13")
    print(report["summary"])
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from .adapter import get_adapter
from .models import STATUS_PAID, SUPPORTED_CHANNELS, Order
from .task_guard import (
    check_daily_limit,
    get_redis_client,
    task_lock,
)

logger = logging.getLogger(__name__)


def _round2(x: float) -> float:
    return round(float(x), 2)


def reconcile_day(
    db: Session,
    *,
    start_date: str,
    end_date: str,
    platform_bills: Optional[list[dict[str, Any]]] = None,
    fetch_timeout_seconds: float = 0,
) -> dict[str, Any]:
    """对账一天的订单(start_date / end_date, `YYYY-MM-DD`,含两端)。

    参数:
      - `db`           : SQLAlchemy Session。
      - `start_date`   : 起始日期字符串。
      - `end_date`     : 结束日期字符串(可与 start_date 相同,表示单日)。
      - `platform_bills`: 平台账单行。若为 None,则遍历已注册的 alipay/wechat
                          adapter 调 `fetch_bill()`;否则直接使用注入的行
                          (便于测试/离线比对)。
      - `fetch_timeout_seconds`: 仅当调用方在**已运行的 event loop** 里同步调用
                          本函数,且 platform_bills=None 且 timeout>0 时才生效。
                          用于兼容测试路径;推荐异步路径使用
                          `fetch_all_bills_with_timeout()` + `platform_bills=<rows>`。
                          在**无 loop** 上下文里,timeout 参数会被忽略并 warn。

    返回:
      {
        "start_date":  "YYYY-MM-DD",
        "end_date":    "YYYY-MM-DD",
        "generated_at":"ISO-8601 UTC",
        "summary": {
          "local_paid":        int,  # 本地当日 paid 订单数
          "platform_rows":     int,  # 平台账单行数
          "matched":           int,  # 金额一致的对齐行
          "local_only":        int,  # 本地有 / 平台无
          "platform_only":     int,  # 平台有 / 本地无
          "amount_mismatch":   int,  # 金额不一致
        },
        "diffs": {
          "local_only":      [ {order_no, user_id, amount, channel, ...}, ... ],
          "platform_only":   [ {out_trade_no, amount, channel, ...}, ... ],
          "amount_mismatch": [ {order_no, local_amount, platform_amount, diff}, ... ],
        },
        "matched_count": int,
      }

    金额比较:两侧都保留 2 位小数,差值 > 0.01 元视为金额不一致。
    """
    # 解析日期
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
    except ValueError as e:
        raise ValueError(f"invalid date range: {e}") from e

    # 1. 拉本地 paid 订单
    local_rows = list(
        db.execute(
            select(Order).where(
                Order.status == STATUS_PAID,
                Order.paid_at >= start_dt,
                Order.paid_at <= end_dt,
            )
        ).scalars().all()
    )

    # 2. 拉平台账单(同步路径)
    if platform_bills is None:
        platform_bills = []
        for channel in sorted(SUPPORTED_CHANNELS):
            adapter = get_adapter(channel)
            if adapter is None:
                continue
            try:
                rows = adapter.fetch_bill(
                    start_date=start_date, end_date=end_date,
                )
                platform_bills.extend(rows)
            except Exception as e:
                logger.warning("fetch_bill(%s) failed: %s", channel, e)
                platform_bills.append({
                    "_error": f"fetch_bill({channel}) failed: {e}",
                })

    # 3. 建索引:按 out_trade_no 建立平台侧映射
    platform_by_order: dict[str, dict[str, Any]] = {}
    bill_rows: list[dict[str, Any]] = []
    for row in platform_bills:
        if not isinstance(row, dict) or row.get("_error"):
            continue
        out_no = str(row.get("out_trade_no") or "").strip()
        if not out_no:
            continue
        bill_rows.append(row)
        platform_by_order[out_no] = row

    local_only: list[dict[str, Any]] = []
    platform_only: list[dict[str, Any]] = []
    amount_mismatch: list[dict[str, Any]] = []
    matched = 0

    for order in local_rows:
        bill = platform_by_order.pop(order.order_no, None)
        if bill is None:
            local_only.append({
                "order_no": order.order_no,
                "user_id": order.user_id,
                "amount": order.amount,
                "channel": order.channel,
                "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            })
            continue
        bill_amount = _round2(float(bill.get("amount") or 0))
        local_amount = _round2(float(order.amount))
        if abs(bill_amount - local_amount) > 0.01:
            amount_mismatch.append({
                "order_no": order.order_no,
                "local_amount": local_amount,
                "platform_amount": bill_amount,
                "diff": round(bill_amount - local_amount, 2),
                "channel": order.channel,
            })
        else:
            matched += 1

    # 平台多出的
    for out_no, bill in platform_by_order.items():
        platform_only.append({
            "out_trade_no": out_no,
            "amount": _round2(float(bill.get("amount") or 0)),
            "channel": str(bill.get("channel") or ""),
            "pay_trade_no": bill.get("pay_trade_no"),
        })

    report: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "local_paid": len(local_rows),
            "platform_rows": len(bill_rows),
            "matched": matched,
            "local_only": len(local_only),
            "platform_only": len(platform_only),
            "amount_mismatch": len(amount_mismatch),
        },
        "diffs": {
            "local_only": local_only,
            "platform_only": platform_only,
            "amount_mismatch": amount_mismatch,
        },
        "matched_count": matched,
    }
    return report


async def fetch_all_bills_with_timeout(
    *,
    start_date: str,
    end_date: str,
    timeout_seconds: float,
    channels: Optional[list[str]] = None,
    redis_client: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """遍历 adapter 拉取账单,每个 adapter 用 `wait_for` 加 wall-clock 超时。

    - 单个 adapter 超时**只影响自身**;其它 adapter 继续执行,不中断整体。
    - 超时的 adapter 会返回一条 `_error` 记录,让对账报告带 notes。
    - 线程池执行同步 `fetch_bill`,避免阻塞事件循环。

    `channels=None` 时按 `SUPPORTED_CHANNELS` 全量执行,与 `reconcile_day` 的
    同步路径一致。测试可传子集控制行为。
    """
    if channels is None:
        channels = sorted(SUPPORTED_CHANNELS)

    rows: list[dict[str, Any]] = []
    for channel in channels:
        adapter = get_adapter(channel)
        if adapter is None:
            continue
        try:
            channel_rows = await asyncio.wait_for(
                asyncio.to_thread(
                    adapter.fetch_bill,
                    start_date=start_date,
                    end_date=end_date,
                ),
                timeout=timeout_seconds,
            )
            if channel_rows:
                rows.extend(channel_rows)
        except asyncio.TimeoutError:
            logger.warning(
                "fetch_bill(%s) timed out after %.1fs; skipping this channel",
                channel, timeout_seconds,
            )
            rows.append({
                "_error": (
                    f"fetch_bill({channel}) timed out after "
                    f"{timeout_seconds}s"
                ),
            })
        except Exception as e:
            logger.warning("fetch_bill(%s) failed: %s", channel, e)
            rows.append({
                "_error": f"fetch_bill({channel}) failed: {e}",
            })
    return rows


def _compute_backoff(attempt: int, *, base: float, cap: float) -> float:
    """指数退避:base * 2 ** (attempt - 1),封顶 cap;attempt>=1。"""
    if attempt <= 0:
        return base
    val = base * (2 ** (attempt - 1))
    return min(val, cap)


async def reconcile_task(
    *,
    interval_seconds: float = 86400.0,
    lookback_hours: int = 24,
    db_factory: Any = None,
    stop_event: asyncio.Event | None = None,
    # C-D: 分布式锁
    lock_enabled: bool = True,
    lock_key: str = "cloud:lock:reconcile",
    lock_ttl_seconds: int = 0,          # 0 = max(60, 2 * interval_seconds)
    redis_client: Optional[Any] = None,
    # C-E: 超时/退避/限次
    fetch_timeout_seconds: float = 30.0,
    backoff_base_seconds: float = 300.0,
    backoff_max_seconds: float = 3600.0,
    daily_limit: int = 10,              # 0 = 关闭
    daily_limit_base_key: str = "cloud:payment:reconcile",
) -> None:
    """循环执行 `reconcile_day` 的后台任务(asyncio)。

    签名与 `close_expired_orders_task` 保持一致,便于 lifespan 统一管理。

    参数:
      - `interval_seconds` : 两次执行的间隔(秒),默认 24h。
      - `lookback_hours`   : 每次执行"从当前时间往前 lookback_hours 小时"作为
                             起止窗口;默认 24h 覆盖"昨日"日切。
      - `db_factory`       : 可选的 session 工厂(callable → Session);默认用
                             `cloud_service.db.SessionLocal`。
      - `stop_event`       : 若给定,`stop_event.set()` 时立即退出循环。
      - `lock_enabled`     : C-D,是否走分布式锁;False 直接执行(单 worker 部署)。
      - `lock_key`         : C-D,锁 key。
      - `lock_ttl_seconds` : C-D,锁 TTL 秒;0 = 自动取 max(60, 2*interval)。
      - `redis_client`     : C-D/C-E 共用;None = 惰性通过 task_guard 构造。
      - `fetch_timeout_seconds` : C-E,单次 adapter.fetch_bill 超时。
      - `backoff_base_seconds`  : C-E,首次失败后等待时间(秒)。
      - `backoff_max_seconds`   : C-E,退避封顶(秒)。
      - `daily_limit`     : C-E,每日调用次数上限;0 = 关闭。
      - `daily_limit_base_key`  : C-E,每日计数 Redis key 前缀。

    注意:
      - 本函数**不会**自己 create_task;由调用方调度。
      - 真实商户 adapter 上线后就是外部调用,由 lifespan 根据 env 决定是否启动。
      - 单次失败(超时/异常/限次)**不会**终止任务,仅记录日志并指数退避。
    """
    if interval_seconds <= 0:
        raise ValueError(f"interval_seconds must be > 0, got {interval_seconds}")
    if lookback_hours <= 0:
        raise ValueError(f"lookback_hours must be > 0, got {lookback_hours}")

    if lock_ttl_seconds <= 0:
        lock_ttl_seconds = max(60, int(interval_seconds * 2))

    consecutive_failures = 0

    async def _sleep_or_stop(seconds: float) -> None:
        if stop_event is not None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=seconds)
            except asyncio.TimeoutError:
                pass  # 正常走下一轮
        else:
            await asyncio.sleep(seconds)

    while True:
        if stop_event is not None and stop_event.is_set():
            break

        # ── C-D: 分布式锁(只在启用时抢)──
        async with task_lock(
            key=lock_key,
            ttl_seconds=lock_ttl_seconds,
            redis_client=redis_client,
            log_label="reconcile",
        ) as lock_mode:
            if lock_mode == "skipped":
                # 别的 worker 已抢到锁,本轮跳过;不改变退避计数
                logger.debug(
                    "reconcile_task: lock busy, skip this round (other worker holds)"
                )
                await _sleep_or_stop(interval_seconds)
                continue

            # lock_mode in {"locked", "unlocked"}(unlocked = Redis 降级为无锁)
            # ── C-E: 每日调用次数上限 ──
            allowed, used = check_daily_limit(
                key=daily_limit_base_key,
                limit=daily_limit,
                redis_client=redis_client,
            )
            if not allowed:
                logger.warning(
                    "reconcile_task: daily limit reached (used=%d, limit=%d); "
                    "skip this round",
                    used, daily_limit,
                )
                await _sleep_or_stop(interval_seconds)
                continue

            # ── 执行本轮对账 ──
            ok = False
            try:
                end_dt = datetime.now(timezone.utc)
                start_dt = end_dt - timedelta(hours=lookback_hours)
                start_date = start_dt.strftime("%Y-%m-%d")
                end_date = end_dt.strftime("%Y-%m-%d")

                if db_factory is None:
                    session = SessionLocal()
                else:
                    session = db_factory()
                try:
                    # C-E: 带超时的账单拉取
                    if fetch_timeout_seconds and fetch_timeout_seconds > 0:
                        platform_bills = await fetch_all_bills_with_timeout(
                            start_date=start_date,
                            end_date=end_date,
                            timeout_seconds=fetch_timeout_seconds,
                            redis_client=redis_client,
                        )
                    else:
                        platform_bills = None
                    report = reconcile_day(
                        session,
                        start_date=start_date,
                        end_date=end_date,
                        platform_bills=platform_bills,
                    )
                    logger.info(
                        "reconcile_task: window=[%s..%s] summary=%s matched=%d",
                        start_date, end_date, report["summary"], report["matched_count"],
                    )
                    ok = True
                finally:
                    session.close()
            except Exception:
                logger.exception("reconcile_task iteration failed")

            # ── C-E: 更新退避计数 ──
            if ok:
                consecutive_failures = 0
                await _sleep_or_stop(interval_seconds)
            else:
                consecutive_failures += 1
                delay = _compute_backoff(
                    consecutive_failures,
                    base=backoff_base_seconds,
                    cap=backoff_max_seconds,
                )
                logger.warning(
                    "reconcile_task: failed #%d, backing off %.1fs",
                    consecutive_failures, delay,
                )
                await _sleep_or_stop(delay)

        # lock 释放后(无论执行结果),回到循环顶部

__all__ = [
    "reconcile_day",
    "fetch_all_bills_with_timeout",
    "reconcile_task",
    "_compute_backoff",
]
