"""
账号健康 API 路由

端点：
- GET  /api/v1/health/dashboard              健康仪表盘
- GET  /api/v1/health/scores/trend           健康分趋势
- GET  /api/v1/health/accounts               列出账号健康状态
- GET  /api/v1/health/accounts/{id}          查询单个账号健康
- POST /api/v1/health/accounts/{id}/compute  计算账号健康分
- GET  /api/v1/health/accounts/{id}/events   查询健康事件
- GET  /api/v1/health/diagnostics/{id}       账号诊断报告
- GET  /api/v1/health/unhealthy              列出异常账号
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from prism_core.account_health import (
    AccountHealthStatus,
    HealthSnapshot,
    account_health_monitor,
    get_latest_health,
    list_health_snapshots,
    compute_health_from_receipts,
)
from prism_core.diagnostics import collect_diagnostics
from prism_core.monitor import list_monitor_events, list_state_transitions

router = APIRouter(prefix="/health", tags=["account-health"])


@router.get("/dashboard")
async def health_dashboard():
    """健康仪表盘：概览统计"""
    snapshots = list_health_snapshots(limit=200)
    total = len(snapshots)
    by_status = {}
    total_publishes = 0
    total_success = 0
    total_failure = 0
    for s in snapshots:
        status_val = s.health_status.value if hasattr(s.health_status, "value") else str(s.health_status)
        by_status[status_val] = by_status.get(status_val, 0) + 1
        total_publishes += s.total_publishes
        total_success += s.success_count
        total_failure += s.failure_count
    success_rate = round(total_success / total_publishes, 4) if total_publishes > 0 else 0.0
    events = list_monitor_events(limit=1000)
    return {
        "total_accounts": total,
        "total_publishes": total_publishes,
        "total_success": total_success,
        "total_failure": total_failure,
        "success_rate": success_rate,
        "by_status": by_status,
        "recent_events_count": len(events),
    }


@router.get("/unhealthy")
async def list_unhealthy():
    """列出异常账号"""
    unhealthy = account_health_monitor.list_unhealthy_accounts()
    return [s.model_dump(mode="json") for s in unhealthy]


@router.get("/scores/trend")
async def health_score_trend(
    account_id: str = Query(..., description="账号ID"),
    limit: int = Query(30, ge=1, le=100),
):
    """健康分趋势"""
    snapshots = list_health_snapshots(account_id=account_id, limit=limit)
    return [
        {
            "snapshot_id": s.snapshot_id,
            "health_status": s.health_status.value,
            "success_rate": s.success_rate,
            "success_count": s.success_count,
            "failure_count": s.failure_count,
            "consecutive_failures": s.consecutive_failures,
            "created_at": s.created_at,
        }
        for s in snapshots
    ]


@router.get("/accounts")
async def list_accounts_health(
    health_status: Optional[str] = Query(None, description="健康状态过滤"),
    account_id: Optional[str] = Query(None, description="账号ID过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出账号健康状态"""
    snapshots = list_health_snapshots(
        account_id=account_id, health_status=health_status,
        limit=limit, offset=offset,
    )
    return [s.model_dump(mode="json") for s in snapshots]


@router.get("/accounts/{account_id}")
async def get_account_health(account_id: str):
    """查询单个账号最新健康状态"""
    snapshot = get_latest_health(account_id)
    if not snapshot:
        raise HTTPException(404, f"账号健康数据不存在: {account_id}")
    return snapshot.model_dump(mode="json")


@router.post("/accounts/{account_id}/compute")
async def compute_score(account_id: str, platform: int = Query(0)):
    """计算账号健康分"""
    snapshot = compute_health_from_receipts(account_id, platform)
    return snapshot.model_dump(mode="json")


@router.get("/accounts/{account_id}/events")
async def get_account_events(
    account_id: str,
    limit: int = Query(50, ge=1, le=200),
):
    """查询账号相关事件"""
    events = list_monitor_events(limit=limit)
    transitions = list_state_transitions(limit=limit)
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "transitions": [t.model_dump(mode="json") for t in transitions],
    }


@router.post("/diagnostics")
async def get_diagnostics(
    task_id: str,
    platform: int,
    platform_name: str,
    error_stack: Optional[str] = None,
    url_snapshot: Optional[str] = None,
    cookie_status: Optional[str] = None,
    ip_address: Optional[str] = None,
):
    """生成诊断报告"""
    report = collect_diagnostics(
        task_id=task_id, platform=platform, platform_name=platform_name,
        url_snapshot=url_snapshot, error_stack=error_stack,
        cookie_status=cookie_status, ip_address=ip_address,
    )
    return report.model_dump(mode="json")
