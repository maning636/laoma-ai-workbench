"""
Easel Web 工作台托管 API（内嵌进 Prism 前端）+ 稿件桥。

- /easel/status|start|stop: Easel 工作台进程托管（前端 /easel iframe 嵌入）
- /easel/drafts: Easel 内容库稿件列表（.easel.json 元数据项目）
- /easel/media/{path}: Easel 成品媒体流式代理（预览/下载）
- /easel/drafts/{project}/import: 导入稿件 deliverables 到 Prism 素材库
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.db.session import main_db_pool
from fastapi_app.services import easel_drafts, easel_workbench

router = APIRouter(prefix="/easel", tags=["Easel"])


async def get_db():
    """与 files/router.py 相同的数据库连接依赖。"""
    with main_db_pool.get_connection() as conn:
        yield conn


@router.get("/status")
async def easel_status():
    """Easel Web 状态（running / url / web_api_online / gateway_online）。"""
    try:
        return {"status": "success", "result": await easel_workbench.get_easel_status()}
    except Exception as e:
        logger.error(f"查询 Easel 状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询 Easel 状态失败: {e}")


@router.post("/start")
async def easel_start():
    """拉起 Easel Web 工作台（幂等：已在运行则直接返回状态）。"""
    try:
        result = await easel_workbench.start_easel()
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"启动 Easel 失败: {e}")
        raise HTTPException(status_code=500, detail=f"启动 Easel 失败: {e}")


@router.post("/stop")
async def easel_stop():
    """停止 Easel Web 工作台。"""
    try:
        result = await easel_workbench.stop_easel()
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"停止 Easel 失败: {e}")
        raise HTTPException(status_code=500, detail=f"停止 Easel 失败: {e}")


@router.get("/drafts")
async def easel_drafts_list():
    """Easel 稿件列表（带 .easel.json 元数据的内容库项目）。"""
    try:
        result = await easel_drafts.list_drafts()
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"获取 Easel 稿件列表失败: {e}")
        raise HTTPException(status_code=502, detail=f"获取 Easel 稿件列表失败: {e}")


@router.get("/drafts/{project}")
async def easel_draft_detail(project: str):
    """单个稿件详情（含每个 deliverable 的代理预览 URL）。"""
    try:
        result = await easel_drafts.get_draft_detail(project)
        return {"status": "success", "result": result}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"获取 Easel 稿件详情失败: {e}")
        raise HTTPException(status_code=502, detail=f"获取 Easel 稿件详情失败: {e}")


@router.get("/outputs")
async def easel_outputs_tree():
    """Easel outputs 完整产物树（内容库浏览：项目目录 + 文件 + 元数据）。"""
    import httpx as _httpx

    from fastapi_app.services.easel_drafts import _easel_base_url

    try:
        async with _httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{_easel_base_url()}/api/outputs")
            resp.raise_for_status()
            return {"status": "success", "result": resp.json()}
    except Exception as e:
        logger.error(f"获取 Easel outputs 树失败: {e}")
        raise HTTPException(status_code=502, detail=f"Easel 内容库不可达: {e}")


@router.get("/media/{path:path}")
async def easel_media(path: str):
    """流式代理 Easel 成品媒体文件（图片/视频/音频，供前端预览）。"""
    try:
        status, headers, iterator = await easel_drafts.get_media_stream(path)
    except LookupError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取 Easel 媒体失败: {e}")
    if status != 200:
        raise HTTPException(status_code=404, detail="Easel 媒体不存在")
    return StreamingResponse(iterator, headers=headers)


@router.post("/drafts/{project}/import")
async def easel_draft_import(project: str, db=Depends(get_db)):
    """导入稿件 deliverables 到 Prism 素材库，返回 material_ids（可直接建投放计划）。"""
    from fastapi_app.api.v1.files.services import FileService

    service = FileService()

    async def upload_file(filename: str, content: bytes, display_name: str, group: str, note: str):
        ext = Path(filename).suffix
        unique_filename = f"{uuid.uuid4()}{ext}"
        file_path = Path(settings.VIDEO_FILES_DIR) / unique_filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(content)
        filesize_mb = len(content) / (1024 * 1024)
        file_id = await service.save_file_record(
            db,
            filename=display_name,
            file_path=str(file_path),
            filesize_mb=filesize_mb,
            note=note,
            group_name=group,
        )
        return {"file_id": file_id, "saved_path": str(file_path)}

    try:
        result = await easel_drafts.import_draft(project, upload_file)
        return {"status": "success", "result": result}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"导入 Easel 稿件失败: {e}")
        raise HTTPException(status_code=502, detail=f"导入 Easel 稿件失败: {e}")
