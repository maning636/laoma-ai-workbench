"""
SQLite schema bootstrap/migrations.

Goal: keep the app usable on fresh installs and older local DB files by
creating required tables and adding missing columns (best-effort).

L1-1 (2026-10-24): 收编散落在各处的 CREATE TABLE / CREATE INDEX 到本模块，
统一由 `ensure_all_tables(conn)` 一次建齐；`ensure_main_db_schema` 保留
向后兼容（内部委托给 ensure_all_tables）。真源在本模块，其他文件的
lazy CREATE 保留不动（IF NOT EXISTS 幂等无害）。

字段语义**冻结**：本模块不改任何表的字段定义，只做收编与统一执行。
两处 DDL 字段不一致时以 schema.py 现有定义为准，不一致清单写入
`.superpowers/sdd/valkyrie-gamora-big-barda/l1-1-report.md`，交给 L1-2 处理。
"""

from __future__ import annotations

import sqlite3
from typing import Dict, Iterable, Optional

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
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


def _exec(cursor: sqlite3.Cursor, sql: str) -> None:
    """执行 DDL，容忍 sqlite 里 IF NOT EXISTS 语义下的重复索引名冲突。"""
    try:
        cursor.execute(sql)
    except sqlite3.OperationalError as e:
        # 并发启动 / 多次运行：索引名已存在（罕见，因 DDL 已用 IF NOT EXISTS）
        msg = str(e).lower()
        if "already exists" in msg:
            return
        raise


# ---------------------------------------------------------------------------
# DDL 字符串：按依赖顺序排列，主表在前，FK 引用的被引用表在前。
# 真源在此；分散文件的 DDL 若字段不一致，以本模块为准（L1-2 收敛）。
# ---------------------------------------------------------------------------

# ---- 1. 主表：artifacts（统一产物总线，schema.py 原有）----
DDL_ARTIFACTS = """
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

DDL_IDX_ARTIFACTS = [
    "CREATE INDEX IF NOT EXISTS idx_artifact_stage ON artifacts(stage)",
    "CREATE INDEX IF NOT EXISTS idx_artifact_source ON artifacts(source)",
    "CREATE INDEX IF NOT EXISTS idx_artifact_ref ON artifacts(ref_type, ref_id)",
    "CREATE INDEX IF NOT EXISTS idx_artifact_parent ON artifacts(parent_id)",
    # 登记幂等：同一 (ref_type, ref_id, path) 只登记一次。
    # 唯一索引放在 dedupe_key 上而不是三列复合索引上——
    # MySQL/SQLite 的 NULL 语义差异会让复合唯一索引在 path 为空时失效。
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_artifact_dedupe ON artifacts(dedupe_key)",
]


# ---- 2. 素材：file_records（schema.py 原有；dashboard/files 两处 DDL 字段少，用此处为准）----
DDL_FILE_RECORDS = """
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


# ---- 3. 用户基础表：user_info（db/createTable.py 收编）----
DDL_USER_INFO = """
CREATE TABLE IF NOT EXISTS user_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type INTEGER NOT NULL,
    filePath TEXT NOT NULL,
    userName TEXT NOT NULL,
    status INTEGER DEFAULT 0
)
"""


# ---- 4. 发布预设：publish_presets（schema.py 原有；create_publish_presets.py 字段一致）----
DDL_PUBLISH_PRESETS = """
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


# ---- 5. 投放计划 / 任务包：plans / task_packages（schema.py 原有；create_campaign_tables.py 版本 FK 完整，此处保留 schema.py 版）----
DDL_PLANS = """
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

DDL_TASK_PACKAGES = """
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


# ---- 6. 发布任务：publish_tasks（schema.py 原有；dashboard 版本字段少）----
# Note: celery_task_id was added to the CREATE TABLE statement with UNIQUE constraint
# SQLite doesn't allow adding UNIQUE constraint via ALTER TABLE, so we only add the column if it doesn't exist
DDL_PUBLISH_TASKS = """
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


