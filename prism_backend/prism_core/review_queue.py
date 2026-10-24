"""
内容审核队列（Phase 3.3）
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


class ReviewStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_EDIT = "needs_edit"
    AUTO_APPROVED = "auto_approved"
    AUTO_REJECTED = "auto_rejected"


class ReviewPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ReviewType(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"
    PRE_CHECK = "pre_check"


class ReviewItem(BaseModel):
    review_id: str = Field(default_factory=lambda: f"rv_{uuid.uuid4().hex[:12]}")
    task_id: str = ""
    campaign_id: str = ""
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    status: ReviewStatus = ReviewStatus.PENDING
    priority: ReviewPriority = ReviewPriority.NORMAL
    review_type: ReviewType = ReviewType.MANUAL
    title: str = ""
    content: str = ""
    cover_url: Optional[str] = None
    risk_score: float = 0.0
    risk_factors: Optional[str] = None
    queue_position: int = 0
    reviewer: Optional[str] = None
    submitted_at: str = Field(default_factory=now_beijing_iso)
    reviewed_at: Optional[str] = None
    decision_reason: Optional[str] = None
    decision_by: Optional[str] = None
    metadata: Optional[str] = None
    # 2026-10-22 修复：`enqueue_review` 一直写入 item.created_at，但模型里没有这个
    # 字段 → 任何送审请求（POST /api/v1/review/queue、auto-check、批量入队）
    # 都在入库前抛 AttributeError，整条「送审」链路是断的。
    created_at: str = Field(default_factory=now_beijing_iso)


class ReviewDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: f"rd_{uuid.uuid4().hex[:12]}")
    review_id: str = ""
    decision: str = ""
    reason: str = ""
    reviewer: str = ""
    created_at: str = Field(default_factory=now_beijing_iso)


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS review_queue (
            review_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            campaign_id TEXT DEFAULT '',
            platform INTEGER DEFAULT 0,
            platform_name TEXT DEFAULT '',
            account_id TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            priority TEXT DEFAULT 'normal',
            review_type TEXT DEFAULT 'manual',
            title TEXT DEFAULT '',
            content TEXT,
            cover_url TEXT,
            risk_score REAL DEFAULT 0.0,
            risk_factors TEXT,
            queue_position INTEGER DEFAULT 0,
            reviewer TEXT,
            submitted_at TEXT NOT NULL,
            reviewed_at TEXT,
            decision_reason TEXT,
            decision_by TEXT,
            metadata TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS review_decisions (
            decision_id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT,
            reviewer TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_rq_status ON review_queue(status)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_rq_priority ON review_queue(priority)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_rq_campaign ON review_queue(campaign_id)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_rd_review ON review_decisions(review_id)")
    conn.commit()


def _get_review_task_id(review_id: str) -> str:
    """取审核项的 task_id（送审时存的是统一产物 ID art_xxx）。"""
    from fastapi_app.db.session import open_main_db
    try:
        conn = open_main_db()
        _ensure_tables(conn)
        cur = conn.execute(
            "SELECT task_id FROM review_queue WHERE review_id = ?", (review_id,)
        )
        row = cur.fetchone()
        if row is None:
            return ""
        return str(row[0] or "")
    except Exception:
        return ""


def _apply_artifact_review_writeback(
    review_id: str, decision: str, reason: str = "", task_id: str = ""
) -> None:
    """审核决策回写到「统一产物总线」的阶段。

    这是「送审 → 审核 → 阶段回写」闭环的最后一环：
    审核通过 → 产物 stage=approved；拒绝/需修改 → stage=rejected。

    回写失败只记日志，不影响审核结果本身（审核是主业务）。
    """
    try:
        from prism_core import artifacts as artifact_service

        artifact_service.apply_review_decision(
            review_id, decision, task_id=task_id, reason=reason
        )
    except Exception as e:
        logger.warning(f"[Review] 产物阶段回写失败 {review_id}: {e}")


def _apply_publish_task_state_writeback(artifact_id: str, decision: str) -> None:
    """审核决策回写到发布任务对应的 task_state 状态（L2-2 修断链 #4）。

    链路：review_queue.task_id = artifact_id → publish_tasks.artifact_id
          → publish_tasks.task_id → task_states.task_id (str)

    决策 → 目标状态映射（走 task_state_machine 合法转换）：
      - approved → APPROVED
      - rejected / needs_edit / auto_rejected → DRAFT（退回修改）

    失败策略（不阻塞审核）：
      - publish_task 不存在 → 静默跳过
      - task_state 不存在 → 静默跳过
      - 非法状态转换 → 静默跳过并记 warning
      - 其他异常 → 静默跳过并记 warning
    """
    if not artifact_id:
        return
    try:
        from fastapi_app.db.session import open_main_db
        from prism_core.task_state_machine import (
            TaskStatus,
            get_task_state,
            save_task_state,
            transition_state,
            InvalidTransition,
        )

        conn = open_main_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT task_id FROM publish_tasks WHERE artifact_id = ? LIMIT 1",
                (artifact_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            logger.debug(
                f"[Review] 无 publish_task 关联 artifact_id={artifact_id}，"
                f"跳过 task_state 回写"
            )
            return

        state_task_id = str(row[0])

        if decision == "approved":
            target = TaskStatus.APPROVED
        elif decision in ("rejected", "needs_edit", "auto_rejected"):
            target = TaskStatus.DRAFT
        else:
            return

        state = get_task_state(state_task_id)
        if state is None:
            logger.debug(
                f"[Review] task_state {state_task_id} 不存在，跳过回写"
            )
            return
        if state.status == target:
            return

        new_status = transition_state(state.status, target)
        state.status = new_status
        save_task_state(state)
        logger.info(
            f"[Review] task_state {state_task_id} → {target.value}（decision={decision}）"
        )
    except InvalidTransition as e:
        logger.warning(
            f"[Review] task_state 非法转换（跳过，不阻塞审核）"
            f" artifact={artifact_id} decision={decision}: {e}"
        )
    except Exception as e:
        logger.warning(
            f"[Review] task_state 回写失败（跳过，不阻塞审核）"
            f" artifact={artifact_id} decision={decision}: {e}"
        )


def enqueue_review(item: ReviewItem) -> str:
    from fastapi_app.db.session import open_main_db
    data = item.model_dump()
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS review_queue (
                    review_id VARCHAR(128) PRIMARY KEY,
                    task_id VARCHAR(128) NOT NULL,
                    campaign_id VARCHAR(128) DEFAULT '',
                    platform INT DEFAULT 0, platform_name VARCHAR(50) DEFAULT '',
                    account_id VARCHAR(200) DEFAULT '',
                    status VARCHAR(30) DEFAULT 'pending',
                    priority VARCHAR(15) DEFAULT 'normal',
                    review_type VARCHAR(20) DEFAULT 'manual',
                    title VARCHAR(500) DEFAULT '', content TEXT,
                    cover_url VARCHAR(1000), risk_score REAL DEFAULT 0.0,
                    risk_factors TEXT, queue_position INT DEFAULT 0,
                    reviewer VARCHAR(200), submitted_at DATETIME NOT NULL,
                    reviewed_at DATETIME, decision_reason TEXT,
                    decision_by VARCHAR(200), metadata TEXT,
                    created_at DATETIME NOT NULL,
                    INDEX idx_rq_status (status),
                    INDEX idx_rq_priority (priority),
                    INDEX idx_rq_campaign (campaign_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS review_decisions (
                    decision_id VARCHAR(128) PRIMARY KEY,
                    review_id VARCHAR(128) NOT NULL,
                    decision VARCHAR(30) NOT NULL, reason TEXT,
                    reviewer VARCHAR(200), created_at DATETIME NOT NULL,
                    INDEX idx_rd_review (review_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO review_queue
                (review_id, task_id, campaign_id, platform, platform_name, account_id,
                 status, priority, review_type, title, content, cover_url,
                 risk_score, risk_factors, queue_position, reviewer,
                 submitted_at, reviewed_at, decision_reason, decision_by, metadata, created_at)
                VALUES (:review_id, :task_id, :campaign_id, :platform, :platform_name, :account_id,
                        :status, :priority, :review_type, :title, :content, :cover_url,
                        :risk_score, :risk_factors, :queue_position, :reviewer,
                        :submitted_at, :reviewed_at, :decision_reason, :decision_by, :metadata, :created_at)
                ON DUPLICATE KEY UPDATE
                    task_id=VALUES(task_id), campaign_id=VALUES(campaign_id),
                    platform=VALUES(platform), platform_name=VALUES(platform_name),
                    account_id=VALUES(account_id), status=VALUES(status),
                    priority=VALUES(priority), review_type=VALUES(review_type),
                    title=VALUES(title), content=VALUES(content),
                    cover_url=VALUES(cover_url), risk_score=VALUES(risk_score),
                    risk_factors=VALUES(risk_factors), queue_position=VALUES(queue_position),
                    reviewer=VALUES(reviewer), submitted_at=VALUES(submitted_at),
                    reviewed_at=VALUES(reviewed_at), decision_reason=VALUES(decision_reason),
                    decision_by=VALUES(decision_by), metadata=VALUES(metadata)
            """), data)
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        conn.execute("""
            INSERT OR REPLACE INTO review_queue
            (review_id, task_id, campaign_id, platform, platform_name, account_id,
             status, priority, review_type, title, content, cover_url,
             risk_score, risk_factors, queue_position, reviewer,
             submitted_at, reviewed_at, decision_reason, decision_by, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.review_id, item.task_id, item.campaign_id, item.platform,
            item.platform_name, item.account_id, item.status.value,
            item.priority.value, item.review_type.value, item.title,
            item.content, item.cover_url, item.risk_score, item.risk_factors,
            item.queue_position, item.reviewer, item.submitted_at,
            item.reviewed_at, item.decision_reason, item.decision_by,
            item.metadata, item.created_at,
        ))
        conn.commit()
    return item.review_id


def approve_review(review_id: str, reviewer: str, reason: str = "") -> Optional[ReviewDecision]:
    from fastapi_app.db.session import open_main_db
    now = now_beijing_iso()
    data = ReviewDecision(review_id=review_id, decision=ReviewStatus.APPROVED.value,
                          reason=reason, reviewer=reviewer)
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("UPDATE review_queue SET status='approved', reviewed_at=:now, decision_by=:reviewer, decision_reason=:reason WHERE review_id=:rid"),
                          {"rid": review_id, "now": now, "reviewer": reviewer, "reason": reason})
            conn.execute(text("""
                INSERT INTO review_decisions
                (decision_id, review_id, decision, reason, reviewer, created_at)
                VALUES (:decision_id, :review_id, :decision, :reason, :reviewer, :created_at)
                ON DUPLICATE KEY UPDATE
                    review_id=VALUES(review_id), decision=VALUES(decision),
                    reason=VALUES(reason), reviewer=VALUES(reviewer)
            """), data.model_dump())
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        conn.execute("UPDATE review_queue SET status='approved', reviewed_at=?, decision_by=?, decision_reason=? WHERE review_id=?",
                     (now, reviewer, reason, review_id))
        conn.execute("""
            INSERT OR REPLACE INTO review_decisions
            (decision_id, review_id, decision, reason, reviewer, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data.decision_id, data.review_id, data.decision, data.reason, data.reviewer, data.created_at))
        conn.commit()
    logger.info(f"[Review] 通过: {review_id} by {reviewer}")
    _review_task_id = _get_review_task_id(review_id)
    _apply_artifact_review_writeback(review_id, "approved", reason, _review_task_id)
    _apply_publish_task_state_writeback(_review_task_id, "approved")
    return data


