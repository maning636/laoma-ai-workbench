"""
内容去重/查重（Phase 4.3）

矩阵投放层：检测跨平台重复发布同一内容。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso
from fastapi_app.db.runtime import mysql_enabled, sa_connection


class DupLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DedupRecord(BaseModel):
    dedup_id: str = Field(default_factory=lambda: f"dup_{uuid.uuid4().hex[:12]}")
    task_id: str = ""
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    content_hash: str = ""
    title_hash: str = ""
    video_hash: str = ""
    dup_level: DupLevel = DupLevel.NONE
    dup_with_task_id: Optional[str] = None
    dup_with_platform: Optional[str] = None
    dup_similarity: float = 0.0
    checked_at: str = Field(default_factory=now_beijing_iso)


def content_fingerprint(title: str = "", content: str = "", video_hash: str = "") -> str:
    """生成内容指纹"""
    combined = f"{title.strip().lower()}|{content.strip()[:500].lower()}|{video_hash}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:32]


def title_fingerprint(title: str) -> str:
    """标题指纹"""
    return hashlib.sha256(title.strip().lower().encode("utf-8")).hexdigest()[:16]


def compute_similarity(title_a: str, title_b: str) -> float:
    """简单的标题相似度（基于字符重叠）"""
    if not title_a or not title_b:
        return 0.0
    a = set(title_a.lower())
    b = set(title_b.lower())
    intersection = a & b
    union = a | b
    return round(len(intersection) / len(union), 4) if union else 0.0


def _ensure_dedup_table(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS dedup_records (
            dedup_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            platform INTEGER DEFAULT 0,
            platform_name TEXT DEFAULT '',
            account_id TEXT DEFAULT '',
            content_hash TEXT NOT NULL,
            title_hash TEXT,
            video_hash TEXT,
            dup_level TEXT DEFAULT 'none',
            dup_with_task_id TEXT,
            dup_with_platform TEXT,
            dup_similarity REAL DEFAULT 0.0,
            checked_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_dedup_hash ON dedup_records(content_hash)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_dedup_task ON dedup_records(task_id)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_dedup_level ON dedup_records(dup_level)")
    conn.commit()


def save_dedup_record(record: DedupRecord) -> str:
    from fastapi_app.db.session import open_main_db
    data = record.model_dump()
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS dedup_records (
                    dedup_id VARCHAR(128) PRIMARY KEY,
                    task_id VARCHAR(128) NOT NULL,
                    platform INT DEFAULT 0,
                    platform_name VARCHAR(50) DEFAULT '',
                    account_id VARCHAR(200) DEFAULT '',
                    content_hash VARCHAR(64) NOT NULL,
                    title_hash VARCHAR(32),
                    video_hash VARCHAR(64),
                    dup_level VARCHAR(10) DEFAULT 'none',
                    dup_with_task_id VARCHAR(128),
                    dup_with_platform VARCHAR(50),
                    dup_similarity REAL DEFAULT 0.0,
                    checked_at DATETIME NOT NULL,
                    INDEX idx_dedup_hash (content_hash),
                    INDEX idx_dedup_task (task_id),
                    INDEX idx_dedup_level (dup_level)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO dedup_records
                (dedup_id, task_id, platform, platform_name, account_id,
                 content_hash, title_hash, video_hash, dup_level,
                 dup_with_task_id, dup_with_platform, dup_similarity, checked_at)
                VALUES (:dedup_id, :task_id, :platform, :platform_name, :account_id,
                        :content_hash, :title_hash, :video_hash, :dup_level,
                        :dup_with_task_id, :dup_with_platform, :dup_similarity, :checked_at)
                ON DUPLICATE KEY UPDATE
                    task_id=VALUES(task_id), platform=VALUES(platform),
                    platform_name=VALUES(platform_name), account_id=VALUES(account_id),
                    content_hash=VALUES(content_hash), title_hash=VALUES(title_hash),
                    video_hash=VALUES(video_hash), dup_level=VALUES(dup_level),
                    dup_with_task_id=VALUES(dup_with_task_id),
                    dup_with_platform=VALUES(dup_with_platform),
                    dup_similarity=VALUES(dup_similarity), checked_at=VALUES(checked_at)
            """), data)
    else:
        conn = open_main_db()
        _ensure_dedup_table(conn)
        conn.execute("""
            INSERT OR REPLACE INTO dedup_records
            (dedup_id, task_id, platform, platform_name, account_id,
             content_hash, title_hash, video_hash, dup_level,
             dup_with_task_id, dup_with_platform, dup_similarity, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.dedup_id, record.task_id, record.platform, record.platform_name,
            record.account_id, record.content_hash, record.title_hash, record.video_hash,
            record.dup_level.value, record.dup_with_task_id, record.dup_with_platform,
            record.dup_similarity, record.checked_at,
        ))
        conn.commit()
    return record.dedup_id


def check_duplicate(task_id: str, platform: int, platform_name: str, account_id: str,
                    title: str = "", content: str = "", video_hash: str = "") -> DedupRecord:
    """检查内容是否重复"""
    c_hash = content_fingerprint(title, content, video_hash)
    t_hash = title_fingerprint(title)
    v_hash = video_hash

    from fastapi_app.db.session import open_main_db
    existing = []

    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            rows = conn.execute(
                text("SELECT * FROM dedup_records WHERE content_hash = :ch OR title_hash = :th ORDER BY checked_at DESC LIMIT 50"),
                {"ch": c_hash, "th": t_hash},
            ).mappings().all()
        existing = [dict(r) for r in rows]
    else:
        conn = open_main_db()
        _ensure_dedup_table(conn)
        c = conn.cursor()
        c.execute("SELECT * FROM dedup_records WHERE content_hash = ? OR title_hash = ? ORDER BY checked_at DESC LIMIT 50", (c_hash, t_hash))
        rows = c.fetchall()
        cols = [d[0] for d in c.description]
        existing = [dict(zip(cols, r)) for r in rows]

    dup_level = DupLevel.NONE
    dup_with_task_id = None
    dup_with_platform = None
    dup_similarity = 0.0

    for ex in existing:
        if ex.get("task_id") == task_id:
            continue
        if ex.get("content_hash") == c_hash:
            dup_level = DupLevel.HIGH
            dup_with_task_id = ex.get("task_id")
            dup_with_platform = ex.get("platform_name")
            dup_similarity = 1.0
            break
        if ex.get("title_hash") == t_hash and t_hash:
            title_sim = compute_similarity(title, ex.get("title_hash", ""))
            if dup_level.value < "medium" or title_sim > dup_similarity:
                dup_level = DupLevel.MEDIUM
                dup_with_task_id = ex.get("task_id")
                dup_with_platform = ex.get("platform_name")
                dup_similarity = title_sim
        if video_hash and ex.get("video_hash") == v_hash:
            if dup_level.value < "high":
                dup_level = DupLevel.HIGH
                dup_with_task_id = ex.get("task_id")
                dup_with_platform = ex.get("platform_name")
                dup_similarity = 1.0

    record = DedupRecord(
        task_id=task_id, platform=platform, platform_name=platform_name,
        account_id=account_id, content_hash=c_hash, title_hash=t_hash,
        video_hash=v_hash, dup_level=dup_level,
        dup_with_task_id=dup_with_task_id, dup_with_platform=dup_with_platform,
        dup_similarity=dup_similarity,
    )
    save_dedup_record(record)

    if dup_level != DupLevel.NONE:
        logger.warning(f"[Dedup] 重复检测: {task_id} -> {dup_level.value} (with {dup_with_task_id})")
    return record


def get_dedup_record(dedup_id: str) -> Optional[DedupRecord]:
    """查询单条查重记录"""
    from fastapi_app.db.session import open_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(text("SELECT * FROM dedup_records WHERE dedup_id = :did"), {"did": dedup_id}).mappings().first()
        if row:
            row = dict(row)
    else:
        conn = open_main_db()
        _ensure_dedup_table(conn)
        c = conn.cursor()
        c.execute("SELECT * FROM dedup_records WHERE dedup_id = ?", (dedup_id,))
        row = c.fetchone()
        cols = [d[0] for d in c.description]
        if row:
            row = dict(zip(cols, row))
    return _row_to_dedup(row) if row else None


def list_dedup_records(dup_level: Optional[str] = None, account_id: Optional[str] = None,
                       limit: int = 50, offset: int = 0) -> list:
    from fastapi_app.db.session import open_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        conds, params = [], {}
        if dup_level: conds.append("dup_level = :dl"); params["dl"] = dup_level
        if account_id: conds.append("account_id = :aid"); params["aid"] = account_id
        where = " WHERE " + " AND ".join(conds) if conds else ""
        params["limit"], params["offset"] = limit, offset
        with sa_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                text(f"SELECT * FROM dedup_records{where} ORDER BY checked_at DESC LIMIT :limit OFFSET :offset"), params
            ).mappings().all()]
    else:
        conn = open_main_db()
        _ensure_dedup_table(conn)
        c = conn.cursor()
        conds, plist = [], []
        if dup_level: conds.append("dup_level = ?"); plist.append(dup_level)
        if account_id: conds.append("account_id = ?"); plist.append(account_id)
        where = " WHERE " + " AND ".join(conds) if conds else ""
        plist.extend([limit, offset])
        c.execute(f"SELECT * FROM dedup_records{where} ORDER BY checked_at DESC LIMIT ? OFFSET ?", plist)
        rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    return [_row_to_dedup(r) for r in rows]


def _row_to_dedup(row: dict) -> DedupRecord:
    return DedupRecord(
        dedup_id=row["dedup_id"], task_id=row["task_id"],
        platform=row.get("platform", 0) or 0, platform_name=row.get("platform_name", "") or "",
        account_id=row.get("account_id", "") or "",
        content_hash=row.get("content_hash", "") or "",
        title_hash=row.get("title_hash"), video_hash=row.get("video_hash"),
        dup_level=DupLevel(row.get("dup_level", "none")),
        dup_with_task_id=row.get("dup_with_task_id"),
        dup_with_platform=row.get("dup_with_platform"),
        dup_similarity=row.get("dup_similarity", 0.0) or 0.0,
        checked_at=row["checked_at"],
    )


class DedupChecker:
    """内容查重检查器"""

    def check_before_publish(self, task_id: str, platform: int, platform_name: str,
                             account_id: str, title: str = "", content: str = "",
                             video_hash: str = "") -> bool:
        """发布前检查，返回 True 表示允许发布（无重复或重复级别可接受）"""
        record = check_duplicate(task_id, platform, platform_name, account_id,
                                  title, content, video_hash)
        return record.dup_level not in (DupLevel.HIGH,)

    def get_duplicate_report(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """获取查重报告"""
        high = list_dedup_records(dup_level=DupLevel.HIGH.value, account_id=account_id, limit=100)
        medium = list_dedup_records(dup_level=DupLevel.MEDIUM.value, account_id=account_id, limit=100)
        low = list_dedup_records(dup_level=DupLevel.LOW.value, account_id=account_id, limit=100)
        return {
            "high": [{"task_id": r.task_id, "platform": r.platform_name, "similarity": r.dup_similarity, "dup_with": r.dup_with_task_id} for r in high],
            "medium": [{"task_id": r.task_id, "platform": r.platform_name, "similarity": r.dup_similarity, "dup_with": r.dup_with_task_id} for r in medium],
            "low": [{"task_id": r.task_id, "platform": r.platform_name, "similarity": r.dup_similarity, "dup_with": r.dup_with_task_id} for r in low],
            "summary": {"high": len(high), "medium": len(medium), "low": len(low), "total": len(high) + len(medium) + len(low)},
        }


dedup_checker = DedupChecker()