# ---- 7. 外部协作：external_users / external_accounts（db/create_campaign_tables.py 收编）----
DDL_EXTERNAL_USERS = """
CREATE TABLE IF NOT EXISTS external_users (
    external_user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    login_method TEXT,
    phone TEXT,
    wechat_openid TEXT,
    email TEXT,
    nickname TEXT,
    avatar TEXT,
    status TEXT DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

DDL_EXTERNAL_ACCOUNTS = """
CREATE TABLE IF NOT EXISTS external_accounts (
    ext_account_id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_user_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    platform_uid TEXT,
    display_name TEXT,
    status TEXT DEFAULT 'active',
    access_token TEXT,
    refresh_token TEXT,
    expire_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (external_user_id) REFERENCES external_users(external_user_id)
)
"""


# ---- 8. 发布回执：publish_receipts（prism_core/receipts.py 版本为准）----
# 漂移：db/migrate_receipts.py 用 `artifacts TEXT`，prism_core/receipts.py 用
# `artifacts_json TEXT`。schema.py 原本无此表，故采用运行时实际使用的
# prism_core/receipts.py 版本；`artifacts` 列通过 ALTER 兼容补齐（L1-2 收敛）。
DDL_PUBLISH_RECEIPTS = """
CREATE TABLE IF NOT EXISTS publish_receipts (
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
    artifacts_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

DDL_IDX_PUBLISH_RECEIPTS = [
    "CREATE INDEX IF NOT EXISTS idx_receipt_status ON publish_receipts(status)",
    "CREATE INDEX IF NOT EXISTS idx_receipt_account ON publish_receipts(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_receipt_idem ON publish_receipts(idempotency_key)",
    # 兼容 db/migrate_receipts.py 里 idx_receipt_idempotency 的命名
    "CREATE INDEX IF NOT EXISTS idx_receipt_idempotency ON publish_receipts(idempotency_key)",
]


# ---- 9. 状态机：task_states（prism_core/task_state_machine.py 版本为准，含 completed_at）----
# 漂移：db/migrate_receipts.py 无 `completed_at`、`idempotency_key` 有 DEFAULT ''；
# 采用 prism_core 版本（更完整），差异在 L1-2 收敛。
DDL_TASK_STATES = """
CREATE TABLE IF NOT EXISTS task_states (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft',
    idempotency_key TEXT NOT NULL,
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
    updated_at TEXT NOT NULL,
    completed_at TEXT
)
"""

DDL_IDX_TASK_STATES = [
    "CREATE INDEX IF NOT EXISTS idx_task_state_status ON task_states(status)",
    "CREATE INDEX IF NOT EXISTS idx_task_state_idempotency ON task_states(idempotency_key)",
    "CREATE INDEX IF NOT EXISTS idx_task_state_account ON task_states(account_id)",
    # 兼容 db/migrate_receipts.py 里的 idx_task_idem / idx_task_status
    "CREATE INDEX IF NOT EXISTS idx_task_idem ON task_states(idempotency_key)",
    "CREATE INDEX IF NOT EXISTS idx_task_status ON task_states(status)",
]


# ---- 10. 监控：monitor_events / state_transitions / account_health_snapshots / alert_webhooks ----
# 漂移说明（详见报告 l1-1-report.md）：
#   monitor_events：migrate_receipts.py 有 `message DEFAULT ''`，monitor.py 无 default；采用后者。
#   state_transitions：migrate_receipts.py 用 id INTEGER PK + triggered_by/metadata，
#     monitor.py 用 transition_id TEXT PK + account_id；主键完全不同，采用 monitor.py。
#   alert_webhooks：migrate_receipts.py 用 name PK，monitor.py 用 id INTEGER + name；
#     采用 monitor.py（更贴合 webhook.py 里的 webhook_subscriptions 模式）。
DDL_MONITOR_EVENTS = """
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
"""

DDL_STATE_TRANSITIONS = """
CREATE TABLE IF NOT EXISTS state_transitions (
    transition_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    account_id TEXT DEFAULT '',
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
)
"""

DDL_ACCOUNT_HEALTH_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS account_health_snapshots (
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
)
"""

DDL_ALERT_WEBHOOKS = """
CREATE TABLE IF NOT EXISTS alert_webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    event_types TEXT,
    created_at TEXT NOT NULL
)
"""

DDL_IDX_MONITOR = [
    "CREATE INDEX IF NOT EXISTS idx_monitor_type ON monitor_events(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_monitor_account ON monitor_events(account_id)",
    # 兼容 monitor.py 的命名
    "CREATE INDEX IF NOT EXISTS idx_monitor_events_type ON monitor_events(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_monitor_events_account ON monitor_events(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_trans_task ON state_transitions(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_state_transitions_task ON state_transitions(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_health_account ON account_health_snapshots(account_id)",
    "CREATE INDEX IF NOT EXISTS idx_health_status ON account_health_snapshots(health_status)",
]


# ---- 11. Webhook 订阅 / 投递 / 事件日志（prism_core/webhook.py 收编）----
DDL_WEBHOOK_SUBSCRIPTIONS = """
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
"""

DDL_WEBHOOK_DELIVERIES = """
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
"""

DDL_WEBHOOK_EVENTS_LOG = """
CREATE TABLE IF NOT EXISTS webhook_events_log (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    source TEXT DEFAULT '',
    payload TEXT,
    dedup_key TEXT,
    received_at TEXT NOT NULL,
    processed INTEGER DEFAULT 0
)
"""

DDL_IDX_WEBHOOK = [
    "CREATE INDEX IF NOT EXISTS idx_wh_sub_active ON webhook_subscriptions(active)",
    "CREATE INDEX IF NOT EXISTS idx_wh_deliv_sub ON webhook_deliveries(subscription_id)",
    "CREATE INDEX IF NOT EXISTS idx_wh_deliv_status ON webhook_deliveries(status)",
    "CREATE INDEX IF NOT EXISTS idx_wh_log_dedup ON webhook_events_log(dedup_key)",
]


# ---- 12. 审核队列：review_queue / review_decisions（prism_core/review_queue.py 收编）----
DDL_REVIEW_QUEUE = """
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
"""

DDL_REVIEW_DECISIONS = """
CREATE TABLE IF NOT EXISTS review_decisions (
    decision_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    reviewer TEXT,
    created_at TEXT NOT NULL
)
"""

DDL_IDX_REVIEW_QUEUE = [
    "CREATE INDEX IF NOT EXISTS idx_rq_status ON review_queue(status)",
    "CREATE INDEX IF NOT EXISTS idx_rq_priority ON review_queue(priority)",
    "CREATE INDEX IF NOT EXISTS idx_rq_campaign ON review_queue(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_rd_review ON review_decisions(review_id)",
]


# ---- 13. 内容变体：content_variants / review_records（prism_core/content_variant.py 收编）----
DDL_CONTENT_VARIANTS = """
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
"""

DDL_REVIEW_RECORDS = """
CREATE TABLE IF NOT EXISTS review_records (
    review_id TEXT PRIMARY KEY,
    variant_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    reviewer TEXT DEFAULT '',
    comment TEXT DEFAULT '',
    created_at TEXT NOT NULL
)
"""

DDL_IDX_CONTENT_VARIANT = [
    "CREATE INDEX IF NOT EXISTS idx_variant_campaign ON content_variants(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_variant_status ON content_variants(status)",
    "CREATE INDEX IF NOT EXISTS idx_review_variant ON review_records(variant_id)",
]


# ---- 14. 诊断留痕：diagnostics_artifacts（prism_core/diagnostics.py 收编）----
DDL_DIAGNOSTICS_ARTIFACTS = """
CREATE TABLE IF NOT EXISTS diagnostics_artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    platform INTEGER DEFAULT 0,
    platform_name TEXT DEFAULT '',
    screenshot_path TEXT,
    dom_path TEXT,
    url_snapshot TEXT,
    error_stack TEXT,
    log_path TEXT,
    cookie_status TEXT,
    ip_address TEXT,
    collector_version TEXT DEFAULT '1.0',
    redacted INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
)
"""

DDL_IDX_DIAGNOSTICS = [
    "CREATE INDEX IF NOT EXISTS idx_diag_task ON diagnostics_artifacts(task_id)",
]


# ---- 15. 去重：dedup_records（prism_core/dedup.py 收编）----
DDL_DEDUP_RECORDS = """
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
"""

DDL_IDX_DEDUP = [
    "CREATE INDEX IF NOT EXISTS idx_dedup_hash ON dedup_records(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_dedup_task ON dedup_records(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_dedup_level ON dedup_records(dup_level)",
]


# ---- 16. 矩阵路由：matrix_groups / matrix_assignments（prism_core/matrix_route.py 收编）----
DDL_MATRIX_GROUPS = """
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
"""

DDL_MATRIX_ASSIGNMENTS = """
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
"""

DDL_IDX_MATRIX = [
    "CREATE INDEX IF NOT EXISTS idx_ma_group ON matrix_assignments(group_id)",
    "CREATE INDEX IF NOT EXISTS idx_ma_account ON matrix_assignments(account_id)",
]


# ---- 17. 表现洞察：publish_insights（prism_core/insight.py 收编）----
DDL_PUBLISH_INSIGHTS = """
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
"""

DDL_IDX_INSIGHT = [
    "CREATE INDEX IF NOT EXISTS idx_insight_task ON publish_insights(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_insight_account ON publish_insights(account_id)",
]


# ---- 18. 聊天历史：chat_sessions / chat_messages（fastapi_app/services/chat_history.py 收编）----
DDL_CHAT_SESSIONS = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT DEFAULT 'chat',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT
)
"""

