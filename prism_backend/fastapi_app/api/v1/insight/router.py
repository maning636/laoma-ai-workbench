"""
数据洞察 API 路由

端点：
- POST /api/v1/insights/collect     采集洞察数据
- GET  /api/v1/insights             列出洞察
- GET  /api/v1/insights/{task_id}   查询单条洞察
- GET  /api/v1/insights/anomalies   异常列表
- GET  /api/v1/insights/summary     洞察摘要
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from prism_core.insight import (
    PublishInsight,
    InsightCollector,
    save_insight,
    get_insight,
    list_insights,
    detect_anomaly,
    generate_suggestion,
    insight_collector,
)

router = APIRouter(prefix="/insights", tags=["insights"])


class CollectBody(BaseModel):
    task_id: str
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    plays: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    favorites: int = 0
    followers_gained: int = 0
    published_at: Optional[str] = None
    data_age_hours: float = 0.0


@router.post("/collect", status_code=201)
async def collect(body: CollectBody):
    """采集洞察数据"""
    platform_data = {
        "platform": body.platform,
        "platform_name": body.platform_name,
        "account_id": body.account_id,
        "plays": body.plays,
        "likes": body.likes,
        "comments": body.comments,
        "shares": body.shares,
        "favorites": body.favorites,
        "followers_gained": body.followers_gained,
        "published_at": body.published_at,
        "data_age_hours": body.data_age_hours,
    }
    insight = insight_collector.collect_from_receipt(body.task_id, platform_data)
    return insight.model_dump(mode="json")


@router.get("")
async def list_insights_endpoint(
    account_id: Optional[str] = Query(None),
    platform: Optional[int] = Query(None),
    anomaly_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出洞察"""
    items = list_insights(
        account_id=account_id, platform=platform,
        anomaly_only=anomaly_only, limit=limit, offset=offset,
    )
    return [i.model_dump(mode="json") for i in items]


@router.get("/anomalies")
async def list_anomalies(
    account_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """异常列表"""
    items = list_insights(account_id=account_id, anomaly_only=True, limit=limit)
    return [i.model_dump(mode="json") for i in items]


@router.get("/summary")
async def insights_summary(
    account_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    """洞察摘要"""
    items = list_insights(account_id=account_id, limit=limit)
    total = len(items)
    total_plays = sum(i.plays for i in items)
    total_likes = sum(i.likes for i in items)
    total_comments = sum(i.comments for i in items)
    total_shares = sum(i.shares for i in items)
    total_followers = sum(i.followers_gained for i in items)
    anomalies = sum(1 for i in items if i.is_anomaly)
    avg_like_rate = round(sum(i.like_rate for i in items) / total, 6) if total > 0 else 0.0
    avg_comment_rate = round(sum(i.comment_rate for i in items) / total, 6) if total > 0 else 0.0
    avg_share_rate = round(sum(i.share_rate for i in items) / total, 6) if total > 0 else 0.0
    return {
        "total_insights": total,
        "total_plays": total_plays,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_shares": total_shares,
        "total_followers_gained": total_followers,
        "anomaly_count": anomalies,
        "avg_like_rate": avg_like_rate,
        "avg_comment_rate": avg_comment_rate,
        "avg_share_rate": avg_share_rate,
    }


@router.get("/{task_id}")
async def get_insight_endpoint(task_id: str):
    """查询单条洞察"""
    insight = get_insight(task_id)
    if not insight:
        raise HTTPException(404, f"洞察不存在: {task_id}")
    return insight.model_dump(mode="json")
