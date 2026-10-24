"""L3-1 孤岛收编测试（后端部分）。

三件收编（对应 module-link-frontend.md 断链 #2 / #5 / 孤岛清单）：
  ① ideas 吃回收数据：`GET /api/v1/content-library/ideas/from-performance`
     - 空 video_analytics → 返回 {suggestions: [], data_ready: false, hint: ...}
     - 有 data → 按互动量加权返回建议条目（title/note/heat 齐全）
  ② campaigns 接向导产物：publish_tasks 加 `campaign_id` 列
     - L1-2 幂等迁移模式：老库缺列 → ensure_all_tables 补齐；再跑一次不报错
     - 按 campaign_id 过滤 publish_tasks（`GET /campaigns/{id}/publish-tasks`）
     - BatchPublishRequest 接受 campaign_id（可选）
  ③ providers 接通道消费：后端 apply-to 端点已存在，仅前端接线，
     本测试文件只覆盖到 BatchPublishRequest schema 契约（campaign_id 字段）

设计取舍：走临时 sqlite 库 + sqlite3 直插数据，避免真跑 FastAPI app；
测试点聚焦「数据链路」，不 mock scheduler / celery。
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import pytest


# ---------------------------------------------------------------------------
# 夹具：临时 sqlite + 最小化 schema
# ---------------------------------------------------------------------------
def _unlink_retry(path: str) -> None:
    for _ in range(5):
        try:
            Path(path).unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.2)


@pytest.fixture()
def tmp_db():
    """临时空的 sqlite 库路径（走 ensure_all_tables 建齐 37 表）。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="l3_island_")
    os.close(fd)
    Path(path).unlink()
    yield Path(path)
    _unlink_retry(path)


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_video_analytics_row(
    conn: sqlite3.Connection,
    *,
    platform: str,
    video_id: str,
    title: str,
    play_count: int = 100,
    like_count: int = 10,
    comment_count: int = 5,
    collect_count: int = 3,
) -> int:
    return conn.execute(
        """
        INSERT INTO video_analytics (
            platform, video_id, title, play_count, like_count, comment_count, collect_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (platform, video_id, title, play_count, like_count, comment_count, collect_count),
    ).lastrowid


def _add_publish_task_row(
    conn: sqlite3.Connection,
    *,
    campaign_id: Optional[str] = None,
    material_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    platform: str = "douyin",
) -> int:
    return conn.execute(
        """
        INSERT INTO publish_tasks (
            celery_task_id, platform, account_id, material_id, artifact_id,
            campaign_id, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"celery_{uuid.uuid4().hex[:12]}",
            platform,
            f"acc_{uuid.uuid4().hex[:6]}",
            material_id,
            artifact_id,
            campaign_id,
            "pending",
        ),
    ).lastrowid


# ===========================================================================
# ① ideas 吃回收数据 —— from-performance 端点
# ===========================================================================


def test_ideas_from_performance_empty_returns_hint_and_empty_list(tmp_db):
    """无 video_analytics 数据 → 返回 {suggestions: [], data_ready: false, hint}。"""
    from fastapi_app.db.schema import ensure_all_tables
    import fastapi_app.core.config as cfg_mod
    from fastapi_app.api.v1.content_library.router import get_ideas_from_performance
    import asyncio

    conn = sqlite3.connect(tmp_db)
    try:
        ensure_all_tables(conn)
    finally:
        conn.close()

    # 让端点读我们的临时库
    orig = cfg_mod.settings.DATABASE_PATH
    cfg_mod.settings.DATABASE_PATH = str(tmp_db)
    try:
        result = asyncio.run(get_ideas_from_performance(limit=10))
    finally:
        cfg_mod.settings.DATABASE_PATH = orig

    assert result["status"] == "success"
    body = result["result"]
    assert body["suggestions"] == [], f"空数据应返回空 suggestions，实际: {body['suggestions']}"
    assert body["data_ready"] is False, f"空数据应 data_ready=False，实际: {body['data_ready']}"
    assert isinstance(body["hint"], str) and body["hint"], "空数据必须给非空 hint 提示字段"


