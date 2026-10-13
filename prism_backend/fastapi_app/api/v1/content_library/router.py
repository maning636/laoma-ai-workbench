"""
原生内容库 API —— 直读 Easel outputs 磁盘（不经 Easel 服务器）。

- GET  /api/v1/content-library            产物树（缓存）
- POST /api/v1/content-library/refresh    强制重扫
- GET  /api/v1/content-library/file?path= 读取文本产物内容
- GET  /api/v1/content-library/media?path= 媒体文件流式输出（预览/下载）
- GET  /api/v1/content-library/preview?path= HTML 渲染（本地图 base64 内联，防公众号回源裂图）
- GET  /api/v1/content-library/ideas      选题库（_ideas.json）
- POST /api/v1/content-library/ideas      保存选题库
- GET  /api/v1/content-library/schedule   排期（_schedule.json）
- POST /api/v1/content-library/schedule   保存排期
- GET  /api/v1/content-library/accounts   各平台登录态
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse

from fastapi_app.core.logger import logger
from fastapi_app.services import easel_outputs as outputs_svc

router = APIRouter(prefix="/content-library", tags=["内容库"])


@router.get("")
async def list_outputs():
    try:
        return {"status": "success", "result": outputs_svc.list_outputs_cached()}
    except Exception as e:
        logger.error(f"内容库扫描失败: {e}")
        raise HTTPException(status_code=500, detail=f"内容库扫描失败: {e}")


@router.post("/refresh")
async def refresh_outputs():
    outputs_svc.get_outputs_cached()
    return {"status": "success", "result": outputs_svc.list_outputs_cached()}


@router.get("/file")
async def read_file(path: str = Query(...)):
    try:
        return {"status": "success", "result": {"path": path, "content": outputs_svc.read_output_text(path)}}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/media")
async def media(path: str = Query(...)):
    try:
        full = outputs_svc.open_output(path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(full, filename=full.name)


@router.get("/preview")
async def preview_html(path: str = Query(...)):
    """HTML 预览：本地图 base64 内联，防公众号回源裂图。参照 Easel v0.2.1。"""
    try:
        result = outputs_svc.preview_html(path)
        return {"status": "success", "result": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"HTML 预览失败: {e}")
        raise HTTPException(status_code=500, detail=f"HTML 预览失败：{e}")


@router.get("/ideas")
async def get_ideas():
    return {"status": "success", "result": {"ideas": outputs_svc.get_ideas()}}


@router.post("/ideas")
async def save_ideas(ideas: List[Dict] = Body(default=[])):
    outputs_svc.save_ideas(ideas)
    return {"status": "success", "result": {"count": len(ideas)}}


@router.get("/schedule")
async def get_schedule():
    return {"status": "success", "result": {"schedule": outputs_svc.get_schedule()}}


@router.post("/schedule")
async def save_schedule(schedule: List[Dict] = Body(default=[])):
    outputs_svc.save_schedule(schedule)
    return {"status": "success", "result": {"count": len(schedule)}}


@router.get("/accounts")
async def get_login_status():
    return {"status": "success", "result": {"accounts": outputs_svc.get_login_status()}}
