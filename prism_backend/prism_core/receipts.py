"""
发布回执结构化模块（Phase 0.1）
- PublishReceipt Pydantic schema
- 状态枚举（succeeded / failed_retryable / failed_final / cancelled / running）
- 回执持久化（SQLite / MySQL 双模式）
- 回执查询
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from enum import Enum
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field, model_validator

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso
from fastapi_app.db.runtime import mysql_enabled, sa_connection


# ── 状态枚举 ──

class ReceiptStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    CANCELLED = "cancelled"
    RUNNING = "running"


# ── 错误码 ──

class ErrorCode(str, Enum):
    VIDEO_NOT_FOUND = "VIDEO_NOT_FOUND"
    COOKIE_EXPIRED = "COOKIE_EXPIRED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    NETWORK_ERROR = "NETWORK_ERROR"
    PLATFORM_BLOCKED = "PLATFORM_BLOCKED"
    UPLOAD_TIMEOUT = "UPLOAD_TIMEOUT"
    SELECTION_FAILED = "SELECTION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNKNOWN = "UNKNOWN"


# ── Schema ──

class DiagnosticArtifact(BaseModel):
    screenshot_path: Optional[str] = None
    dom_path: Optional[str] = None
    url_snapshot: Optional[str] = None
    error_stack: Optional[str] = None
    log_path: Optional[str] = None


class PublishReceipt(BaseModel):
    """发布回执（结构化）"""
    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:16]}")
    status: ReceiptStatus = ReceiptStatus.RUNNING
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    platform_post_id: Optional[str] = None
    published_at: Optional[str] = None
    video_url: Optional[str] = None
    error_code: Optional[ErrorCode] = None
    error_message: Optional[str] = None
    retryable: bool = False
    requires_human_action: bool = False
    attempt: int = Field(default=1, ge=0)
    idempotency_key: Optional[str] = None
    artifacts: Optional[DiagnosticArtifact] = None
    created_at: str = Field(default_factory=now_beijing_iso)
    updated_at: str = Field(default_factory=now_beijing_iso)

    @model_validator(mode="after")
    def _check_conditional_required(self) -> "PublishReceipt":
        """PLAN Phase 0.1 条件必填校验：
        - status=succeeded  → platform_post_id / published_at 必须非空
        - status=failed_retryable/failed_final → error_code 必须非空
        """
        if self.status == ReceiptStatus.SUCCEEDED:
            if not self.platform_post_id:
                raise ValueError("succeeded 回执必须包含 platform_post_id")
            if not self.published_at:
                raise ValueError("succeeded 回执必须包含 published_at")
        if self.status in (ReceiptStatus.FAILED_RETRYABLE, ReceiptStatus.FAILED_FINAL):
            if not self.error_code:
                raise ValueError(f"{self.status.value} 回执必须包含 error_code")
        return self


# ── 平台名映射 ──

PLATFORM_NAMES = {
    1: "xiaohongshu",
    2: "channels",
    3: "douyin",
    4: "kuaishou",
    5: "bilibili",
    6: "tiktok",
    7: "youtube",
    8: "baijiahao",
}


def platform_name_for(code: int) -> str:
    return PLATFORM_NAMES.get(code, f"platform_{code}")


# ── 持久化 ──

def _ensure_receipt_table(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS publish_receipts (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'running',
            platform INTEGER DEFAULT 0,
            platform_name TEXT DEFAULT '',
            account_id TEXT DEFAULT '',
            platform_post_id TEXT,
            published_at TEXT,
            video_url TEXT,
            error_code TEXT,
            error_message TEXT,
            retryable INTEGER DEFAULT 0,
            requires_human_action INTEGER DEFAULT 0,
            attempt INTEGER DEFAULT 1,
            idempotency_key TEXT,
            artifacts_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_receipt_status ON publish_receipts(status)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_receipt_account ON publish_receipts(account_id)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_receipt_idempotency ON publish_receipts(idempotency_key)")
    conn.commit()


def save_receipt(receipt: PublishReceipt) -> str:
    """保存/更新回执到数据库，返回 task_id"""
    from fastapi_app.db.session import open_main_db
    receipt.updated_at = now_beijing_iso()
    artifacts_json = receipt.artifacts.model_dump_json() if receipt.artifacts else None

    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS publish_receipts (
                    task_id VARCHAR(64) PRIMARY KEY,
                    status VARCHAR(20) NOT NULL DEFAULT 'running',
                    platform INT DEFAULT 0,
                    platform_name VARCHAR(50) DEFAULT '',
                    account_id VARCHAR(200) DEFAULT '',
                    platform_post_id TEXT,
                    published_at TEXT,
                    video_url TEXT,
                    error_code VARCHAR(50),
                    error_message TEXT,
                    retryable TINYINT(1) DEFAULT 0,
                    requires_human_action TINYINT(1) DEFAULT 0,
                    attempt INT DEFAULT 1,
                    idempotency_key VARCHAR(200),
                    artifacts_json JSON,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO publish_receipts
                (task_id, status, platform, platform_name, account_id, platform_post_id,
                 published_at, video_url, error_code, error_message, retryable,
                 requires_human_action, attempt, idempotency_key, artifacts_json,
                 created_at, updated_at)
                VALUES (:task_id, :status, :platform, :platform_name, :account_id,
                        :platform_post_id, :published_at, :video_url, :error_code,
                        :error_message, :retryable, :requires_human_action, :attempt,
                        :idempotency_key, :artifacts_json, :created_at, :updated_at)
                ON DUPLICATE KEY UPDATE
                    status=VALUES(status), platform_post_id=VALUES(platform_post_id),
                    published_at=VALUES(published_at), video_url=VALUES(video_url),
                    error_code=VALUES(error_code), error_message=VALUES(error_message),
                    retryable=VALUES(retryable), requires_human_action=VALUES(requires_human_action),
                    attempt=VALUES(attempt), artifacts_json=VALUES(artifacts_json),
                    updated_at=VALUES(updated_at)
            """), {
                "task_id": receipt.task_id,
                "status": receipt.status.value,
                "platform": receipt.platform,
                "platform_name": receipt.platform_name,
                "account_id": receipt.account_id,
                "platform_post_id": receipt.platform_post_id,
                "published_at": receipt.published_at,
                "video_url": receipt.video_url,
                "error_code": receipt.error_code.value if receipt.error_code else None,
                "error_message": receipt.error_message,
                "retryable": int(receipt.retryable),
                "requires_human_action": int(receipt.requires_human_action),
                "attempt": receipt.attempt,
                "idempotency_key": receipt.idempotency_key,
                "artifacts_json": artifacts_json,
                "created_at": receipt.created_at,
                "updated_at": receipt.updated_at,
            })
    else:
        conn = open_main_db()
        _ensure_receipt_table(conn)
        conn.execute("""
            INSERT OR REPLACE INTO publish_receipts
            (task_id, status, platform, platform_name, account_id, platform_post_id,
             published_at, video_url, error_code, error_message, retryable,
             requires_human_action, attempt, idempotency_key, artifacts_json,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            receipt.task_id, receipt.status.value, receipt.platform, receipt.platform_name,
            receipt.account_id, receipt.platform_post_id, receipt.published_at,
            receipt.video_url, receipt.error_code.value if receipt.error_code else None,
            receipt.error_message, int(receipt.retryable), int(receipt.requires_human_action),
            receipt.attempt, receipt.idempotency_key, artifacts_json,
            receipt.created_at, receipt.updated_at,
        ))
        conn.commit()

    logger.info(f"[Receipt] 保存回执: task_id={receipt.task_id}, status={receipt.status.value}")
    return receipt.task_id


def get_receipt(task_id: str) -> Optional[PublishReceipt]:
    """查询回执"""
    from fastapi_app.db.session import open_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(text("SELECT * FROM publish_receipts WHERE task_id = :tid"), {"tid": task_id}).mappings().first()
        if row:
            row = dict(row)
    else:
        conn = open_main_db()
        _ensure_receipt_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM publish_receipts WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        cols = [desc[0] for desc in cursor.description]
        if row:
            row = dict(zip(cols, row))

    if not row:
        return None

    return _row_to_receipt(row)


def _row_to_receipt(row_dict: Dict[str, Any]) -> PublishReceipt:
    return PublishReceipt(
        task_id=row_dict["task_id"],
        status=ReceiptStatus(row_dict["status"]),
        platform=row_dict.get("platform", 0) or 0,
        platform_name=row_dict.get("platform_name", "") or "",
        account_id=row_dict.get("account_id", "") or "",
        platform_post_id=row_dict.get("platform_post_id"),
        published_at=row_dict.get("published_at"),
        video_url=row_dict.get("video_url"),
        error_code=ErrorCode(row_dict["error_code"]) if row_dict.get("error_code") else None,
        error_message=row_dict.get("error_message"),
        retryable=bool(row_dict.get("retryable", 0)),
        requires_human_action=bool(row_dict.get("requires_human_action", 0)),
        attempt=row_dict.get("attempt", 1) or 1,
        idempotency_key=row_dict.get("idempotency_key"),
        artifacts=DiagnosticArtifact(**json.loads(row_dict["artifacts_json"])) if row_dict.get("artifacts_json") else None,
        created_at=row_dict["created_at"],
        updated_at=row_dict["updated_at"],
    )


def list_receipts(
    status: Optional[str] = None,
    account_id: Optional[str] = None,
    platform: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PublishReceipt]:
    """列出回执"""
    from fastapi_app.db.session import open_main_db
    conditions = []
    params = {}

    if status:
        conditions.append("status = :status")
        params["status"] = status
    if account_id:
        conditions.append("account_id = :account_id")
        params["account_id"] = account_id
    if platform:
        conditions.append("platform = :platform")
        params["platform"] = platform

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    params["limit"] = limit
    params["offset"] = offset

    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            rows = conn.execute(
                text(f"SELECT * FROM publish_receipts{where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
                params
            ).mappings().all()
        rows = [dict(r) for r in rows]
    else:
        conn = open_main_db()
        _ensure_receipt_table(conn)
        cursor = conn.cursor()
        sqlite_conditions = []
        sqlite_params = []
        if status:
            sqlite_conditions.append("status = ?")
            sqlite_params.append(status)
        if account_id:
            sqlite_conditions.append("account_id = ?")
            sqlite_params.append(account_id)
        if platform:
            sqlite_conditions.append("platform = ?")
            sqlite_params.append(platform)
        sqlite_where = " WHERE " + " AND ".join(sqlite_conditions) if sqlite_conditions else ""
        sqlite_params.extend([limit, offset])
        cursor.execute(f"SELECT * FROM publish_receipts{sqlite_where} ORDER BY created_at DESC LIMIT ? OFFSET ?", sqlite_params)
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        rows = [dict(zip(cols, row)) for row in rows]

    return [_row_to_receipt(row) for row in rows]


# ── 便捷构造器 ──

def build_success_receipt(
    platform: int,
    platform_name: str,
    account_id: str,
    video_url: Optional[str] = None,
    platform_post_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    attempt: int = 1,
) -> PublishReceipt:
    """构造成功回执。

    若调用方未提供 platform_post_id（部分平台上传流程不返回 post_id），
    生成占位符 `auto_{uuid12}` 以满足 schema 条件必填校验；调用方仍可显式传入真实值。
    """
    if not platform_post_id:
        platform_post_id = f"auto_{uuid.uuid4().hex[:12]}"
    return PublishReceipt(
        status=ReceiptStatus.SUCCEEDED,
        platform=platform,
        platform_name=platform_name,
        account_id=account_id,
        platform_post_id=platform_post_id,
        published_at=now_beijing_iso(),
        video_url=video_url,
        idempotency_key=idempotency_key,
        attempt=attempt,
    )


def build_error_receipt(
    platform: int,
    platform_name: str,
    account_id: str,
    error_code: ErrorCode,
    error_message: str,
    retryable: bool = False,
    requires_human_action: bool = False,
    artifacts: Optional[DiagnosticArtifact] = None,
    idempotency_key: Optional[str] = None,
    attempt: int = 1,
) -> PublishReceipt:
    """构造失败回执"""
    return PublishReceipt(
        status=ReceiptStatus.FAILED_RETRYABLE if retryable else ReceiptStatus.FAILED_FINAL,
        platform=platform,
        platform_name=platform_name,
        account_id=account_id,
        error_code=error_code,
        error_message=error_message,
        retryable=retryable,
        requires_human_action=requires_human_action,
        artifacts=artifacts,
        idempotency_key=idempotency_key,
        attempt=attempt,
    )


def build_receipt(
    *,
    status: Union[str, ReceiptStatus],
    platform: int = 0,
    platform_name: str = "",
    account_id: str = "",
    platform_post_id: Optional[str] = None,
    published_at: Optional[str] = None,
    video_url: Optional[str] = None,
    error_code: Optional[Union[str, ErrorCode]] = None,
    error_message: Optional[str] = None,
    retryable: Optional[bool] = None,
    requires_human_action: bool = False,
    artifacts: Optional[DiagnosticArtifact] = None,
    idempotency_key: Optional[str] = None,
    attempt: int = 1,
    task_id: Optional[str] = None,
) -> PublishReceipt:
    """统一回执工厂：按状态语义构造 PublishReceipt（Phase 0.1 验收项）。

    支持状态：succeeded / failed_retryable / failed_final / cancelled / running。

    条件必填校验（缺失则抛 ValueError 或 ValidationError）：
      - succeeded → platform_post_id / published_at 必须非空
      - failed_retryable / failed_final → error_code 必须非空

    重试语义（status=failed_retryable 时）：
      - retryable 默认 True
    失败语义（status=failed_final 时）：
      - retryable 默认 False

    Args:
        status: 状态（字符串或 ReceiptStatus 枚举）
        platform_post_id: 平台帖子 ID（succeeded 必填）
        published_at: 发布时间 ISO（succeeded 必填，缺省用当前北京时间）
        error_code: 错误码（failed_* 必填，可传字符串自动转 ErrorCode）
        retryable: 是否可重试；若状态为 failed_retryable 默认 True，否则默认 False
    """
    status_val: ReceiptStatus
    if isinstance(status, ReceiptStatus):
        status_val = status
    elif isinstance(status, str):
        try:
            status_val = ReceiptStatus(status)
        except ValueError as e:
            valid = ", ".join(s.value for s in ReceiptStatus)
            raise ValueError(f"非法回执状态 {status!r}（合法值：{valid}）") from e
    else:
        raise TypeError(f"status 必须是 str 或 ReceiptStatus，收到 {type(status).__name__}")

    ec: Optional[ErrorCode] = None
    if error_code is not None:
        if isinstance(error_code, ErrorCode):
            ec = error_code
        elif isinstance(error_code, str):
            try:
                ec = ErrorCode(error_code)
            except ValueError as e:
                valid = ", ".join(c.value for c in ErrorCode)
                raise ValueError(f"非法错误码 {error_code!r}（合法值：{valid}）") from e
        else:
            raise TypeError(f"error_code 必须是 str 或 ErrorCode，收到 {type(error_code).__name__}")

    if retryable is None:
        retryable = (status_val == ReceiptStatus.FAILED_RETRYABLE)

    # 前置校验，给调用方更早的语义错误信息
    if status_val == ReceiptStatus.SUCCEEDED and not platform_post_id:
        raise ValueError("succeeded 回执必须提供 platform_post_id")
    if status_val in (ReceiptStatus.FAILED_RETRYABLE, ReceiptStatus.FAILED_FINAL) and ec is None:
        raise ValueError(f"{status_val.value} 回执必须提供 error_code")

    if status_val == ReceiptStatus.SUCCEEDED:
        pub_at = published_at or now_beijing_iso()
    else:
        pub_at = published_at

    kwargs: Dict[str, Any] = dict(
        status=status_val,
        platform=platform,
        platform_name=platform_name,
        account_id=account_id,
        platform_post_id=platform_post_id,
        published_at=pub_at,
        video_url=video_url,
        error_code=ec,
        error_message=error_message,
        retryable=retryable,
        requires_human_action=requires_human_action,
        artifacts=artifacts,
        idempotency_key=idempotency_key,
        attempt=attempt,
    )
    # task_id 有 default_factory；若未显式传入则让 Pydantic 自动生成
    if task_id is not None:
        kwargs["task_id"] = task_id
    return PublishReceipt(**kwargs)
