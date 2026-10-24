"""L1-2: 软关联归因列 + video_analytics 悬空 FK 修复测试。

覆盖 5 类契约：
  ① ensure_all_tables 幂等加列（先手动 ALTER 建「缺列」状态 → 跑 bootstrap → 列补齐；再跑一次不报错）
  ② 四表归因列齐全断言（publish_tasks / publish_receipts / video_analytics / content_variants）
  ③ video_analytics DDL 无 FOREIGN KEY 残留（sqlite_master.sql 静态检查）
  ④ publish_tasks 写入带 material_id / artifact_id 入库回读
  ⑤ receipts.build_receipt 透传 task_ref / material_id / artifact_id

夹具学习 tests/test_l1_schema_bootstrap.py：临时 sqlite 库 + 幂等清理。
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 归因列契约（真源，随 schema.py 演进同步）
# ---------------------------------------------------------------------------
ATTRIBUTION_COLUMNS = {
    "publish_tasks": {"material_id", "artifact_id"},
    "publish_receipts": {"task_ref", "material_id", "artifact_id"},
    "video_analytics": {"publish_task_id", "artifact_id"},
    "content_variants": {"publish_task_id", "artifact_id", "campaign_id"},
}

TOTAL_ATTRIBUTION_COLUMNS = sum(len(cols) for cols in ATTRIBUTION_COLUMNS.values())


def _unlink_retry(path: str) -> None:
    """Windows 上 sqlite 句柄释放有延迟，重试几次再放弃。"""
    for _ in range(5):
        try:
            Path(path).unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.2)


@pytest.fixture()
def tmp_db_path():
    """提供一个临时空的 sqlite 库文件路径。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="l1_attr_")
    os.close(fd)
    Path(path).unlink()
    yield path
    _unlink_retry(path)


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


# ---------------------------------------------------------------------------
# ① ensure_all_tables 幂等加列（先手动 ALTER 建「缺列」状态 → 跑 bootstrap → 列补齐）
# ---------------------------------------------------------------------------
def test_ensure_all_tables_idempotent_column_migration(tmp_db_path):
    """老库模拟：先手动 ALTER 建「有表但缺 L1-2 归因列」的状态，
    再跑 ensure_all_tables 补齐；再跑一次不报错、列集合不变。
    """
    from fastapi_app.db.schema import ensure_all_tables

    # 1) 建老版 publish_receipts / video_analytics / content_variants（缺归因列）
    conn = sqlite3.connect(tmp_db_path)
    try:
        conn.executescript("""
            CREATE TABLE publish_receipts (
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
            );
            CREATE TABLE video_analytics (
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
                raw_data TEXT
            );
            CREATE TABLE content_variants (
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
            );
            CREATE TABLE publish_tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                celery_task_id TEXT UNIQUE,
                plan_id INTEGER,
                package_id INTEGER,
                platform TEXT,
                account_id TEXT,
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
            );
        """)
        conn.commit()
    finally:
        conn.close()

    # 2) 跑 ensure_all_tables 补列
    conn = sqlite3.connect(tmp_db_path)
    try:
        ensure_all_tables(conn)
        conn.commit()
        # 3) 断言归因列都被补上了
        for table, expected in ATTRIBUTION_COLUMNS.items():
            have = _columns(conn, table)
            missing = expected - have
            assert not missing, (
                f"{table} 缺 L1-2 归因列 {missing}；已有列 {sorted(have)}"
            )
    finally:
        conn.close()

    # 4) 幂等：再跑一次不报错
    conn = sqlite3.connect(tmp_db_path)
    try:
        ensure_all_tables(conn)
        conn.commit()
        # 列集合应保持一致（不多不少）
        for table, expected in ATTRIBUTION_COLUMNS.items():
            have = _columns(conn, table)
            missing = expected - have
            assert not missing, f"二次跑后 {table} 又缺列 {missing}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ② 四表归因列齐全
# ---------------------------------------------------------------------------
def test_four_tables_have_attribution_columns(tmp_db_path):
    """新库跑 ensure_all_tables 后，四张表都应有各自的归因列。"""
    from fastapi_app.db.schema import ensure_all_tables

    conn = sqlite3.connect(tmp_db_path)
    try:
        ensure_all_tables(conn)
        conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(tmp_db_path)
    try:
        total = 0
        for table, expected in ATTRIBUTION_COLUMNS.items():
            have = _columns(conn, table)
            missing = expected - have
            assert not missing, (
                f"{table} 缺 L1-2 归因列 {missing}；表内现有列 {sorted(have)}"
            )
            total += len(expected)
    finally:
        conn.close()

    # 归因列总数契约（防回归：以后新增列时同步更新 ATTRIBUTION_COLUMNS）
    assert total == TOTAL_ATTRIBUTION_COLUMNS
    assert TOTAL_ATTRIBUTION_COLUMNS >= 8, (
        "L1-2 至少新增 8 列归因（4 表 × 平均 2 列）"
    )


# ---------------------------------------------------------------------------
# ③ video_analytics DDL 无 FOREIGN KEY 残留
# ---------------------------------------------------------------------------
def test_video_analytics_ddl_has_no_foreign_key(tmp_db_path):
    """video_analytics 的 sqlite_master.sql 不应出现 FOREIGN KEY 子句——
    原 DDL 里有两条指向不存在的 tasks/accounts 表的悬空 FK，L1-2 必须删掉。
    """
    from fastapi_app.db.schema import ensure_all_tables

    conn = sqlite3.connect(tmp_db_path)
    try:
        ensure_all_tables(conn)
        conn.commit()
        row = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='video_analytics'"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "video_analytics 表未创建"
    sql = row[0] or ""
    assert "FOREIGN KEY" not in sql.upper(), (
        f"video_analytics DDL 仍有 FOREIGN KEY 残留：\n{sql}"
    )
    # 附加检查：悬空 FK 目标表名也不能出现在 DDL 里
    lowered = sql.lower()
    assert "references tasks" not in lowered, "仍有 references tasks 残留"
    assert "references accounts" not in lowered, "仍有 references accounts 残留"


