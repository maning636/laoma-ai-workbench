from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from myUtils.tikhub_client import get_tikhub_client

router = APIRouter(prefix="/recovery", tags=["recovery"])


class RecoveryCollectRequest(BaseModel):
    account_ids: Optional[List[str]] = Field(None, description="Optional account IDs to recover")
    platform: Optional[str] = Field(None, description="Platform filter: kuaishou/xiaohongshu/channels")


def _require_client():
    client = get_tikhub_client()
    if not client:
        raise HTTPException(status_code=400, detail="TikHub API key not configured")
    return client


def _require_data_recovery(request: Request) -> None:
    """Feature Gate (M3 Open Core): Community 用户无数据回收能力。

    调用 `billing_client.require_feature(user_id, "data_recovery")`；
    Community flag = False → 抛 HTTPException(403, upgrade_required)。
    Pro flag = True 或云端不可达回落 Community → 后者仍会 403（按任务规范）。

    注意：本 helper **不阻断** `/health` 端点（运维探针，不需要用户身份）。
    """
    from fastapi_app.api.billing_client import require_feature

    # 从 Authorization Bearer 提取 user_id；无 token 时视为 anonymous（→ Community → 403）
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    uid = auth.replace("Bearer ", "").replace("bearer ", "").strip() or "anonymous"
    require_feature(uid, "data_recovery")


@router.get("/health")
async def health_check():
    client = get_tikhub_client()
    return {
        "status": "ok",
        "module": "recovery",
        "tikhub_configured": bool(client),
    }


@router.get("/kuaishou/user-info")
async def kuaishou_user_info(user_id: str):
    client = _require_client()
    return await client.fetch_kuaishou_user_info(user_id=user_id)


@router.get("/kuaishou/user-posts")
async def kuaishou_user_posts(user_id: str, pcursor: Optional[str] = None):
    client = _require_client()
    return await client.fetch_kuaishou_user_posts(user_id=user_id, pcursor=pcursor)


@router.get("/xiaohongshu/user-info")
async def xiaohongshu_user_info(user_id: str):
    client = _require_client()
    return await client.fetch_xiaohongshu_user_info(user_id=user_id)


@router.get("/xiaohongshu/user-notes")
async def xiaohongshu_user_notes(user_id: str, last_cursor: Optional[str] = None):
    client = _require_client()
    return await client.fetch_xiaohongshu_user_notes_v2(user_id=user_id, last_cursor=last_cursor)


@router.get("/channels/home")
async def channels_home(username: str, last_buffer: Optional[str] = None):
    client = _require_client()
    return await client.fetch_channels_home(username=username, last_buffer=last_buffer)


@router.get("/channels/video-detail")
async def channels_video_detail(id: Optional[str] = None, export_id: Optional[str] = None):
    if not id and not export_id:
        raise HTTPException(status_code=422, detail="Provide id or export_id")
    client = _require_client()
    return await client.fetch_channels_video_detail(video_id=id, export_id=export_id)


@router.post("/collect")
async def collect_recovery_data(payload: RecoveryCollectRequest, request: Request):
    """批量数据采集端点 — 调用多平台 API。

    Open Core Feature Gate: Community 无数据回收能力，仅 Pro/Pro_Plus 可调用。
    """
    from myUtils.video_collector import collector

    # Feature Gate (Open Core) — Community 用户被 403 拒绝
    _require_data_recovery(request)

    results = await collector.collect_all_accounts(
        account_ids=payload.account_ids,
        platform_filter=payload.platform,
    )
    return {"status": "success", "data": results}
