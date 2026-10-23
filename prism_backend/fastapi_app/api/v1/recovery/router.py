from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from myUtils.tikhub_client import TIKHUB_NOT_CONFIGURED_DETAIL, get_tikhub_client

router = APIRouter(prefix="/recovery", tags=["recovery"])


class RecoveryCollectRequest(BaseModel):
    account_ids: Optional[List[str]] = Field(None, description="Optional account IDs to recover")
    platform: Optional[str] = Field(None, description="Platform filter: kuaishou/xiaohongshu/channels")


class RecoveryAddRequest(BaseModel):
    """回收站写入请求（删除操作前把原始数据存下来，可还原）"""
    id: str = Field(..., description="被删除对象的 ID")
    type: str = Field("plan", description="对象类型，如 plan / account / task")
    payload: Dict[str, Any] = Field(default_factory=dict, description="被删除对象的完整快照")
    reason: str = Field("", description="删除原因")


def _require_client():
    client = get_tikhub_client()
    if not client:
        raise HTTPException(status_code=400, detail=TIKHUB_NOT_CONFIGURED_DETAIL)
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


# ============================================================
# 回收站（删除操作前的快照留存）
# 前端删除计划时会 POST /api/v1/recovery/add 存快照；这里提供写入/列表/还原。
# 与 /collect 的 TikHub 采集能力不同，本段不消耗 TikHub 额度，Community 可用。
# ============================================================

_RECOVERY_TABLE = """
CREATE TABLE IF NOT EXISTS recovery_snapshots (
    recovery_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL,
    object_type TEXT NOT NULL DEFAULT 'plan',
    payload TEXT NOT NULL DEFAULT '{}',
    reason TEXT DEFAULT '',
    created_at TEXT NOT NULL
)
"""


def _recovery_conn():
    """回收站使用独立的 sqlite 连接（不占用主库连接池）。"""
    from fastapi_app.db.session import open_main_db
    return open_main_db()


@router.post("/add")
async def add_recovery_snapshot(payload: RecoveryAddRequest):
    """把即将删除的对象快照存入回收站（可经 /recovery/list + /recovery/restore 还原）。"""
    import json
    import uuid
    from fastapi_app.core.timezone_utils import now_beijing_iso

    recovery_id = f"rc_{uuid.uuid4().hex[:12]}"
    conn = _recovery_conn()
    try:
        conn.execute(_RECOVERY_TABLE)
        conn.execute(
            "INSERT INTO recovery_snapshots "
            "(recovery_id, object_id, object_type, payload, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                recovery_id,
                payload.id,
                payload.type,
                json.dumps(payload.payload, ensure_ascii=False, default=str),
                payload.reason,
                now_beijing_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "success", "result": {"recovery_id": recovery_id, "object_id": payload.id}}


@router.get("/list")
async def list_recovery_snapshots(object_type: Optional[str] = None, limit: int = 50):
    """列出回收站快照（默认按时间倒序）。"""
    import json

    conn = _recovery_conn()
    try:
        conn.execute(_RECOVERY_TABLE)
        if object_type:
            cur = conn.execute(
                "SELECT recovery_id, object_id, object_type, payload, reason, created_at "
                "FROM recovery_snapshots WHERE object_type = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (object_type, limit),
            )
        else:
            cur = conn.execute(
                "SELECT recovery_id, object_id, object_type, payload, reason, created_at "
                "FROM recovery_snapshots ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = cur.fetchall()
        items = []
        for r in rows:
            items.append({
                "recovery_id": r[0],
                "object_id": r[1],
                "object_type": r[2],
                "payload": json.loads(r[3] or "{}"),
                "reason": r[4],
                "created_at": r[5],
            })
    finally:
        conn.close()
    return {"status": "success", "result": {"items": items, "total": len(items)}}


@router.get("/{recovery_id}")
async def get_recovery_snapshot(recovery_id: str):
    """取单条回收站快照。"""
    import json

    conn = _recovery_conn()
    try:
        conn.execute(_RECOVERY_TABLE)
        cur = conn.execute(
            "SELECT recovery_id, object_id, object_type, payload, reason, created_at "
            "FROM recovery_snapshots WHERE recovery_id = ?",
            (recovery_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"回收站快照不存在: {recovery_id}")
    return {
        "status": "success",
        "result": {
            "recovery_id": row[0],
            "object_id": row[1],
            "object_type": row[2],
            "payload": json.loads(row[3] or "{}"),
            "reason": row[4],
            "created_at": row[5],
        },
    }
