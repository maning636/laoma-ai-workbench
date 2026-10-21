"""
Webhook/API 集成（Phase 5）

- 支持第三方平台 Webhook 接收（抖音/小红书/快手/B站/视频号）
- 支持外部系统主动调用 老马AI工作台 API 的回调机制
- 签名验证、重试机制、事件去重
"""
from __future__ import annotations

import hashlib
import hmac
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


class WebhookEventType(str, Enum):
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_RETRIED = "task.retried"
    ACCOUNT_LOGIN = "account.login"
    ACCOUNT_BANNED = "account.banned"
    ACCOUNT_SUSPICIOUS = "account.suspicious"
    CONTENT_PUBLISHED = "content.published"
    CONTENT_REJECTED = "content.rejected"
    ALERT_TRIGGERED = "alert.triggered"
    ALERT_RESOLVED = "alert.resolved"
    REVIEW_APPROVED = "review.approved"
    REVIEW_REJECTED = "review.rejected"
    INSIGHT_COLLECTED = "insight.collected"
    MATRIX_ROUTED = "matrix.routed"
    CUSTOM = "custom.event"


class WebhookSubscription(BaseModel):
    subscription_id: str = Field(default_factory=lambda: f"wh_{uuid.uuid4().hex[:12]}")
    name: str = ""
    url: str = ""
    events: Optional[str] = None
    secret: str = ""
    active: bool = True
    retry_count: int = 3
    retry_interval: int = 60
    timeout: int = 30
    last_delivery_at: Optional[str] = None
    last_status_code: Optional[int] = None
    total_deliveries: int = 0
    failed_deliveries: int = 0
    created_at: str = Field(default_factory=now_beijing_iso)
    updated_at: str = Field(default_factory=now_beijing_iso)


