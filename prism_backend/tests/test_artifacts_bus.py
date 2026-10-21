"""统一产物总线 后端测试（自运行，不启动服务）。

覆盖：
  1. artifacts 建表 + publish_tasks.artifact_id 列（schema.py 唯一真源）
  2. 产物登记：art_ 前缀 ID、幂等键 (ref_type|ref_id|path)
  3. 一次生图 count>1 → 同 ref_id 不同 path 产生多个产物
  4. 阶段机：合法流转 / 非法流转被拒
  5. 送审 → 审核 → 阶段回写（approved / rejected）
  6. 反查：ref → 产物、review_id → 产物
  7. 血缘：父链 / 子链
  8. ReviewItem.created_at 缺失导致送审 500 的回归防护

约定：
  - 用临时 SQLite（monkeypatch settings.DATABASE_PATH），**不污染真实主库**；
  - 风格对齐 tests/test_m1_ai_design.py（check + 计数）。

用法：
  cd prism_backend && python -m pytest tests/test_artifacts_bus.py -q
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("FEATURE_FLAGS_DISABLED", "1")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402
from fastapi_app.core.config import settings  # noqa: E402


_FAILS = 0
_PASSES = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global _FAILS, _PASSES
    tag = "PASS" if cond else "FAIL"
    suffix = f" — {extra}" if extra else ""
    print(f"[{tag}] {label}{suffix}")
    if cond:
        _PASSES += 1
    else:
        _FAILS += 1


@pytest.fixture()
def artifact_env(tmp_path, monkeypatch):
    """把主库指向临时 SQLite，并建好 schema。"""
    db_path = tmp_path / "artifacts_test.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))

    from fastapi_app.db.schema import ensure_main_db_schema
    from fastapi_app.db.session import open_main_db

    conn = open_main_db()
    ensure_main_db_schema(conn)
    conn.close()
    return db_path


# ──────────────────────────────────────────────────────────────
# 1. schema
# ──────────────────────────────────────────────────────────────


def test_01_artifacts_table_and_publish_task_column(artifact_env):
    from fastapi_app.db.session import open_main_db

    conn = open_main_db()
    tbl = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'"
    ).fetchone()
    check("artifacts 表已建", tbl is not None)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(publish_tasks)").fetchall()}
    check("publish_tasks.artifact_id 列已建", "artifact_id" in cols)
    conn.close()


# ──────────────────────────────────────────────────────────────
# 2-4. 登记 / 幂等 / 阶段机
# ──────────────────────────────────────────────────────────────


def test_02_register_returns_art_id_and_is_idempotent(artifact_env):
    from prism_core import artifacts as art

    a1 = art.register_artifact(
        source=art.SOURCE_UPLOAD, ref_type="file_record", ref_id="42",
        path="42.mp4", kind=art.KIND_VIDEO, stage=art.STAGE_UPLOADED,
    )
    check("登记返回 art_ 前缀 ID", bool(a1) and a1.startswith("art_"), str(a1))
    check("artifact_id 长度 16（art_ + 12 hex）", bool(a1) and len(a1) == 16, str(a1))

    a2 = art.register_artifact(
        source=art.SOURCE_UPLOAD, ref_type="file_record", ref_id="42",
        path="42.mp4", kind=art.KIND_VIDEO, stage=art.STAGE_UPLOADED,
    )
    check("重复登记幂等（同 ref+path → 同 ID）", a1 == a2, f"{a1} vs {a2}")


def test_03_same_ref_different_path_yields_distinct_artifacts(artifact_env):
    """一次生图 count>1：共享同一个 image_generations.id，但 path 不同 → 两个产物。"""
    from prism_core import artifacts as art

    a = art.register_artifact(
        source=art.SOURCE_IMAGE_GEN, ref_type="image_generation", ref_id="77",
        path="https://cdn.example/a.png", kind=art.KIND_IMAGE,
    )
    b = art.register_artifact(
        source=art.SOURCE_IMAGE_GEN, ref_type="image_generation", ref_id="77",
        path="https://cdn.example/b.png", kind=art.KIND_IMAGE,
    )
    check("同 ref_id 不同 path → 不同产物", a != b, f"{a} vs {b}")


def test_04_stage_machine_transitions(artifact_env):
    from prism_core import artifacts as art

    check("uploaded→reviewing 合法",
          art.can_transition(art.STAGE_UPLOADED, art.STAGE_REVIEWING))
    check("reviewing→approved 合法",
          art.can_transition(art.STAGE_REVIEWING, art.STAGE_APPROVED))
    check("published→reviewing 非法",
          not art.can_transition(art.STAGE_PUBLISHED, art.STAGE_REVIEWING))

    aid = art.register_artifact(
        source=art.SOURCE_MANUAL, ref_type="manual", ref_id="m1",
        path="m1.png", kind=art.KIND_IMAGE, stage=art.STAGE_GENERATED,
    )
    ok = art.set_stage(aid, art.STAGE_PUBLISHED, force=True)
    check("force=True 可强制推进", ok)
    bad = art.set_stage(aid, art.STAGE_REVIEWING)
    row = art.get_artifact(aid)
    check("非法流转被拒绝且不改写阶段",
          (not bad) and row["stage"] == art.STAGE_PUBLISHED, str(row["stage"]))


# ──────────────────────────────────────────────────────────────
# 5. 送审 → 审核 → 阶段回写
# ──────────────────────────────────────────────────────────────


def test_05_review_item_has_created_at(artifact_env):
    """回归防护：ReviewItem 缺 created_at 时 enqueue_review 会 AttributeError（送审 500）。"""
    from prism_core.review_queue import ReviewItem

    item = ReviewItem(task_id="art_x", title="t", content="c")
    check("ReviewItem 具备 created_at 字段", hasattr(item, "created_at"))
    check("created_at 默认非空", bool(getattr(item, "created_at", "")))


def test_06_submit_review_then_approve_writes_back_approved(artifact_env):
    from prism_core import artifacts as art
    from prism_core.review_queue import (
        ReviewItem, approve_review, enqueue_review,
    )

    aid = art.register_artifact(
        source=art.SOURCE_UPLOAD, ref_type="file_record", ref_id="101",
        path="101.png", kind=art.KIND_IMAGE, stage=art.STAGE_UPLOADED,
    )
    item = ReviewItem(task_id=aid, title="送审标题", content="送审内容")
    enqueue_review(item)
    art.attach_review(aid, item.review_id)

    row = art.get_artifact(aid)
    check("送审后 stage=reviewing", row["stage"] == art.STAGE_REVIEWING, row["stage"])
    check("送审后回填 review_id", row["review_id"] == item.review_id)

    approve_review(item.review_id, "tester", "通过")
    row = art.get_artifact(aid)
    check("审核通过后 stage=approved", row["stage"] == art.STAGE_APPROVED, row["stage"])


def test_07_submit_review_then_reject_writes_back_rejected(artifact_env):
    from prism_core import artifacts as art
    from prism_core.review_queue import ReviewItem, enqueue_review, reject_review

    aid = art.register_artifact(
        source=art.SOURCE_UPLOAD, ref_type="file_record", ref_id="102",
        path="102.png", kind=art.KIND_IMAGE, stage=art.STAGE_UPLOADED,
    )
    item = ReviewItem(task_id=aid, title="送审标题", content="送审内容")
    enqueue_review(item)
    art.attach_review(aid, item.review_id)
    reject_review(item.review_id, "tester", "拒绝")

    row = art.get_artifact(aid)
    check("审核拒绝后 stage=rejected", row["stage"] == art.STAGE_REJECTED, row["stage"])


def test_08_review_decision_writeback_via_review_id_only(artifact_env):
    """即使审核项的 task_id 不是 art_xxx，也能凭 review_id 找回产物并回写。"""
    from prism_core import artifacts as art
    from prism_core.review_queue import ReviewItem, approve_review, enqueue_review

    aid = art.register_artifact(
        source=art.SOURCE_UPLOAD, ref_type="file_record", ref_id="103",
        path="103.png", kind=art.KIND_IMAGE, stage=art.STAGE_UPLOADED,
    )
    item = ReviewItem(task_id="legacy-task-1", title="旧链路送审")
    enqueue_review(item)
    art.attach_review(aid, item.review_id)
    approve_review(item.review_id, "tester", "通过")

    row = art.get_artifact(aid)
    check("凭 review_id 回写 stage=approved", row["stage"] == art.STAGE_APPROVED, row["stage"])


# ──────────────────────────────────────────────────────────────
# 6-7. 反查与血缘
# ──────────────────────────────────────────────────────────────


def test_09_lookup_by_ref_and_by_review_id(artifact_env):
    from prism_core import artifacts as art

    aid = art.register_artifact(
        source=art.SOURCE_UPLOAD, ref_type="file_record", ref_id="200",
        path="200.png", kind=art.KIND_IMAGE, stage=art.STAGE_UPLOADED,
    )
    found = art.find_artifacts_by_ref("file_record", "200")
    check("按 ref 反查命中", len(found) == 1 and found[0]["artifact_id"] == aid)

    art.attach_review(aid, "rv_test_1")
    by_review = art.find_artifact_by_review_id("rv_test_1")
    check("按 review_id 反查命中", bool(by_review) and by_review["artifact_id"] == aid)


def test_10_lineage_parent_and_children(artifact_env):
    from prism_core import artifacts as art

    parent = art.register_artifact(
        source=art.SOURCE_MANUAL, ref_type="manual", ref_id="p1",
        path="p1.png", kind=art.KIND_IMAGE, stage=art.STAGE_GENERATED,
    )
    child = art.register_artifact(
        source=art.SOURCE_MANUAL, ref_type="manual", ref_id="c1",
        path="c1.png", kind=art.KIND_IMAGE, stage=art.STAGE_GENERATED,
        parent_id=parent,
    )
    lin_parent = art.lineage(parent)
    lin_child = art.lineage(child)
    check("父产物子链包含 child",
          any(c["artifact_id"] == child for c in lin_parent["children"]))
    check("子产物父链指向 parent",
          bool(lin_child["parent"]) and lin_child["parent"]["artifact_id"] == parent)


# ──────────────────────────────────────────────────────────────
# 8. 产物中心 API 路由（用 TestClient，不连真实服务）
# ──────────────────────────────────────────────────────────────


def test_11_artifacts_api_routes(artifact_env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from fastapi_app.api.v1.artifacts.router import router as artifacts_router

    app = FastAPI()
    app.include_router(artifacts_router, prefix="/api/v1")
    tc = TestClient(app)

    resp = tc.post("/api/v1/artifacts", json={
        "source": "manual", "ref_type": "manual", "ref_id": "api-1",
        "path": "api-1.png", "kind": "image", "title": "接口登记",
    })
    check("POST /artifacts 返回 201", resp.status_code == 201, str(resp.status_code))
    artifact_id = resp.json().get("artifact_id", "")

    listing = tc.get("/api/v1/artifacts")
    check("GET /artifacts 返回 200", listing.status_code == 200)
    check("列表包含刚登记的产物",
          any(i["artifact_id"] == artifact_id for i in listing.json()["items"]))

    detail = tc.get(f"/api/v1/artifacts/{artifact_id}")
    check("GET /artifacts/{id} 返回 200", detail.status_code == 200)
    check("详情含 lineage", "lineage" in detail.json())

    stats = tc.get("/api/v1/artifacts/stats")
    check("GET /artifacts/stats 返回 200", stats.status_code == 200)
    check("统计含 by_stage", "by_stage" in stats.json())

    submit = tc.post(f"/api/v1/artifacts/{artifact_id}/submit-review", json={"title": "送审"})
    check("POST submit-review 返回 201", submit.status_code == 201, str(submit.status_code))
    check("submit-review 返回 review_id", bool(submit.json().get("review_id")))

    approve = tc.post(
        f"/api/v1/review/items/{submit.json()['review_id']}/approve",
        json={"reviewer": "tester", "reason": "ok"},
    )
    check("审核通过返回 200", approve.status_code == 200, str(approve.status_code))
    check("审核响应带 artifact_stage=approved",
          approve.json().get("artifact_stage") == "approved",
          str(approve.json().get("artifact_stage")))

    missing = tc.get("/api/v1/artifacts/art_notexists")
    check("不存在的产物返回 404", missing.status_code == 404, str(missing.status_code))


if __name__ == "__main__":
    print(f"\n=== 产物总线测试：{_PASSES} 通过 / {_FAILS} 失败 ===")
    raise SystemExit(0 if _FAILS == 0 else 1)
