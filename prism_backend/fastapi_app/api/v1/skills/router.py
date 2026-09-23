"""
技能库 API（Prism × Easel 融合）—— 对外"实时更新 skills"接口。

- GET  /api/v1/skills            技能目录（支持 layer/keyword 过滤）
- GET  /api/v1/skills/{name}     技能详情（含 SKILL.md 正文）
- POST /api/v1/skills/refresh    强制重扫磁盘（Easel 更新后调用即生效）
- GET  /api/v1/skills/shared-scripts   Easel 公共脚本工具清单（创作工坊执行层）
"""
from fastapi import APIRouter, HTTPException, Query

from fastapi_app.core.logger import logger
from fastapi_app.services import skill_registry

router = APIRouter(prefix="/skills", tags=["技能库"])


@router.get("")
async def list_skills(
    layer: str = Query(None, description="按分层过滤: discover/plan/produce/publish/attribute/general"),
    keyword: str = Query(None, description="按名称/描述关键词搜索"),
):
    """技能目录（轻量，不含正文）。"""
    try:
        return {"status": "success", "result": skill_registry.list_skills(layer=layer, keyword=keyword)}
    except Exception as e:
        logger.error(f"技能目录查询失败: {e}")
        raise HTTPException(status_code=500, detail=f"技能目录查询失败: {e}")


@router.get("/shared-scripts")
async def shared_scripts():
    """Easel 公共脚本工具清单（47 个 Python 工具，创作工坊执行层）。"""
    try:
        return {"status": "success", "result": {"items": skill_registry.shared_scripts()}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"脚本清单查询失败: {e}")


@router.post("/refresh")
async def refresh_skills():
    """强制重扫技能磁盘目录（Easel git pull 后调用即生效）。"""
    try:
        return {"status": "success", "result": skill_registry.refresh_skills()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"技能刷新失败: {e}")


@router.get("/{name}")
async def get_skill(name: str):
    """技能详情（含 SKILL.md 正文）。"""
    try:
        return {"status": "success", "result": skill_registry.get_skill(name)}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"技能详情查询失败: {e}")
