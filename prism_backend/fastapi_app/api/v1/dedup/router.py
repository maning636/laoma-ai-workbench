"""
去重查重 API 路由

端点：
- POST /api/v1/dedup/check          检查内容重复
- GET  /api/v1/dedup/records        列出查重记录
- GET  /api/v1/dedup/records/{id}   查询单条记录
- GET  /api/v1/dedup/report         查重报告
- GET  /api/v1/dedup/fingerprint    计算内容指纹
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from prism_core.dedup import (
    DedupRecord,
    DupLevel,
    check_duplicate,
    get_dedup_record,
    list_dedup_records,
    content_fingerprint,
    title_fingerprint,
    compute_similarity,
    dedup_checker,
)

router = APIRouter(prefix="/dedup", tags=["dedup"])


class CheckBody(BaseModel):
    task_id: str
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    title: str = ""
    content: str = ""
    video_hash: str = ""


@router.post("/check", status_code=201)
async def check(body: CheckBody):
    """检查内容是否重复"""
    record = check_duplicate(
        task_id=body.task_id,
        platform=body.platform,
        platform_name=body.platform_name,
        account_id=body.account_id,
        title=body.title,
        content=body.content,
        video_hash=body.video_hash,
    )
    return record.model_dump(mode="json")


@router.get("/records")
async def list_records(
    dup_level: Optional[str] = Query(None, description="dup_level: none/low/medium/high"),
    account_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """列出查重记录"""
    records = list_dedup_records(
        dup_level=dup_level, account_id=account_id,
        limit=limit, offset=offset,
    )
    return [r.model_dump(mode="json") for r in records]


@router.get("/records/{dedup_id}")
async def get_record(dedup_id: str):
    """查询单条查重记录"""
    record = get_dedup_record(dedup_id)
    if not record:
        raise HTTPException(404, f"查重记录不存在: {dedup_id}")
    return record.model_dump(mode="json")


@router.get("/report")
async def dedup_report(account_id: Optional[str] = Query(None)):
    """查重报告"""
    return dedup_checker.get_duplicate_report(account_id)


@router.get("/fingerprint")
async def compute_fp(
    title: str = Query("", description="标题"),
    content: str = Query("", description="内容"),
    video_hash: str = Query("", description="视频哈希"),
):
    """计算内容指纹"""
    return {
        "content_hash": content_fingerprint(title, content, video_hash),
        "title_hash": title_fingerprint(title),
        "video_hash": video_hash,
    }


class SimilarityBody(BaseModel):
    title_a: str
    title_b: str


@router.post("/similarity")
async def compute_sim(body: SimilarityBody):
    """计算标题相似度"""
    sim = compute_similarity(body.title_a, body.title_b)
    return {"title_a": body.title_a, "title_b": body.title_b, "similarity": sim}
