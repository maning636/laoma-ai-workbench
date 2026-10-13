"""
发布回执 API 路由（Phase 0.1）

端点：
- GET /api/v1/receipts/{task_id}          查询单个回执
- GET /api/v1/receipts                    列出回执（带过滤）
- GET /api/v1/receipts/stats              回执状态统计
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from prism_core.receipts import (
    ReceiptStatus,
    get_receipt,
    list_receipts,
)

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.get("/{task_id}")
async def get_receipt_by_id(task_id: str):
    """查询单个发布回执"""
    receipt = get_receipt(task_id)
    if not receipt:
        raise HTTPException(status_code=404, detail=f"回执不存在: {task_id}")
    return receipt.model_dump(mode="json")


@router.get("")
async def list_receipts_endpoint(
    status: Optional[str] = Query(None, description="状态过滤"),
    account_id: Optional[str] = Query(None, description="账号ID过滤"),
    platform: Optional[int] = Query(None, description="平台code过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出发布回执"""
    receipts = list_receipts(
        status=status,
        account_id=account_id,
        platform=platform,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [r.model_dump(mode="json") for r in receipts],
        "total": len(receipts),
    }


class ReceiptStats(BaseModel):
    total: int = 0
    succeeded: int = 0
    failed_retryable: int = 0
    failed_final: int = 0
    cancelled: int = 0
    running: int = 0


@router.get("/stats")
async def receipt_stats():
    """回执状态统计"""
    stats = ReceiptStats()
    for status_val in [
        ReceiptStatus.SUCCEEDED,
        ReceiptStatus.FAILED_RETRYABLE,
        ReceiptStatus.FAILED_FINAL,
        ReceiptStatus.CANCELLED,
        ReceiptStatus.RUNNING,
    ]:
        receipts = list_receipts(status=status_val.value, limit=1000)
        count = len(receipts)
        setattr(stats, status_val.value, count)
        stats.total += count
    return stats.model_dump()


# ── Phase 0.3: 监控事件 ──

class MonitorEventResponse(BaseModel):
    items: list = Field(default_factory=list)
    total: int = 0


@router.get("/monitor/events")
async def list_monitor_events_endpoint(
    event_type: Optional[str] = Query(None, description="事件类型过滤"),
    account_id: Optional[str] = Query(None, description="账号ID过滤"),
    severity: Optional[str] = Query(None, description="严重级别过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出监控事件"""
    from prism_core.monitor import list_monitor_events
    events = list_monitor_events(event_type=event_type, account_id=account_id, severity=severity, limit=limit, offset=offset)
    return {"items": [e.model_dump(mode="json") for e in events], "total": len(events)}


@router.get("/monitor/transitions")
async def list_transitions_endpoint(
    task_id: Optional[str] = Query(None, description="任务ID过滤"),
    limit: int = Query(50, ge=1, le=200),
):
    """列出状态流转记录"""
    from prism_core.monitor import list_state_transitions
    transitions = list_state_transitions(task_id=task_id, limit=limit)
    return {"items": [t.model_dump(mode="json") for t in transitions], "total": len(transitions)}


@router.get("/monitor/alerts/webhooks")
async def list_alert_webhooks():
    """列出告警 Webhook 配置"""
    from prism_core.monitor import AlertHub
    return AlertHub.list_webhooks()


@router.post("/monitor/alerts/webhooks")
async def add_alert_webhook(name: str, url: str, event_types: Optional[str] = None):
    """添加告警 Webhook"""
    from prism_core.monitor import AlertHub
    types = [t.strip() for t in event_types.split(",")] if event_types else None
    AlertHub.add_webhook(name=name, url=url, event_types=types)
    return {"message": "Webhook 已添加", "name": name}


@router.delete("/monitor/alerts/webhooks/{name}")
async def remove_alert_webhook(name: str):
    """删除告警 Webhook"""
    from prism_core.monitor import AlertHub
    result = AlertHub.remove_webhook(name)
    if not result:
        raise HTTPException(status_code=404, detail=f"Webhook 不存在: {name}")
    return {"message": "Webhook 已删除"}


# ── Phase 0.4: 账号健康 ──

@router.get("/health/{account_id}")
async def get_account_health(account_id: str, platform: Optional[int] = Query(None)):
    """查询账号健康状态"""
    from prism_core.account_health import get_latest_health, compute_health_from_receipts
    snapshot = get_latest_health(account_id)
    if not snapshot:
        snapshot = compute_health_from_receipts(account_id, platform or 0)
    return snapshot.model_dump(mode="json")


@router.get("/health")
async def list_health_snapshots_endpoint(
    account_id: Optional[str] = Query(None),
    health_status: Optional[str] = Query(None, description="健康状态过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出账号健康快照"""
    from prism_core.account_health import list_health_snapshots
    snapshots = list_health_snapshots(account_id=account_id, health_status=health_status, limit=limit, offset=offset)
    return {"items": [s.model_dump(mode="json") for s in snapshots], "total": len(snapshots)}


@router.get("/health/unhealthy")
async def list_unhealthy_accounts():
    """列出所有不健康账号"""
    from prism_core.account_health import account_health_monitor
    snapshots = account_health_monitor.list_unhealthy_accounts()
    return {"items": [s.model_dump(mode="json") for s in snapshots], "total": len(snapshots)}
