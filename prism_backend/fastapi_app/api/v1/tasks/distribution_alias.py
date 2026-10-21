"""
Tasks Distribution 路由别名
提供 /api/tasks/distribution 端点（扫码派发）

对接 myUtils/distribution_manager.py 的真实实现：
  - POST   /api/v1/tasks/distribution              创建派发任务（生成 qr_token）
  - GET    /api/v1/tasks/distribution              派发任务列表（含库存统计）
  - GET    /api/v1/tasks/distribution/{task_id}    派发任务详情 + 库存统计
  - POST   /api/v1/tasks/distribution/{task_id}/videos   追加素材
  - POST   /api/v1/tasks/distribution/{task_id}/claim    按 task_id 原子领取一条素材
  - POST   /api/v1/tasks/distribution/claim/{qr_token}  按 qr_token 原子领取（扫码入口）

历史版本此处为 TODO 空壳（GET 恒返回空列表，POST 直接回 success），
前端扫码派发页因此永远拿不到真实数据。
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from myUtils.distribution_manager import distribution_manager
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
    from myUtils.distribution_manager import distribution_manager

router = APIRouter(prefix="/tasks", tags=["任务管理"])


class DistributionTaskRequest(BaseModel):
    platform: str = Field(..., description="平台：douyin/kuaishou 等")
    title_template: str = Field("", description="标题模板")
    video_files: List[str] = Field(default_factory=list, description="素材文件路径列表")
    poi_location: Optional[str] = Field(None, description="POI 位置")
    expire_time: Optional[str] = Field(None, description="过期时间（ISO 字符串）")


class AddVideosRequest(BaseModel):
    video_files: List[str] = Field(default_factory=list, description="追加的素材文件路径列表")


class ClaimRequest(BaseModel):
    claimer_id: str = Field("", description="领取人标识（扫码用户 ID / 账号 ID）")


@router.get("/distribution")
async def list_distribution_tasks():
    """获取派发任务列表（含每个任务的素材库存统计）。"""
    tasks = distribution_manager.get_all_tasks()
    return {
        "status": "success",
        "result": {
            "success": True,
            "items": tasks,
        },
    }


@router.post("/distribution")
async def create_distribution_task(request: DistributionTaskRequest):
    """创建派发任务：生成 qr_token 并把素材放入可领取池。"""
    if not request.video_files:
        raise HTTPException(status_code=400, detail="至少需要选择一条素材")

    result = distribution_manager.create_task(
        platform=request.platform,
        title_template=request.title_template,
        video_files=request.video_files,
        poi_location=request.poi_location,
        expire_time=request.expire_time,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "创建派发任务失败"))
    return {"status": "success", "result": result}


# 注意：claim 路由必须声明在 /distribution/{task_id} 之前，
# 否则 "claim" 会被当成 task_id（路径参数类型为 int，本可拦截，但显式顺序更稳）。
@router.post("/distribution/claim/{qr_token}")
async def claim_video_by_qr(qr_token: str, request: ClaimRequest):
    """按 qr_token 原子领取一条可用素材（扫码入口）。"""
    result = distribution_manager.claim_video_atomically(qr_token, request.claimer_id)
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("error", "无可用素材"))
    return {"status": "success", "result": result}


@router.get("/distribution/{task_id}")
async def get_distribution_task(task_id: int):
    """获取派发任务详情 + 库存统计。"""
    status = distribution_manager.get_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"派发任务不存在: {task_id}")
    return {"status": "success", "result": {"success": True, **status}}


@router.post("/distribution/{task_id}/videos")
async def add_videos_to_distribution_task(task_id: int, request: AddVideosRequest):
    """向已有派发任务追加素材。"""
    if not request.video_files:
        raise HTTPException(status_code=400, detail="未提供素材路径")
    status = distribution_manager.get_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"派发任务不存在: {task_id}")
    result = distribution_manager.add_videos_to_task(task_id, request.video_files)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "追加素材失败"))
    return {"status": "success", "result": result}


@router.post("/distribution/{task_id}/claim")
async def claim_video_by_task(task_id: int, request: ClaimRequest):
    """按 task_id 原子领取一条可用素材（发布流程调用）。"""
    result = distribution_manager.claim_video_by_task(task_id, request.claimer_id)
    if not result.get("success"):
        raise HTTPException(status_code=409, detail=result.get("error", "无可用素材"))
    return {"status": "success", "result": result}
