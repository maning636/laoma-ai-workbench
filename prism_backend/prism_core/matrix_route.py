"""
矩阵路由（Phase 2.3）
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso
from fastapi_app.db.runtime import mysql_enabled, sa_connection


class MatrixMode(str, Enum):
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    RANDOM = "random"
    BEST_TIME = "best_time"
    CUSTOM = "custom"


class MatrixGroup(BaseModel):
    group_id: str = Field(default_factory=lambda: f"mg_{uuid.uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    platforms: Optional[str] = None
    routing_mode: MatrixMode = MatrixMode.ROUND_ROBIN
    weights: Optional[str] = None
    schedule: Optional[str] = None
    max_daily_tasks: int = 10
    active_accounts: int = 0
    created_at: str = Field(default_factory=now_beijing_iso)
    updated_at: str = Field(default_factory=now_beijing_iso)


class MatrixAssignment(BaseModel):
    assignment_id: str = Field(default_factory=lambda: f"ma_{uuid.uuid4().hex[:12]}")
    group_id: str = ""
    task_id: str = ""
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    assigned_at: str = Field(default_factory=now_beijing_iso)
    status: str = "pending"


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS matrix_groups (
            group_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            platforms TEXT,
            routing_mode TEXT DEFAULT 'round_robin',
            weights TEXT,
            schedule TEXT,
            max_daily_tasks INTEGER DEFAULT 10,
            active_accounts INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS matrix_assignments (
            assignment_id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            platform INTEGER DEFAULT 0,
            platform_name TEXT DEFAULT '',
            account_id TEXT DEFAULT '',
            assigned_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_ma_group ON matrix_assignments(group_id)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_ma_account ON matrix_assignments(account_id)")
    conn.commit()


def save_group(group: MatrixGroup) -> str:
    from fastapi_app.db.session import get_main_db
    data = group.model_dump()
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS matrix_groups (
                    group_id VARCHAR(128) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL, description TEXT,
                    platforms TEXT, routing_mode VARCHAR(30) DEFAULT 'round_robin',
                    weights TEXT, schedule TEXT,
                    max_daily_tasks INT DEFAULT 10, active_accounts INT DEFAULT 0,
                    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO matrix_groups
                (group_id, name, description, platforms, routing_mode, weights, schedule, max_daily_tasks, active_accounts, created_at, updated_at)
                VALUES (:group_id, :name, :description, :platforms, :routing_mode, :weights, :schedule, :max_daily_tasks, :active_accounts, :created_at, :updated_at)
                ON DUPLICATE KEY UPDATE
                    name=VALUES(name), description=VALUES(description),
                    platforms=VALUES(platforms), routing_mode=VALUES(routing_mode),
                    weights=VALUES(weights), schedule=VALUES(schedule),
                    max_daily_tasks=VALUES(max_daily_tasks),
                    active_accounts=VALUES(active_accounts), updated_at=VALUES(updated_at)
            """), data)
    else:
        conn = get_main_db()
        _ensure_tables(conn)
        conn.execute("""
            INSERT OR REPLACE INTO matrix_groups
            (group_id, name, description, platforms, routing_mode, weights, schedule, max_daily_tasks, active_accounts, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            group.group_id, group.name, group.description, group.platforms,
            group.routing_mode.value, group.weights, group.schedule,
            group.max_daily_tasks, group.active_accounts, group.created_at, group.updated_at,
        ))
        conn.commit()
    return group.group_id


def get_group(group_id: str) -> Optional[MatrixGroup]:
    from fastapi_app.db.session import get_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(text("SELECT * FROM matrix_groups WHERE group_id = :gid"), {"gid": group_id}).mappings().first()
        if row: row = dict(row)
    else:
        conn = get_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        c.execute("SELECT * FROM matrix_groups WHERE group_id = ?", (group_id,))
        row = c.fetchone()
        cols = [d[0] for d in c.description]
        if row: row = dict(zip(cols, row))
    if not row: return None
    return MatrixGroup(
        group_id=row["group_id"], name=row.get("name", "") or "",
        description=row.get("description", "") or "",
        platforms=row.get("platforms"), routing_mode=MatrixMode(row.get("routing_mode", "round_robin")),
        weights=row.get("weights"), schedule=row.get("schedule"),
        max_daily_tasks=row.get("max_daily_tasks", 10) or 10,
        active_accounts=row.get("active_accounts", 0) or 0,
        created_at=row["created_at"], updated_at=row.get("updated_at", "") or "",
    )


def list_groups(limit: int = 50, offset: int = 0) -> list:
    from fastapi_app.db.session import get_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        params = {"limit": limit, "offset": offset}
        with sa_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                text("SELECT * FROM matrix_groups ORDER BY created_at DESC LIMIT :limit OFFSET :offset"), params
            ).mappings().all()]
    else:
        conn = get_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        c.execute("SELECT * FROM matrix_groups ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
        rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    return [_row_to_group(r) for r in rows]


def _row_to_group(row: dict) -> MatrixGroup:
    return MatrixGroup(
        group_id=row["group_id"], name=row.get("name", "") or "",
        description=row.get("description", "") or "",
        platforms=row.get("platforms"), routing_mode=MatrixMode(row.get("routing_mode", "round_robin")),
        weights=row.get("weights"), schedule=row.get("schedule"),
        max_daily_tasks=row.get("max_daily_tasks", 10) or 10,
        active_accounts=row.get("active_accounts", 0) or 0,
        created_at=row["created_at"], updated_at=row.get("updated_at", "") or "",
    )


def assign_task(group_id: str, task_id: str, accounts: List[Dict[str, Any]]) -> MatrixAssignment:
    """
    根据路由模式分配任务到指定账号
    accounts: [{"account_id": "xxx", "platform": 1, "platform_name": "抖音", "last_task_at": "...", "health_score": 85.0}, ...]
    """
    group = get_group(group_id)
    if not group:
        raise ValueError(f"Matrix group not found: {group_id}")
    if not accounts:
        raise ValueError("No available accounts")

    mode = group.routing_mode
    selected = accounts[0]
    if mode == MatrixMode.ROUND_ROBIN:
        now = now_beijing_iso()
        selected = min(accounts, key=lambda a: a.get("last_task_at", "0000-00-00T00:00:00") or "0000-00-00T00:00:00")
    elif mode == MatrixMode.WEIGHTED:
        import random
        weights = json.loads(group.weights) if group.weights else {}
        ws = [weights.get(str(a.get("platform", 0)), 1) for a in accounts]
        selected = random.choices(accounts, weights=ws, k=1)[0]
    elif mode == MatrixMode.RANDOM:
        import random
        selected = random.choice(accounts)
    elif mode == MatrixMode.BEST_TIME:
        now_h = int(now_beijing_iso()[11:13])
        best_score = -1
        for a in accounts:
            schedule = a.get("schedule") or "{}"
            try:
                sched_data = json.loads(schedule) if isinstance(schedule, str) else schedule
                hour_data = sched_data.get(str(now_h), 0.5)
                if isinstance(hour_data, dict):
                    hour_data = hour_data.get("score", 0.5)
                elif isinstance(hour_data, (int, float)):
                    pass
                else:
                    hour_data = 0.5
            except Exception:
                hour_data = 0.5
            hs = a.get("health_score", 50.0) or 50.0
            score = (hour_data * 0.4) + (hs / 100 * 0.6)
            if score > best_score:
                best_score = score
                selected = a

    assignment = MatrixAssignment(
        group_id=group_id, task_id=task_id,
        platform=selected.get("platform", 0) or 0,
        platform_name=selected.get("platform_name", "") or "",
        account_id=selected.get("account_id", "") or "",
        status="assigned",
    )
    _save_assignment(assignment)
    logger.info(f"[Matrix] 分配任务 {task_id} -> {selected.get('account_id')} ({selected.get('platform_name')})")
    return assignment


def _save_assignment(assignment: MatrixAssignment) -> str:
    from fastapi_app.db.session import get_main_db
    data = assignment.model_dump()
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS matrix_assignments (
                    assignment_id VARCHAR(128) PRIMARY KEY,
                    group_id VARCHAR(128) NOT NULL,
                    task_id VARCHAR(128) NOT NULL,
                    platform INT DEFAULT 0, platform_name VARCHAR(50) DEFAULT '',
                    account_id VARCHAR(200) DEFAULT '',
                    assigned_at DATETIME NOT NULL,
                    status VARCHAR(30) DEFAULT 'pending',
                    INDEX idx_ma_group (group_id),
                    INDEX idx_ma_account (account_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO matrix_assignments
                (assignment_id, group_id, task_id, platform, platform_name, account_id, assigned_at, status)
                VALUES (:assignment_id, :group_id, :task_id, :platform, :platform_name, :account_id, :assigned_at, :status)
                ON DUPLICATE KEY UPDATE
                    group_id=VALUES(group_id), task_id=VALUES(task_id),
                    platform=VALUES(platform), platform_name=VALUES(platform_name),
                    account_id=VALUES(account_id), assigned_at=VALUES(assigned_at),
                    status=VALUES(status)
            """), data)
    else:
        conn = get_main_db()
        _ensure_tables(conn)
        conn.execute("""
            INSERT OR REPLACE INTO matrix_assignments
            (assignment_id, group_id, task_id, platform, platform_name, account_id, assigned_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            assignment.assignment_id, assignment.group_id, assignment.task_id,
            assignment.platform, assignment.platform_name, assignment.account_id,
            assignment.assigned_at, assignment.status,
        ))
        conn.commit()
    return assignment.assignment_id


def get_assignments(group_id: Optional[str] = None, limit: int = 50, offset: int = 0) -> list:
    from fastapi_app.db.session import get_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        conds, params = [], {}
        if group_id: conds.append("group_id = :gid"); params["gid"] = group_id
        where = " WHERE " + " AND ".join(conds) if conds else ""
        params["limit"], params["offset"] = limit, offset
        with sa_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                text(f"SELECT * FROM matrix_assignments{where} ORDER BY assigned_at DESC LIMIT :limit OFFSET :offset"), params
            ).mappings().all()]
    else:
        conn = get_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        if group_id:
            c.execute("SELECT * FROM matrix_assignments WHERE group_id = ? ORDER BY assigned_at DESC LIMIT ? OFFSET ?", (group_id, limit, offset))
        else:
            c.execute("SELECT * FROM matrix_assignments ORDER BY assigned_at DESC LIMIT ? OFFSET ?", (limit, offset))
        rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    return [MatrixAssignment(
        assignment_id=r["assignment_id"], group_id=r["group_id"], task_id=r["task_id"],
        platform=r.get("platform", 0) or 0, platform_name=r.get("platform_name", "") or "",
        account_id=r.get("account_id", "") or "", assigned_at=r["assigned_at"],
        status=r.get("status", "pending") or "pending",
    ) for r in rows]


class MatrixRouter:
    def __init__(self):
        pass

    def create_group(self, name: str, platforms: List[int], mode: str = "round_robin",
                     weights: Optional[Dict[str, int]] = None, schedule: Optional[Dict[str, Any]] = None,
                     max_daily: int = 10) -> MatrixGroup:
        group = MatrixGroup(
            name=name,
            platforms=json.dumps(platforms) if isinstance(platforms, list) else json.dumps(platforms or []),
            routing_mode=MatrixMode(mode) if mode else MatrixMode.ROUND_ROBIN,
            weights=json.dumps(weights) if weights else None,
            schedule=json.dumps(schedule) if schedule else None,
            max_daily_tasks=max_daily,
        )
        save_group(group)
        return group

    def route(self, group_id: str, task_id: str, accounts: List[Dict[str, Any]]) -> MatrixAssignment:
        return assign_task(group_id, task_id, accounts)

    def group_stats(self, group_id: str) -> Dict[str, Any]:
        group = get_group(group_id)
        if not group:
            return {"error": "Group not found"}
        assignments = get_assignments(group_id=group_id, limit=1000)
        status_counts = {}
        for a in assignments:
            status_counts[a.status] = status_counts.get(a.status, 0) + 1
        return {
            "group_id": group_id, "name": group.name, "routing_mode": group.routing_mode.value,
            "total_assignments": len(assignments), "status_breakdown": status_counts,
            "created_at": group.created_at,
        }


matrix_router = MatrixRouter()
