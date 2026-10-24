"""L2-2: 审核通过回写发布任务状态 + 回执归因回填 —— 修断链 #4。

背景：
  前端断链 #4（`.superpowers/sdd/valkyrie-gamora-big-barda/module-link-frontend.md` §D4）：
  「审核通过后不回写发布任务状态（review/page.tsx:311）」。
  同时回执 → 任务的归因链断：L1 已铺 publish_receipts.task_ref/material_id/artifact_id 列
  与 build_receipt 透传参数，但发布执行侧的 save_receipt 调用点尚未把三字段透传下去。

契约（TDD 先测后码）：
  ① 审核通过 → 关联 publish_task 对应 task_state 状态推进 approved
     （用 task_state_machine 合法转换；awaiting_review → approved）
  ② 无关联任务时审核通过不报错（task_state 不存在 / 无 publish_task → 静默跳过）
  ③ 退回 → 状态推进（awaiting_review → draft）或安全跳过
  ④ save_receipt 调用点带归因（task_ref / material_id / artifact_id）
     —— mock 验证参数链
  ⑤ 非法转换被 InvalidTransition 拦截且审核本身不崩（当前态不能推进时静默跳过）

隔离策略：
  - 临时 sqlite 库（monkeypatch settings.DATABASE_PATH）+ schema.ensure_all_tables
  - 直接调 review_queue.approve_review / reject_review（不经 FastAPI）
  - batch_publish_service 的 save_receipt 用 monkeypatch 捕获 receipt 对象

运行：
  cd prism_backend && ../prismenv/Scripts/python.exe -m pytest tests/test_l2_review_receipt_link.py -q
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 与既有测试一致：跳过云端 feature flag，避免 HTTP 超时
os.environ.setdefault("FEATURE_FLAGS_DISABLED", "1")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture：隔离的 sqlite 库 + schema bootstrap
# ---------------------------------------------------------------------------


def _unlink_retry(path: str) -> None:
    for _ in range(5):
        try:
            Path(path).unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.2)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """把主库指到 tmp 目录，跑一次 ensure_all_tables，返回 (db_path, conn)。"""
    db_path = str(tmp_path / "test_l2_2.db")

    from fastapi_app.core import config as _config
    from fastapi_app.db import schema

    monkeypatch.setattr(_config.settings, "DATABASE_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        schema.ensure_all_tables(conn)
        conn.commit()
    finally:
        conn.close()

    yield db_path

    _unlink_retry(db_path)


# ---------------------------------------------------------------------------
# Helper：直接插入 publish_tasks / task_states / review_queue 行
# ---------------------------------------------------------------------------


def _open(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_publish_task(
    db_path: str,
    *,
    celery_task_id: str,
    artifact_id: Optional[str],
    material_id: Optional[str] = None,
    status: str = "pending",
    platform: str = "3",
    account_id: str = "acc_001",
) -> int:
    """插入一行 publish_tasks，返回自增 task_id（INTEGER）。"""
    conn = _open(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO publish_tasks
                (celery_task_id, platform, account_id, material_id,
                 title, status, created_at, updated_at, artifact_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                celery_task_id,
                platform,
                account_id,
                material_id,
                "测试任务",
                status,
                "2026-10-24T00:00:00",
                "2026-10-24T00:00:00",
                artifact_id,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def _insert_task_state(
    db_path: str,
    *,
    task_id: str,
    status: str,
    material_id: Optional[str] = None,
) -> None:
    """插入一行 task_states（状态机表）—— 用 str(publish_tasks.task_id) 作为桥接键。"""
    conn = _open(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO task_states
                (task_id, status, idempotency_key, platform, platform_name,
                 account_id, material_id, attempt, max_attempts,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                status,
                f"campaign:l2_2:variant:v:account:acc",
                3,
                "douyin",
                "acc_001",
                material_id,
                1,
                3,
                "2026-10-24T00:00:00",
                "2026-10-24T00:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _get_task_state_status(db_path: str, task_id: str) -> Optional[str]:
    conn = _open(db_path)
    try:
        row = conn.execute(
            "SELECT status FROM task_states WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _insert_review_item(
    db_path: str,
    *,
    review_id: str,
    task_id: str,  # 约定：这里传 artifact_id
) -> None:
    conn = _open(db_path)
    try:
        conn.execute(
            """
            INSERT INTO review_queue
                (review_id, task_id, campaign_id, platform, platform_name,
                 account_id, status, priority, review_type, title, content,
                 submitted_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                task_id,
                "cmp_test",
                3,
                "douyin",
                "acc_001",
                "pending",
                "normal",
                "manual",
                "审核标题",
                "审核内容",
                "2026-10-24T00:00:00",
                "2026-10-24T00:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ① 审核通过 → 关联任务状态推进 approved
# ---------------------------------------------------------------------------


def test_approve_review_advances_task_state_to_approved(isolated_db):
    """造数据：publish_task + task_state（awaiting_review）+ review(task_id=artifact_id)
    → 调 approve_review → 断言 task_states.status 变为 approved。

    契约：审核自身状态（review_queue.status='approved'、review_decisions 一行）保留原行为。
    """
    from prism_core.review_queue import approve_review

    artifact_id = "art_l2_2_approved_001"
    pt_id = _insert_publish_task(
        isolated_db,
        celery_task_id="celery_l2_2_ok_001",
        artifact_id=artifact_id,
        material_id="mat_l2_2_001",
        status="scheduled",
    )
    _insert_task_state(
        isolated_db,
        task_id=str(pt_id),
        status="awaiting_review",
        material_id="mat_l2_2_001",
    )
    review_id = "rv_l2_2_approved_001"
    _insert_review_item(isolated_db, review_id=review_id, task_id=artifact_id)

    decision = approve_review(review_id, "reviewer_001", "内容合规")
    assert decision is not None
    assert decision.decision == "approved"

    # 审核自身状态：原行为保留
    conn = _open(isolated_db)
    try:
        row = conn.execute(
            "SELECT status FROM review_queue WHERE review_id = ?", (review_id,)
        ).fetchone()
        assert row is not None
        assert row[0] == "approved", f"review_queue.status 应为 approved，实为 {row[0]!r}"

        drow = conn.execute(
            "SELECT decision FROM review_decisions WHERE review_id = ?", (review_id,)
        ).fetchone()
        assert drow is not None
        assert drow[0] == "approved"
    finally:
        conn.close()

    # L2-2 新契约：task_states 状态推进 approved
    assert _get_task_state_status(isolated_db, str(pt_id)) == "approved"


# ---------------------------------------------------------------------------
# ② 无关联任务时审核通过不报错
# ---------------------------------------------------------------------------


def test_approve_review_without_linked_task_no_error(isolated_db):
    """publish_tasks 里没有匹配 artifact_id → approve_review 不抛异常，
    且审核自身状态（review_queue.status='approved'）正常落库。"""
    from prism_core.review_queue import approve_review

    artifact_id = "art_l2_2_no_link_001"
    review_id = "rv_l2_2_no_link_001"
    _insert_review_item(isolated_db, review_id=review_id, task_id=artifact_id)

    # 无 publish_tasks、无 task_states —— 审核通过必须静默跳过
    decision = approve_review(review_id, "reviewer_001", "内容合规")
    assert decision is not None
    assert decision.decision == "approved"

    conn = _open(isolated_db)
    try:
        row = conn.execute(
            "SELECT status FROM review_queue WHERE review_id = ?", (review_id,)
        ).fetchone()
        assert row is not None
        assert row[0] == "approved"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ③ 退回 → 状态推进（awaiting_review → draft）或安全跳过
# ---------------------------------------------------------------------------


def test_reject_review_pushes_task_state_back_to_draft(isolated_db):
    """退回/需修改 → task_states 从 awaiting_review 回退到 draft。

    契约：awaiting_review → draft 是合法转换（VALID_TRANSITIONS）。
    """
    from prism_core.review_queue import reject_review

    artifact_id = "art_l2_2_reject_001"
    pt_id = _insert_publish_task(
        isolated_db,
        celery_task_id="celery_l2_2_rej_001",
        artifact_id=artifact_id,
        material_id="mat_l2_2_rej_001",
        status="scheduled",
    )
    _insert_task_state(
        isolated_db,
        task_id=str(pt_id),
        status="awaiting_review",
        material_id="mat_l2_2_rej_001",
    )
    review_id = "rv_l2_2_reject_001"
    _insert_review_item(isolated_db, review_id=review_id, task_id=artifact_id)

    decision = reject_review(review_id, "reviewer_001", "含敏感词，退回修改")
    assert decision is not None
    assert decision.decision == "rejected"

    # 审核自身：review_queue.status='rejected'
    conn = _open(isolated_db)
    try:
        row = conn.execute(
            "SELECT status FROM review_queue WHERE review_id = ?", (review_id,)
        ).fetchone()
        assert row is not None
        assert row[0] == "rejected"
    finally:
        conn.close()

    # L2-2 新契约：task_states 状态回退 draft
    assert _get_task_state_status(isolated_db, str(pt_id)) == "draft"


# ---------------------------------------------------------------------------
# ④ save_receipt 调用点带归因（参数链验证）
# ---------------------------------------------------------------------------


def test_record_success_receipt_passes_attribution_fields(isolated_db, monkeypatch):
    """_record_success_receipt 必须把 data 里的 task_ref / material_id / artifact_id
    透传到 build_success_receipt → save_receipt。

    实现：monkeypatch save_receipt 捕获 receipt 对象，断言三字段落进 PublishReceipt。
    """
    from prism_core import receipts as receipts_module
    from myUtils.batch_publish_service import _record_success_receipt

    captured: List[Any] = []

    def _fake_save_receipt(receipt: Any) -> str:
        captured.append(receipt)
        return receipt.task_id

    monkeypatch.setattr(receipts_module, "save_receipt", _fake_save_receipt)

    data: Dict[str, Any] = {
        "attempt": 1,
        "task_ref": "celery_l2_2_attr_001",
        "material_id": "mat_l2_2_attr_001",
        "artifact_id": "art_l2_2_attr_001",
    }

    _record_success_receipt(platform=3, account_id="acc_001", video_url=None, data=data)

    assert len(captured) == 1, f"save_receipt 应被调用 1 次，实为 {len(captured)} 次"
    receipt = captured[0]
    assert receipt.task_ref == "celery_l2_2_attr_001", (
        f"task_ref 未透传：{receipt.task_ref!r}"
    )
    assert receipt.material_id == "mat_l2_2_attr_001", (
        f"material_id 未透传：{receipt.material_id!r}"
    )
    assert receipt.artifact_id == "art_l2_2_attr_001", (
        f"artifact_id 未透传：{receipt.artifact_id!r}"
    )


def test_record_success_receipt_keeps_attribution_null_when_absent(
    isolated_db, monkeypatch
):
    """data 里无归因字段时，_record_success_receipt 保持三字段为 NULL（不强造）。"""
    from prism_core import receipts as receipts_module
    from myUtils.batch_publish_service import _record_success_receipt

    captured: List[Any] = []

    def _fake_save_receipt(receipt: Any) -> str:
        captured.append(receipt)
        return receipt.task_id

    monkeypatch.setattr(receipts_module, "save_receipt", _fake_save_receipt)

    data: Dict[str, Any] = {"attempt": 1}

    _record_success_receipt(platform=3, account_id="acc_001", video_url=None, data=data)

    assert len(captured) == 1
    receipt = captured[0]
    assert receipt.task_ref is None
    assert receipt.material_id is None
    assert receipt.artifact_id is None


# ---------------------------------------------------------------------------
# ⑤ 非法转换被拦截，审核本身不崩
# ---------------------------------------------------------------------------


def test_approve_review_illegal_transition_silently_skipped(isolated_db):
    """task_state 当前为 succeeded（终态，无合法出边）→ 审核通过静默跳过，
    不抛 InvalidTransition，审核自身行为不受影响。"""
    from prism_core.review_queue import approve_review

    artifact_id = "art_l2_2_illegal_001"
    pt_id = _insert_publish_task(
        isolated_db,
        celery_task_id="celery_l2_2_illegal_001",
        artifact_id=artifact_id,
        material_id="mat_l2_2_illegal_001",
    )
    # 终态：succeeded 无法推进到 approved
    _insert_task_state(
        isolated_db,
        task_id=str(pt_id),
        status="succeeded",
        material_id="mat_l2_2_illegal_001",
    )
    review_id = "rv_l2_2_illegal_001"
    _insert_review_item(isolated_db, review_id=review_id, task_id=artifact_id)

    # 不抛异常
    decision = approve_review(review_id, "reviewer_001", "补审通过")
    assert decision is not None
    assert decision.decision == "approved"

    # task_state 保持原状
    assert _get_task_state_status(isolated_db, str(pt_id)) == "succeeded"

    # 审核自身行为不受影响
    conn = _open(isolated_db)
    try:
        row = conn.execute(
            "SELECT status FROM review_queue WHERE review_id = ?", (review_id,)
        ).fetchone()
        assert row is not None
        assert row[0] == "approved"
    finally:
        conn.close()


def test_approve_review_when_task_state_missing_silently_skipped(isolated_db):
    """publish_tasks 存在（有 artifact_id）但 task_states 无对应行 → 静默跳过，
    审核通过本身正常落库。"""
    from prism_core.review_queue import approve_review

    artifact_id = "art_l2_2_missing_state_001"
    _insert_publish_task(
        isolated_db,
        celery_task_id="celery_l2_2_missing_state_001",
        artifact_id=artifact_id,
        material_id="mat_l2_2_missing_state_001",
    )
    # 故意不插 task_states 行
    review_id = "rv_l2_2_missing_state_001"
    _insert_review_item(isolated_db, review_id=review_id, task_id=artifact_id)

    decision = approve_review(review_id, "reviewer_001", "内容合规")
    assert decision is not None
    assert decision.decision == "approved"

    conn = _open(isolated_db)
    try:
        row = conn.execute(
            "SELECT status FROM review_queue WHERE review_id = ?", (review_id,)
        ).fetchone()
        assert row is not None
        assert row[0] == "approved"
    finally:
        conn.close()
