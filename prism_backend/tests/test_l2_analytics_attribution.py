"""L2-3: 数据回收按任务/素材归因统计 —— 修断链 #3 测试。

覆盖契约（TDD 先测后码）：
  ① video_analytics 入库带 publish_task_id / artifact_id → 落库回读一致
  ② upsert 未带归因时保留原值（NULL 不覆盖）
  ③ get_analytics_videos 按 publish_task_id 过滤命中且不误伤其它
  ④ get_analytics_videos 按 material_id 反查 publish_tasks 过滤（链路正确）
  ⑤ 不传新参数 = 旧结果（回归保障）
  ⑥ NULL 归因记录在新维度过滤下不崩
  ⑦ get_analytics_summary 按任务维度返回小计（复用现有汇总逻辑）
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
# 夹具：临时 sqlite + 最小化 schema（video_analytics + publish_tasks）
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
    fd, path = tempfile.mkstemp(suffix=".db", prefix="l2_attr_")
    os.close(fd)
    Path(path).unlink()
    yield Path(path)
    _unlink_retry(path)


def _bootstrap(db_path: Path) -> None:
    """建 video_analytics（走 ensure_analytics_schema 真源）+ 最小 publish_tasks。"""
    from myUtils.analytics_db import ensure_analytics_schema

    ensure_analytics_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS publish_tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                celery_task_id TEXT UNIQUE,
                platform TEXT,
                account_id TEXT,
                material_id TEXT,
                artifact_id TEXT,
                title TEXT,
                tags TEXT,
                video_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def _add_task(
    conn: sqlite3.Connection,
    *,
    material_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
) -> str:
    """插入 publish_tasks 一条，返回 str(task_id)（匹配 video_analytics.publish_task_id 类型）。"""
    cur = conn.execute(
        "INSERT INTO publish_tasks (celery_task_id, platform, material_id, artifact_id) "
        "VALUES (?, ?, ?, ?)",
        (
            f"celery_{uuid.uuid4().hex[:12]}",
            "3",
            material_id,
            artifact_id,
        ),
    )
    return str(cur.lastrowid)


def _add_video(
    conn: sqlite3.Connection,
    *,
    video_id: str,
    publish_task_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    play_count: int = 100,
    like_count: int = 10,
    platform: str = "douyin",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO video_analytics (
            platform, video_id, play_count, like_count, publish_task_id, artifact_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (platform, video_id, play_count, like_count, publish_task_id, artifact_id),
    )
    return cur.lastrowid


# ---------------------------------------------------------------------------
# ① 带归因的记录入库回读
# ---------------------------------------------------------------------------
def test_insert_video_analytics_with_attribution_roundtrip(tmp_db):
    """insert_video_analytics 带 publish_task_id + artifact_id → 落库回读一致。"""
    _bootstrap(tmp_db)
    from myUtils.analytics_db import insert_video_analytics

    vid = insert_video_analytics(
        tmp_db,
        {
            "platform": "douyin",
            "video_id": "v_l23_001",
            "title": "带归因视频",
            "play_count": 123,
            "like_count": 45,
            "publish_task_id": "celery_task_1",
            "artifact_id": "art_20261024a1b2c3",
        },
    )
    with sqlite3.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT publish_task_id, artifact_id FROM video_analytics WHERE id=?",
            (vid,),
        ).fetchone()
    assert row == ("celery_task_1", "art_20261024a1b2c3")


def test_upsert_video_analytics_by_key_preserves_attribution(tmp_db):
    """二次 upsert 未带归因时，publish_task_id / artifact_id 应保留首次值（COALESCE 语义）。"""
    _bootstrap(tmp_db)
    from myUtils.analytics_db import upsert_video_analytics_by_key

    upsert_video_analytics_by_key(
        tmp_db,
        platform="douyin",
        video_id="v_upsert_001",
        data={
            "play_count": 10,
            "publish_task_id": "celery_t1",
            "artifact_id": "art_a1",
            "raw_data": {},
        },
    )
    upsert_video_analytics_by_key(
        tmp_db,
        platform="douyin",
        video_id="v_upsert_001",
        data={"play_count": 99, "raw_data": {}},
    )
    with sqlite3.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT play_count, publish_task_id, artifact_id FROM video_analytics "
            "WHERE platform=? AND video_id=?",
            ("douyin", "v_upsert_001"),
        ).fetchone()
    assert row == (99, "celery_t1", "art_a1")


# ---------------------------------------------------------------------------
# ③ 列表端点按 publish_task_id 过滤命中且不误伤其它
# ---------------------------------------------------------------------------
def test_get_analytics_videos_filter_by_publish_task_id(tmp_db):
    """命中 task_A 的两条、不误伤 task_B 或其它任务。"""
    _bootstrap(tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        _add_video(conn, video_id="v1", publish_task_id="task_A", play_count=100)
        _add_video(conn, video_id="v2", publish_task_id="task_B", play_count=200)
        _add_video(conn, video_id="v3", publish_task_id="task_A", play_count=300)
        conn.commit()

    from myUtils.analytics_db import get_analytics_videos

    got = get_analytics_videos(tmp_db, publish_task_id="task_A")
    assert len(got) == 2
    assert {v["playCount"] for v in got} == {100, 300}
    assert {v["videoId"] for v in got} == {"v1", "v3"}


def test_get_analytics_videos_filter_by_artifact_id(tmp_db):
    """按 artifact_id 过滤，命中该 artifact 的所有记录。"""
    _bootstrap(tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        _add_video(conn, video_id="v1", artifact_id="art_1", play_count=111)
        _add_video(conn, video_id="v2", artifact_id="art_2", play_count=222)
        _add_video(conn, video_id="v3", artifact_id="art_1", play_count=333)
        conn.commit()

    from myUtils.analytics_db import get_analytics_videos

    got = get_analytics_videos(tmp_db, artifact_id="art_1")
    assert len(got) == 2
    assert {v["videoId"] for v in got} == {"v1", "v3"}


# ---------------------------------------------------------------------------
# ④ 按 material_id 链路过滤（material_id → publish_tasks.task_id → video_analytics）
# ---------------------------------------------------------------------------
def test_get_analytics_videos_filter_by_material_id_via_tasks(tmp_db):
    """material_id 反查 publish_tasks 得 task_id 集合，再过滤 video_analytics。"""
    _bootstrap(tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        t1 = _add_task(conn, material_id="mat_M1", artifact_id="art_x")
        t2 = _add_task(conn, material_id="mat_M2", artifact_id="art_y")
        _add_video(conn, video_id="v1", publish_task_id=t1, play_count=111)
        _add_video(conn, video_id="v2", publish_task_id=t2, play_count=222)
        _add_video(conn, video_id="v3", publish_task_id=t1, play_count=333)
        conn.commit()

    from myUtils.analytics_db import get_analytics_videos

    got = get_analytics_videos(tmp_db, material_id="mat_M1")
    assert len(got) == 2
    assert {v["playCount"] for v in got} == {111, 333}
    assert {v["videoId"] for v in got} == {"v1", "v3"}

    # 空链路：查一个不存在的 material_id，应返回空而不是抛错
    got_missing = get_analytics_videos(tmp_db, material_id="mat_missing")
    assert got_missing == []


# ---------------------------------------------------------------------------
# ⑤ 不传新参数 = 旧结果（回归保障）
# ---------------------------------------------------------------------------
def test_get_analytics_videos_no_new_params_returns_legacy(tmp_db):
    """不传新参数时，行为与旧版一致：全量返回；旧平台过滤仍生效。"""
    _bootstrap(tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        _add_video(conn, video_id="v1", platform="douyin", publish_task_id="t1")
        _add_video(conn, video_id="v2", platform="kuaishou", publish_task_id="t2")
        conn.commit()

    from myUtils.analytics_db import get_analytics_videos

    got_all = get_analytics_videos(tmp_db)
    assert len(got_all) == 2

    got_platform = get_analytics_videos(tmp_db, platforms=["douyin"])
    assert len(got_platform) == 1
    assert got_platform[0]["platform"] == "douyin"


# ---------------------------------------------------------------------------
# ⑥ NULL 归因记录在新维度过滤下不崩
# ---------------------------------------------------------------------------
def test_null_attribution_does_not_break_filters(tmp_db):
    """未归因记录（publish_task_id / artifact_id 为 NULL）
    不应被任何归因过滤命中，且查询不报错。"""
    _bootstrap(tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        _add_video(conn, video_id="v_null", play_count=5)
        _add_video(conn, video_id="v_hit", publish_task_id="t_hit",
                   artifact_id="art_hit", play_count=7)
        conn.commit()

    from myUtils.analytics_db import get_analytics_videos

    got_task = get_analytics_videos(tmp_db, publish_task_id="t_hit")
    assert len(got_task) == 1
    assert got_task[0]["videoId"] == "v_hit"

    got_artifact = get_analytics_videos(tmp_db, artifact_id="art_hit")
    assert len(got_artifact) == 1
    assert got_artifact[0]["videoId"] == "v_hit"

    # 查一个既无 hit 也无 null 匹配的值 → 空
    got_none = get_analytics_videos(tmp_db, artifact_id="art_missing")
    assert got_none == []

    # material_id 反查空集合也不崩
    got_m_empty = get_analytics_videos(tmp_db, material_id="nonexistent")
    assert got_m_empty == []


# ---------------------------------------------------------------------------
# ⑦ 汇总口径：按任务维度返回小计（复用现有汇总逻辑）
# ---------------------------------------------------------------------------
def test_summary_subtotal_with_attribution_filter(tmp_db):
    """get_analytics_summary 带 publish_task_id 时，聚合仅覆盖该任务命中的记录。"""
    _bootstrap(tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        _add_video(conn, video_id="v1", publish_task_id="t1",
                   play_count=100, like_count=10)
        _add_video(conn, video_id="v2", publish_task_id="t1",
                   play_count=200, like_count=20)
        _add_video(conn, video_id="v3", publish_task_id="t2",
                   play_count=300, like_count=30)
        conn.commit()

    from myUtils.analytics_db import get_analytics_summary

    s = get_analytics_summary(tmp_db, publish_task_id="t1")
    assert s["totalVideos"] == 2
    assert s["totalPlays"] == 300
    assert s["totalLikes"] == 30

    # 不带过滤时全量聚合（回归保障）
    s_all = get_analytics_summary(tmp_db)
    assert s_all["totalVideos"] == 3
    assert s_all["totalPlays"] == 600


# ---------------------------------------------------------------------------
# 回收写入带归因：resolve + set 双向 helper
# ---------------------------------------------------------------------------
def test_resolve_task_attribution_from_publish_tasks(tmp_db):
    """resolve_task_attribution_from_publish_tasks 按 (platform, account_id, video_id)
    反查 publish_tasks，命中 → (task_id, artifact_id)；未命中 → (None, None)。"""
    _bootstrap(tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        t1 = _add_task(conn, material_id="mat_M1", artifact_id="art_x")
        # 模拟「ID 回收」阶段把 video_id 回写到 publish_tasks
        # （L1-2 的 _proximity_match_and_recover 语义）
        conn.execute(
            "UPDATE publish_tasks SET video_id = 'vid_abc', "
            "platform = 'douyin', account_id = 'acc1' WHERE task_id = ?",
            (t1,),
        )
        conn.commit()

    from myUtils.analytics_db import resolve_task_attribution_from_publish_tasks

    got_task, got_artifact = resolve_task_attribution_from_publish_tasks(
        tmp_db, platform="douyin", account_id="acc1", video_id="vid_abc",
    )
    assert got_task == str(t1)
    assert got_artifact == "art_x"

    # 未命中：查一个不存在的 video_id → 双 None，不崩
    got_missing = resolve_task_attribution_from_publish_tasks(
        tmp_db, platform="douyin", account_id="acc1", video_id="vid_missing",
    )
    assert got_missing == (None, None)


def test_set_video_analytics_attribution_backfill(tmp_db):
    """set_video_analytics_attribution 用 COALESCE 回写归因；已归因不覆盖。"""
    _bootstrap(tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        _add_video(conn, video_id="v_backfill", play_count=5)
        conn.commit()

    from myUtils.analytics_db import set_video_analytics_attribution

    # 首次回写：从零归因 → 有归因
    set_video_analytics_attribution(
        tmp_db, platform="douyin", video_id="v_backfill",
        publish_task_id="celery_t1", artifact_id="art_a1",
    )
    with sqlite3.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT publish_task_id, artifact_id FROM video_analytics WHERE video_id=?",
            ("v_backfill",),
        ).fetchone()
    assert row == ("celery_t1", "art_a1")

    # 二次回写传 None：不覆盖旧值（COALESCE 语义）
    set_video_analytics_attribution(
        tmp_db, platform="douyin", video_id="v_backfill",
        publish_task_id=None, artifact_id=None,
    )
    with sqlite3.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT publish_task_id, artifact_id FROM video_analytics WHERE video_id=?",
            ("v_backfill",),
        ).fetchone()
    assert row == ("celery_t1", "art_a1")

    # 传空/缺参：无副作用
    set_video_analytics_attribution(tmp_db, platform="", video_id="", publish_task_id="x")
    set_video_analytics_attribution(tmp_db, platform="douyin", video_id="v_backfill")
    with sqlite3.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT publish_task_id, artifact_id FROM video_analytics WHERE video_id=?",
            ("v_backfill",),
        ).fetchone()
    assert row == ("celery_t1", "art_a1")


def test_end_to_end_collect_write_with_attribution(tmp_db):
    """端到端：先在 publish_tasks 建记录并回写 video_id → 走 save_video_data
    入库 → video_analytics 应带 publish_task_id / artifact_id。"""
    _bootstrap(tmp_db)

    # 模拟采集器初始化后的 publish_tasks 状态：已把 video_id 回写到某任务
    with sqlite3.connect(tmp_db) as conn:
        task_id = _add_task(conn, material_id="mat_M1", artifact_id="art_x")
        conn.execute(
            "UPDATE publish_tasks SET video_id = 'vid_e2e', "
            "platform = 'douyin', account_id = 'acc1' WHERE task_id = ?",
            (task_id,),
        )
        conn.commit()

    # 走 helper 层模拟 save_video_data 里的采集-回写-归因回写三步骤
    from myUtils.analytics_db import (
        upsert_video_analytics_by_key,
        resolve_task_attribution_from_publish_tasks,
        set_video_analytics_attribution,
    )

    upsert_video_analytics_by_key(
        tmp_db,
        platform="douyin",
        video_id="vid_e2e",
        data={
            "account_id": "acc1",
            "title": "采集到的标题",
            "play_count": 500,
            "raw_data": {},
        },
    )
    p_tid, a_id = resolve_task_attribution_from_publish_tasks(
        tmp_db, platform="douyin", account_id="acc1", video_id="vid_e2e",
    )
    if p_tid or a_id:
        set_video_analytics_attribution(
            tmp_db, platform="douyin", video_id="vid_e2e",
            publish_task_id=p_tid, artifact_id=a_id,
        )

    from myUtils.analytics_db import get_analytics_videos
    got = get_analytics_videos(tmp_db, publish_task_id=str(task_id))
    assert len(got) == 1
    assert got[0]["videoId"] == "vid_e2e"
    assert got[0]["publishTaskId"] == str(task_id)
    assert got[0]["artifactId"] == "art_x"