class WebhookDelivery(BaseModel):
    delivery_id: str = Field(default_factory=lambda: f"wd_{uuid.uuid4().hex[:12]}")
    subscription_id: str = ""
    event_type: str = ""
    event_payload: Optional[str] = None
    status: str = "pending"
    attempt: int = 0
    max_attempts: int = 3
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    signed: bool = False
    signature: Optional[str] = None
    created_at: str = Field(default_factory=now_beijing_iso)
    delivered_at: Optional[str] = None


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS webhook_subscriptions (
            subscription_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            events TEXT,
            secret TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            retry_count INTEGER DEFAULT 3,
            retry_interval INTEGER DEFAULT 60,
            timeout INTEGER DEFAULT 30,
            last_delivery_at TEXT,
            last_status_code INTEGER,
            total_deliveries INTEGER DEFAULT 0,
            failed_deliveries INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            delivery_id TEXT PRIMARY KEY,
            subscription_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_payload TEXT,
            status TEXT DEFAULT 'pending',
            attempt INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3,
            status_code INTEGER,
            response_body TEXT,
            error_message TEXT,
            signed INTEGER DEFAULT 0,
            signature TEXT,
            created_at TEXT NOT NULL,
            delivered_at TEXT
        )
    """)
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS webhook_events_log (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            source TEXT DEFAULT '',
            payload TEXT,
            dedup_key TEXT,
            received_at TEXT NOT NULL,
            processed INTEGER DEFAULT 0
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_wh_sub_active ON webhook_subscriptions(active)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_wh_deliv_sub ON webhook_deliveries(subscription_id)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_wh_deliv_status ON webhook_deliveries(status)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_wh_log_dedup ON webhook_events_log(dedup_key)")
    conn.commit()


def _save_subscription(sub: WebhookSubscription) -> str:
    from fastapi_app.db.session import open_main_db
    data = sub.model_dump()
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS webhook_subscriptions (
                    subscription_id VARCHAR(128) PRIMARY KEY,
                    name VARCHAR(200) NOT NULL, url VARCHAR(1000) NOT NULL,
                    events TEXT, secret VARCHAR(500) DEFAULT '',
                    active TINYINT(1) DEFAULT 1,
                    retry_count INT DEFAULT 3, retry_interval INT DEFAULT 60,
                    timeout INT DEFAULT 30,
                    last_delivery_at DATETIME, last_status_code INT,
                    total_deliveries INT DEFAULT 0, failed_deliveries INT DEFAULT 0,
                    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                    INDEX idx_wh_sub_active (active)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO webhook_subscriptions
                (subscription_id, name, url, events, secret, active, retry_count, retry_interval, timeout,
                 last_delivery_at, last_status_code, total_deliveries, failed_deliveries, created_at, updated_at)
                VALUES (:subscription_id, :name, :url, :events, :secret, :active, :retry_count, :retry_interval,
                        :timeout, :last_delivery_at, :last_status_code, :total_deliveries, :failed_deliveries,
                        :created_at, :updated_at)
                ON DUPLICATE KEY UPDATE
                    name=VALUES(name), url=VALUES(url), events=VALUES(events),
                    secret=VALUES(secret), active=VALUES(active),
                    retry_count=VALUES(retry_count), retry_interval=VALUES(retry_interval),
                    timeout=VALUES(timeout),
                    last_delivery_at=VALUES(last_delivery_at),
                    last_status_code=VALUES(last_status_code),
                    total_deliveries=VALUES(total_deliveries),
                    failed_deliveries=VALUES(failed_deliveries), updated_at=VALUES(updated_at)
            """), data)
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        conn.execute("""
            INSERT OR REPLACE INTO webhook_subscriptions
            (subscription_id, name, url, events, secret, active, retry_count, retry_interval, timeout,
             last_delivery_at, last_status_code, total_deliveries, failed_deliveries, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sub.subscription_id, sub.name, sub.url, sub.events, sub.secret,
            int(sub.active), sub.retry_count, sub.retry_interval, sub.timeout,
            sub.last_delivery_at, sub.last_status_code, sub.total_deliveries,
            sub.failed_deliveries, sub.created_at, sub.updated_at,
        ))
        conn.commit()
    return sub.subscription_id


def _save_delivery(delivery: WebhookDelivery) -> str:
    from fastapi_app.db.session import open_main_db
    data = delivery.model_dump()
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    delivery_id VARCHAR(128) PRIMARY KEY,
                    subscription_id VARCHAR(128) NOT NULL,
                    event_type VARCHAR(50) NOT NULL, event_payload TEXT,
                    status VARCHAR(30) DEFAULT 'pending',
                    attempt INT DEFAULT 0, max_attempts INT DEFAULT 3,
                    status_code INT, response_body TEXT, error_message TEXT,
                    signed TINYINT(1) DEFAULT 0, signature VARCHAR(256),
                    created_at DATETIME NOT NULL, delivered_at DATETIME,
                    INDEX idx_wh_deliv_sub (subscription_id),
                    INDEX idx_wh_deliv_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO webhook_deliveries
                (delivery_id, subscription_id, event_type, event_payload, status, attempt, max_attempts,
                 status_code, response_body, error_message, signed, signature, created_at, delivered_at)
                VALUES (:delivery_id, :subscription_id, :event_type, :event_payload, :status, :attempt,
                        :max_attempts, :status_code, :response_body, :error_message, :signed,
                        :signature, :created_at, :delivered_at)
                ON DUPLICATE KEY UPDATE
                    subscription_id=VALUES(subscription_id), event_type=VALUES(event_type),
                    event_payload=VALUES(event_payload), status=VALUES(status),
                    attempt=VALUES(attempt), max_attempts=VALUES(max_attempts),
                    status_code=VALUES(status_code), response_body=VALUES(response_body),
                    error_message=VALUES(error_message), signed=VALUES(signed),
                    signature=VALUES(signature), delivered_at=VALUES(delivered_at)
            """), data)
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        conn.execute("""
            INSERT OR REPLACE INTO webhook_deliveries
            (delivery_id, subscription_id, event_type, event_payload, status, attempt, max_attempts,
             status_code, response_body, error_message, signed, signature, created_at, delivered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            delivery.delivery_id, delivery.subscription_id, delivery.event_type,
            delivery.event_payload, delivery.status, delivery.attempt,
            delivery.max_attempts, delivery.status_code, delivery.response_body,
            delivery.error_message, int(delivery.signed), delivery.signature,
            delivery.created_at, delivery.delivered_at,
        ))
        conn.commit()
    return delivery.delivery_id


def log_incoming_event(event_type: str, source: str, payload: Dict[str, Any]) -> str:
    """记录收到的事件，支持去重"""
    from fastapi_app.db.session import open_main_db
    now = now_beijing_iso()
    dedup_key = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:32]
    log_id = f"wel_{uuid.uuid4().hex[:12]}"
    payload_str = json.dumps(payload, ensure_ascii=False)

    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            existing = conn.execute(
                text("SELECT COUNT(*) as cnt FROM webhook_events_log WHERE dedup_key = :dk"),
                {"dk": dedup_key}
            ).scalar()
            if existing and int(existing) > 0:
                logger.info(f"[Webhook] 重复事件，已跳过: {dedup_key[:8]}...")
                return ""
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS webhook_events_log (
                    id VARCHAR(128) PRIMARY KEY,
                    event_type VARCHAR(50) NOT NULL, source VARCHAR(200) DEFAULT '',
                    payload TEXT, dedup_key VARCHAR(64),
                    received_at DATETIME NOT NULL, processed TINYINT(1) DEFAULT 0,
                    INDEX idx_wh_log_dedup (dedup_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO webhook_events_log
                (id, event_type, source, payload, dedup_key, received_at, processed)
                VALUES (:id, :event_type, :source, :payload, :dedup_key, :received_at, :processed)
            """), {"id": log_id, "event_type": event_type, "source": source,
                    "payload": payload_str, "dedup_key": dedup_key,
                    "received_at": now, "processed": 0})
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM webhook_events_log WHERE dedup_key = ?", (dedup_key,))
        if c.fetchone()[0] > 0:
            logger.info(f"[Webhook] 重复事件，已跳过: {dedup_key[:8]}...")
            return ""
        conn.execute("""
            INSERT INTO webhook_events_log
            (id, event_type, source, payload, dedup_key, received_at, processed)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (log_id, event_type, source, payload_str, dedup_key, now, 0))
        conn.commit()
    return log_id


def verify_signature(secret: str, body: str, signature: str) -> bool:
    """验证 Webhook 签名"""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def generate_signature(secret: str, body: str) -> str:
    """生成 Webhook 签名"""
    if not secret:
        return ""
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def create_subscription(sub: WebhookSubscription) -> str:
    return _save_subscription(sub)


def get_subscription(sub_id: str) -> Optional[WebhookSubscription]:
    from fastapi_app.db.session import open_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(text("SELECT * FROM webhook_subscriptions WHERE subscription_id = :sid"), {"sid": sub_id}).mappings().first()
        if row: row = dict(row)
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        c.execute("SELECT * FROM webhook_subscriptions WHERE subscription_id = ?", (sub_id,))
        row = c.fetchone()
        cols = [d[0] for d in c.description]
        if row: row = dict(zip(cols, row))
    return _row_to_sub(row) if row else None


def list_subscriptions(active_only: bool = False, limit: int = 50, offset: int = 0) -> list:
    from fastapi_app.db.session import open_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        where = " WHERE active = 1" if active_only else ""
        params = {"limit": limit, "offset": offset}
        with sa_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                text(f"SELECT * FROM webhook_subscriptions{where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"), params
            ).mappings().all()]
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        if active_only:
            c.execute("SELECT * FROM webhook_subscriptions WHERE active = 1 ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
        else:
            c.execute("SELECT * FROM webhook_subscriptions ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
        rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    return [_row_to_sub(r) for r in rows]


def _row_to_sub(row: dict) -> WebhookSubscription:
    return WebhookSubscription(
        subscription_id=row["subscription_id"], name=row.get("name", "") or "",
        url=row.get("url", "") or "", events=row.get("events"),
        secret=row.get("secret", "") or "",
        active=bool(row.get("active", 1)),
        retry_count=row.get("retry_count", 3) or 3,
        retry_interval=row.get("retry_interval", 60) or 60,
        timeout=row.get("timeout", 30) or 30,
        last_delivery_at=row.get("last_delivery_at"),
        last_status_code=row.get("last_status_code"),
        total_deliveries=row.get("total_deliveries", 0) or 0,
        failed_deliveries=row.get("failed_deliveries", 0) or 0,
        created_at=row["created_at"], updated_at=row.get("updated_at", "") or "",
    )


def list_deliveries(subscription_id: Optional[str] = None, status: Optional[str] = None,
                    limit: int = 50, offset: int = 0) -> list:
    from fastapi_app.db.session import open_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        conds, params = [], {}
        if subscription_id: conds.append("subscription_id = :sid"); params["sid"] = subscription_id
        if status: conds.append("status = :st"); params["st"] = status
        where = " WHERE " + " AND ".join(conds) if conds else ""
        params["limit"], params["offset"] = limit, offset
        with sa_connection() as conn:
            rows = [dict(r) for r in conn.execute(
                text(f"SELECT * FROM webhook_deliveries{where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"), params
            ).mappings().all()]
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        conds, plist = [], []
        if subscription_id: conds.append("subscription_id = ?"); plist.append(subscription_id)
        if status: conds.append("status = ?"); plist.append(status)
        where = " WHERE " + " AND ".join(conds) if conds else ""
        plist.extend([limit, offset])
        c.execute(f"SELECT * FROM webhook_deliveries{where} ORDER BY created_at DESC LIMIT ? OFFSET ?", plist)
        rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    return [WebhookDelivery(
        delivery_id=r["delivery_id"], subscription_id=r["subscription_id"],
        event_type=r.get("event_type", "") or "", event_payload=r.get("event_payload"),
        status=r.get("status", "pending") or "pending",
        attempt=r.get("attempt", 0) or 0, max_attempts=r.get("max_attempts", 3) or 3,
        status_code=r.get("status_code"), response_body=r.get("response_body"),
        error_message=r.get("error_message"), signed=bool(r.get("signed", 0)),
        signature=r.get("signature"), created_at=r["created_at"], delivered_at=r.get("delivered_at"),
    ) for r in rows]


def delete_subscription(sub_id: str) -> bool:
    from fastapi_app.db.session import open_main_db
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            result = conn.execute(text("DELETE FROM webhook_subscriptions WHERE subscription_id = :sid"), {"sid": sub_id})
            return result.rowcount > 0
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        c.execute("DELETE FROM webhook_subscriptions WHERE subscription_id = ?", (sub_id,))
        conn.commit()
        return c.rowcount > 0


def deactivate_subscription(sub_id: str) -> bool:
    from fastapi_app.db.session import open_main_db
    now = now_beijing_iso()
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            result = conn.execute(text("UPDATE webhook_subscriptions SET active = 0, updated_at = :now WHERE subscription_id = :sid"),
                                  {"sid": sub_id, "now": now})
            return result.rowcount > 0
    else:
        conn = open_main_db()
        _ensure_tables(conn)
        c = conn.cursor()
        c.execute("UPDATE webhook_subscriptions SET active = 0, updated_at = ? WHERE subscription_id = ?", (now, sub_id))
        conn.commit()
        return c.rowcount > 0


class WebhookManager:
    """Webhook 管理器"""

    def __init__(self):
        self._http_client = None

    async def _get_client(self):
        if self._http_client is None:
            try:
                import httpx
                self._http_client = httpx.AsyncClient(timeout=30)
            except ImportError:
                return None
        return self._http_client

    async def dispatch_event(self, event_type: str, payload: Dict[str, Any]) -> List[WebhookDelivery]:
        """向所有订阅者发送事件"""
        logger.info(f"[Webhook] 分发事件: {event_type}")
        subscriptions = list_subscriptions(active_only=True)
        deliveries = []

        for sub in subscriptions:
            if sub.events:
                subscribed_events = json.loads(sub.events) if isinstance(sub.events, str) else sub.events or []
                if event_type not in subscribed_events:
                    continue

            body = json.dumps({
                "event": event_type,
                "timestamp": now_beijing_iso(),
                "data": payload,
            }, ensure_ascii=False)

            signature = generate_signature(sub.secret, body) if sub.secret else ""

            delivery = WebhookDelivery(
                subscription_id=sub.subscription_id,
                event_type=event_type,
                event_payload=body,
                status="pending",
                max_attempts=sub.retry_count,
                signed=bool(signature),
                signature=signature,
            )
            _save_delivery(delivery)
            deliveries.append(delivery)

            try:
                await self._deliver(sub, body, signature, delivery)
            except Exception as e:
                logger.warning(f"[Webhook] 投递失败: {sub.subscription_id} - {str(e)[:200]}")

        return deliveries

    async def _deliver(self, sub: WebhookSubscription, body: str, signature: str,
                       delivery: WebhookDelivery) -> None:
        client = await self._get_client()
        if client is None:
            return

        headers = {"Content-Type": "application/json"}
        if signature:
            headers["X-LaomaAI-Signature"] = signature

        try:
            response = await client.post(sub.url, content=body, headers=headers, timeout=sub.timeout)
            delivery.status = "delivered" if 200 <= response.status_code < 300 else "failed"
            delivery.status_code = response.status_code
            delivery.response_body = response.text[:1000]
            delivery.attempt = 1
            delivery.delivered_at = now_beijing_iso()

            if delivery.status == "failed":
                logger.warning(f"[Webhook] 投递失败: {sub.subscription_id} HTTP {response.status_code}")
            else:
                logger.info(f"[Webhook] 投递成功: {sub.subscription_id}")

            # 更新订阅统计
            if mysql_enabled():
                from sqlalchemy import text
                with sa_connection() as conn:
                    conn.execute(text("""
                        UPDATE webhook_subscriptions SET last_delivery_at = :now,
                        last_status_code = :code, total_deliveries = total_deliveries + 1,
                        failed_deliveries = failed_deliveries + :fail, updated_at = :now
                        WHERE subscription_id = :sid
                    """), {
                        "sid": sub.subscription_id, "now": now_beijing_iso(),
                        "code": response.status_code,
                        "fail": 0 if delivery.status == "delivered" else 1,
                    })
            else:
                from fastapi_app.db.session import open_main_db
                conn = open_main_db()
                now = now_beijing_iso()
                fail = 0 if delivery.status == "delivered" else 1
                conn.execute("""
                    UPDATE webhook_subscriptions SET last_delivery_at = ?,
                    last_status_code = ?, total_deliveries = total_deliveries + 1,
                    failed_deliveries = failed_deliveries + ?, updated_at = ?
                    WHERE subscription_id = ?
                """, (now, response.status_code, fail, now, sub.subscription_id))
                conn.commit()

        except Exception as e:
            delivery.status = "error"
            delivery.error_message = str(e)[:500]
            delivery.delivered_at = now_beijing_iso()
            logger.error(f"[Webhook] 投递异常: {sub.subscription_id} - {str(e)[:200]}")
            if mysql_enabled():
                from sqlalchemy import text
                with sa_connection() as conn:
                    conn.execute(text("""
                        UPDATE webhook_subscriptions SET last_delivery_at = :now,
                        failed_deliveries = failed_deliveries + 1, updated_at = :now
                        WHERE subscription_id = :sid
                    """), {"sid": sub.subscription_id, "now": now_beijing_iso()})
            else:
                from fastapi_app.db.session import open_main_db
                conn = open_main_db()
                conn.execute("""
                    UPDATE webhook_subscriptions SET last_delivery_at = ?,
                    failed_deliveries = failed_deliveries + 1, updated_at = ?
                    WHERE subscription_id = ?
                """, (now_beijing_iso(), now_beijing_iso(), sub.subscription_id))
                conn.commit()

        _save_delivery(delivery)

    async def retry_failed(self, subscription_id: Optional[str] = None) -> int:
        """重试失败的投递"""
        deliveries = list_deliveries(subscription_id=subscription_id, status="failed", limit=100)
        retried = 0
        for d in deliveries:
            if d.attempt >= d.max_attempts:
                continue
            sub = get_subscription(d.subscription_id)
            if not sub or not sub.active:
                continue
            body = d.event_payload or ""
            signature = generate_signature(sub.secret, body) if sub.secret else ""
            d.attempt += 1
            try:
                await self._deliver(sub, body, signature, d)
                retried += 1
            except Exception as e:
                logger.warning(f"[Webhook] 重试失败: {d.delivery_id} - {str(e)[:200]}")
        return retried

    def verify_incoming(self, secret: str, body: str, signature: str) -> bool:
        return verify_signature(secret, body, signature)


webhook_manager = WebhookManager()
