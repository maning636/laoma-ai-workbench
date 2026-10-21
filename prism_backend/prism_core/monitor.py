"""
任务监控与告警（Phase 0.3）

- TaskMonitor: 状态流转记录、异常检测
- AlertHub: Webhook 告警分发
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso
from fastapi_app.db.runtime import mysql_enabled, sa_connection


# ── 监控事件类型 ──
class MonitorEventType(str, Enum):
    TASK_STATE_CHANGED = "task_state_changed"
    TASK_FAILED = "task_failed"
    TASK_RETRYING = "task_retrying"
    RECEIPT_SUCCEEDED = "receipt_succeeded"
    RECEIPT_FAILED = "receipt_failed"
    ACCOUNT_COOLDOWN = "account_cooldown"
    ACCOUNT_BLOCKED = "account_blocked"
    SYSTEM_HEALTH_WARNING = "system_health_warning"


# ── 监控事件 ──
class MonitorEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    event_type: MonitorEventType = MonitorEventType.TASK_STATE_CHANGED
    severity: str = "info"  # info, warning, critical
    task_id: Optional[str] = None
    receipt_task_id: Optional[str] = None
    account_id: Optional[str] = None
    platform: int = 0
    platform_name: str = ""
    message: str = ""
    metadata: Optional[str] = None  # JSON
    created_at: str = Field(default_factory=now_beijing_iso)


# ── 状态流转记录 ──
class StateTransition(BaseModel):
    transition_id: str = Field(default_factory=lambda: f"tr_{uuid.uuid4().hex[:12]}")
    task_id: str = ""
    account_id: str = ""
    from_status: str = ""
    to_status: str = ""
    reason: str = ""
    created_at: str = Field(default_factory=now_beijing_iso)


# ── 告警 Webhook 配置 ──
class AlertWebhookConfig(BaseModel):
    name: str = ""
    url: str = ""
    enabled: bool = True
    event_types: List[str] = Field(default_factory=lambda: ["task_failed", "account_blocked"])
    created_at: str = Field(default_factory=now_beijing_iso)


# ── 表结构 ──
def _ensure_monitor_tables(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS monitor_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            severity TEXT DEFAULT 'info',
            task_id TEXT,
            receipt_task_id TEXT,
            account_id TEXT,
            platform INTEGER DEFAULT 0,
            platform_name TEXT DEFAULT '',
            message TEXT,
            metadata TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS state_transitions (
            transition_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            account_id TEXT DEFAULT '',
            from_status TEXT NOT NULL,
            to_status TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS alert_webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            event_types TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_monitor_events_type ON monitor_events(event_type)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_monitor_events_account ON monitor_events(account_id)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_state_transitions_task ON state_transitions(task_id)")
    conn.commit()


# ── 记录事件 ──
def record_event(event: MonitorEvent) -> str:
    from fastapi_app.db.session import open_main_db
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS monitor_events (
                    event_id VARCHAR(64) PRIMARY KEY,
                    event_type VARCHAR(50) NOT NULL,
                    severity VARCHAR(10) DEFAULT 'info',
                    task_id VARCHAR(64),
                    receipt_task_id VARCHAR(64),
                    account_id VARCHAR(200),
                    platform INT DEFAULT 0,
                    platform_name VARCHAR(50) DEFAULT '',
                    message TEXT,
                    metadata JSON,
                    created_at DATETIME NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO monitor_events 
                (event_id, event_type, severity, task_id, receipt_task_id, account_id,
                 platform, platform_name, message, metadata, created_at)
                VALUES (:event_id, :event_type, :severity, :task_id, :receipt_task_id,
                        :account_id, :platform, :platform_name, :message, :metadata, :created_at)
            """), {
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "severity": event.severity,
                "task_id": event.task_id,
                "receipt_task_id": event.receipt_task_id,
                "account_id": event.account_id,
                "platform": event.platform,
                "platform_name": event.platform_name,
                "message": event.message,
                "metadata": event.metadata,
                "created_at": event.created_at,
            })
    else:
        conn = open_main_db()
        _ensure_monitor_tables(conn)
        conn.execute("""
            INSERT INTO monitor_events 
            (event_id, event_type, severity, task_id, receipt_task_id, account_id,
             platform, platform_name, message, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.event_id, event.event_type.value, event.severity,
            event.task_id, event.receipt_task_id, event.account_id,
            event.platform, event.platform_name, event.message,
            event.metadata, event.created_at,
        ))
        conn.commit()
    logger.info(f"[Monitor] 事件: {event.event_type.value} - {event.message}")
    return event.event_id


# ── 记录状态流转 ──
def record_state_transition(transition: StateTransition) -> str:
    from fastapi_app.db.session import open_main_db
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS state_transitions (
                    transition_id VARCHAR(64) PRIMARY KEY,
                    task_id VARCHAR(64) NOT NULL,
                    account_id VARCHAR(200) DEFAULT '',
                    from_status VARCHAR(20) NOT NULL,
                    to_status VARCHAR(20) NOT NULL,
                    reason TEXT,
                    created_at DATETIME NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO state_transitions 
                (transition_id, task_id, account_id, from_status, to_status, reason, created_at)
                VALUES (:transition_id, :task_id, :account_id, :from_status, :to_status, :reason, :created_at)
            """), {
                "transition_id": transition.transition_id,
                "task_id": transition.task_id,
                "account_id": transition.account_id,
                "from_status": transition.from_status,
                "to_status": transition.to_status,
                "reason": transition.reason,
                "created_at": transition.created_at,
            })
    else:
        conn = open_main_db()
        _ensure_monitor_tables(conn)
        conn.execute("""
            INSERT INTO state_transitions 
            (transition_id, task_id, account_id, from_status, to_status, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            transition.transition_id, transition.task_id, transition.account_id,
            transition.from_status, transition.to_status, transition.reason, transition.created_at,
        ))
        conn.commit()
    logger.info(f"[Monitor] 状态流转: {transition.from_status} → {transition.to_status} (task={transition.task_id})")
    return transition.transition_id


# ── 查询事件 ──
def list_monitor_events(
    event_type: Optional[str] = None,
    account_id: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[MonitorEvent]:
    from fastapi_app.db.session import open_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        conditions = []
        params = {}
        if event_type:
            conditions.append("event_type = :et")
            params["et"] = event_type
        if account_id:
            conditions.append("account_id = :aid")
            params["aid"] = account_id
        if severity:
            conditions.append("severity = :sev")
            params["sev"] = severity
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params["limit"] = limit
        params["offset"] = offset
        with sa_connection() as conn:
            rows = conn.execute(
                text(f"SELECT * FROM monitor_events{where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
                params
            ).mappings().all()
        rows = [dict(r) for r in rows]
    else:
        conn = open_main_db()
        _ensure_monitor_tables(conn)
        cursor = conn.cursor()
        conditions = []
        params: list = []
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if account_id:
            conditions.append("account_id = ?")
            params.append(account_id)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([limit, offset])
        cursor.execute(f"SELECT * FROM monitor_events{where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params)
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in rows]
    
    result = []
    for row in rows:
        try:
            result.append(MonitorEvent(
                event_id=row["event_id"],
                event_type=MonitorEventType(row["event_type"]),
                severity=row.get("severity", "info") or "info",
                task_id=row.get("task_id"),
                receipt_task_id=row.get("receipt_task_id"),
                account_id=row.get("account_id"),
                platform=row.get("platform", 0) or 0,
                platform_name=row.get("platform_name", "") or "",
                message=row.get("message", "") or "",
                metadata=row.get("metadata"),
                created_at=row["created_at"],
            ))
        except Exception as e:
            logger.warning(f"[Monitor] 解析事件失败: {e}")
    return result


def list_state_transitions(task_id: Optional[str] = None, limit: int = 50) -> List[StateTransition]:
    from fastapi_app.db.session import open_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        if task_id:
            with sa_connection() as conn:
                rows = conn.execute(
                    text("SELECT * FROM state_transitions WHERE task_id = :tid ORDER BY created_at DESC LIMIT :limit"),
                    {"tid": task_id, "limit": limit}
                ).mappings().all()
        else:
            with sa_connection() as conn:
                rows = conn.execute(
                    text("SELECT * FROM state_transitions ORDER BY created_at DESC LIMIT :limit"),
                    {"limit": limit}
                ).mappings().all()
        rows = [dict(r) for r in rows]
    else:
        conn = open_main_db()
        _ensure_monitor_tables(conn)
        cursor = conn.cursor()
        if task_id:
            cursor.execute("SELECT * FROM state_transitions WHERE task_id = ? ORDER BY created_at DESC LIMIT ?", (task_id, limit))
        else:
            cursor.execute("SELECT * FROM state_transitions ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in rows]
    
    return [StateTransition(
        transition_id=r["transition_id"],
        task_id=r["task_id"],
        account_id=r.get("account_id", "") or "",
        from_status=r["from_status"],
        to_status=r["to_status"],
        reason=r.get("reason"),
        created_at=r["created_at"],
    ) for r in rows]


# ── 告警 Hub ──
class AlertHub:
    """告警分发中心"""

    _webhooks: List[Dict] = []

    @classmethod
    def add_webhook(cls, name: str, url: str, event_types: Optional[List[str]] = None) -> None:
        cls._webhooks.append({
            "name": name,
            "url": url,
            "enabled": True,
            "event_types": event_types or ["*"],
            "created_at": now_beijing_iso(),
        })
        logger.info(f"[AlertHub] 添加 Webhook: {name} -> {url}")

    @classmethod
    def remove_webhook(cls, name: str) -> bool:
        before = len(cls._webhooks)
        cls._webhooks = [w for w in cls._webhooks if w["name"] != name]
        return len(cls._webhooks) < before

    @classmethod
    def list_webhooks(cls) -> List[Dict]:
        return cls._webhooks

    @classmethod
    async def send_alert(cls, event_type: str, severity: str, message: str, **kwargs) -> int:
        """发送告警到所有匹配的 Webhook，返回成功数"""
        if not cls._webhooks:
            return 0

        payload = {
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "timestamp": now_beijing_iso(),
            **kwargs,
        }

        sent_count = 0
        for hook in cls._webhooks:
            if not hook["enabled"]:
                continue
            if hook["event_types"] != ["*"] and event_type not in hook["event_types"]:
                continue
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(hook["url"], json=payload)
                    if resp.status_code < 400:
                        sent_count += 1
                        logger.info(f"[AlertHub] 告警已发送: {hook['name']} - {event_type}")
                    else:
                        logger.warning(f"[AlertHub] 告警发送失败: {hook['name']} - HTTP {resp.status_code}")
            except Exception as e:
                logger.warning(f"[AlertHub] 告警发送异常: {hook['name']} - {e}")

        return sent_count


# ── 全局 TaskMonitor 单例 ──
class TaskMonitor:
    """任务监控器（全局单例）"""

    _instance: Optional["TaskMonitor"] = None

    @classmethod
    def get_instance(cls) -> "TaskMonitor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def record_event(self, event: MonitorEvent) -> str:
        return record_event(event)

    def record_transition(self, transition: StateTransition) -> str:
        return record_state_transition(transition)

    def log_state_change(
        self,
        task_id: str,
        account_id: str,
        from_status: str,
        to_status: str,
        reason: str = "",
    ) -> str:
        """便捷方法：记录状态变更"""
        transition = StateTransition(
            task_id=task_id,
            account_id=account_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
        )
        tid = record_state_transition(transition)

        event = MonitorEvent(
            event_type=MonitorEventType.TASK_STATE_CHANGED,
            severity="info",
            task_id=task_id,
            account_id=account_id,
            message=f"状态变更: {from_status} → {to_status}" + (f" ({reason})" if reason else ""),
        )
        record_event(event)
        return tid

    def log_failure(
        self,
        task_id: str,
        receipt_task_id: Optional[str],
        account_id: str,
        platform: int,
        platform_name: str,
        error_code: str,
        error_message: str,
        retryable: bool = False,
    ) -> str:
        """便捷方法：记录失败并发送告警"""
        severity = "warning" if retryable else "critical"
        event = MonitorEvent(
            event_type=MonitorEventType.TASK_FAILED,
            severity=severity,
            task_id=task_id,
            receipt_task_id=receipt_task_id,
            account_id=account_id,
            platform=platform,
            platform_name=platform_name,
            message=f"{error_code}: {error_message[:200]}",
            metadata=json.dumps({"retryable": retryable, "error_code": error_code}),
        )
        eid = record_event(event)

        asyncio.create_task(AlertHub.send_alert(
            event_type="task_failed",
            severity=severity,
            message=f"发布失败: {account_id} @ {platform_name} - {error_code}",
            task_id=task_id,
            account_id=account_id,
            error_code=error_code,
            retryable=retryable,
        ))
        return eid


# 全局实例
task_monitor = TaskMonitor.get_instance()
