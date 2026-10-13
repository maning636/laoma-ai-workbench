"""
Webhook API 路由

端点：
- POST   /api/v1/webhooks/subscriptions     创建订阅
- GET    /api/v1/webhooks/subscriptions     列出订阅
- GET    /api/v1/webhooks/subscriptions/{id} 查询订阅
- PUT    /api/v1/webhooks/subscriptions/{id} 更新订阅
- DELETE /api/v1/webhooks/subscriptions/{id} 删除订阅
- POST   /api/v1/webhooks/subscriptions/{id}/deactivate 停用订阅
- POST   /api/v1/webhooks/events/dispatch    手动触发事件分发
- POST   /api/v1/webhooks/events/receive     接收外部事件
- GET    /api/v1/webhooks/deliveries         查询投递记录
- POST   /api/v1/webhooks/deliveries/retry   重试失败投递
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from prism_core.webhook import (
    WebhookSubscription,
    WebhookEventType,
    create_subscription,
    get_subscription,
    list_subscriptions,
    delete_subscription,
    deactivate_subscription,
    list_deliveries,
    log_incoming_event,
    verify_signature,
    generate_signature,
    webhook_manager,
    _save_subscription,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class SubscriptionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1, max_length=1000)
    events: Optional[List[str]] = None
    secret: str = ""
    retry_count: int = 3
    retry_interval: int = 60
    timeout: int = 30


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[List[str]] = None
    secret: Optional[str] = None
    retry_count: Optional[int] = None
    retry_interval: Optional[int] = None
    timeout: Optional[int] = None
    active: Optional[bool] = None


@router.post("/subscriptions", status_code=201)
async def create_sub_endpoint(body: SubscriptionCreate):
    """创建 Webhook 订阅"""
    sub = WebhookSubscription(
        name=body.name,
        url=body.url,
        events=json.dumps(body.events) if body.events else None,
        secret=body.secret,
        retry_count=body.retry_count,
        retry_interval=body.retry_interval,
        timeout=body.timeout,
    )
    sid = create_subscription(sub)
    return {"subscription_id": sid, "name": sub.name, "url": sub.url}


@router.get("/subscriptions")
async def list_subs(
    active_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出 Webhook 订阅"""
    subs = list_subscriptions(active_only=active_only, limit=limit, offset=offset)
    return [s.model_dump(mode="json") for s in subs]


@router.get("/subscriptions/{sub_id}")
async def get_sub_endpoint(sub_id: str):
    """查询单个订阅"""
    sub = get_subscription(sub_id)
    if not sub:
        raise HTTPException(404, f"订阅不存在: {sub_id}")
    return sub.model_dump(mode="json")


@router.put("/subscriptions/{sub_id}")
async def update_sub_endpoint(sub_id: str, body: SubscriptionUpdate):
    """更新订阅"""
    sub = get_subscription(sub_id)
    if not sub:
        raise HTTPException(404, f"订阅不存在: {sub_id}")
    from fastapi_app.core.timezone_utils import now_beijing_iso
    if body.name is not None:
        sub.name = body.name
    if body.url is not None:
        sub.url = body.url
    if body.events is not None:
        sub.events = json.dumps(body.events)
    if body.secret is not None:
        sub.secret = body.secret
    if body.retry_count is not None:
        sub.retry_count = body.retry_count
    if body.retry_interval is not None:
        sub.retry_interval = body.retry_interval
    if body.timeout is not None:
        sub.timeout = body.timeout
    if body.active is not None:
        sub.active = body.active
    sub.updated_at = now_beijing_iso()
    _save_subscription(sub)
    return sub.model_dump(mode="json")


@router.delete("/subscriptions/{sub_id}")
async def delete_sub_endpoint(sub_id: str):
    """删除订阅"""
    deleted = delete_subscription(sub_id)
    if not deleted:
        raise HTTPException(404, f"订阅不存在: {sub_id}")
    return {"deleted": True}


@router.post("/subscriptions/{sub_id}/deactivate")
async def deactivate_sub_endpoint(sub_id: str):
    """停用订阅"""
    result = deactivate_subscription(sub_id)
    if not result:
        raise HTTPException(404, f"订阅不存在: {sub_id}")
    return {"deactivated": True}


@router.post("/events/dispatch")
async def dispatch_event_endpoint(body: Dict[str, Any]):
    """手动触发事件分发"""
    event_type = body.get("event", "")
    payload = body.get("data", {})
    if not event_type:
        raise HTTPException(400, "缺少 event 字段")
    deliveries = await webhook_manager.dispatch_event(event_type, payload)
    return {
        "event": event_type,
        "dispatched": len(deliveries),
        "delivery_ids": [d.delivery_id for d in deliveries],
    }


@router.post("/events/receive")
async def receive_event_endpoint(request: Request):
    """接收外部 Webhook 事件"""
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(400, "请求体不是有效 JSON")

    event_type = payload.get("event", "custom.event")
    source = payload.get("source", "")

    # 签名验证
    secret = payload.get("secret", "")
    signature = request.headers.get("X-LaomaAI-Signature", "")
    if secret and signature:
        if not verify_signature(secret, raw_body.decode("utf-8", errors="replace"), signature):
            raise HTTPException(401, "签名验证失败")

    log_id = log_incoming_event(event_type, source, payload)
    if not log_id:
        return {"status": "duplicate", "message": "重复事件已跳过"}
    return {"status": "received", "log_id": log_id, "event_type": event_type}


@router.get("/deliveries")
async def list_deliveries_endpoint(
    subscription_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """查询投递记录"""
    deliveries = list_deliveries(subscription_id=subscription_id, status=status, limit=limit, offset=offset)
    return [d.model_dump(mode="json") for d in deliveries]


@router.post("/deliveries/retry")
async def retry_deliveries_endpoint(body: Optional[Dict[str, str]] = None):
    """重试失败投递"""
    sub_id = (body or {}).get("subscription_id")
    retried = await webhook_manager.retry_failed(sub_id)
    return {"retried": retried}