def test_ideas_from_performance_aggregates_top_materials_by_engagement(tmp_db):
    """造 video_analytics 数据 → 返回建议条目，标题去重 + 热度归一 0-1。"""
    from fastapi_app.db.schema import ensure_all_tables
    import fastapi_app.core.config as cfg_mod
    from fastapi_app.api.v1.content_library.router import get_ideas_from_performance
    import asyncio

    conn = sqlite3.connect(tmp_db)
    try:
        ensure_all_tables(conn)
        # 三条数据：一条最高（title="话题A"），两条次高；另加一条同 title 重复
        _add_video_analytics_row(
            conn, platform="douyin", video_id="v1", title="话题A",
            play_count=1000, like_count=200, comment_count=50, collect_count=30,
        )
        _add_video_analytics_row(
            conn, platform="douyin", video_id="v2", title="话题B",
            play_count=500, like_count=100, comment_count=20, collect_count=10,
        )
        # 同 title 重复（应被去重）
        _add_video_analytics_row(
            conn, platform="tiktok", video_id="v3", title="话题A",
            play_count=200, like_count=50, comment_count=5, collect_count=2,
        )
        conn.commit()
    finally:
        conn.close()

    orig = cfg_mod.settings.DATABASE_PATH
    cfg_mod.settings.DATABASE_PATH = str(tmp_db)
    try:
        result = asyncio.run(get_ideas_from_performance(limit=10))
    finally:
        cfg_mod.settings.DATABASE_PATH = orig

    assert result["status"] == "success"
    body = result["result"]
    assert body["data_ready"] is True
    suggestions = body["suggestions"]
    # 至少 2 条（去重后：话题A、话题B）
    assert len(suggestions) >= 2, f"去重后至少 2 条建议，实际 {len(suggestions)} 条"
    # 首条应为最高互动量的话题A
    titles = [s["title"] for s in suggestions]
    assert titles.count("话题A") == 1, f"同 title 应去重为一条，实际出现 {titles.count('话题A')} 次"
    assert titles[0] == "话题A", f"首条应为最高互动量话题A，实际: {titles[0]}"
    # 热度归一化：首条 = 1.0，其余 ∈ (0, 1]
    heats = [s["heat"] for s in suggestions]
    assert abs(heats[0] - 1.0) < 1e-6, f"首条 heat 应为 1.0，实际 {heats[0]}"
    for h in heats[1:]:
        assert 0 < h <= 1.0, f"其余 heat 应在 (0, 1]，实际 {h}"
    # 条目必备字段
    for s in suggestions:
        assert "title" in s and "note" in s and "heat" in s
        assert s["source"] == "performance"


def test_ideas_from_performance_platform_filter(tmp_db):
    """platforms 参数过滤生效——只返回该平台的数据。"""
    from fastapi_app.db.schema import ensure_all_tables
    import fastapi_app.core.config as cfg_mod
    from fastapi_app.api.v1.content_library.router import get_ideas_from_performance
    import asyncio

    conn = sqlite3.connect(tmp_db)
    try:
        ensure_all_tables(conn)
        _add_video_analytics_row(
            conn, platform="douyin", video_id="v_dy", title="抖音话题",
            play_count=100, like_count=10,
        )
        _add_video_analytics_row(
            conn, platform="tiktok", video_id="v_tt", title="TT话题",
            play_count=200, like_count=20,
        )
        conn.commit()
    finally:
        conn.close()

    orig = cfg_mod.settings.DATABASE_PATH
    cfg_mod.settings.DATABASE_PATH = str(tmp_db)
    try:
        result = asyncio.run(get_ideas_from_performance(limit=10, platforms="douyin"))
    finally:
        cfg_mod.settings.DATABASE_PATH = orig

    body = result["result"]
    assert body["data_ready"] is True
    for s in body["suggestions"]:
        assert s["platform"] == "douyin", f"platforms='douyin' 应只返回 douyin，实际: {s['platform']}"


# ===========================================================================
# ② campaigns 接向导产物 —— campaign_id 列迁移
# ===========================================================================