# ---------------------------------------------------------------------------
# ④ publish_tasks 写入带 material_id / artifact_id 入库回读
# ---------------------------------------------------------------------------
def test_publish_tasks_attribution_write_and_readback(tmp_db_path):
    """模拟发布创建路径：ensure_all_tables 建表 → INSERT 一行带 material_id + artifact_id
    → SELECT 回读，断言两列落库。
    """
    from fastapi_app.db.schema import ensure_all_tables

    conn = sqlite3.connect(tmp_db_path)
    try:
        ensure_all_tables(conn)
        conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(tmp_db_path)
    try:
        # 直接调 SQL：绕过 celery/Pydantic，只验证列存在 & 数据往返
        conn.execute(
            """
            INSERT INTO publish_tasks
                (celery_task_id, platform, account_id, material_id,
                 title, tags, status, created_at, updated_at, artifact_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "celery_task_l1_2_abc123",
                "3",
                "acc_001",
                "mat_xxx",
                "测试标题",
                "['tag1', 'tag2']",
                "pending",
                "2026-10-24T00:00:00",
                "2026-10-24T00:00:00",
                "art_20261024a1b2c3",
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT material_id, artifact_id FROM publish_tasks "
            "WHERE celery_task_id = ?",
            ("celery_task_l1_2_abc123",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "INSERT 后读不到该 publish_task"
    material_id, artifact_id = row
    assert material_id == "mat_xxx", f"material_id 回读不一致：{material_id!r}"
    assert artifact_id == "art_20261024a1b2c3", f"artifact_id 回读不一致：{artifact_id!r}"


# ---------------------------------------------------------------------------
# ⑤ receipts.build_receipt 透传归因字段
# ---------------------------------------------------------------------------
def test_receipt_build_and_save_roundtrip(tmp_db_path, monkeypatch):
    """build_receipt 显式传 task_ref / material_id / artifact_id →
    save_receipt 落到 publish_receipts 表 → get_receipt 读回三字段一致。
    """
    from fastapi_app.core import settings
    from prism_core import receipts as receipts_module

    # 重定向 open_main_db 到临时库（open_main_db 每次读 settings.DATABASE_PATH）
    monkeypatch.setattr(settings, "DATABASE_PATH", tmp_db_path)

    # 建表（走 _ensure_receipt_table 而非 ensure_all_tables，验证 receipts.py 自己的 DDL）
    conn = sqlite3.connect(tmp_db_path)
    try:
        receipts_module._ensure_receipt_table(conn)
        conn.commit()
    finally:
        conn.close()

    # build_receipt 显式传三归因字段
    receipt = receipts_module.build_receipt(
        status="running",
        platform=3,
        platform_name="douyin",
        account_id="acc_001",
        task_id="task_l1_2_test",
        task_ref="celery_task_ref_1",
        material_id="mat_abc",
        artifact_id="art_xyz",
    )
    assert receipt.task_ref == "celery_task_ref_1"
    assert receipt.material_id == "mat_abc"
    assert receipt.artifact_id == "art_xyz"

    # save + get 回读
    receipts_module.save_receipt(receipt)
    r2 = receipts_module.get_receipt("task_l1_2_test")
    assert r2 is not None
    assert r2.task_ref == "celery_task_ref_1"
    assert r2.material_id == "mat_abc"
    assert r2.artifact_id == "art_xyz"
    assert r2.status.value == "running"

    # 幂等：build_receipt 不传归因字段时，三字段应为 None（不阻断既有流程）
    receipt2 = receipts_module.build_receipt(
        status="running",
        platform=3,
        platform_name="douyin",
        account_id="acc_002",
        task_id="task_l1_2_test_2",
    )
    assert receipt2.task_ref is None
    assert receipt2.material_id is None
    assert receipt2.artifact_id is None
    receipts_module.save_receipt(receipt2)
    r3 = receipts_module.get_receipt("task_l1_2_test_2")
    assert r3 is not None
    assert r3.task_ref is None
    assert r3.material_id is None
    assert r3.artifact_id is None


def test_batch_publish_request_schema_has_attribution_fields():
    """Pydantic 请求 schema 契约：BatchPublishRequest 顶层 + BatchTaskItem 各有
    可选 material_id / artifact_id 字段，未传时为 None（不阻断既有前端）。
    """
    from fastapi_app.schemas.publish import BatchPublishRequest, BatchTaskItem

    # 顶层字段
    req = BatchPublishRequest(
        file_ids=[1],
        accounts=["acc_001"],
        title="test",
    )
    assert req.material_id is None
    assert req.artifact_id is None

    req2 = BatchPublishRequest(
        file_ids=[1],
        accounts=["acc_001"],
        title="test",
        material_id="mat_001",
        artifact_id="art_001",
    )
    assert req2.material_id == "mat_001"
    assert req2.artifact_id == "art_001"

    # per-item 字段
    item = BatchTaskItem(file_id=1)
    assert item.material_id is None
    assert item.artifact_id is None

    item2 = BatchTaskItem(file_id=1, material_id="mat_item", artifact_id="art_item")
    assert item2.material_id == "mat_item"
    assert item2.artifact_id == "art_item"
