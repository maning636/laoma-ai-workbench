"""任务监控与告警 API（Phase 0.3）

端点：
  POST /monitor/events                     记录监控事件
  GET  /monitor/events                     事件列表（支持类型/账号/严重度筛选）
  POST /monitor/transitions                记录状态转换
  GET  /monitor/transitions                状态转换列表
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from prism_core.monitor import (
    MonitorEventType,
    MonitorEvent,
    StateTransition,
    AlertWebhookConfig,
    record_event,
    record_state_transition,
    list_monitor_events,
    list_state_transitions,
)

router = APIRouter()


class MonitorEventCreate(BaseModel):
    event_type: MonitorEventType = MonitorEventType.TASK_STATE_CHANGED
    severity: str = "info"
    task_id: Optional[str] = None
    receipt_task_id: Optional[str] = None
    account_id: Optional[str] = None
    platform: int = 0
    platform_name: str = ""
    message: str = ""
    metadata: Optional[str] = None


class StateTransitionCreate(BaseModel):
    task_id: str = ""
    account_id: str = ""
    from_status: str = ""
    to_status: str = ""
    reason: str = ""


@router.post("/events", response_model=MonitorEvent)
def create_event(body: MonitorEventCreate):
    event = MonitorEvent(**body.model_dump())
    record_event(event)
    return event


@router.get("/events", response_model=list[MonitorEvent])
def list_events(
    event_type: Optional[str] = None,
    account_id: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    return list_monitor_events(
        event_type=event_type,
        account_id=account_id,
        severity=severity,
        limit=limit,
        offset=offset,
    )


@router.post("/transitions", response_model=StateTransition)
def create_transition(body: StateTransitionCreate):
    transition = StateTransition(**body.model_dump())
    record_state_transition(transition)
    return transition


@router.get("/transitions", response_model=list[StateTransition])
def list_transitions(task_id: Optional[str] = None, limit: int = 50):
    return list_state_transitions(task_id=task_id, limit=limit)
