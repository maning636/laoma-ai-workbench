"""内容版本管理与审核队列 API（Phase 3.1 + 3.3）

端点：
  POST   /variants/                 创建内容版本
  GET    /variants/                 列表（支持 campaign_id/status/platform 筛选）
  GET    /variants/{variant_id}     查询单个
  PUT    /variants/{variant_id}     更新内容版本
  DELETE /variants/{variant_id}     删除内容版本
  POST   /variants/{variant_id}/submit   提交审核
  POST   /variants/{variant_id}/approve  批准
  POST   /variants/{variant_id}/reject   拒绝
  POST   /variants/{variant_id}/return   退回修改
  GET    /reviews/                  审核记录列表
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from prism_core.content_variant import (
    ContentVariant,
    VariantStatus,
    ReviewRecord,
    ReviewDecision,
    save_variant,
    get_variant,
    list_variants,
    submit_for_review,
    record_review,
    list_reviews,
    approve_variant,
    reject_variant,
    return_variant,
)

router = APIRouter()


# ── ContentVariant Pydantic models ──

class ContentVariantCreate(BaseModel):
    campaign_id: Optional[str] = None
    material_id: Optional[str] = None
    video_id: Optional[str] = None
    platform: int = 0
    platform_name: str = ""
    title: str = ""
    content: str = ""
    tags: List[str] = Field(default_factory=list)
    cover_url: Optional[str] = None
    format_spec: Optional[str] = None
    status: VariantStatus = VariantStatus.DRAFT


class ContentVariantUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    cover_url: Optional[str] = None
    format_spec: Optional[str] = None
    status: Optional[VariantStatus] = None


class ReviewActionRequest(BaseModel):
    reviewer: str = ""
    comment: str = ""


class SubmitReviewResponse(BaseModel):
    variant_id: str
    submitted: bool
    message: str = ""


# ── CRUD endpoints ──

@router.post("/variants/", response_model=ContentVariant)
def create_variant(body: ContentVariantCreate):
    variant = ContentVariant(**body.model_dump())
    save_variant(variant)
    return variant


@router.get("/variants/", response_model=list[ContentVariant])
def list_all(
    campaign_id: Optional[str] = None,
    status: Optional[str] = None,
    platform: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
):
    return list_variants(campaign_id=campaign_id, status=status, platform=platform, limit=limit, offset=offset)


@router.get("/variants/{variant_id}", response_model=ContentVariant)
def get_one(variant_id: str):
    variant = get_variant(variant_id)
    if not variant:
        raise HTTPException(status_code=404, detail=f"内容版本 '{variant_id}' 不存在")
    return variant


@router.put("/variants/{variant_id}", response_model=ContentVariant)
def update_variant(variant_id: str, body: ContentVariantUpdate):
    variant = get_variant(variant_id)
    if not variant:
        raise HTTPException(status_code=404, detail=f"内容版本 '{variant_id}' 不存在")
    update_data = body.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        if value is not None:
            setattr(variant, field_name, value)
    from prism_core.content_variant import now_beijing_iso
    variant.updated_at = now_beijing_iso()
    save_variant(variant)
    return variant


@router.delete("/variants/{variant_id}")
def delete_variant(variant_id: str):
    from fastapi_app.db.runtime import mysql_enabled, sa_connection
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("DELETE FROM content_variants WHERE variant_id = :vid"), {"vid": variant_id})
            conn.commit()
    else:
        from fastapi_app.db.session import open_main_db
        conn = open_main_db()
        conn.execute("DELETE FROM content_variants WHERE variant_id = ?", (variant_id,))
        conn.commit()
    return {"ok": True, "variant_id": variant_id}


# ── Review endpoints ──

@router.post("/variants/{variant_id}/submit", response_model=SubmitReviewResponse)
def submit_review(variant_id: str):
    ok = submit_for_review(variant_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"内容版本 '{variant_id}' 不存在")
    return SubmitReviewResponse(variant_id=variant_id, submitted=True, message="已提交审核")


@router.post("/variants/{variant_id}/approve", response_model=ReviewRecord)
def approve(variant_id: str, body: ReviewActionRequest):
    record = approve_variant(variant_id, body.reviewer, body.comment)
    if not record:
        raise HTTPException(status_code=404, detail=f"内容版本 '{variant_id}' 不存在")
    return record


@router.post("/variants/{variant_id}/reject", response_model=ReviewRecord)
def reject(variant_id: str, body: ReviewActionRequest):
    record = reject_variant(variant_id, body.reviewer, body.comment)
    if not record:
        raise HTTPException(status_code=404, detail=f"内容版本 '{variant_id}' 不存在")
    return record


@router.post("/variants/{variant_id}/return", response_model=ReviewRecord)
def return_for_edit(variant_id: str, body: ReviewActionRequest):
    record = return_variant(variant_id, body.reviewer, body.comment)
    if not record:
        raise HTTPException(status_code=404, detail=f"内容版本 '{variant_id}' 不存在")
    return record


@router.get("/reviews/", response_model=list[ReviewRecord])
def list_all_reviews(variant_id: Optional[str] = None, limit: int = 50):
    return list_reviews(variant_id=variant_id, limit=limit)