DDL_CHAT_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata TEXT,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
)
"""

DDL_IDX_CHAT = [
    "CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON chat_sessions(updated_at DESC)",
]


# ---- 19. AI 会话线程：ai_threads / ai_messages（fastapi_app/api/v1/ai/threads_router.py 收编）----
DDL_AI_THREADS = """
CREATE TABLE IF NOT EXISTS ai_threads (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'chat',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT,
    message_count INTEGER DEFAULT 0
)
"""

DDL_AI_MESSAGES = """
CREATE TABLE IF NOT EXISTS ai_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (thread_id) REFERENCES ai_threads(id) ON DELETE CASCADE
)
"""

DDL_IDX_AI_THREADS = [
    "CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON ai_messages(thread_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON ai_messages(created_at)",
]


# ---- 20. 回收站：recovery_snapshots（fastapi_app/api/v1/recovery/router.py 收编）----
DDL_RECOVERY_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS recovery_snapshots (
    recovery_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL,
    object_type TEXT NOT NULL DEFAULT 'plan',
    payload TEXT NOT NULL DEFAULT '{}',
    reason TEXT DEFAULT '',
    created_at TEXT NOT NULL
)
"""


# ---- 21. AI 服务密钥 / 供应商：ai_model_configs / model_providers（schema.py 原有）----
DDL_AI_MODEL_CONFIGS = """
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

DDL_MODEL_PROVIDERS = """
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


