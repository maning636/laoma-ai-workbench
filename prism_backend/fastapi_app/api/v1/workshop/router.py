"""
创作工坊 API —— Easel 技能脚本的表单直调。

- GET  /api/v1/workshop/tools   工具注册表（前端动态表单依据）
- POST /api/v1/workshop/run     执行工具（multipart: files[] + tool + params JSON），
                                产物自动写入素材库并返回 file_ids
"""
import json
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from fastapi_app.core.logger import logger
from fastapi_app.services import workshop

router = APIRouter(prefix="/workshop", tags=["创作工坊"])


@router.get("/tools")
async def list_tools():
    """工具注册表（创作工坊动态表单的依据）。"""
    return {"status": "success", "result": {"tools": workshop.get_tool_specs()}}


@router.post("/run")
async def run_tool(
    tool: str = Form(..., description="工具 ID"),
    params: str = Form("{}", description="工具参数 JSON"),
    files: List[UploadFile] = File(None, description="输入文件（按工具声明的 inputs 顺序）"),
):
    """执行创作工具：输入文件 + 参数 → 脚本运行 → 产物自动入素材库。"""
    try:
        parsed_params = json.loads(params) if params else {}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"params 不是合法 JSON: {e}")

    spec = workshop.get_tool_spec(tool)
    declared_inputs = spec.get("inputs", [])
    input_files: dict[str, bytes] = {}
    input_exts: dict[str, str] = {}
    for idx, f in enumerate(files or []):
        key = declared_inputs[idx]["name"] if idx < len(declared_inputs) else f"file{idx}"
        input_files[key] = await f.read()
        input_exts[key] = Path(f.filename or "input").suffix

    from fastapi_app.api.v1.files.services import FileService
    from fastapi_app.db.session import main_db_pool

    try:
        result = workshop.run_tool(tool, parsed_params, input_files, input_exts)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        logger.error(f"[Workshop] {tool} 执行失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"[Workshop] {tool} 异常: {e}")
        raise HTTPException(status_code=500, detail=f"执行异常: {e}")

    # 产物自动入库
    service = FileService()
    file_ids: List[int] = []
    with main_db_pool.get_connection() as conn:
        for out_path in result.get("outputs", []):
            p = Path(out_path)
            try:
                file_id = await service.save_file_record(
                    conn,
                    filename=f"[workshop:{tool}] {p.name}",
                    file_path=str(p),
                    filesize_mb=p.stat().st_size / (1024 * 1024),
                    note=f"workshop:{tool} params={json.dumps(parsed_params, ensure_ascii=False)[:200]}",
                    group_name=f"workshop:{tool}",
                )
                file_ids.append(file_id)
            except Exception as e:
                logger.error(f"[Workshop] 产物入库失败 {p.name}: {e}")

    return {
        "status": "success",
        "result": {
            "tool": tool,
            "elapsed_seconds": result.get("elapsed_seconds"),
            "outputs": [Path(o).name for o in result.get("outputs", [])],
            "file_ids": file_ids,
        },
    }
