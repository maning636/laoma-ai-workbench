"""
Phase 0 数据库迁移脚本

为 SQLite 和 MySQL 创建所有 Phase 0 新增表：
- publish_receipts
- task_states
- monitor_events
- state_transitions
- account_health_snapshots
- alert_webhooks

L1-2 收敛（2026-10-24）：所有 DDL 常量改从 `fastapi_app.db.schema` 导入，
本文件不再维护自己的 CREATE TABLE 字符串，避免与 schema.py 二次漂移。
schema.py 是当前唯一真源；本文件只做"运行 migrate 脚本"的入口。

裁决理由（对齐 l1-2-report.md §"漂移裁决表"）：
  publish_receipts: 保 schema.py 的 `artifacts_json`（运行时实际使用）
  task_states: 保 schema.py 含 completed_at 版本（更完整）
  monitor_events: 保 schema.py `message TEXT` 无默认（sqlite 里 NULL 语义正确）
  state_transitions: 保 schema.py 的 `transition_id TEXT PK`（monitor.py 版本）
  alert_webhooks: 保 schema.py 的 `id + name` 双列（webhook.py 模式统一）
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.db.runtime import mysql_enabled, sa_connection
from fastapi_app.db.session import open_main_db
from fastapi_app.db.schema import (
    DDL_PUBLISH_RECEIPTS,
    DDL_TASK_STATES,
    DDL_MONITOR_EVENTS,
    DDL_STATE_TRANSITIONS,
    DDL_ACCOUNT_HEALTH_SNAPSHOTS,
    DDL_ALERT_WEBHOOKS,
    DDL_IDX_PUBLISH_RECEIPTS,
    DDL_IDX_TASK_STATES,
    DDL_IDX_MONITOR,
)


def migrate_sqlite() -> None:
    conn = open_main_db()
    c = conn.cursor()

    # L1-2: 全部 DDL 从 schema.py 导入（唯一真源）
    for sql in (
        DDL_PUBLISH_RECEIPTS,
        DDL_TASK_STATES,
        DDL_MONITOR_EVENTS,
        DDL_STATE_TRANSITIONS,
        DDL_ACCOUNT_HEALTH_SNAPSHOTS,
        DDL_ALERT_WEBHOOKS,
    ):
        c.execute(sql)

    for sql in (
        *DDL_IDX_PUBLISH_RECEIPTS,
        *DDL_IDX_TASK_STATES,
        *DDL_IDX_MONITOR,
    ):
        c.execute(sql)

    conn.commit()
    conn.close()
    logger.info("[Migration] SQLite tables created/verified")


def migrate_mysql() -> None:
    # MySQL DDL 保留在本文件（MySQL 不走 schema.py 的 sqlite-only DDL）；
    # 字段结构与 schema.py 保持一致（L1-2 裁决见文件顶部注释）。
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
            artifacts_json JSON,
            task_ref VARCHAR(128),
            material_id VARCHAR(128),
            artifact_id VARCHAR(64),
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            INDEX idx_receipt_status (status),
            INDEX idx_receipt_account (account_id),
            INDEX idx_receipt_idem (idempotency_key),
            INDEX idx_receipt_task_ref (task_ref),
            INDEX idx_receipt_material (material_id),
            INDEX idx_receipt_artifact (artifact_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))

        conn.execute(text("""CREATE TABLE IF NOT EXISTS task_states (
            task_id VARCHAR(128) PRIMARY KEY,
            status VARCHAR(30) NOT NULL DEFAULT 'draft',
            idempotency_key VARCHAR(256) NOT NULL,
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
            completed_at DATETIME,
            INDEX idx_task_state_status (status),
            INDEX idx_task_state_idempotency (idempotency_key),
            INDEX idx_task_state_account (account_id)
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
            message TEXT,
            metadata TEXT,
            created_at DATETIME NOT NULL,
            INDEX idx_monitor_type (event_type),
            INDEX idx_monitor_account (account_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""))

        conn.execute(text("""CREATE TABLE IF NOT EXISTS state_transitions (
            transition_id VARCHAR(128) PRIMARY KEY,
            task_id VARCHAR(128) NOT NULL,
            account_id VARCHAR(200) DEFAULT '',
            from_status VARCHAR(30) NOT NULL,
            to_status VARCHAR(30) NOT NULL,
            reason TEXT,
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
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
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
