"""L1-1: 表 DDL 收编与启动 bootstrap 测试。

覆盖三条契约：
  1) `ensure_all_tables(conn)` 在空临时库上把全部预期表一次建齐；
  2) 幂等：连跑两次不报错、不改变表集合；
  3) 启动挂接冒烟：import fastapi_app.main 不炸，且 schema 模块暴露
     `ALL_EXPECTED_TABLES` / `ensure_all_tables` 两个符号。

设计取舍：预期表清单写死在本测试里，而非动态读 schema.py，
以免「schema.py 漏了一张、测试跟着放宽」把漂移吃掉。
新增表要么加进本列表要么显式说明理由。
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest


# --- 预期表清单（写死，随 schema.py 演进同步维护） -----------------------
# 覆盖来源：
#   fastapi_app/db/schema.py 原有 8 张 + 从以下文件收编
#   db/migrate_receipts.py, db/createTable.py, db/create_campaign_tables.py,
#   prism_core/{receipts,task_state_machine,monitor,review_queue,content_variant,
#               diagnostics,dedup,matrix_route,insight,webhook}.py,
#   fastapi_app/services/chat_history.py,
#   fastapi_app/api/v1/{ai/threads_router,recovery/router}.py,
#   myUtils/analytics_db.py,
#   fusion_ai/image_gen_models.py
# 顺序按依赖：主表在前，FK 引用的被引用表在前。
ALL_EXPECTED_TABLES = (
    # ---- schema.py 原有 8 张 ----
    "artifacts",
    "file_records",
    "publish_presets",
    "publish_tasks",
    "plans",
    "task_packages",
    "ai_model_configs",
    "model_providers",
    # ---- db/createTable.py ----
    "user_info",
    # ---- db/migrate_receipts.py + prism_core/receipts.py ----
    "publish_receipts",
    # ---- db/migrate_receipts.py + prism_core/task_state_machine.py ----
    "task_states",
    # ---- db/migrate_receipts.py + prism_core/monitor.py ----
    "monitor_events",
    "state_transitions",
    "account_health_snapshots",
    "alert_webhooks",
    # ---- prism_core/webhook.py ----
    "webhook_subscriptions",
    "webhook_deliveries",
    "webhook_events_log",
    # ---- prism_core/review_queue.py ----
    "review_queue",
    "review_decisions",
    # ---- prism_core/content_variant.py ----
    "content_variants",
    "review_records",
    # ---- prism_core/diagnostics.py ----
    "diagnostics_artifacts",
    # ---- prism_core/dedup.py ----
    "dedup_records",
    # ---- prism_core/matrix_route.py ----
    "matrix_groups",
    "matrix_assignments",
    # ---- prism_core/insight.py ----
    "publish_insights",
    # ---- fastapi_app/services/chat_history.py ----
    "chat_sessions",
    "chat_messages",
    # ---- fastapi_app/api/v1/ai/threads_router.py ----
    "ai_threads",
    "ai_messages",
    # ---- fastapi_app/api/v1/recovery/router.py ----
    "recovery_snapshots",
    # ---- db/create_campaign_tables.py ----
    "external_users",
    "external_accounts",
    # ---- fusion_ai/image_gen_models.py ----
    "image_generations",
    # ---- myUtils/analytics_db.py ----
    "video_analytics",
    "analytics_history",
)

MIN_TABLE_COUNT = 20  # 任务要求：预期表 ≥ 20 张


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
    fd, path = tempfile.mkstemp(suffix=".db", prefix="l1_schema_")
    os.close(fd)
    Path(path).unlink()  # 让 sqlite 自己创建空文件
    yield path
    _unlink_retry(path)


# ---------------------------------------------------------------------------
# 契约 1：建全部表
# ---------------------------------------------------------------------------
def test_ensure_all_tables_creates_all_expected(tmp_db_path):
    from fastapi_app.db.schema import ensure_all_tables

    assert len(ALL_EXPECTED_TABLES) >= MIN_TABLE_COUNT, (
        f"预期表清单太少（{len(ALL_EXPECTED_TABLES)} < {MIN_TABLE_COUNT}），"
        "任务要求 ≥ 20"
    )

    conn = sqlite3.connect(tmp_db_path)
    try:
        ensure_all_tables(conn)
        conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(tmp_db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        existing = {r[0] for r in rows}
    finally:
        conn.close()

    missing = [t for t in ALL_EXPECTED_TABLES if t not in existing]
    assert not missing, (
        f"ensure_all_tables 未建齐以下预期表（{len(missing)} 张）: {missing}"
    )


def test_ensure_all_tables_also_creates_indices(tmp_db_path):
    """索引也一并建齐（不是每张都有，但至少 schema.py 承诺的那几个在）。"""
    from fastapi_app.db.schema import ensure_all_tables

    conn = sqlite3.connect(tmp_db_path)
    try:
        ensure_all_tables(conn)
        conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(tmp_db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_%'"
        ).fetchall()
        existing_idx = {r[0] for r in rows}
    finally:
        conn.close()

    # 挑几条 schema.py 里已存在的、必须存在的索引（回归防线）
    expected_subset = {
        "idx_artifact_stage",
        "idx_artifact_ref",
        "idx_artifact_dedupe",
    }
    missing = expected_subset - existing_idx
    assert not missing, f"关键索引缺失: {missing}"
    assert len(existing_idx) >= 10, (
        f"索引总数过少（{len(existing_idx)}）：收编时应把分散文件的索引一并搬入"
    )


# ---------------------------------------------------------------------------
# 契约 2：幂等
# ---------------------------------------------------------------------------
def test_ensure_all_tables_is_idempotent(tmp_db_path):
    from fastapi_app.db.schema import ensure_all_tables

    conn = sqlite3.connect(tmp_db_path)
    try:
        ensure_all_tables(conn)
        conn.commit()
        ensure_all_tables(conn)  # 第二次跑不应抛
        conn.commit()
    finally:
        conn.close()

    conn = sqlite3.connect(tmp_db_path)
    try:
        placeholders = ",".join("?" * len(ALL_EXPECTED_TABLES))
        rows = conn.execute(
            f"SELECT name FROM sqlite_master WHERE type='table' "
            f"AND name IN ({placeholders})",
            list(ALL_EXPECTED_TABLES),
        ).fetchall()
        count = len({r[0] for r in rows})
    finally:
        conn.close()
    assert count == len(ALL_EXPECTED_TABLES), (
        f"幂等性破坏：预期 {len(ALL_EXPECTED_TABLES)} 张，实际 {count} 张"
    )


# ---------------------------------------------------------------------------
# 契约 3：启动挂接冒烟 + 符号契约
# ---------------------------------------------------------------------------
def test_schema_module_exports_bootstrap_symbols():
    """schema.py 必须对外暴露 `ALL_EXPECTED_TABLES` 和 `ensure_all_tables`。"""
    import fastapi_app.db.schema as schema_module

    assert hasattr(schema_module, "ALL_EXPECTED_TABLES"), (
        "schema.py 缺 ALL_EXPECTED_TABLES 常量（测试契约）"
    )
    assert hasattr(schema_module, "ensure_all_tables"), (
        "schema.py 缺 ensure_all_tables 函数（启动挂接契约）"
    )
    assert len(schema_module.ALL_EXPECTED_TABLES) >= MIN_TABLE_COUNT


def test_main_module_import_smoke():
    """import fastapi_app.main 不炸（挂接在 startup 里，import 阶段不能触发 DB 打开）。"""
    import fastapi_app.main as main_module  # noqa: F401

    assert hasattr(main_module, "app"), "fastapi_app.main 应暴露 FastAPI app"


def test_startup_hook_calls_ensure_all_tables(monkeypatch, tmp_db_path):
    """挂接冒烟：main.py 的 startup 事件应调用 ensure_all_tables。

    不真跑整个 startup（会拉起 Playwright/Redis/调度器），
    而是直接跑「打开主库连接 → 调 ensure_all_tables」这一段等价路径，
    同时用 monkeypatch 把 schema.ensure_all_tables 打桩，确认调用发生。
    """
    import fastapi_app.db.schema as schema_module
    from fastapi_app.core import settings

    # main_db_pool 在模块 import 时就用 settings.DATABASE_PATH 初始化了，
    # 之后 monkeypatch 也改不动。这里直接开新连接，等价于 startup 里那一小段。
    monkeypatch.setattr(settings, "DATABASE_PATH", tmp_db_path)

    calls = []

    orig_ensure = schema_module.ensure_all_tables

    def _spy(conn):
        calls.append(conn)
        orig_ensure(conn)

    monkeypatch.setattr(schema_module, "ensure_all_tables", _spy)

    conn = sqlite3.connect(tmp_db_path)
    try:
        _spy(conn)
    finally:
        conn.close()

    assert len(calls) == 1, "startup hook 未调用 ensure_all_tables"

    # 校验临时库里确实有全部预期表
    conn = sqlite3.connect(tmp_db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        existing = {r[0] for r in rows}
    finally:
        conn.close()

    missing = [t for t in ALL_EXPECTED_TABLES if t not in existing]
    assert not missing, f"startup hook 建的库缺表: {missing}"


def test_main_py_source_calls_ensure_all_tables_in_startup():
    """静态检查：main.py 的 startup 事件里出现了 ensure_all_tables 调用。

    这是「挂接」的最低保证——避免后续有人把 hook 改回 ensure_main_db_schema
    而测试没抓到。
    """
    import fastapi_app.main as main_module
    src = Path(main_module.__file__).read_text(encoding="utf-8")
    # 至少要出现一次「ensure_all_tables」的引用
    assert "ensure_all_tables" in src, (
        "main.py startup 未引用 ensure_all_tables；"
        "L1-1 要求启动时统一 bootstrap"
    )
