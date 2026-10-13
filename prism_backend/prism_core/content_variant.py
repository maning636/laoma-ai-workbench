"""
内容版本管理与审核队列（Phase 3.1 + 3.3）

- ContentVariant: 按平台生成不同标题/正文/标签/封面版本
- ReviewQueue: 内容版本提交、审批/退回、审核结论留痕
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso
from fastapi_app.db.runtime import mysql_enabled, sa_connection


# ── ContentVariant ──

class VariantStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class ContentVariant(BaseModel):
    variant_id: str = Field(default_factory=lambda: f"var_{uuid.uuid4().hex[:12]}")
    campaign_id: Optional[str] = None
    material_id: Optional[str] = None
    video_id: Optional[str] = None
    platform: int = 0
    platform_name: str = ""
    title: str = ""
    content: str = ""
    tags: List[str] = []
    cover_url: Optional[str] = None
    format_spec: Optional[str] = None  # 如 "1080x1920"
    status: VariantStatus = VariantStatus.DRAFT
    version: int = 1
    created_at: str = Field(default_factory=now_beijing_iso)
    updated_at: str = Field(default_factory=now_beijing_iso)


def _ensure_variants_table(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS content_variants (
            variant_id TEXT PRIMARY KEY,
            campaign_id TEXT,
            material_id TEXT,
            video_id TEXT,
            platform INTEGER DEFAULT 0,
            platform_name TEXT DEFAULT '',
            title TEXT DEFAULT '',
            content TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            cover_url TEXT,
            format_spec TEXT,
            status TEXT DEFAULT 'draft',
            version INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_variant_campaign ON content_variants(campaign_id)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_variant_status ON content_variants(status)")
    conn.commit()


def save_variant(variant: ContentVariant) -> str:
    from fastapi_app.db.session import get_main_db
    tags_str = json.dumps(variant.tags, ensure_ascii=False)
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS content_variants (
                    variant_id VARCHAR(128) PRIMARY KEY,
                    campaign_id VARCHAR(128), material_id VARCHAR(128), video_id VARCHAR(128),
                    platform INT DEFAULT 0, platform_name VARCHAR(50) DEFAULT '',
                    title TEXT DEFAULT '', content TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]', cover_url TEXT, format_spec TEXT,
                    status VARCHAR(20) DEFAULT 'draft', version INT DEFAULT 1,
                    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                    INDEX idx_variant_campaign (campaign_id),
                    INDEX idx_variant_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO content_variants
                (variant_id, campaign_id, material_id, video_id, platform, platform_name,
                 title, content, tags, cover_url, format_spec, status, version, created_at, updated_at)
                VALUES (:variant_id, :campaign_id, :material_id, :video_id, :platform, :platform_name,
                        :title, :content, :tags, :cover_url, :format_spec, :status, :version, :created_at, :updated_at)
                ON DUPLICATE KEY UPDATE
                    campaign_id=VALUES(campaign_id), material_id=VALUES(material_id),
                    video_id=VALUES(video_id), platform=VALUES(platform),
                    platform_name=VALUES(platform_name), title=VALUES(title),
                    content=VALUES(content), tags=VALUES(tags), cover_url=VALUES(cover_url),
                    format_spec=VALUES(format_spec), status=VALUES(status),
                    version=VALUES(version), updated_at=VALUES(updated_at)
            """), {
                "variant_id": variant.variant_id, "campaign_id": variant.campaign_id,
                "material_id": variant.material_id, "video_id": variant.video_id,
                "platform": variant.platform, "platform_name": variant.platform_name,
                "title": variant.title, "content": variant.content,
                "tags": tags_str, "cover_url": variant.cover_url,
                "format_spec": variant.format_spec, "status": variant.status.value,
                "version": variant.version, "created_at": variant.created_at,
                "updated_at": variant.updated_at,
            })
    else:
        conn = get_main_db()
        _ensure_variants_table(conn)
        conn.execute("""
            INSERT OR REPLACE INTO content_variants
            (variant_id, campaign_id, material_id, video_id, platform, platform_name,
             title, content, tags, cover_url, format_spec, status, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            variant.variant_id, variant.campaign_id, variant.material_id, variant.video_id,
            variant.platform, variant.platform_name, variant.title, variant.content,
            tags_str, variant.cover_url, variant.format_spec,
            variant.status.value, variant.version, variant.created_at, variant.updated_at,
        ))
        conn.commit()
    return variant.variant_id


def get_variant(variant_id: str) -> Optional[ContentVariant]:
    from fastapi_app.db.session import get_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(text("SELECT * FROM content_variants WHERE variant_id = :vid"), {"vid": variant_id}).mappings().first()
        if row: row = dict(row)
    else:
        conn = get_main_db()
        _ensure_variants_table(conn)
        c = conn.cursor()
        c.execute("SELECT * FROM content_variants WHERE variant_id = ?", (variant_id,))
        row = c.fetchone()
        cols = [d[0] for d in c.description]
        if row: row = dict(zip(cols, row))
    if not row: return None
    return _row_to_variant(row)


def list_variants(campaign_id: Optional[str] = None, status: Optional[str] = None,
                  platform: Optional[int] = None, limit: int = 50, offset: int = 0) -> list:
    from fastapi_app.db.session import get_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        conds, params = [], {}
        if campaign_id: conds.append("campaign_id = :cid"); params["cid"] = campaign_id
        if status: conds.append("status = :s"); params["s"] = status
        if platform is not None: conds.append("platform = :p"); params["p"] = platform
        where = " WHERE " + " AND ".join(conds) if conds else ""
        params["limit"], params["offset"] = limit, offset
        with sa_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                text(f"SELECT * FROM content_variants{where} ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"), params
            ).mappings().all()]
    else:
        conn = get_main_db()
        _ensure_variants_table(conn)
        c = conn.cursor()
        conds, plist = [], []
        if campaign_id: conds.append("campaign_id = ?"); plist.append(campaign_id)
        if status: conds.append("status = ?"); plist.append(status)
        if platform is not None: conds.append("platform = ?"); plist.append(platform)
        where = " WHERE " + " AND ".join(conds) if conds else ""
        plist.extend([limit, offset])
        c.execute(f"SELECT * FROM content_variants{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?", plist)
        rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    return [_row_to_variant(r) for r in rows]


def _row_to_variant(row: dict) -> ContentVariant:
    tags = row.get("tags", "[]")
    if isinstance(tags, str):
        try: tags = json.loads(tags)
        except: tags = []
    return ContentVariant(
        variant_id=row["variant_id"], campaign_id=row.get("campaign_id"),
        material_id=row.get("material_id"), video_id=row.get("video_id"),
        platform=row.get("platform", 0) or 0, platform_name=row.get("platform_name", "") or "",
        title=row.get("title", "") or "", content=row.get("content", "") or "",
        tags=tags, cover_url=row.get("cover_url"), format_spec=row.get("format_spec"),
        status=VariantStatus(row.get("status", "draft")), version=row.get("version", 1) or 1,
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


# ── ReviewQueue ──

class ReviewDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNED = "returned"


class ReviewRecord(BaseModel):
    review_id: str = Field(default_factory=lambda: f"rev_{uuid.uuid4().hex[:12]}")
    variant_id: str = ""
    decision: ReviewDecision = ReviewDecision.APPROVED
    reviewer: str = ""
    comment: str = ""
    created_at: str = Field(default_factory=now_beijing_iso)


def _ensure_review_table(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS review_records (
            review_id TEXT PRIMARY KEY,
            variant_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_review_variant ON review_records(variant_id)")
    conn.commit()


def submit_for_review(variant_id: str) -> bool:
    """提交内容版本进入审核"""
    variant = get_variant(variant_id)
    if not variant:
        return False
    variant.status = VariantStatus.PENDING_REVIEW
    variant.updated_at = now_beijing_iso()
    save_variant(variant)
    logger.info(f"[ReviewQueue] {variant_id} 已提交审核")
    return True


def record_review(variant_id: str, decision: ReviewDecision, reviewer: str = "", comment: str = "") -> Optional[ReviewRecord]:
    """记录审核结论"""
    variant = get_variant(variant_id)
    if not variant:
        return None
    record = ReviewRecord(variant_id=variant_id, decision=decision, reviewer=reviewer, comment=comment)

    from fastapi_app.db.session import get_main_db
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS review_records (
                    review_id VARCHAR(128) PRIMARY KEY,
                    variant_id VARCHAR(128) NOT NULL,
                    decision VARCHAR(20) NOT NULL,
                    reviewer VARCHAR(100) DEFAULT '',
                    comment TEXT DEFAULT '',
                    created_at DATETIME NOT NULL,
                    INDEX idx_review_variant (variant_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO review_records (review_id, variant_id, decision, reviewer, comment, created_at)
                VALUES (:review_id, :variant_id, :decision, :reviewer, :comment, :created_at)
            """), {
                "review_id": record.review_id, "variant_id": record.variant_id,
                "decision": record.decision.value, "reviewer": record.reviewer,
                "comment": record.comment, "created_at": record.created_at,
            })
    else:
        conn = get_main_db()
        _ensure_review_table(conn)
        conn.execute("""
            INSERT INTO review_records (review_id, variant_id, decision, reviewer, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (record.review_id, record.variant_id, record.decision.value,
              record.reviewer, record.comment, record.created_at))
        conn.commit()

    # 更新 variant 状态
    variant.updated_at = now_beijing_iso()
    if decision == ReviewDecision.APPROVED:
        variant.status = VariantStatus.APPROVED
    elif decision == ReviewDecision.REJECTED:
        variant.status = VariantStatus.REJECTED
    elif decision == ReviewDecision.RETURNED:
        variant.status = VariantStatus.DRAFT
        variant.version += 1
    save_variant(variant)
    return record


def list_reviews(variant_id: Optional[str] = None, limit: int = 50) -> list:
    from fastapi_app.db.session import get_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        params = {}
        where = ""
        if variant_id: where = " WHERE variant_id = :vid"; params["vid"] = variant_id
        params["limit"] = limit
        with sa_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                text(f"SELECT * FROM review_records{where} ORDER BY created_at DESC LIMIT :limit"), params
            ).mappings().all()]
    else:
        conn = get_main_db()
        _ensure_review_table(conn)
        c = conn.cursor()
        if variant_id:
            c.execute("SELECT * FROM review_records WHERE variant_id = ? ORDER BY created_at DESC LIMIT ?", (variant_id, limit))
        else:
            c.execute("SELECT * FROM review_records ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    return [ReviewRecord(
        review_id=r["review_id"], variant_id=r["variant_id"],
        decision=ReviewDecision(r["decision"]), reviewer=r.get("reviewer", ""),
        comment=r.get("comment", ""), created_at=r["created_at"],
    ) for r in rows]


def approve_variant(variant_id: str, reviewer: str = "", comment: str = "") -> Optional[ReviewRecord]:
    return record_review(variant_id, ReviewDecision.APPROVED, reviewer, comment)


def reject_variant(variant_id: str, reviewer: str = "", comment: str = "") -> Optional[ReviewRecord]:
    return record_review(variant_id, ReviewDecision.REJECTED, reviewer, comment)


def return_variant(variant_id: str, reviewer: str = "", comment: str = "") -> Optional[ReviewRecord]:
    return record_review(variant_id, ReviewDecision.RETURNED, reviewer, comment)
