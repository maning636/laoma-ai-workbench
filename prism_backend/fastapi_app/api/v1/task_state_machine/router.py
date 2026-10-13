"""幂等任务状态机 API（Phase 0.2）

端点：
  POST   /task-state/              创建任务状态
  GET    /task-state/              列表（支持 status 筛选）
  GET    /task-state/{task_id}     查询单个
  PUT    /task-state/{task_id}     更新（含状态转换校验）
  GET    /task-state/key/{key}     按幂等键查找
  GET    /task-state/validations   合法状态转换表
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from prism_core.task_state_machine import (
    TaskState,
    TaskStatus,
    VALID_TRANSITIONS,
    can_transition,
    transition_state,
    save_task_state,
    get_task_state,
    find_by_idempotency_key,
    list_task_states,
)

router = APIRouter()


class TaskStateCreate(BaseModel):
    status: TaskStatus = TaskStatus.DRAFT
    idempotency_key: str = ""
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    campaign_id: Optional[str] = None
    variant_id: Optional[str] = None
    video_id: Optional[str] = None
    material_id: Optional[str] = None
    attempt: int = 1
    max_attempts: int = 3
    receipt_task_id: Optional[str] = None
    metadata: Optional[str] = None
    error_message: Optional[str] = None


class TaskStateUpdate(BaseModel):
    status: Optional[TaskStatus] = None
    receipt_task_id: Optional[str] = None
    metadata: Optional[str] = None
    error_message: Optional[str] = None
    attempt: Optional[int] = None
    max_attempts: Optional[int] = None


class TaskStateUpdateResponse(BaseModel):
    task_id: str
    status: str
    transition_valid: bool
    message: str = ""


@router.post("/", response_model=TaskState)
def create_task_state(body: TaskStateCreate):
    state = TaskState(**body.model_dump())
    save_task_state(state)
    return state


@router.get("/", response_model=list[TaskState])
def list_tasks(status: Optional[str] = None, limit: int = 50, offset: int = 0):
    return list_task_states(status=status, limit=limit, offset=offset)


@router.get("/key/{key}", response_model=TaskState)
def find_by_key(key: str):
    state = find_by_idempotency_key(key)
    if not state:
        raise HTTPException(status_code=404, detail=f"幂等键 '{key}' 未找到任务")
    return state


@router.get("/validations")
def get_valid_transitions():
    """返回合法状态转换表"""
    return {
        current.value: [t.value for t in targets]
        for current, targets in VALID_TRANSITIONS.items()
    }


@router.get("/{task_id}", response_model=TaskState)
def get_task(task_id: str):
    state = get_task_state(task_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")
    return state


@router.put("/{task_id}", response_model=TaskStateUpdateResponse)
def update_task(task_id: str, body: TaskStateUpdate):
    state = get_task_state(task_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")

    # 状态转换校验
    if body.status is not None and body.status != state.status:
        if not can_transition(state.status, body.status):
            raise HTTPException(
                status_code=400,
                detail=f"非法状态转换: {state.status.value} → {body.status.value}",
            )
        state.status = transition_state(state.status, body.status)

    # 应用其他字段更新
    update_data = body.model_dump(exclude_unset=True)
    update_data.pop("status", None)
    for field_name, value in update_data.items():
        if value is not None:
            setattr(state, field_name, value)

    save_task_state(state)
    return TaskStateUpdateResponse(
        task_id=state.task_id,
        status=state.status.value,
        transition_valid=True,
    )
