"""
SQLite schema bootstrap/migrations.

Goal: keep the app usable on fresh installs and older local DB files by
creating required tables and adding missing columns (best-effort).
"""

from __future__ import annotations

import sqlite3
from typing import Dict, Iterable

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger


def _existing_columns(cursor: sqlite3.Cursor, table: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_columns(
    conn: sqlite3.Connection,
    table: str,
    required: Dict[str, str],
) -> int:
    """
    Ensure columns exist on a given table using ALTER TABLE ADD COLUMN.
    Returns number of columns added.
    """
    cursor = conn.cursor()
    existing = _existing_columns(cursor, table)
    added = 0
    for column_name, alter_sql in required.items():
        if column_name in existing:
            continue
        try:
            cursor.execute(alter_sql)
            added += 1
        except sqlite3.OperationalError as e:
            # Concurrent startup / multiple workers may race to add columns.
            if "duplicate column name" in str(e).lower():
                continue
            raise
    return added


def ensure_artifacts_table(conn: sqlite3.Connection) -> None:
    """
    建「统一产物总线」主表 `artifacts`（唯一真源）。

    背景：项目里原本有四套互不相通的 ID 空间——
      image_generations.id（生图）、file_records.id（素材）、
      review_queue.review_id（审核）、publish_tasks.task_id（发布），
    导致「上一步的产出接不到下一步的调用」。本表把四者统一到
    一个 `artifact_id`（art_ + 12 位十六进制）之下：

      - stage：产物在流水线上的阶段（generated/uploaded/reviewing/
        approved/rejected/published），是「功能之间串联」的状态载体；
      - ref_type + ref_id：回指本域记录（哪张生图记录、哪个素材、
        哪个审核项、哪个发布任务），保证旧数据仍可反查；
      - parent_id：血缘（父产物 → 子产物），支撑「一稿多版」；
      - dedupe_key：登记幂等键 = hash(ref_type|ref_id|path)，
        一次生图 count>1 会产生多张图共享同一 record_id，靠 path 区分。

    本函数是 DDL 的**唯一真源**：`prism_core/artifacts.py` 只做 CRUD，
    不再自己 CREATE TABLE，避免两处漂移。
    """
    conn.cursor().execute(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            stage TEXT NOT NULL DEFAULT 'generated',
            kind TEXT NOT NULL DEFAULT 'image',
            title TEXT DEFAULT '',
            path TEXT DEFAULT '',
            thumb TEXT DEFAULT '',
            media_type TEXT DEFAULT '',
            source TEXT DEFAULT '',
            ref_type TEXT DEFAULT '',
            ref_id TEXT DEFAULT '',
            parent_id TEXT,
            campaign_id TEXT DEFAULT '',
            platform TEXT DEFAULT '',
            review_id TEXT DEFAULT '',
            publish_task_id TEXT DEFAULT '',
            dedupe_key TEXT,
            meta TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.cursor().execute(
        "CREATE INDEX IF NOT EXISTS idx_artifact_stage ON artifacts(stage)"
    )
    conn.cursor().execute(
        "CREATE INDEX IF NOT EXISTS idx_artifact_source ON artifacts(source)"
    )
    conn.cursor().execute(
        "CREATE INDEX IF NOT EXISTS idx_artifact_ref ON artifacts(ref_type, ref_id)"
    )
    conn.cursor().execute(
        "CREATE INDEX IF NOT EXISTS idx_artifact_parent ON artifacts(parent_id)"
    )
    # 登记幂等：同一 (ref_type, ref_id, path) 只登记一次。
    # 唯一索引放在 dedupe_key 上而不是三列复合索引上——
    # MySQL/SQLite 的 NULL 语义差异会让复合唯一索引在 path 为空时失效。
    conn.cursor().execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_artifact_dedupe ON artifacts(dedupe_key)"
    )
    conn.commit()


def ensure_main_db_schema(conn: sqlite3.Connection) -> None:
    """
    Ensure required tables/columns exist in settings.DATABASE_PATH.
    """
    cursor = conn.cursor()

    # --- file_records (materials) ---
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS file_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            filesize REAL,
            file_path TEXT,
            upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending',
            published_at DATETIME,
            last_platform INTEGER,
            last_accounts TEXT,
            note TEXT,
            group_name TEXT,
            title TEXT,
            description TEXT,
            tags TEXT,
            cover_image TEXT,
            duration REAL,
            ai_title TEXT,
            ai_description TEXT,
            ai_tags TEXT,
            ai_generated_at TIMESTAMP
        )
        """
    )

    file_records_required: Dict[str, str] = {
        "filename": "ALTER TABLE file_records ADD COLUMN filename TEXT",
        "filesize": "ALTER TABLE file_records ADD COLUMN filesize REAL",
        "file_path": "ALTER TABLE file_records ADD COLUMN file_path TEXT",
        "upload_time": "ALTER TABLE file_records ADD COLUMN upload_time DATETIME",
        "status": "ALTER TABLE file_records ADD COLUMN status TEXT DEFAULT 'pending'",
        "published_at": "ALTER TABLE file_records ADD COLUMN published_at DATETIME",
        "last_platform": "ALTER TABLE file_records ADD COLUMN last_platform INTEGER",
        "last_accounts": "ALTER TABLE file_records ADD COLUMN last_accounts TEXT",
        "note": "ALTER TABLE file_records ADD COLUMN note TEXT",
        "group_name": "ALTER TABLE file_records ADD COLUMN group_name TEXT",
        "title": "ALTER TABLE file_records ADD COLUMN title TEXT",
        "description": "ALTER TABLE file_records ADD COLUMN description TEXT",
        "tags": "ALTER TABLE file_records ADD COLUMN tags TEXT",
        "cover_image": "ALTER TABLE file_records ADD COLUMN cover_image TEXT",
        "duration": "ALTER TABLE file_records ADD COLUMN duration REAL",
        "ai_title": "ALTER TABLE file_records ADD COLUMN ai_title TEXT",
        "ai_description": "ALTER TABLE file_records ADD COLUMN ai_description TEXT",
        "ai_tags": "ALTER TABLE file_records ADD COLUMN ai_tags TEXT",
        "ai_generated_at": "ALTER TABLE file_records ADD COLUMN ai_generated_at TIMESTAMP",
    }

    # --- publish_presets ---
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS publish_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            platform TEXT NOT NULL,
            accounts TEXT NOT NULL,
            material_ids TEXT,
            title TEXT,
            description TEXT,
            schedule_enabled INTEGER DEFAULT 0,
            videos_per_day INTEGER DEFAULT 1,
            schedule_date TEXT,
            time_point TEXT DEFAULT '10:00',
            usage_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    publish_presets_required: Dict[str, str] = {
        "usage_count": "ALTER TABLE publish_presets ADD COLUMN usage_count INTEGER DEFAULT 0",
    }

    # Note: celery_task_id was added to the CREATE TABLE statement with UNIQUE constraint
    # SQLite doesn't allow adding UNIQUE constraint via ALTER TABLE, so we only add the column if it doesn't exist
    publish_tasks_required: Dict[str, str] = {
        "celery_task_id": "ALTER TABLE publish_tasks ADD COLUMN celery_task_id TEXT",
        "completed_at": "ALTER TABLE publish_tasks ADD COLUMN completed_at DATETIME",
        "task_data": "ALTER TABLE publish_tasks ADD COLUMN task_data TEXT",  # 完整的任务数据（JSON）
        "priority": "ALTER TABLE publish_tasks ADD COLUMN priority INTEGER DEFAULT 5",
        # 统一产物总线：发布任务指回它的来源产物（art_xxx），
        # 让「生成 → 审核 → 发布」三段在数据层连成一条线。
        "artifact_id": "ALTER TABLE publish_tasks ADD COLUMN artifact_id TEXT",
    }

    # --- publish_tasks ---
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS publish_tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            celery_task_id TEXT UNIQUE,
            plan_id INTEGER,
            package_id INTEGER,
            platform TEXT,
            account_id TEXT,
            material_id TEXT,
            title TEXT,
            tags TEXT,
            cover TEXT,
            schedule_time DATETIME,
            publish_mode TEXT DEFAULT 'auto',
            status TEXT DEFAULT 'pending',
            external_user_id TEXT,
            external_account_id TEXT,
            result_metrics TEXT,
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            published_at DATETIME,
            completed_at DATETIME
        )
        """
    )

    # --- plans（投放计划，旧版 plans API 使用） ---
    # 矩阵发布「存草稿」与任务包构建器都要往这里写；
    # 历史实现只在 db/create_campaign_tables.py 里建过，主库从未执行，
    # 导致 /api/v1/plans 建计划静默失败（no such table: plans）。
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            platforms TEXT,
            start_date TEXT,
            end_date TEXT,
            goal_type TEXT DEFAULT 'other',
            remark TEXT,
            status TEXT DEFAULT 'draft',
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # --- task_packages（任务包 / 波次） ---
    # plan_id 兼容两种来源：
    #   1) 旧 plans API 写入的整数 plan_id；
    #   2) 营销活动（campaigns）写入的 UUID —— SQLite INTEGER 亲和列遇到
    #      非数字文本会按 TEXT 存储，因此同一个字段可以同时容纳两者。
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS task_packages (
            package_id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER,
            name TEXT NOT NULL,
            platform TEXT NOT NULL,
            account_ids_scope TEXT,
            material_ids_scope TEXT,
            dispatch_mode TEXT DEFAULT 'random',
            time_strategy TEXT,
            generated_task_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'draft',
            created_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # --- ai_model_configs ---
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_model_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_type TEXT NOT NULL UNIQUE,
            provider TEXT NOT NULL,
            api_key TEXT NOT NULL,
            base_url TEXT,
            model_name TEXT,
            extra_config TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # --- model_providers（模型供应商注册表） ---
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS model_providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            base_url TEXT,
            api_key TEXT,
            enabled INTEGER DEFAULT 1,
            remark TEXT,
            available_models TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()

    # --- artifacts（统一产物总线） ---
    ensure_artifacts_table(conn)

    added = 0
    added += _ensure_columns(conn, "file_records", file_records_required)
    added += _ensure_columns(conn, "publish_presets", publish_presets_required)
    added += _ensure_columns(conn, "publish_tasks", publish_tasks_required)  # 添加celery_task_id字段迁移

    if added:
        conn.commit()
        logger.info(f"[DB] Schema ensured; added {added} missing column(s)")


def ensure_default_schema() -> None:
    """
    Convenience entrypoint using settings.DATABASE_PATH.
    """
    conn = sqlite3.connect(settings.DATABASE_PATH)
    try:
        ensure_main_db_schema(conn)
    finally:
        conn.close()