def test_publish_tasks_campaign_id_column_idempotent_migration(tmp_db):
    """老库模拟：先建「缺 campaign_id」的 publish_tasks，跑 ensure_all_tables 补齐；
    再跑一次不报错、列集合不变（幂等）。"""
    from fastapi_app.db.schema import ensure_all_tables

    # 1) 建老版 publish_tasks（缺 campaign_id）
    conn = sqlite3.connect(tmp_db)
    try:
        conn.execute(
            """
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
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    # 2) 跑 ensure_all_tables 补齐 campaign_id
    conn = sqlite3.connect(tmp_db)
    try:
        ensure_all_tables(conn)
        conn.commit()
        cols = _columns(conn, "publish_tasks")
        assert "campaign_id" in cols, (
            f"ensure_all_tables 未补齐 campaign_id；已有列 {sorted(cols)}"
        )
    finally:
        conn.close()

    # 3) 幂等：再跑一次不报错
    conn = sqlite3.connect(tmp_db)
    try:
        ensure_all_tables(conn)
        conn.commit()
        cols = _columns(conn, "publish_tasks")
        assert "campaign_id" in cols, "二次跑后 campaign_id 又丢了"
    finally:
        conn.close()


def test_publish_tasks_campaign_id_index_exists(tmp_db):
    """ensure_all_tables 应建 idx_publish_tasks_campaign 索引。"""
    from fastapi_app.db.schema import ensure_all_tables

    conn = sqlite3.connect(tmp_db)
    try:
        ensure_all_tables(conn)
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_publish_tasks_campaign'"
        ).fetchall()
        assert rows, "缺 idx_publish_tasks_campaign 索引"
    finally:
        conn.close()


def test_publish_tasks_filter_by_campaign_id(tmp_db):
    """按 campaign_id 过滤：命中对应任务且不误伤其它（含 campaign_id=NULL 的行）。"""
    from fastapi_app.db.schema import ensure_all_tables

    conn = sqlite3.connect(tmp_db)
    try:
        ensure_all_tables(conn)
        # 造 3 条：两条 cam_a，一条 cam_b，一条 NULL
        _add_publish_task_row(conn, campaign_id="cam_a")
        _add_publish_task_row(conn, campaign_id="cam_a")
        _add_publish_task_row(conn, campaign_id="cam_b")
        _add_publish_task_row(conn, campaign_id=None)
        conn.commit()

        rows_a = conn.execute(
            "SELECT celery_task_id FROM publish_tasks WHERE campaign_id = ?",
            ("cam_a",),
        ).fetchall()
        assert len(rows_a) == 2, f"cam_a 应命中 2 条，实际 {len(rows_a)} 条"

        rows_b = conn.execute(
            "SELECT celery_task_id FROM publish_tasks WHERE campaign_id = ?",
            ("cam_b",),
        ).fetchall()
        assert len(rows_b) == 1, f"cam_b 应命中 1 条，实际 {len(rows_b)} 条"

        # 不存在的 campaign_id → 空
        rows_missing = conn.execute(
            "SELECT celery_task_id FROM publish_tasks WHERE campaign_id = ?",
            ("cam_nonexistent",),
        ).fetchall()
        assert rows_missing == [], "不存在的 campaign_id 应返回空"
    finally:
        conn.close()


def test_publish_tasks_campaign_id_write_and_readback(tmp_db):
    """INSERT 带 campaign_id → 回读一致（模拟向导提交入库路径）。"""
    from fastapi_app.db.schema import ensure_all_tables

    conn = sqlite3.connect(tmp_db)
    try:
        ensure_all_tables(conn)
        conn.execute(
            """
            INSERT INTO publish_tasks (
                celery_task_id, platform, account_id, material_id,
                title, status, campaign_id, artifact_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "celery_l3_1_abc123",
                "douyin",
                "acc_001",
                "mat_xxx",
                "测试标题",
                "pending",
                "cam_l3_test",
                "art_20261024a1b2c3",
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT campaign_id, artifact_id, material_id FROM publish_tasks "
            "WHERE celery_task_id = ?",
            ("celery_l3_1_abc123",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "INSERT 后读不到该 publish_task"
    campaign_id, artifact_id, material_id = row
    assert campaign_id == "cam_l3_test", f"campaign_id 回读不一致：{campaign_id!r}"
    assert artifact_id == "art_20261024a1b2c3"
    assert material_id == "mat_xxx"


# ===========================================================================
# ③ 端到端：campaign 详情端点按 campaign_id 反查
# ===========================================================================


def test_campaign_publish_tasks_endpoint_roundtrip(tmp_db):
    """GET /campaigns/{id}/publish-tasks → 按 campaign_id 过滤返回关联任务。"""
    from fastapi_app.db.schema import ensure_all_tables
    import fastapi_app.core.config as cfg_mod
    from fastapi_app.api.v1.campaigns.router import get_campaign_publish_tasks
    import asyncio

    conn = sqlite3.connect(tmp_db)
    try:
        ensure_all_tables(conn)
        _add_publish_task_row(conn, campaign_id="cam_x", material_id="m1")
        _add_publish_task_row(conn, campaign_id="cam_x", material_id="m2")
        _add_publish_task_row(conn, campaign_id="cam_y", material_id="m3")
        _add_publish_task_row(conn, campaign_id=None, material_id="m4")
        conn.commit()
    finally:
        conn.close()

    orig = cfg_mod.settings.DATABASE_PATH
    cfg_mod.settings.DATABASE_PATH = str(tmp_db)
    try:
        result = asyncio.run(get_campaign_publish_tasks("cam_x", limit=200))
    finally:
        cfg_mod.settings.DATABASE_PATH = orig

    assert result["status"] == "success"
    body = result["result"]
    assert body["campaign_id"] == "cam_x"
    assert body["count"] == 2, f"cam_x 应关联 2 条，实际 {body['count']} 条"
    material_ids = [it["material_id"] for it in body["items"]]
    assert "m1" in material_ids and "m2" in material_ids
    # 不含 cam_y 的 m3 或 NULL 的 m4
    assert "m3" not in material_ids
    assert "m4" not in material_ids


def test_campaign_publish_tasks_endpoint_empty_when_no_tasks(tmp_db):
    """无关联任务 → 返回空列表 + count=0，不报错。"""
    from fastapi_app.db.schema import ensure_all_tables
    import fastapi_app.core.config as cfg_mod
    from fastapi_app.api.v1.campaigns.router import get_campaign_publish_tasks
    import asyncio

    conn = sqlite3.connect(tmp_db)
    try:
        ensure_all_tables(conn)
    finally:
        conn.close()

    orig = cfg_mod.settings.DATABASE_PATH
    cfg_mod.settings.DATABASE_PATH = str(tmp_db)
    try:
        result = asyncio.run(get_campaign_publish_tasks("cam_missing", limit=200))
    finally:
        cfg_mod.settings.DATABASE_PATH = orig

    assert result["status"] == "success"
    body = result["result"]
    assert body["count"] == 0
    assert body["items"] == []


# ===========================================================================
# ④ schema 契约：BatchPublishRequest 接受 campaign_id（可选）
# ===========================================================================


def test_batch_publish_request_schema_has_campaign_id():
    """Pydantic 契约：BatchPublishRequest 顶层加可选 campaign_id 字段。"""
    from fastapi_app.schemas.publish import BatchPublishRequest

    req = BatchPublishRequest(
        file_ids=[1],
        accounts=["acc_001"],
        title="test",
    )
    assert req.campaign_id is None, "campaign_id 缺省应为 None"

    req2 = BatchPublishRequest(
        file_ids=[1],
        accounts=["acc_001"],
        title="test",
        campaign_id="cam_abc123",
    )
    assert req2.campaign_id == "cam_abc123"


def test_batch_publish_request_campaign_id_does_not_break_attribution_fields():
    """campaign_id 加入不影响 L1-2 已有的 material_id / artifact_id 字段。"""
    from fastapi_app.schemas.publish import BatchPublishRequest

    req = BatchPublishRequest(
        file_ids=[1],
        accounts=["acc_001"],
        title="test",
        material_id="mat_001",
        artifact_id="art_001",
        campaign_id="cam_001",
    )
    assert req.material_id == "mat_001"
    assert req.artifact_id == "art_001"
    assert req.campaign_id == "cam_001"
