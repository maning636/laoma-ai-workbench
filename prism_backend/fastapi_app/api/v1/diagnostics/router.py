"""发布诊断工件采集 API（Phase 2.2）

端点：
  POST /diagnostics/                       采集并保存诊断工件
  GET  /diagnostics/                       列表（支持 task_id/platform 筛选）
  POST /diagnostics/redact                 文本脱敏
  GET  /diagnostics/{task_id}              按任务查询诊断工件
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from prism_core.diagnostics import (
    DiagnosticArtifacts,
    save_diagnostic_artifacts,
    get_diagnostic_artifacts,
    list_diagnostic_artifacts,
    collect_diagnostics,
    redact_sensitive_info,
)

router = APIRouter()


class CollectDiagnosticsRequest(BaseModel):
    task_id: str = ""
    platform: int = 0
    platform_name: str = ""
    screenshot_path: Optional[str] = None
    dom_path: Optional[str] = None
    url_snapshot: Optional[str] = None
    error_stack: Optional[str] = None
    log_path: Optional[str] = None
    cookie_status: Optional[str] = None
    ip_address: Optional[str] = None


class RedactRequest(BaseModel):
    text: str


@router.post("/", response_model=DiagnosticArtifacts)
def collect(body: CollectDiagnosticsRequest):
    """采集并发布诊断工件"""
    return collect_diagnostics(**body.model_dump())


@router.post("/redact")
def redact_text(body: RedactRequest):
    """对文本做敏感信息脱敏"""
    return {"redacted": redact_sensitive_info(body.text)}


@router.get("/", response_model=list[DiagnosticArtifacts])
def list_artifacts(
    task_id: Optional[str] = None,
    platform: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
):
    return list_diagnostic_artifacts(task_id=task_id, platform=platform, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=DiagnosticArtifacts)
def get_by_task(task_id: str):
    artifacts = get_diagnostic_artifacts(task_id)
    if not artifacts:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 无诊断工件")
    return artifacts
