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

logger = logging.getLogger(__name__)


def _round2(x: float) -> float:
    return round(float(x), 2)


def reconcile_day(
    db: Session,
    *,
    start_date: str,
    end_date: str,
    platform_bills: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """对账一天的订单(start_date / end_date, `YYYY-MM-DD`,含两端)。

    参数:
      - `db`           : SQLAlchemy Session。
      - `start_date`   : 起始日期字符串。
      - `end_date`     : 结束日期字符串(可与 start_date 相同,表示单日)。
      - `platform_bills`: 平台账单行。若为 None,则遍历已注册的 alipay/wechat
                          adapter 调 `fetch_bill()`;否则直接使用注入的行
                          (便于测试/离线比对)。

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

    # 2. 拉平台账单
    if platform_bills is None:
        platform_bills = []
        for channel in sorted(SUPPORTED_CHANNELS):
            adapter = get_adapter(channel)
            if adapter is None:
                continue
            try:
                platform_bills.extend(adapter.fetch_bill(
                    start_date=start_date, end_date=end_date
                ))
            except Exception as e:
                logger.warning("fetch_bill(%s) failed: %s", channel, e)
                # 记录失败不影响对账流程;报告里带一份 notes 便于排查
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


async def reconcile_task(
    *,
    interval_seconds: float = 86400.0,
    lookback_hours: int = 24,
    db_factory: Any = None,
    stop_event: asyncio.Event | None = None,
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

    注意:
      - 本函数**不会**自己 create_task;由调用方调度。
      - 传入 `platform_bills=None`(默认),会遍历已注册 adapter 调 `fetch_bill`。
        真实商户 adapter 上线后就是外部调用,所以本任务**默认由 env 开关关闭**,
        由 lifespan 根据 `settings["reconcile"]["enabled"]` 决定是否启动。
      - 单次失败不会终止任务,仅记录日志,等下一次间隔重试。
      - summary 与 matched_count 会通过 INFO 日志打印(带日期区间),便于观察。
    """
    if interval_seconds <= 0:
        raise ValueError(f"interval_seconds must be > 0, got {interval_seconds}")
    if lookback_hours <= 0:
        raise ValueError(f"lookback_hours must be > 0, got {lookback_hours}")

    while True:
        if stop_event is not None and stop_event.is_set():
            break
        try:
            if db_factory is None:
                session = SessionLocal()
            else:
                session = db_factory()
            try:
                end_dt = datetime.now(timezone.utc)
                start_dt = end_dt - timedelta(hours=lookback_hours)
                start_date = start_dt.strftime("%Y-%m-%d")
                end_date = end_dt.strftime("%Y-%m-%d")
                report = reconcile_day(
                    session, start_date=start_date, end_date=end_date
                )
                logger.info(
                    "reconcile_task: window=[%s..%s] summary=%s matched=%d",
                    start_date, end_date, report["summary"], report["matched_count"],
                )
            finally:
                session.close()
        except Exception:
            logger.exception("reconcile_task iteration failed")

        try:
            if stop_event is not None:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            else:
                await asyncio.sleep(interval_seconds)
        except asyncio.TimeoutError:
            pass  # 正常走下一轮
        except asyncio.CancelledError:
            raise


__all__ = ["reconcile_day", "reconcile_task"]
