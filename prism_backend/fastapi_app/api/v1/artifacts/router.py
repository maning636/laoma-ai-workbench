"""统一产物总线 API 路由（/api/v1/artifacts）。

端点：
- GET  /api/v1/artifacts                列出产物（可按阶段/来源/类型/关键字过滤）
- GET  /api/v1/artifacts/stats          产物统计（按阶段 / 来源 / 类型）
- GET  /api/v1/artifacts/{artifact_id}  产物详情（含血缘）
- GET  /api/v1/artifacts/{artifact_id}/lineage   产物血缘（父链 / 子链）
- POST /api/v1/artifacts                手动登记一个产物
- POST /api/v1/artifacts/{artifact_id}/promote   推进阶段
- POST /api/v1/artifacts/{artifact_id}/submit-review  送审（自动入审核队列）
- GET  /api/v1/artifacts/by-ref/{ref_type}/{ref_id}  按本域记录反查产物
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from prism_core import artifacts as artifact_service
from prism_core.artifacts import (
    ALL_STAGES,
    KIND_IMAGE,
    KIND_OTHER,
    KIND_VIDEO,
    SOURCE_MANUAL,
    STAGE_GENERATED,
    STAGE_UPLOADED,
    is_artifact_id,
)

router = APIRouter(prefix="/artifacts", tags=["产物总线"])


class RegisterBody(BaseModel):
    """手动登记产物。"""

    source: str = SOURCE_MANUAL
    ref_type: str = "manual"
    ref_id: str = ""
    path: str = ""
    kind: str = KIND_OTHER
    stage: str = STAGE_GENERATED
    title: str = ""
    thumb: str = ""
    media_type: str = ""
    parent_id: Optional[str] = None
    campaign_id: str = ""
    platform: str = ""
    meta: Dict[str, Any] = Field(default_factory=dict)


class PromoteBody(BaseModel):
    """推进阶段。"""

    stage: str
    force: bool = False
    review_id: Optional[str] = None
    publish_task_id: Optional[str] = None
    campaign_id: Optional[str] = None
    platform: Optional[str] = None


class SubmitReviewBody(BaseModel):
    """送审参数。"""

    title: str = ""
    content: str = ""
    campaign_id: str = ""
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    priority: str = "normal"
    review_type: str = "manual"
    cover_url: Optional[str] = None


@router.get("")
async def list_artifacts(
    stage: Optional[str] = Query(None, description="阶段过滤"),
    source: Optional[str] = Query(None, description="来源域过滤"),
    ref_type: Optional[str] = Query(None, description="本域记录类型"),
    ref_id: Optional[str] = Query(None, description="本域记录 ID"),
    kind: Optional[str] = Query(None, description="产物类型"),
    campaign_id: Optional[str] = Query(None),
    parent_id: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None, description="标题/路径/来源 ID 模糊匹配"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出产物（按创建时间倒序）。"""
    items = artifact_service.list_artifacts(
        stage=stage,
        source=source,
        ref_type=ref_type,
        ref_id=ref_id,
        kind=kind,
        campaign_id=campaign_id,
        parent_id=parent_id,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    total = artifact_service.count_artifacts(
        stage=stage,
        source=source,
        ref_type=ref_type,
        ref_id=ref_id,
        kind=kind,
        campaign_id=campaign_id,
        parent_id=parent_id,
    )
    return {"total": total, "items": items, "limit": limit, "offset": offset}


@router.get("/stats")
async def stats():
    """产物统计。"""
    return artifact_service.artifact_stats()


@router.get("/by-ref/{ref_type}/{ref_id}")
async def by_ref(ref_type: str, ref_id: str):
    """按本域记录（生图记录 / 素材 / 审核项 / 发布任务）反查产物。"""
    items = artifact_service.find_artifacts_by_ref(ref_type, ref_id)
    return {"ref_type": ref_type, "ref_id": ref_id, "items": items, "total": len(items)}


@router.post("", status_code=201)
async def register(body: RegisterBody):
    """手动登记产物。"""
    artifact_id = artifact_service.register_artifact(
        source=body.source,
        ref_type=body.ref_type,
        ref_id=body.ref_id,
        path=body.path,
        kind=body.kind,
        stage=body.stage,
        title=body.title,
        thumb=body.thumb,
        media_type=body.media_type,
        parent_id=body.parent_id,
        campaign_id=body.campaign_id,
        platform=body.platform,
        meta=body.meta,
    )
    if not artifact_id:
        raise HTTPException(status_code=500, detail="产物登记失败")
    return artifact_service.get_artifact(artifact_id) or {"artifact_id": artifact_id}


@router.get("/{artifact_id}")
async def detail(artifact_id: str):
    """产物详情（含血缘）。"""
    item = artifact_service.get_artifact(artifact_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"产物不存在: {artifact_id}")
    item["lineage"] = artifact_service.lineage(artifact_id)
    return item


@router.get("/{artifact_id}/lineage")
async def get_lineage(artifact_id: str):
    """产物血缘：父链 + 子链。"""
    item = artifact_service.get_artifact(artifact_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"产物不存在: {artifact_id}")
    return artifact_service.lineage(artifact_id)


@router.post("/{artifact_id}/promote")
async def promote(artifact_id: str, body: PromoteBody):
    """推进产物阶段。"""
    item = artifact_service.get_artifact(artifact_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"产物不存在: {artifact_id}")
    if body.stage not in ALL_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"未知阶段: {body.stage}（可选 {', '.join(ALL_STAGES)}）",
        )
    ok = artifact_service.set_stage(
        artifact_id,
        body.stage,
        review_id=body.review_id,
        publish_task_id=body.publish_task_id,
        campaign_id=body.campaign_id,
        platform=body.platform,
        force=body.force,
    )
    if not ok:
        raise HTTPException(
            status_code=409,
            detail=(
                f"阶段流转被拒绝: {item.get('stage')} → {body.stage}"
                "（合法流转见 ALLOWED_TRANSITIONS，或传 force=true 强制）"
            ),
        )
    return artifact_service.get_artifact(artifact_id)


@router.post("/{artifact_id}/submit-review", status_code=201)
async def submit_review(artifact_id: str, body: SubmitReviewBody):
    """把产物送进审核队列。

    审核项的 `task_id` 存 artifact_id，审核决策回写时据此找到产物并推进阶段，
    从而形成「生成 → 送审 → 审核 → 阶段回写」的闭环。
    """
    item = artifact_service.get_artifact(artifact_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"产物不存在: {artifact_id}")

    from prism_core.review_queue import (
        ReviewItem,
        ReviewPriority,
        ReviewType,
        enqueue_review,
    )

    review_item = ReviewItem(
        task_id=artifact_id,
        campaign_id=body.campaign_id or str(item.get("campaign_id") or ""),
        platform=body.platform,
        platform_name=body.platform_name,
        account_id=body.account_id,
        priority=ReviewPriority(body.priority),
        review_type=ReviewType(body.review_type),
        title=body.title or str(item.get("title") or ""),
        content=body.content,
        cover_url=body.cover_url or (str(item.get("path") or "") or None),
    )
    enqueue_review(review_item)
    artifact_service.attach_review(artifact_id, review_item.review_id)

    return {
        "artifact_id": artifact_id,
        "review_id": review_item.review_id,
        "stage": artifact_service.STAGE_REVIEWING,
    }


__all__ = ["router", "is_artifact_id"]