# ---- 22. AI 生图记录：image_generations（fusion_ai/image_gen_models.py 收编）----
DDL_IMAGE_GENERATIONS = """
CREATE TABLE IF NOT EXISTS image_generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    model_key VARCHAR(64) NOT NULL,
    prompt TEXT,
    agent_id VARCHAR(64),
    aspect_ratio VARCHAR(16),
    count INTEGER DEFAULT 1,
    images_url TEXT,
    points_cost REAL DEFAULT 0.0,
    freeze_tx_id INTEGER,
    status VARCHAR(16) DEFAULT 'pending',
    error_message TEXT,
    idempotency_key VARCHAR(64),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""

DDL_IDX_IMAGE_GEN = [
    "CREATE INDEX IF NOT EXISTS idx_image_gen_user ON image_generations(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_image_gen_created ON image_generations(created_at DESC)",
]


# ---- 23. 视频数据回收：video_analytics / analytics_history（myUtils/analytics_db.py 收编）----
# 注意：video_analytics.task_id FK 指向不存在的 `tasks` 表（FK 悬空）——
# 这是 L1-2 的任务（见 module-link-backend.md §2）。此处保留原字段不动。
DDL_VIDEO_ANALYTICS = """
CREATE TABLE IF NOT EXISTS video_analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    account_id INTEGER,
    platform VARCHAR(20) NOT NULL,
    video_id VARCHAR(100),
    video_url TEXT,
    title VARCHAR(500),
    thumbnail TEXT,
    publish_date DATE,
    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    play_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    collect_count INTEGER DEFAULT 0,
    share_count INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    match_confidence FLOAT,
    raw_data TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
)
"""

DDL_ANALYTICS_HISTORY = """
CREATE TABLE IF NOT EXISTS analytics_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_analytics_id INTEGER NOT NULL,
    play_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    collect_count INTEGER DEFAULT 0,
    share_count INTEGER DEFAULT 0,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (video_analytics_id) REFERENCES video_analytics(id)
)
"""

DDL_IDX_ANALYTICS = [
    "CREATE INDEX IF NOT EXISTS idx_video_analytics_platform ON video_analytics(platform)",
    "CREATE INDEX IF NOT EXISTS idx_video_analytics_publish_date ON video_analytics(publish_date)",
    "CREATE INDEX IF NOT EXISTS idx_analytics_history_video_id ON analytics_history(video_analytics_id)",
]


# ---------------------------------------------------------------------------
# 收编清单：ALL_EXPECTED_TABLES —— 全量预期表集合（测试契约）
# ---------------------------------------------------------------------------
ALL_EXPECTED_TABLES: tuple[str, ...] = (
    # 主表 + 素材 + 用户
    "artifacts",
    "file_records",
    "user_info",
    # 发布链
    "publish_presets",
    "publish_tasks",
    "plans",
    "task_packages",
    "external_users",
    "external_accounts",
    # 回执 / 状态机 / 监控
    "publish_receipts",
    "task_states",
    "monitor_events",
    "state_transitions",
    "account_health_snapshots",
    "alert_webhooks",
    # Webhook 订阅 / 投递
    "webhook_subscriptions",
    "webhook_deliveries",
    "webhook_events_log",
    # 审核 / 变体 / 诊断 / 去重 / 矩阵 / 洞察
    "review_queue",
    "review_decisions",
    "content_variants",
    "review_records",
    "diagnostics_artifacts",
    "dedup_records",
    "matrix_groups",
    "matrix_assignments",
    "publish_insights",
    # AI 会话
    "chat_sessions",
    "chat_messages",
    "ai_threads",
    "ai_messages",
    # 回收站
    "recovery_snapshots",
    # AI 模型 / 供应商
    "ai_model_configs",
    "model_providers",
    # AI 生图
    "image_generations",
    # 数据回收
    "video_analytics",
    "analytics_history",
)


# ---------------------------------------------------------------------------
# 按依赖顺序：先 DDL，后索引；父表在前，子表在后。
# ---------------------------------------------------------------------------
_DDL_TABLE_STATEMENTS: tuple[str, ...] = (
    DDL_ARTIFACTS,
    DDL_FILE_RECORDS,
    DDL_USER_INFO,
    DDL_PUBLISH_PRESETS,
    DDL_PLANS,
    DDL_TASK_PACKAGES,
    DDL_PUBLISH_TASKS,
    DDL_EXTERNAL_USERS,
    DDL_EXTERNAL_ACCOUNTS,
    DDL_PUBLISH_RECEIPTS,
    DDL_TASK_STATES,
    DDL_MONITOR_EVENTS,
    DDL_STATE_TRANSITIONS,
    DDL_ACCOUNT_HEALTH_SNAPSHOTS,
    DDL_ALERT_WEBHOOKS,
    DDL_WEBHOOK_SUBSCRIPTIONS,
    DDL_WEBHOOK_DELIVERIES,
    DDL_WEBHOOK_EVENTS_LOG,
    DDL_REVIEW_QUEUE,
    DDL_REVIEW_DECISIONS,
    DDL_CONTENT_VARIANTS,
    DDL_REVIEW_RECORDS,
    DDL_DIAGNOSTICS_ARTIFACTS,
    DDL_DEDUP_RECORDS,
    DDL_MATRIX_GROUPS,
    DDL_MATRIX_ASSIGNMENTS,
    DDL_PUBLISH_INSIGHTS,
    DDL_CHAT_SESSIONS,
    DDL_CHAT_MESSAGES,
    DDL_AI_THREADS,
    DDL_AI_MESSAGES,
    DDL_RECOVERY_SNAPSHOTS,
    DDL_AI_MODEL_CONFIGS,
    DDL_MODEL_PROVIDERS,
    DDL_IMAGE_GENERATIONS,
    DDL_VIDEO_ANALYTICS,
    DDL_ANALYTICS_HISTORY,
)

_DDL_INDEX_STATEMENTS: tuple[str, ...] = tuple(
    it
    for group in (
        DDL_IDX_ARTIFACTS,
        DDL_IDX_PUBLISH_RECEIPTS,
        DDL_IDX_TASK_STATES,
        DDL_IDX_MONITOR,
        DDL_IDX_WEBHOOK,
        DDL_IDX_REVIEW_QUEUE,
        DDL_IDX_CONTENT_VARIANT,
        DDL_IDX_DIAGNOSTICS,
        DDL_IDX_DEDUP,
        DDL_IDX_MATRIX,
        DDL_IDX_INSIGHT,
        DDL_IDX_CHAT,
        DDL_IDX_AI_THREADS,
        DDL_IDX_IMAGE_GEN,
        DDL_IDX_ANALYTICS,
    )
    for it in group
)


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
      - dedupe_key：登记幂等键 = hash(ref_type|ref_id|path），
        一次生图 count>1 会产生多张图共享同一 record_id，靠 path 区分。

    本函数是 DDL 的**唯一真源**：`prism_core/artifacts.py` 只做 CRUD，
    不再自己 CREATE TABLE，避免两处漂移。
    """
    _exec(conn.cursor(), DDL_ARTIFACTS)
    for sql in DDL_IDX_ARTIFACTS:
        _exec(conn.cursor(), sql)
    conn.commit()


