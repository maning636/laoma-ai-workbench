"""
投放计划模块路由 (Refactored for Matrix System)
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, List, Optional

from fastapi_app.models.campaign_new import CreateCampaignRequest, Campaign
from fastapi_app.services.campaign_service import get_campaign_service, CampaignService

router = APIRouter(prefix="/campaigns", tags=["投放计划"])

@router.post("/create")
async def create_campaign(
    request: CreateCampaignRequest,
    service: CampaignService = Depends(get_campaign_service)
):
    """创建新的矩阵投放计划"""
    campaign = await service.create_campaign(request)
    return {
        "status": "success",
        "result": {
            "success": True,
            "campaign_id": campaign.id,
            "tasks_created": campaign.task_count
        }
    }

@router.get("/list")
async def list_campaigns(
    service: CampaignService = Depends(get_campaign_service)
):
    """获取所有投放计划列表（附带真实执行进度）"""
    campaigns = service.list_campaigns()
    items = []
    for campaign in campaigns:
        item = campaign.model_dump(mode="json")
        item.update(service.compute_task_stats(campaign))
        items.append(item)
    return {
        "status": "success",
        "result": {
            "success": True,
            "items": items
        }
    }

@router.get("/{campaign_id}")
async def get_campaign_detail(
    campaign_id: str,
    service: CampaignService = Depends(get_campaign_service)
):
    """获取投放计划详情"""
    campaign = service.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    plan = campaign.model_dump(mode="json")
    plan.update(service.compute_task_stats(campaign))
    return {
        "status": "success",
        "result": {
            "success": True,
            "plan": plan
        }
    }

@router.get("/{campaign_id}/tasks")
async def get_campaign_tasks(
    campaign_id: str,
    service: CampaignService = Depends(get_campaign_service)
):
    """获取计划关联的任务清单"""
    tasks = service.get_campaign_tasks(campaign_id)
    return {
        "status": "success",
        "result": {
            "success": True,
            "items": tasks
        }
    }


@router.get("/{campaign_id}/publish-tasks")
async def get_campaign_publish_tasks(
    campaign_id: str,
    limit: Optional[int] = 200,
):
    """按 campaign_id 反查 publish_tasks（L3-1）。

    publish_tasks.campaign_id 由向导发布时透传写入（BatchPublishRequest.campaign_id）；
    本端点让 campaigns 页可以列出「本活动关联的发布任务」——原本 campaigns 是孤岛，
    现在通过软关联列打通。老数据 campaign_id 为空 → 返回空列表，不报错。
    """
    import sqlite3
    from fastapi_app.core.config import settings

    limit = max(1, min(int(limit or 200), 1000))
    try:
        conn = sqlite3.connect(settings.DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT task_id, celery_task_id, platform, account_id, material_id, "
                "title, status, campaign_id, artifact_id, created_at, published_at "
                "FROM publish_tasks WHERE campaign_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (campaign_id, limit),
            ).fetchall()
            items = [dict(r) for r in rows]
        finally:
            conn.close()
    except sqlite3.OperationalError:
        # 老库若尚无 campaign_id 列（未跑过 ensure_all_tables）→ 视为无关联，返回空
        items = []
    return {
        "status": "success",
        "result": {
            "success": True,
            "campaign_id": campaign_id,
            "items": items,
            "count": len(items),
        },
    }

@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str,
    service: CampaignService = Depends(get_campaign_service)
):
    """暂停投放计划"""
    service.pause_campaign(campaign_id)
    return {"status": "success", "result": {"success": True}}

@router.post("/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: str,
    service: CampaignService = Depends(get_campaign_service)
):
    """恢复投放计划"""
    service.resume_campaign(campaign_id)
    return {"status": "success", "result": {"success": True}}


@router.post("/{campaign_id}/execute")
async def execute_campaign(
    campaign_id: str,
    service: CampaignService = Depends(get_campaign_service)
):
    campaign = await service.execute_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return {
        "status": "success",
        "result": {
            "success": True,
            "campaign_id": campaign.id,
            "tasks_created": campaign.task_count
        }
    }

@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: str,
    service: CampaignService = Depends(get_campaign_service)
):
    """删除投放计划"""
    service.delete_campaign(campaign_id)
    return {"status": "success", "result": {"success": True}}
