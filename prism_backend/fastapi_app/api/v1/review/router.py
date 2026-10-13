"""
审核队列 API 路由

端点：
- POST /api/v1/review/queue           提交审核
- GET  /api/v1/review/queue           列出审核项
- GET  /api/v1/review/items/{id}      查询单个审核项
- POST /api/v1/review/items/{id}/approve  通过
- POST /api/v1/review/items/{id}/reject   拒绝
- POST /api/v1/review/items/{id}/edit     要求修改
- POST /api/v1/review/auto-check         自动预检查
- POST /api/v1/review/batch-approve      批量通过
- POST /api/v1/review/batch-reject       批量拒绝
- GET  /api/v1/review/stats              审核统计
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from prism_core.review_queue import (
    ReviewItem,
    ReviewStatus,
    ReviewPriority,
    ReviewType,
    ReviewQueueManager,
    enqueue_review,
    approve_review,
    reject_review,
    auto_pre_check,
    list_reviews,
    get_review_item,
    review_queue_manager,
)

router = APIRouter(prefix="/review", tags=["review"])


class EnqueueBody(BaseModel):
    task_id: str = ""
    campaign_id: str = ""
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    priority: str = "normal"
    review_type: str = "manual"
    title: str = ""
    content: str = ""
    cover_url: Optional[str] = None


class DecisionBody(BaseModel):
    reviewer: str = ""
    reason: str = ""


class AutoCheckBody(BaseModel):
    task_id: str
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    title: str = ""
    content: str = ""


class BatchBody(BaseModel):
    review_ids: List[str]
    reviewer: str = ""
    reason: str = ""


@router.post("/queue", status_code=201)
async def enqueue(body: EnqueueBody):
    """提交审核"""
    item = ReviewItem(
        task_id=body.task_id,
        campaign_id=body.campaign_id,
        platform=body.platform,
        platform_name=body.platform_name,
        account_id=body.account_id,
        priority=ReviewPriority(body.priority),
        review_type=ReviewType(body.review_type),
        title=body.title,
        content=body.content,
        cover_url=body.cover_url,
    )
    enqueue_review(item)
    return item.model_dump(mode="json")


@router.get("/queue")
async def list_queue(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    campaign_id: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出审核项"""
    items = list_reviews(
        status=status, priority=priority,
        campaign_id=campaign_id, account_id=account_id,
        limit=limit, offset=offset,
    )
    return [i.model_dump(mode="json") for i in items]


@router.get("/items/{review_id}")
async def get_item(review_id: str):
    """查询单个审核项"""
    item = get_review_item(review_id)
    if not item:
        raise HTTPException(404, f"审核项不存在: {review_id}")
    return item.model_dump(mode="json")


@router.post("/items/{review_id}/approve")
async def approve(review_id: str, body: DecisionBody):
    """通过审核"""
    decision = approve_review(review_id, body.reviewer, body.reason)
    if not decision:
        raise HTTPException(404, f"审核项不存在: {review_id}")
    return decision.model_dump(mode="json")


@router.post("/items/{review_id}/reject")
async def reject(review_id: str, body: DecisionBody):
    """拒绝审核"""
    decision = reject_review(review_id, body.reviewer, body.reason)
    if not decision:
        raise HTTPException(404, f"审核项不存在: {review_id}")
    return decision.model_dump(mode="json")


@router.post("/items/{review_id}/edit")
async def request_edit(review_id: str, body: DecisionBody):
    """要求修改"""
    item = get_review_item(review_id)
    if not item:
        raise HTTPException(404, f"审核项不存在: {review_id}")
    review_queue_manager.request_edit(review_id, body.reviewer, body.reason)
    return {"status": "needs_edit", "review_id": review_id}


@router.post("/auto-check", status_code=201)
async def auto_check(body: AutoCheckBody):
    """自动预检查"""
    item = auto_pre_check(
        task_id=body.task_id, platform=body.platform,
        platform_name=body.platform_name, account_id=body.account_id,
        title=body.title, content=body.content,
    )
    return item.model_dump(mode="json")


@router.post("/batch-approve")
async def batch_approve(body: BatchBody):
    """批量通过"""
    count = review_queue_manager.batch_approve(body.review_ids, body.reviewer, body.reason)
    return {"approved": count}


@router.post("/batch-reject")
async def batch_reject(body: BatchBody):
    """批量拒绝"""
    count = review_queue_manager.batch_reject(body.review_ids, body.reviewer, body.reason)
    return {"rejected": count}


@router.get("/stats")
async def review_stats():
    """审核统计"""
    stats = review_queue_manager.stats()
    return stats