def _ensure_legacy_column_migrations(conn: sqlite3.Connection) -> int:
    """对已存在的旧库补齐缺失列（ALTER TABLE ADD COLUMN 集合）。

    与 create-table 阶段解耦：老库跑过一次之后，后续 ALTER 全是 no-op。
    """
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

    # publish_receipts：db/migrate_receipts.py 用 `artifacts`，prism_core/receipts.py 用
    # `artifacts_json`。schema.py 以 prism_core 为准，同时补 `artifacts` 列以保持旧代码可读。
    publish_receipts_required: Dict[str, str] = {
        "artifacts": "ALTER TABLE publish_receipts ADD COLUMN artifacts TEXT",
    }

    # publish_tasks.schedule_time 在 dashboard/router.py 里叫 TEXT，schema.py 叫 DATETIME——
    # ALTER 阶段无法改类型，此处只做存在性检查，不动。

    added = 0
    added += _ensure_columns(conn, "file_records", file_records_required)
    added += _ensure_columns(conn, "publish_presets", publish_presets_required)
    added += _ensure_columns(conn, "publish_tasks", publish_tasks_required)
    added += _ensure_columns(conn, "publish_receipts", publish_receipts_required)
    return added


def ensure_all_tables(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
    _commit: bool = True,
) -> None:
    """
    统一 bootstrap：按依赖顺序创建全部预期表 + 索引，并补齐旧库缺失列。

    参数：
      conn     —— 传入已打开的 sqlite3.Connection 则用之（不再 close）；
      db_path  —— 未传 conn 时使用，从该路径新建连接（用完关闭）；
                   两者都缺省时回落到 settings.DATABASE_PATH；
      _commit  —— 是否 commit（默认 True；测试里已手动 commit 时可关）。

    幂等：所有 DDL 都是 CREATE ... IF NOT EXISTS；索引 IF NOT EXISTS；
          ALTER 只补缺失列。重复调用无副作用。

    顺序：主表在前、FK 引用的被引用表在前；索引在所属表之后。
    """
    owns_conn = False
    if conn is None:
        target_path = db_path or settings.DATABASE_PATH
        conn = sqlite3.connect(target_path)
        owns_conn = True
    try:
        cursor = conn.cursor()

        # 1) 全量表 DDL（按依赖顺序）
        for sql in _DDL_TABLE_STATEMENTS:
            _exec(cursor, sql)

        # 2) 全量索引（每张表的索引紧跟其 DDL，避免顺序误）
        for sql in _DDL_INDEX_STATEMENTS:
            _exec(cursor, sql)

        if _commit:
            conn.commit()

        # 3) 旧库列补齐（ALTER TABLE ADD COLUMN）
        added = _ensure_legacy_column_migrations(conn)
        if added:
            conn.commit()
            logger.info(f"[DB] Schema bootstrap; added {added} missing column(s)")
    finally:
        if owns_conn:
            conn.close()


def ensure_main_db_schema(conn: sqlite3.Connection) -> None:
    """
    Ensure required tables/columns exist in settings.DATABASE_PATH.

    向后兼容入口。L1-1 起内部委托给 `ensure_all_tables`，不再自己维护
    DDL 字符串集合。所有 DDL 真源在模块级 `_DDL_TABLE_STATEMENTS`。
    """
    ensure_all_tables(conn=conn)


def ensure_default_schema() -> None:
    """
    Convenience entrypoint using settings.DATABASE_PATH.
    """
    ensure_all_tables(db_path=settings.DATABASE_PATH)
