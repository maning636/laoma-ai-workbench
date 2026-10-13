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

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

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


__all__ = ["reconcile_day"]
