"""
Phase 0 数据库迁移脚本

为 SQLite 和 MySQL 创建所有 Phase 0 新增表：
- publish_receipts
- task_states
- monitor_events
- state_transitions
- account_health_snapshots
- alert_webhooks
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.db.runtime import mysql_enabled, sa_connection
from fastapi_app.db.session import get_main_db


def migrate_sqlite() -> None:
    conn = get_main_db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS publish_receipts (
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
        artifacts TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_receipt_status ON publish_receipts(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_receipt_account ON publish_receipts(account_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_receipt_idem ON publish_receipts(idempotency_key)")

    c.execute("""CREATE TABLE IF NOT EXISTS task_states (
        task_id TEXT PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'draft',
        idempotency_key TEXT NOT NULL DEFAULT '',
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
        updated_at TEXT NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_task_idem ON task_states(idempotency_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_task_status ON task_states(status)")

    c.execute("""CREATE TABLE IF NOT EXISTS monitor_events (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        severity TEXT DEFAULT 'info',
        task_id TEXT,
        receipt_task_id TEXT,
        account_id TEXT,
        platform INTEGER DEFAULT 0,
        platform_name TEXT DEFAULT '',
        message TEXT DEFAULT '',
        metadata TEXT,
        created_at TEXT NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_monitor_type ON monitor_events(event_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_monitor_account ON monitor_events(account_id)")

    c.execute("""CREATE TABLE IF NOT EXISTS state_transitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        from_status TEXT,
        to_status TEXT NOT NULL,
        reason TEXT DEFAULT '',
        triggered_by TEXT DEFAULT 'system',
        metadata TEXT,
        created_at TEXT NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_trans_task ON state_transitions(task_id)")

    c.execute("""CREATE TABLE IF NOT EXISTS account_health_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        platform INTEGER DEFAULT 0,
        platform_name TEXT DEFAULT '',
        health_status TEXT DEFAULT 'healthy',
        total_publishes INTEGER DEFAULT 0,
        success_count INTEGER DEFAULT 0,
        failure_count INTEGER DEFAULT 0,
        success_rate REAL DEFAULT 0.0,
        last_success_at TEXT,
        last_failure_at TEXT,
        last_error_code TEXT,
        last_error_message TEXT,
        consecutive_failures INTEGER DEFAULT 0,
        cooldown_until TEXT,
        probe_status TEXT,
        probe_checked_at TEXT,
        created_at TEXT NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_health_account ON account_health_snapshots(account_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_health_status ON account_health_snapshots(health_status)")

    c.execute("""CREATE TABLE IF NOT EXISTS alert_webhooks (
        name TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        event_types TEXT,
        enabled INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )""")

    conn.commit()
    conn.close()
    logger.info("[Migration] SQLite tables created/verified")


def migrate_mysql() -> None:
    from sqlalchemy import text
    with sa_connection() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS publish_receipts (
            task_id VARCHAR(128) PRIMARY KEY,
            status VARCHAR(30) NOT NULL DEFAULT 'running',
            platform INT DEFAULT 0,
            platform_name VARCHAR(50) DEFAULT '',
            account_id VARCHAR(200) DEFAULT '',
            platform_post_id VARCHAR(256),
            published_at DATETIME,
            video_url TEXT,
            error_code VARCHAR(50),
            error_message TEXT,
            retryable TINYINT DEFAULT 0,
            requires_human_action TINYINT DEFAULT 0,
            attempt INT DEFAULT 1,
            idempotency_key VARCHAR(256),
            artifacts TEXT,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            INDEX idx_receipt_status (status),
            INDEX idx_receipt_account (account_id),
            INDEX idx_receipt_idem (idempotency_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))

        conn.execute(text("""CREATE TABLE IF NOT EXISTS task_states (
            task_id VARCHAR(128) PRIMARY KEY,
            status VARCHAR(30) NOT NULL DEFAULT 'draft',
            idempotency_key VARCHAR(256) NOT NULL DEFAULT '',
            platform INT DEFAULT 0,
            platform_name VARCHAR(50) DEFAULT '',
            account_id VARCHAR(200) DEFAULT '',
            campaign_id VARCHAR(128),
            variant_id VARCHAR(128),
            video_id VARCHAR(128),
            material_id VARCHAR(128),
            attempt INT DEFAULT 1,
            max_attempts INT DEFAULT 3,
            receipt_task_id VARCHAR(128),
            metadata TEXT,
            error_message TEXT,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            INDEX idx_task_idem (idempotency_key),
            INDEX idx_task_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))

        conn.execute(text("""CREATE TABLE IF NOT EXISTS monitor_events (
            event_id VARCHAR(128) PRIMARY KEY,
            event_type VARCHAR(50) NOT NULL,
            severity VARCHAR(20) DEFAULT 'info',
            task_id VARCHAR(128),
            receipt_task_id VARCHAR(128),
            account_id VARCHAR(200),
            platform INT DEFAULT 0,
            platform_name VARCHAR(50) DEFAULT '',
            message TEXT DEFAULT '',
            metadata TEXT,
            created_at DATETIME NOT NULL,
            INDEX idx_monitor_type (event_type),
            INDEX idx_monitor_account (account_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))

        conn.execute(text("""CREATE TABLE IF NOT EXISTS state_transitions (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            task_id VARCHAR(128) NOT NULL,
            from_status VARCHAR(30),
            to_status VARCHAR(30) NOT NULL,
            reason TEXT DEFAULT '',
            triggered_by VARCHAR(50) DEFAULT 'system',
            metadata TEXT,
            created_at DATETIME NOT NULL,
            INDEX idx_trans_task (task_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))

        conn.execute(text("""CREATE TABLE IF NOT EXISTS account_health_snapshots (
            snapshot_id VARCHAR(128) PRIMARY KEY,
            account_id VARCHAR(200) NOT NULL,
            platform INT DEFAULT 0,
            platform_name VARCHAR(50) DEFAULT '',
            health_status VARCHAR(20) DEFAULT 'healthy',
            total_publishes INT DEFAULT 0,
            success_count INT DEFAULT 0,
            failure_count INT DEFAULT 0,
            success_rate REAL DEFAULT 0.0,
            last_success_at DATETIME,
            last_failure_at DATETIME,
            last_error_code VARCHAR(50),
            last_error_message TEXT,
            consecutive_failures INT DEFAULT 0,
            cooldown_until DATETIME,
            probe_status VARCHAR(20),
            probe_checked_at DATETIME,
            created_at DATETIME NOT NULL,
            INDEX idx_health_account (account_id),
            INDEX idx_health_status (health_status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))

        conn.execute(text("""CREATE TABLE IF NOT EXISTS alert_webhooks (
            name VARCHAR(100) PRIMARY KEY,
            url TEXT NOT NULL,
            event_types TEXT,
            enabled TINYINT DEFAULT 1,
            created_at DATETIME NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))


def run_migration() -> None:
    if mysql_enabled():
        logger.info("[Migration] MySQL mode")
        migrate_mysql()
    else:
        logger.info("[Migration] SQLite mode")
        migrate_sqlite()
    logger.info("[Migration] All Phase 0 tables ready")


if __name__ == "__main__":
    run_migration()
