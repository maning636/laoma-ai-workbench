"""
发布后数据回收与洞察（Phase 4.2）

- 发布后数据采集（播放/互动/转化）
- 异常检测（发布失败率突增、互动率异常）
- 下一轮建议
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso
from fastapi_app.db.runtime import mysql_enabled, sa_connection


class PublishInsight(BaseModel):
    insight_id: str = Field(default_factory=lambda: f"ins_{uuid.uuid4().hex[:12]}")
    task_id: str = ""
    platform: int = 0
    platform_name: str = ""
    account_id: str = ""
    # 数据指标
    plays: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    favorites: int = 0
    followers_gained: int = 0
    # 时间
    published_at: Optional[str] = None
    collected_at: str = Field(default_factory=now_beijing_iso)
    data_age_hours: float = 0.0
    # 互动率
    like_rate: float = 0.0
    comment_rate: float = 0.0
    share_rate: float = 0.0
    # 异常标记
    is_anomaly: bool = False
    anomaly_reason: Optional[str] = None
    # 建议
    suggestion: Optional[str] = None
    raw_data: Optional[str] = None


class AnomalyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _ensure_insight_table(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS publish_insights (
            insight_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            platform INTEGER DEFAULT 0,
            platform_name TEXT DEFAULT '',
            account_id TEXT DEFAULT '',
            plays INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            favorites INTEGER DEFAULT 0,
            followers_gained INTEGER DEFAULT 0,
            published_at TEXT,
            collected_at TEXT NOT NULL,
            data_age_hours REAL DEFAULT 0.0,
            like_rate REAL DEFAULT 0.0,
            comment_rate REAL DEFAULT 0.0,
            share_rate REAL DEFAULT 0.0,
            is_anomaly INTEGER DEFAULT 0,
            anomaly_reason TEXT,
            suggestion TEXT,
            raw_data TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_insight_task ON publish_insights(task_id)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_insight_account ON publish_insights(account_id)")
    conn.commit()


def save_insight(insight: PublishInsight) -> str:
    from fastapi_app.db.session import get_main_db
    data = insight.model_dump()
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS publish_insights (
                    insight_id VARCHAR(128) PRIMARY KEY,
                    task_id VARCHAR(128) NOT NULL,
                    platform INT DEFAULT 0, platform_name VARCHAR(50) DEFAULT '',
                    account_id VARCHAR(200) DEFAULT '',
                    plays BIGINT DEFAULT 0, likes BIGINT DEFAULT 0,
                    comments BIGINT DEFAULT 0, shares BIGINT DEFAULT 0,
                    favorites BIGINT DEFAULT 0, followers_gained BIGINT DEFAULT 0,
                    published_at DATETIME, collected_at DATETIME NOT NULL,
                    data_age_hours REAL DEFAULT 0.0,
                    like_rate REAL DEFAULT 0.0, comment_rate REAL DEFAULT 0.0,
                    share_rate REAL DEFAULT 0.0,
                    is_anomaly TINYINT DEFAULT 0, anomaly_reason TEXT,
                    suggestion TEXT, raw_data TEXT,
                    created_at DATETIME NOT NULL,
                    INDEX idx_insight_task (task_id),
                    INDEX idx_insight_account (account_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO publish_insights
                (insight_id, task_id, platform, platform_name, account_id,
                 plays, likes, comments, shares, favorites, followers_gained,
                 published_at, collected_at, data_age_hours,
                 like_rate, comment_rate, share_rate,
                 is_anomaly, anomaly_reason, suggestion, raw_data, created_at)
                VALUES (:insight_id, :task_id, :platform, :platform_name, :account_id,
                        :plays, :likes, :comments, :shares, :favorites, :followers_gained,
                        :published_at, :collected_at, :data_age_hours,
                        :like_rate, :comment_rate, :share_rate,
                        :is_anomaly, :anomaly_reason, :suggestion, :raw_data, :created_at)
                ON DUPLICATE KEY UPDATE
                    task_id=VALUES(task_id), platform=VALUES(platform),
                    platform_name=VALUES(platform_name), account_id=VALUES(account_id),
                    plays=VALUES(plays), likes=VALUES(likes), comments=VALUES(comments),
                    shares=VALUES(shares), favorites=VALUES(favorites),
                    followers_gained=VALUES(followers_gained),
                    published_at=VALUES(published_at), collected_at=VALUES(collected_at),
                    data_age_hours=VALUES(data_age_hours),
                    like_rate=VALUES(like_rate), comment_rate=VALUES(comment_rate),
                    share_rate=VALUES(share_rate),
                    is_anomaly=VALUES(is_anomaly), anomaly_reason=VALUES(anomaly_reason),
                    suggestion=VALUES(suggestion), raw_data=VALUES(raw_data)
            """), {"is_anomaly": int(insight.is_anomaly), **data})
    else:
        conn = get_main_db()
        _ensure_insight_table(conn)
        conn.execute("""
            INSERT OR REPLACE INTO publish_insights
            (insight_id, task_id, platform, platform_name, account_id,
             plays, likes, comments, shares, favorites, followers_gained,
             published_at, collected_at, data_age_hours,
             like_rate, comment_rate, share_rate,
             is_anomaly, anomaly_reason, suggestion, raw_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            insight.insight_id, insight.task_id, insight.platform, insight.platform_name,
            insight.account_id, insight.plays, insight.likes, insight.comments,
            insight.shares, insight.favorites, insight.followers_gained,
            insight.published_at, insight.collected_at, insight.data_age_hours,
            insight.like_rate, insight.comment_rate, insight.share_rate,
            int(insight.is_anomaly), insight.anomaly_reason, insight.suggestion,
            insight.raw_data, insight.created_at,
        ))
        conn.commit()
    return insight.insight_id


def get_insight(task_id: str) -> Optional[PublishInsight]:
    from fastapi_app.db.session import get_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(text("SELECT * FROM publish_insights WHERE task_id = :tid ORDER BY collected_at DESC LIMIT 1"), {"tid": task_id}).mappings().first()
        if row: row = dict(row)
    else:
        conn = get_main_db()
        _ensure_insight_table(conn)
        c = conn.cursor()
        c.execute("SELECT * FROM publish_insights WHERE task_id = ? ORDER BY collected_at DESC LIMIT 1", (task_id,))
        row = c.fetchone()
        cols = [d[0] for d in c.description]
        if row: row = dict(zip(cols, row))
    if not row: return None
    return _row_to_insight(row)


def list_insights(account_id: Optional[str] = None, platform: Optional[int] = None,
                  anomaly_only: bool = False, limit: int = 50, offset: int = 0) -> list:
    from fastapi_app.db.session import get_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        conds, params = [], {}
        if account_id: conds.append("account_id = :aid"); params["aid"] = account_id
        if platform is not None: conds.append("platform = :p"); params["p"] = platform
        if anomaly_only: conds.append("is_anomaly = 1")
        where = " WHERE " + " AND ".join(conds) if conds else ""
        params["limit"], params["offset"] = limit, offset
        with sa_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                text(f"SELECT * FROM publish_insights{where} ORDER BY collected_at DESC LIMIT :limit OFFSET :offset"), params
            ).mappings().all()]
    else:
        conn = get_main_db()
        _ensure_insight_table(conn)
        c = conn.cursor()
        conds, plist = [], []
        if account_id: conds.append("account_id = ?"); plist.append(account_id)
        if platform is not None: conds.append("platform = ?"); plist.append(platform)
        if anomaly_only: conds.append("is_anomaly = 1")
        where = " WHERE " + " AND ".join(conds) if conds else ""
        plist.extend([limit, offset])
        c.execute(f"SELECT * FROM publish_insights{where} ORDER BY collected_at DESC LIMIT ? OFFSET ?", plist)
        rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    return [_row_to_insight(r) for r in rows]


def _row_to_insight(row: dict) -> PublishInsight:
    return PublishInsight(
        insight_id=row["insight_id"], task_id=row["task_id"],
        platform=row.get("platform", 0) or 0, platform_name=row.get("platform_name", "") or "",
        account_id=row.get("account_id", "") or "",
        plays=row.get("plays", 0) or 0, likes=row.get("likes", 0) or 0,
        comments=row.get("comments", 0) or 0, shares=row.get("shares", 0) or 0,
        favorites=row.get("favorites", 0) or 0, followers_gained=row.get("followers_gained", 0) or 0,
        published_at=row.get("published_at"), collected_at=row["collected_at"],
        data_age_hours=row.get("data_age_hours", 0.0) or 0.0,
        like_rate=row.get("like_rate", 0.0) or 0.0,
        comment_rate=row.get("comment_rate", 0.0) or 0.0,
        share_rate=row.get("share_rate", 0.0) or 0.0,
        is_anomaly=bool(row.get("is_anomaly", 0)),
        anomaly_reason=row.get("anomaly_reason"),
        suggestion=row.get("suggestion"),
        raw_data=row.get("raw_data"),
    )


def detect_anomaly(insight: PublishInsight) -> Optional[str]:
    """检测异常数据"""
    if insight.plays == 0 and insight.likes == 0 and insight.comments == 0:
        return "零互动：播放/点赞/评论均为0"
    if insight.plays > 0 and insight.like_rate < 0.001:
        return f"互动率异常低：{insight.like_rate:.4%}"
    if insight.plays > 1000 and insight.likes == 0:
        return "播放>1000但零点赞"
    if insight.followers_gained < 0:
        return "掉粉异常"
    return None


def generate_suggestion(insight: PublishInsight) -> Optional[str]:
    """生成下一轮建议"""
    suggestions = []
    if insight.plays == 0:
        suggestions.append("发布后无任何数据，检查是否发布成功")
    elif insight.like_rate < 0.005:
        suggestions.append("点赞率偏低，考虑优化标题和封面")
    elif insight.like_rate > 0.05:
        suggestions.append("表现优秀，可加大此类内容投入")
    if insight.comment_rate < 0.001 and insight.plays > 100:
        suggestions.append("评论率极低，考虑在内容中增加互动引导")
    if insight.followers_gained > insight.likes:
        suggestions.append("涨粉效果好，继续此类选题")
    return "; ".join(suggestions) if suggestions else None


class InsightCollector:
    """洞察采集器"""

    def __init__(self):
        self._platform_apis = {}

    def collect_from_receipt(self, task_id: str, platform_data: Dict[str, Any]) -> PublishInsight:
        """从平台 API 数据创建洞察"""
        plays = platform_data.get("plays", 0)
        likes = platform_data.get("likes", 0)
        comments = platform_data.get("comments", 0)
        shares = platform_data.get("shares", 0)
        favorites = platform_data.get("favorites", 0)
        followers_gained = platform_data.get("followers_gained", 0)

        like_rate = round(likes / plays, 6) if plays > 0 else 0.0
        comment_rate = round(comments / plays, 6) if plays > 0 else 0.0
        share_rate = round(shares / plays, 6) if plays > 0 else 0.0

        insight = PublishInsight(
            task_id=task_id,
            platform=platform_data.get("platform", 0),
            platform_name=platform_data.get("platform_name", ""),
            account_id=platform_data.get("account_id", ""),
            plays=plays, likes=likes, comments=comments,
            shares=shares, favorites=favorites, followers_gained=followers_gained,
            published_at=platform_data.get("published_at"),
            data_age_hours=platform_data.get("data_age_hours", 0.0),
            like_rate=like_rate, comment_rate=comment_rate, share_rate=share_rate,
            raw_data=json.dumps(platform_data, ensure_ascii=False) if platform_data else None,
        )

        # 异常检测
        anomaly = detect_anomaly(insight)
        if anomaly:
            insight.is_anomaly = True
            insight.anomaly_reason = anomaly
            logger.warning(f"[Insight] 异常检测: {task_id} - {anomaly}")

        # 生成建议
        insight.suggestion = generate_suggestion(insight)

        save_insight(insight)
        return insight


insight_collector = InsightCollector()
