"""矩阵分组路由 API（Phase 2.3）

端点：
  POST /matrix-groups/                   创建分组
  GET  /matrix-groups/                   列表
  GET  /matrix-groups/{group_id}         查询单个分组
  POST /matrix-groups/{group_id}/assign  任务分配
  GET  /matrix-groups/{group_id}/stats   分组统计
  GET  /matrix-assignments/              分配记录列表
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from prism_core.matrix_route import (
    MatrixMode,
    MatrixGroup,
    MatrixAssignment,
    save_group,
    get_group,
    list_groups,
    assign_task,
    get_assignments,
    matrix_router,
)

router = APIRouter()


class MatrixGroupCreate(BaseModel):
    name: str = ""
    description: str = ""
    platforms: Optional[List[int]] = None
    routing_mode: MatrixMode = MatrixMode.ROUND_ROBIN
    weights: Optional[Dict[str, int]] = None
    schedule: Optional[Dict[str, Any]] = None
    max_daily_tasks: int = 10
    active_accounts: int = 0


class AssignTaskRequest(BaseModel):
    task_id: str = ""
    accounts: List[Dict[str, Any]] = Field(default_factory=list)


@router.post("/matrix-groups/", response_model=MatrixGroup)
def create_group(body: MatrixGroupCreate):
    group = MatrixGroup(
        name=body.name,
        description=body.description,
        platforms=json.dumps(body.platforms) if body.platforms else None,
        routing_mode=body.routing_mode,
        weights=json.dumps(body.weights) if body.weights else None,
        schedule=json.dumps(body.schedule) if body.schedule else None,
        max_daily_tasks=body.max_daily_tasks,
        active_accounts=body.active_accounts,
    )
    save_group(group)
    return group


@router.get("/matrix-groups/", response_model=list[MatrixGroup])
def list_all_groups(limit: int = 50, offset: int = 0):
    return list_groups(limit=limit, offset=offset)


@router.get("/matrix-groups/{group_id}", response_model=MatrixGroup)
def get_one_group(group_id: str):
    group = get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail=f"矩阵分组 '{group_id}' 不存在")
    return group


@router.post("/matrix-groups/{group_id}/assign", response_model=MatrixAssignment)
def assign(group_id: str, body: AssignTaskRequest):
    try:
        return assign_task(group_id, body.task_id, body.accounts)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/matrix-groups/{group_id}/stats")
def group_stats(group_id: str):
    result = matrix_router.group_stats(group_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/matrix-assignments/", response_model=list[MatrixAssignment])
def list_all_assignments(
    group_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    return get_assignments(group_id=group_id, limit=limit, offset=offset)
