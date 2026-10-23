"""
幂等任务状态机（Phase 0.2）

状态流转：
  draft → awaiting_review → approved → scheduled → queued → running → succeeded
                                                         ↘ failed_retryable → running (重试)
                                                         ↘ failed_final
                                                         ↘ cancelled

幂等键格式：
  campaign:{campaign_id}:variant:{variant_id}:account:{account_id}
  无 campaign/variant 时 fallback：video:{video_hash}:account:{account_id}
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso
from fastapi_app.db.runtime import mysql_enabled, sa_connection


# ── 任务状态 ──

class TaskStatus(str, Enum):
    DRAFT = "draft"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    CANCELLED = "cancelled"


# ── 状态机异常 ──

class InvalidTransition(ValueError):
    """非法状态转换（PLAN Phase 0.2 契约）。

    继承 ValueError 保持向后兼容：既有调用点 catch ValueError 仍生效。
    """
    pass


# ── 旧状态名映射（回归：processing 等旧名自动映射到新枚举）──

LEGACY_STATUS_MAP: Dict[str, TaskStatus] = {
    "processing": TaskStatus.RUNNING,
    "success": TaskStatus.SUCCEEDED,
    "successful": TaskStatus.SUCCEEDED,
    "done": TaskStatus.SUCCEEDED,
    "completed": TaskStatus.SUCCEEDED,
    "failed": TaskStatus.FAILED_FINAL,
    "retryable": TaskStatus.FAILED_RETRYABLE,
    "pending": TaskStatus.DRAFT,
    "review": TaskStatus.AWAITING_REVIEW,
    "submit": TaskStatus.AWAITING_REVIEW,
    "submitted": TaskStatus.AWAITING_REVIEW,
    "cancel": TaskStatus.CANCELLED,
}


# 合法状态转换表
VALID_TRANSITIONS: Dict[TaskStatus, List[TaskStatus]] = {
    TaskStatus.DRAFT: [TaskStatus.AWAITING_REVIEW, TaskStatus.APPROVED, TaskStatus.CANCELLED],
    TaskStatus.AWAITING_REVIEW: [TaskStatus.APPROVED, TaskStatus.CANCELLED, TaskStatus.DRAFT],
    TaskStatus.APPROVED: [TaskStatus.SCHEDULED, TaskStatus.QUEUED, TaskStatus.CANCELLED],
    TaskStatus.SCHEDULED: [TaskStatus.QUEUED, TaskStatus.CANCELLED],
    TaskStatus.QUEUED: [TaskStatus.RUNNING, TaskStatus.CANCELLED],
    TaskStatus.RUNNING: [TaskStatus.SUCCEEDED, TaskStatus.FAILED_RETRYABLE, TaskStatus.FAILED_FINAL],
    TaskStatus.FAILED_RETRYABLE: [TaskStatus.RUNNING, TaskStatus.FAILED_FINAL, TaskStatus.CANCELLED],
    TaskStatus.FAILED_FINAL: [],
    TaskStatus.CANCELLED: [],
    TaskStatus.SUCCEEDED: [],
}


class TaskState(BaseModel):
    """任务状态记录"""
    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:16]}")
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
    receipt_task_id: Optional[str] = None  # 关联的 PublishReceipt.task_id
    metadata: Optional[str] = None  # JSON
    error_message: Optional[str] = None
    created_at: str = Field(default_factory=now_beijing_iso)
    updated_at: str = Field(default_factory=now_beijing_iso)
    completed_at: Optional[str] = None

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_legacy_status(cls, v: Any) -> Any:
        """旧状态名（processing/success/failed/…）自动映射到新枚举。

        回归保障：PLAN Phase 0.2 要求旧状态名自动映射。
        未识别字符串保持原样让 Pydantic 抛 ValidationError。
        """
        if isinstance(v, TaskStatus) or v is None:
            return v
        if isinstance(v, str):
            return LEGACY_STATUS_MAP.get(v.lower(), v)
        return v


# ── 幂等键生成 ──

def build_idempotency_key(
    campaign_id: Optional[str] = None,
    variant_id: Optional[str] = None,
    account_id: str = "",
    video_hash: Optional[str] = None,
) -> str:
    """
    生成幂等键。
    优先 campaign:variant:account，无则 fallback 到 video_hash:account。
    """
    if campaign_id and variant_id:
        return f"campaign:{campaign_id}:variant:{variant_id}:account:{account_id}"
    if video_hash:
        return f"video:{video_hash}:account:{account_id}"
    return f"task:{uuid.uuid4().hex[:12]}"


def compute_video_hash(video_path: str) -> str:
    """基于路径生成视频哈希（轻量）"""
    return hashlib.md5(video_path.encode("utf-8")).hexdigest()[:12]


# ── 状态转换 ──

def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in VALID_TRANSITIONS.get(current, [])


def transition_state(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    if not can_transition(current, target):
        raise InvalidTransition(f"非法状态转换: {current.value} → {target.value}")
    return target


def retry_task(state: TaskState, error_message: Optional[str] = None) -> TaskState:
    """failed_retryable → running 重入（PLAN Phase 0.2 验收项）。

    契约：
      - task_id 保持不变
      - attempt + 1
      - 状态变为 running，error_message 清空
      - 若 attempt 已达 max_attempts → 转 failed_final（防止无限重试）
      - 非 failed_retryable 状态调用 → InvalidTransition
    """
    if state.status != TaskStatus.FAILED_RETRYABLE:
        raise InvalidTransition(
            f"retry_task 只能在 failed_retryable 状态调用，当前: {state.status.value}"
        )
    if state.attempt >= state.max_attempts:
        # 重试次数耗尽 → 转为 failed_final
        return state.model_copy(update={
            "status": TaskStatus.FAILED_FINAL,
            "error_message": state.error_message or error_message,
            "updated_at": now_beijing_iso(),
            "completed_at": state.completed_at or now_beijing_iso(),
        })
    return state.model_copy(update={
        "status": TaskStatus.RUNNING,
        "attempt": state.attempt + 1,
        "error_message": None,
        "updated_at": now_beijing_iso(),
    })


# ── 持久化 ──

def _ensure_task_state_table(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS task_states (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'draft',
            idempotency_key TEXT NOT NULL,
            platform INTEGER DEFAULT 0,
            platform_name TEXT DEFAULT '',
            account_id TEXT DEFAULT '',
            campaign_id TEXT,
            variant_id TEXT,
            video_id TEXT,
            material_id TEXT,
            attempt INTEGER DEFAULT 1,
            max_attempts INTEGER DEFAULT 3,
            receipt_task_id TEXT,
            metadata TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_task_state_status ON task_states(status)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_task_state_idempotency ON task_states(idempotency_key)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_task_state_account ON task_states(account_id)")
    conn.commit()


def save_task_state(state: TaskState) -> str:
    """保存/更新任务状态"""
    from fastapi_app.db.session import open_main_db
    state.updated_at = now_beijing_iso()

    if state.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED_FINAL, TaskStatus.CANCELLED):
        if not state.completed_at:
            state.completed_at = now_beijing_iso()

    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS task_states (
                    task_id VARCHAR(64) PRIMARY KEY,
                    status VARCHAR(20) NOT NULL DEFAULT 'draft',
                    idempotency_key VARCHAR(200) NOT NULL,
                    platform INT DEFAULT 0,
                    platform_name VARCHAR(50) DEFAULT '',
                    account_id VARCHAR(200) DEFAULT '',
                    campaign_id VARCHAR(100),
                    variant_id VARCHAR(100),
                    video_id VARCHAR(100),
                    material_id VARCHAR(100),
                    attempt INT DEFAULT 1,
                    max_attempts INT DEFAULT 3,
                    receipt_task_id VARCHAR(64),
                    metadata JSON,
                    error_message TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    completed_at DATETIME
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO task_states 
                (task_id, status, idempotency_key, platform, platform_name, account_id,
                 campaign_id, variant_id, video_id, material_id, attempt, max_attempts,
                 receipt_task_id, metadata, error_message, created_at, updated_at, completed_at)
                VALUES (:task_id, :status, :idempotency_key, :platform, :platform_name,
                        :account_id, :campaign_id, :variant_id, :video_id, :material_id,
                        :attempt, :max_attempts, :receipt_task_id, :metadata,
                        :error_message, :created_at, :updated_at, :completed_at)
                ON DUPLICATE KEY UPDATE
                    status=VALUES(status), idempotency_key=VALUES(idempotency_key),
                    receipt_task_id=VALUES(receipt_task_id), metadata=VALUES(metadata),
                    error_message=VALUES(error_message), attempt=VALUES(attempt),
                    updated_at=VALUES(updated_at), completed_at=VALUES(completed_at)
            """), {
                "task_id": state.task_id,
                "status": state.status.value,
                "idempotency_key": state.idempotency_key,
                "platform": state.platform,
                "platform_name": state.platform_name,
                "account_id": state.account_id,
                "campaign_id": state.campaign_id,
                "variant_id": state.variant_id,
                "video_id": state.video_id,
                "material_id": state.material_id,
                "attempt": state.attempt,
                "max_attempts": state.max_attempts,
                "receipt_task_id": state.receipt_task_id,
                "metadata": state.metadata,
                "error_message": state.error_message,
                "created_at": state.created_at,
                "updated_at": state.updated_at,
                "completed_at": state.completed_at,
            })
    else:
        conn = open_main_db()
        _ensure_task_state_table(conn)
        conn.execute("""
            INSERT OR REPLACE INTO task_states 
            (task_id, status, idempotency_key, platform, platform_name, account_id,
             campaign_id, variant_id, video_id, material_id, attempt, max_attempts,
             receipt_task_id, metadata, error_message, created_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            state.task_id, state.status.value, state.idempotency_key,
            state.platform, state.platform_name, state.account_id,
            state.campaign_id, state.variant_id, state.video_id, state.material_id,
            state.attempt, state.max_attempts, state.receipt_task_id,
            state.metadata, state.error_message, state.created_at, state.updated_at,
            state.completed_at,
        ))
        conn.commit()

    logger.info(f"[TaskState] 保存: task_id={state.task_id}, status={state.status.value}")
    return state.task_id


def get_task_state(task_id: str) -> Optional[TaskState]:
    from fastapi_app.db.session import open_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(text("SELECT * FROM task_states WHERE task_id = :tid"), {"tid": task_id}).mappings().first()
        if row: row = dict(row)
    else:
        conn = open_main_db()
        _ensure_task_state_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM task_states WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        cols = [d[0] for d in cursor.description]
        if row: row = dict(zip(cols, row))
    if not row: return None
    return _row_to_task_state(row)


def find_by_idempotency_key(key: str) -> Optional[TaskState]:
    """按幂等键查找任务（用于去重）"""
    from fastapi_app.db.session import open_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(text("SELECT * FROM task_states WHERE idempotency_key = :k LIMIT 1"), {"k": key}).mappings().first()
        if row: row = dict(row)
    else:
        conn = open_main_db()
        _ensure_task_state_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM task_states WHERE idempotency_key = ? LIMIT 1", (key,))
        row = cursor.fetchone()
        cols = [d[0] for d in cursor.description]
        if row: row = dict(zip(cols, row))
    if not row: return None
    return _row_to_task_state(row)


def list_task_states(status: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[TaskState]:
    from fastapi_app.db.session import open_main_db
    where = " WHERE status = ?" if status else ""
    params: list = []
    if status: params.append(status)
    params.extend([limit, offset])
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        w = " WHERE status = :status" if status else ""
        p = {"limit": limit, "offset": offset}
        if status: p["status"] = status
        with sa_connection() as conn:
            rows = conn.execute(text(f"SELECT * FROM task_states{w} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"), p).mappings().all()
        rows = [dict(r) for r in rows]
    else:
        conn = open_main_db()
        _ensure_task_state_table(conn)
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM task_states{where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params)
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in rows]
    return [_row_to_task_state(r) for r in rows]


def _row_to_task_state(row: Dict[str, Any]) -> TaskState:
    return TaskState(
        task_id=row["task_id"],
        status=TaskStatus(row["status"]),
        idempotency_key=row.get("idempotency_key", "") or "",
        platform=row.get("platform", 0) or 0,
        platform_name=row.get("platform_name", "") or "",
        account_id=row.get("account_id", "") or "",
        campaign_id=row.get("campaign_id"),
        variant_id=row.get("variant_id"),
        video_id=row.get("video_id"),
        material_id=row.get("material_id"),
        attempt=row.get("attempt", 1) or 1,
        max_attempts=row.get("max_attempts", 3) or 3,
        receipt_task_id=row.get("receipt_task_id"),
        metadata=row.get("metadata"),
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row.get("completed_at"),
    )