def reject_review(review_id: str, reviewer: str, reason: str = "") -> Optional[ReviewDecision]:
    from fastapi_app.db.session import open_main_db
    now = now_beijing_iso()
    data = ReviewDecision(review_id=review_id, decision=ReviewStatus.REJECTED.value,
                          reason=reason, reviewer=reviewer)
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("UPDATE review_queue SET status='rejected', reviewed_at=:now, decision_by=:reviewer, decision_reason=:reason WHERE review_id=:rid"),
                          {"rid": review_id, "now": now, "reviewer": reviewer, "reason": reason})
            conn.execute(text("""
                INSERT INTO review_decisions
                (decision_id, review_id, decision, reason, reviewer, created_at)
                VALUES (:decision_id, :review_id, :decision, :reason, :reviewer, :created_at)
                ON DUPLICATE KEY UPDATE
                    review_id=VALUES(review_id), decision=VALUES(decision),
                    reason=VALUES(reason), reviewer=VALUES(reviewer)
            """), data.model_dump())
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        conn.execute("UPDATE review_queue SET status='rejected', reviewed_at=?, decision_by=?, decision_reason=? WHERE review_id=?",
                     (now, reviewer, reason, review_id))
        conn.execute("""
            INSERT OR REPLACE INTO review_decisions
            (decision_id, review_id, decision, reason, reviewer, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data.decision_id, data.review_id, data.decision, data.reason, data.reviewer, data.created_at))
        conn.commit()
    logger.warning(f"[Review] 拒绝: {review_id} by {reviewer} - {reason}")
    _review_task_id = _get_review_task_id(review_id)
    _apply_artifact_review_writeback(
        review_id, "rejected", reason, _review_task_id
    )
    _apply_publish_task_state_writeback(_review_task_id, "rejected")
    return data


def auto_pre_check(task_id: str, platform: int, platform_name: str, account_id: str,
                   title: str = "", content: str = "") -> ReviewItem:
    """自动预检查"""
    risk_score = 0.0
    risk_factors = []
    if len(title) < 5:
        risk_factors.append("标题过短")
        risk_score += 0.3
    if len(content) < 10:
        risk_factors.append("内容过短")
        risk_score += 0.2
    sensitive_words = ["色情", "暴力", "赌博", "毒品", "政治", "反动"]
    for w in sensitive_words:
        if w in title or w in content:
            risk_factors.append(f"包含敏感词: {w}")
            risk_score += 0.4
    risk_score = min(round(risk_score, 2), 1.0)

    if risk_score >= 0.7:
        status = ReviewStatus.AUTO_REJECTED
    elif risk_score >= 0.4:
        status = ReviewStatus.NEEDS_EDIT
    elif risk_score < 0.1:
        status = ReviewStatus.AUTO_APPROVED
    else:
        status = ReviewStatus.PENDING

    item = ReviewItem(
        task_id=task_id, platform=platform, platform_name=platform_name,
        account_id=account_id, status=status, review_type=ReviewType.PRE_CHECK,
        title=title, content=content, risk_score=risk_score,
        risk_factors=json.dumps(risk_factors, ensure_ascii=False) if risk_factors else None,
        reviewed_at=now_beijing_iso() if status != ReviewStatus.PENDING else None,
        decision_by="auto_checker" if status != ReviewStatus.PENDING else None,
        decision_reason="; ".join(risk_factors) if risk_factors else None,
    )
    enqueue_review(item)
    # 自动预检查有结论时，同步回写产物阶段
    if status in (
        ReviewStatus.AUTO_APPROVED,
        ReviewStatus.AUTO_REJECTED,
        ReviewStatus.NEEDS_EDIT,
    ):
        _apply_artifact_review_writeback(
            item.review_id,
            status.value,
            "; ".join(risk_factors) if risk_factors else "",
            task_id,
        )
    if status == ReviewStatus.AUTO_REJECTED:
        logger.warning(f"[Review] 自动拒绝: {task_id} - {risk_factors}")
    return item


def list_reviews(status: Optional[str] = None, priority: Optional[str] = None,
                 campaign_id: Optional[str] = None, account_id: Optional[str] = None,
                 limit: int = 50, offset: int = 0) -> list:
    from fastapi_app.db.session import open_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        conds, params = [], {}
        if status: conds.append("status = :st"); params["st"] = status
        if priority: conds.append("priority = :pr"); params["pr"] = priority
        if campaign_id: conds.append("campaign_id = :ci"); params["ci"] = campaign_id
        if account_id: conds.append("account_id = :aid"); params["aid"] = account_id
        where = " WHERE " + " AND ".join(conds) if conds else ""
        params["limit"], params["offset"] = limit, offset
        with sa_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                text(f"SELECT * FROM review_queue{where} ORDER BY queue_position ASC, submitted_at ASC LIMIT :limit OFFSET :offset"), params
            ).mappings().all()]
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        conds, plist = [], []
        if status: conds.append("status = ?"); plist.append(status)
        if priority: conds.append("priority = ?"); plist.append(priority)
        if campaign_id: conds.append("campaign_id = ?"); plist.append(campaign_id)
        if account_id: conds.append("account_id = ?"); plist.append(account_id)
        where = " WHERE " + " AND ".join(conds) if conds else ""
        plist.extend([limit, offset])
        c.execute(f"SELECT * FROM review_queue{where} ORDER BY queue_position ASC, submitted_at ASC LIMIT ? OFFSET ?", plist)
        rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    return [_row_to_item(r) for r in rows]


def get_review_item(review_id: str) -> Optional[ReviewItem]:
    from fastapi_app.db.session import open_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(text("SELECT * FROM review_queue WHERE review_id = :rid"), {"rid": review_id}).mappings().first()
        if row: row = dict(row)
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        c.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,))
        row = c.fetchone()
        cols = [d[0] for d in c.description]
        if row: row = dict(zip(cols, row))
    return _row_to_item(row) if row else None


def _row_to_item(row: dict) -> ReviewItem:
    return ReviewItem(
        review_id=row["review_id"], task_id=row["task_id"],
        campaign_id=row.get("campaign_id", "") or "",
        platform=row.get("platform", 0) or 0, platform_name=row.get("platform_name", "") or "",
        account_id=row.get("account_id", "") or "",
        status=ReviewStatus(row.get("status", "pending")),
        priority=ReviewPriority(row.get("priority", "normal")),
        review_type=ReviewType(row.get("review_type", "manual")),
        title=row.get("title", "") or "", content=row.get("content"),
        cover_url=row.get("cover_url"), risk_score=row.get("risk_score", 0.0) or 0.0,
        risk_factors=row.get("risk_factors"), queue_position=row.get("queue_position", 0) or 0,
        reviewer=row.get("reviewer"), submitted_at=row["submitted_at"],
        reviewed_at=row.get("reviewed_at"), decision_reason=row.get("decision_reason"),
        decision_by=row.get("decision_by"), metadata=row.get("metadata"),
        created_at=row.get("created_at") or row.get("submitted_at") or now_beijing_iso(),
    )


class ReviewQueueManager:
    def __init__(self):
        pass

    def enqueue(self, **kwargs) -> ReviewItem:
        item = ReviewItem(**kwargs)
        enqueue_review(item)
        return item

    def approve(self, review_id: str, reviewer: str, reason: str = "") -> Optional[ReviewDecision]:
        return approve_review(review_id, reviewer, reason)

    def reject(self, review_id: str, reviewer: str, reason: str = "") -> Optional[ReviewDecision]:
        return reject_review(review_id, reviewer, reason)

    def request_edit(self, review_id: str, reviewer: str, reason: str = "") -> None:
        from fastapi_app.db.session import open_main_db
        now = now_beijing_iso()
        if mysql_enabled():
            from sqlalchemy import text
            with sa_connection() as conn:
                conn.execute(text("UPDATE review_queue SET status='needs_edit', reviewed_at=:now, decision_by=:reviewer, decision_reason=:reason WHERE review_id=:rid"),
                              {"rid": review_id, "now": now, "reviewer": reviewer, "reason": reason})
        else:
            conn = open_main_db()
            _ensure_tables(conn)
            conn.execute("UPDATE review_queue SET status='needs_edit', reviewed_at=?, decision_by=?, decision_reason=? WHERE review_id=?",
                         (now, reviewer, reason, review_id))
            conn.commit()
        _review_task_id = _get_review_task_id(review_id)
        _apply_artifact_review_writeback(
            review_id, "needs_edit", reason, _review_task_id
        )
        _apply_publish_task_state_writeback(_review_task_id, "needs_edit")

    def get_next_pending(self, platform: Optional[int] = None, limit: int = 1) -> list:
        return list_reviews(status=ReviewStatus.PENDING.value, account_id=None,
                           priority=None, campaign_id=None,
                           limit=limit, offset=0)

    def batch_approve(self, review_ids: list, reviewer: str, reason: str = "") -> int:
        count = 0
        for rid in review_ids:
            approve_review(rid, reviewer, reason)
            count += 1
        return count

    def batch_reject(self, review_ids: list, reviewer: str, reason: str = "") -> int:
        count = 0
        for rid in review_ids:
            reject_review(rid, reviewer, reason)
            count += 1
        return count

    def stats(self) -> Dict[str, int]:
        result = {}
        for status in ReviewStatus:
            rows = list_reviews(status=status.value, limit=1000)
            result[status.value] = len(rows)
        result["total"] = sum(result.values())
        return result


review_queue_manager = ReviewQueueManager()
