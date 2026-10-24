"""L2-1: AI 生图产物自动登记进素材库测试。

背景：
  前端断链 #1（`.superpowers/sdd/valkyrie-gamora-big-barda/module-link-frontend.md` §D1）：
  「AI 生图不写 /api/v1/files，素材库永不见」。
  根因：`fusion_ai/ai_design.py::POST /ai-design/generate` 生成成功后只登记
  `artifacts`（统一产物总线）+ 写 `image_generations` 记录，**从不落 `file_records`**。
  而素材库页 `/api/materials` → `/api/v1/files` 只读 `file_records`。

本任务契约（TDD 先测后码）：
  ① `file_records` 补齐 `artifact_id` / `source` 两列（幂等 ALTER，schema.py 收口）
  ② 新增 `_register_file_record_for_generation` 同步 INSERT（不 probe 视频元数据、不阻塞）
  ③ 记录字段完整（filename / file_path / filesize_mb / source='ai_image' /
     artifact_id / note / group_name / title）
  ④ 幂等：同 artifact_id 不重复登记；artifact_id 缺失时按 (file_path, source) 去重
  ⑤ 端到端：POST /ai-design/generate 生图成功 → file_records 新增对应行
  ⑥ TestClient GET /api/v1/files/ 素材库列表能查到该记录

隔离策略：
  - 临时 sqlite 库文件（tmp_path）+ 临时 VIDEO_FILES_DIR
  - monkeypatch `settings.DATABASE_PATH` / `settings.VIDEO_FILES_DIR`
  - 替换 `fastapi_app.api.v1.files.router.main_db_pool` 指向临时库
  - 复用 test_m1_ai_design.py 的 MockCloud + MockProvider 模式

运行：
  cd prism_backend && ../prismenv/Scripts/python.exe -m pytest tests/test_l2_image_to_library.py -q
"""
from __future__ import annotations

import base64
import os
import sqlite3
import sys
import time
import uuid as _uuid
from pathlib import Path
from typing import Any, Dict, List

# 与 test_m1_ai_design.py 一致：跳过云端 feature flag，避免 HTTP 超时
os.environ.setdefault("FEATURE_FLAGS_DISABLED", "1")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture：隔离的 sqlite 库 + 临时 video 目录
# ---------------------------------------------------------------------------


def _unlink_retry(path: str) -> None:
    for _ in range(5):
        try:
            Path(path).unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.2)


@pytest.fixture()
def tmp_video_dir(tmp_path):
    d = tmp_path / "videoFile"
    d.mkdir()
    return d


@pytest.fixture()
def isolated_env(tmp_path, tmp_video_dir, monkeypatch):
    """把 DB 与素材落盘目录指到 tmp 目录，并跑一次 bootstrap。

    返回 `(db_path, main_pool)` —— 供测试直接读断言。
    """
    db_path = str(tmp_path / "test.db")

    from fastapi_app.core import config as _config
    from fastapi_app.db import schema
    from fastapi_app.db.session import ConnectionPool

    monkeypatch.setattr(_config.settings, "DATABASE_PATH", db_path)
    monkeypatch.setattr(_config.settings, "VIDEO_FILES_DIR", str(tmp_video_dir))

    # Bootstrap 建齐所有表（含 file_records 的 artifact_id / source 列）
    conn = sqlite3.connect(db_path)
    try:
        schema.ensure_all_tables(conn)
        conn.commit()
    finally:
        conn.close()

    # 替换 files router 用的 main_db_pool，指向临时库
    new_pool = ConnectionPool(db_path, pool_size=2)
    import fastapi_app.api.v1.files.router as files_router_mod
    monkeypatch.setattr(files_router_mod, "main_db_pool", new_pool)

    yield db_path, new_pool

    try:
        new_pool.close_all()
    except Exception:
        pass


def _open_tmp_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _write_local_image(video_dir: Path, rel_path: str, size: int = 1024) -> None:
    """在 VIDEO_FILES_DIR 下写一个假 PNG 供测试使用。"""
    full = video_dir / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"0" * max(0, size - 8)))


# ---------------------------------------------------------------------------
# Mock：云端积分 + AI provider（复用 test_m1_ai_design.py 结构，做 data: URL）
# ---------------------------------------------------------------------------


class MockCloud:
    """内存版 /cloud/points/* mock，与 test_m1_ai_design.py 同结构。"""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self._tx = 0
        self.frozen: Dict[int, float] = {}

    def __call__(
        self, method, url, *, headers=None, json=None, timeout=None, **_
    ) -> Dict[str, Any]:
        self.calls.append({"method": method, "url": url, "json": json})
        path = url.split("/cloud/")[-1]
        if method.upper() == "GET" and path == "points/pricing":
            return {"status_code": 200, "data": {
                "pricingVersion": "mock",
                "items": [{
                    "pricingKey": "aiImageGeneration", "points": 10,
                    "displayName": "ai", "category": "ai_design",
                    "enabled": True, "sortOrder": 0,
                }],
            }}
        if method.upper() == "POST" and path == "points/freeze":
            amt = float(json["amount"])
            self._tx += 1
            fid = self._tx
            self.frozen[fid] = amt
            return {"status_code": 200, "data": {
                "freezeTxId": fid, "amount": amt, "status": "active",
            }}
        if method.upper() == "POST" and path == "points/consume":
            return {"status_code": 200, "data": {
                "freezeTxId": 1, "consumeTxId": 1, "status": "consumed",
            }}
        if method.upper() == "POST" and path == "points/rollback":
            return {"status_code": 200, "data": {
                "freezeTxId": 1, "status": "rolled_back",
            }}
        return {"status_code": 404, "data": {"detail": f"unknown {method} {path}"}}


async def _fake_data_url_provider(model_def, prompt, size):
    """返回 `data:image/png;base64,...` 让 `persist_data_url` 走落盘路径。"""
    b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"A" * 512).decode()
    return {"success": True, "url": f"data:image/png;base64,{b64}"}


def _make_testclient():
    """构造挂 ai_design.router 的 TestClient，注入 mock provider 与 mock 云端。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from fusion_ai import ai_design
    from fusion_ai.points_client import PointsClient

    ai_design.reset_generate_fn()
    ai_design.reset_points_client_provider()
    ai_design.set_generate_fn(_fake_data_url_provider)
    cloud = MockCloud()
    pc = PointsClient(
        base_url="http://cloud.mock",
        token_provider=lambda: "tok",
        transport=cloud,
    )
    ai_design.set_points_client_provider(lambda: pc)
    app = FastAPI()
    app.include_router(ai_design.router)
    return TestClient(app), cloud


# ---------------------------------------------------------------------------
# 契约 ①：schema 列迁移
# ---------------------------------------------------------------------------


def test_file_records_has_artifact_id_and_source_columns(isolated_env):
    db_path, _ = isolated_env
    conn = _open_tmp_conn(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(file_records)").fetchall()}
    finally:
        conn.close()
    assert "artifact_id" in cols, (
        f"file_records 缺 artifact_id 列（L2-1 归因列），实际列集合: {sorted(cols)}"
    )
    assert "source" in cols, (
        f"file_records 缺 source 列（L2-1 来源标记），实际列集合: {sorted(cols)}"
    )


# ---------------------------------------------------------------------------
# 契约 ②③：helper 插入 file_records 字段完整
# ---------------------------------------------------------------------------


def test_register_file_record_inserts_row_with_all_fields(isolated_env, tmp_video_dir):
    from fusion_ai.ai_design import _register_file_record_for_generation

    rel_path = "generated/img_aaaaaaaa.png"
    _write_local_image(tmp_video_dir, rel_path, size=2048)

    file_id = _register_file_record_for_generation(
        local_path=rel_path,
        artifact_id="art_aaaaaaaaaaaa",
        prompt="a cute cat on a rooftop at sunrise",
        model_key="dall-e-3",
        aspect_ratio="1:1",
        media_type="image/png",
    )
    assert isinstance(file_id, int) and file_id > 0, (
        f"helper 应返回新插入的 file_records.id（正整数），实际: {file_id!r}"
    )

    db_path, _ = isolated_env
    conn = _open_tmp_conn(db_path)
    try:
        row = conn.execute(
            "SELECT id, filename, file_path, filesize, status, source, "
            "artifact_id, note, group_name, title FROM file_records WHERE id=?",
            (file_id,),
        ).fetchone()
        assert row is not None, "刚插入的 file_records.id 查不到"
        rec = dict(row)
    finally:
        conn.close()

    # file_path / source / artifact_id：核心链路字段
    assert rec["file_path"] == rel_path, f"file_path 应为相对路径，实际 {rec['file_path']!r}"
    assert rec["source"] == "ai_image", f"source 应为 'ai_image'，实际 {rec['source']!r}"
    assert rec["artifact_id"] == "art_aaaaaaaaaaaa", (
        f"artifact_id 应保留产物总线 ID，实际 {rec['artifact_id']!r}"
    )
    # filename：以 .png 结尾（保留扩展名）
    assert rec["filename"].endswith(".png"), f"filename 应保留扩展名: {rec['filename']!r}"
    # filesize：单位 MB，>= 0
    assert isinstance(rec["filesize"], (int, float)) and rec["filesize"] >= 0
    # status：初始 pending
    assert rec["status"] == "pending"
    # note 含 prompt 片段，title 非空
    assert "cute cat" in (rec["note"] or ""), f"note 应含 prompt 摘要，实际 {rec['note']!r}"
    assert rec["title"], "title 不应为空"


def test_register_file_record_source_marker_is_ai_image(isolated_env, tmp_video_dir):
    """来源标记契约：素材库可按 source='ai_image' 过滤出 AI 生图。"""
    from fusion_ai.ai_design import _register_file_record_for_generation

    _write_local_image(tmp_video_dir, "generated/img_bbbbbbbb.png")
    _register_file_record_for_generation(
        local_path="generated/img_bbbbbbbb.png",
        artifact_id="art_bbbbbbbbbbbb",
        prompt="p",
        model_key="dall-e-3",
        aspect_ratio="1:1",
    )

    db_path, _ = isolated_env
    conn = _open_tmp_conn(db_path)
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM file_records WHERE source='ai_image'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert cnt == 1


# ---------------------------------------------------------------------------
# 契约 ④：幂等
# ---------------------------------------------------------------------------


def test_register_file_record_idempotent_by_artifact_id(isolated_env, tmp_video_dir):
    """同 artifact_id 二次登记 → 返回 None 且不重复插入。"""
    from fusion_ai.ai_design import _register_file_record_for_generation

    rel_path = "generated/img_cccccccccc.png"
    _write_local_image(tmp_video_dir, rel_path)

    id1 = _register_file_record_for_generation(
        local_path=rel_path,
        artifact_id="art_cccccccccccc",
        prompt="p1",
        model_key="dall-e-3",
        aspect_ratio="1:1",
    )
    id2 = _register_file_record_for_generation(
        local_path=rel_path,
        artifact_id="art_cccccccccccc",
        prompt="p2",
        model_key="dall-e-3",
        aspect_ratio="1:1",
    )
    assert id1 is not None and id2 is None, (
        f"同 artifact_id 二次登记应返回 None（幂等），实际 id1={id1}, id2={id2}"
    )

    db_path, _ = isolated_env
    conn = _open_tmp_conn(db_path)
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM file_records WHERE artifact_id='art_cccccccccccc'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert cnt == 1, f"同 artifact_id 应只有一行，实际 {cnt}"


def test_register_file_record_idempotent_by_path_when_no_artifact_id(isolated_env, tmp_video_dir):
    """artifact_id 为 None 时按 (file_path, source) 去重。"""
    from fusion_ai.ai_design import _register_file_record_for_generation

    rel_path = "generated/img_dddddddddd.png"
    _write_local_image(tmp_video_dir, rel_path)

    id1 = _register_file_record_for_generation(
        local_path=rel_path,
        artifact_id=None,
        prompt="p1",
        model_key="dall-e-3",
        aspect_ratio="1:1",
    )
    id2 = _register_file_record_for_generation(
        local_path=rel_path,
        artifact_id=None,
        prompt="p2",
        model_key="dall-e-3",
        aspect_ratio="1:1",
    )
    assert id1 is not None and id2 is None, (
        f"artifact_id=None 时应按 path 去重，实际 id1={id1}, id2={id2}"
    )

    db_path, _ = isolated_env
    conn = _open_tmp_conn(db_path)
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM file_records WHERE file_path=? AND source='ai_image'",
            (rel_path,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert cnt == 1


def test_register_file_record_missing_file_still_registers(isolated_env):
    """目标文件不在磁盘也应登记（仅 filesize 退化 0），不 crash。"""
    from fusion_ai.ai_design import _register_file_record_for_generation

    file_id = _register_file_record_for_generation(
        local_path="generated/missing_eeeeeeee.png",
        artifact_id="art_eeeeeeeeeeee",
        prompt="p",
        model_key="dall-e-3",
        aspect_ratio="1:1",
    )
    assert file_id is not None, "缺失文件也应登记"

    db_path, _ = isolated_env
    conn = _open_tmp_conn(db_path)
    try:
        row = conn.execute(
            "SELECT filesize FROM file_records WHERE id=?", (file_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 0.0, f"文件缺失时 filesize 应退化 0.0，实际 {row[0]!r}"


# ---------------------------------------------------------------------------
# 契约 ⑤：端到端 POST /ai-design/generate 触发 file_records 登记
# ---------------------------------------------------------------------------


def test_generate_endpoint_registers_file_record(isolated_env):
    tc, _ = _make_testclient()
    # 每次运行用独立 idempotency_key，避免命中上一次运行的缓存
    # （cache TTL 24h，跨测试进程共享 Redis/in-memory）
    idem_key = f"l2-endtoend-{_uuid.uuid4().hex[:8]}"
    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3",
        "prompt": "a serene mountain lake at dawn",
        "count": 1,
        "idempotency_key": idem_key,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # 生图应至少产出一张图，且响应带 artifact_ids
    assert body.get("images"), f"响应缺 images 字段: {body}"
    aid_list = body.get("artifact_ids") or []
    assert aid_list, f"响应缺 artifact_ids（应至少 1 个）: {body}"
    first_aid = aid_list[0]
    assert first_aid.startswith("art_"), f"artifact_id 格式异常: {first_aid!r}"

    # file_records 应有对应 source='ai_image' 行
    db_path, _ = isolated_env
    conn = _open_tmp_conn(db_path)
    try:
        row = conn.execute(
            "SELECT id, filename, file_path, source, artifact_id FROM file_records "
            "WHERE source='ai_image' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None, "生图成功后 file_records 应新增 source='ai_image' 记录"
        rec = dict(row)
    finally:
        conn.close()

    assert rec["artifact_id"] == first_aid, (
        f"file_records.artifact_id 应与响应里首张图的 artifact_id 一致，"
        f"期望 {first_aid!r} 实际 {rec['artifact_id']!r}"
    )
    assert rec["file_path"].startswith("generated/"), (
        f"file_path 应以 generated/ 开头，实际 {rec['file_path']!r}"
    )
    assert rec["file_path"].endswith(".png"), (
        f"file_path 应以 .png 结尾（image/png），实际 {rec['file_path']!r}"
    )
    assert rec["filename"].endswith(".png")


def test_generate_endpoint_dedupes_by_artifact_id_across_retries(isolated_env):
    """预置一行 file_records 后再生图，应保留原有行 + 新增一行（互不干扰）。

    同时验证：即使生成流程里 artifact_id 全新，pre-existing 行也不会被覆盖。
    """
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from fusion_ai import ai_design
    from fusion_ai.points_client import PointsClient

    db_path, _ = isolated_env
    conn = _open_tmp_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO file_records (filename, file_path, filesize, upload_time, "
            "status, source, artifact_id) VALUES (?, ?, 0.0, CURRENT_TIMESTAMP, "
            "'pending', 'ai_image', ?)",
            ("existing.png", "generated/existing_aaaaaaaa.png", "art_preaaaaaaaaaaa"),
        )
        conn.commit()
    finally:
        conn.close()

    cloud = MockCloud()
    ai_design.reset_generate_fn()
    ai_design.reset_points_client_provider()
    ai_design.set_generate_fn(_fake_data_url_provider)
    pc = PointsClient(
        base_url="http://cloud.mock",
        token_provider=lambda: "tok",
        transport=cloud,
    )
    ai_design.set_points_client_provider(lambda: pc)
    app = FastAPI()
    app.include_router(ai_design.router)
    tc = TestClient(app)

    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3",
        "prompt": "p",
        "count": 1,
        "idempotency_key": f"l2-coexist-{_uuid.uuid4().hex[:8]}",
    })
    assert resp.status_code == 200, resp.text

    conn = _open_tmp_conn(db_path)
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM file_records WHERE source='ai_image'"
        ).fetchone()[0]
        new_aids = {
            r[0] for r in conn.execute(
                "SELECT artifact_id FROM file_records WHERE source='ai_image'"
            ).fetchall()
        }
    finally:
        conn.close()
    assert cnt == 2, f"预置 1 行 + 生图新 1 行，实际 {cnt}"
    assert "art_preaaaaaaaaaaa" in new_aids, "预置行的 artifact_id 应保留"


# ---------------------------------------------------------------------------
# 契约 ⑥：素材库列表接口能查到 AI 生图记录
# ---------------------------------------------------------------------------


def test_materials_list_endpoint_can_see_ai_image(isolated_env, tmp_video_dir):
    """TestClient 打 GET /api/v1/files/ 断言新登记的 AI 生图记录能被看到。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from fusion_ai.ai_design import _register_file_record_for_generation

    rel_path = "generated/img_listffff.png"
    _write_local_image(tmp_video_dir, rel_path, size=4096)

    file_id = _register_file_record_for_generation(
        local_path=rel_path,
        artifact_id="art_listfffffff0",
        prompt="a stylized portrait of an astronaut",
        model_key="flux-pro",
        aspect_ratio="3:2",
        media_type="image/png",
    )
    assert file_id is not None

    from fastapi_app.api.v1.files.router import router as files_router

    app = FastAPI()
    app.include_router(files_router)
    tc = TestClient(app)

    resp = tc.get("/files/", params={"limit": 100})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body.get("items") or []
    ids = [it["id"] for it in items]
    assert file_id in ids, (
        f"新插入的 AI 生图记录 (id={file_id}) 未出现在素材库列表 GET /api/v1/files/ 中，"
        f"返回 items ids={ids}"
    )


# ---------------------------------------------------------------------------
# 契约 ⑦：素材库列表接口能按 source 过滤（可选）
# ---------------------------------------------------------------------------


def test_file_records_query_by_artifact_id(isolated_env, tmp_video_dir):
    """归因链路：从 artifact_id 反查 file_records 唯一命中。"""
    from fusion_ai.ai_design import _register_file_record_for_generation

    _write_local_image(tmp_video_dir, "generated/img_xxxxxxxx.png")
    _register_file_record_for_generation(
        local_path="generated/img_xxxxxxxx.png",
        artifact_id="art_xxxxxxxxxxxx",
        prompt="p",
        model_key="dall-e-3",
        aspect_ratio="1:1",
    )

    db_path, _ = isolated_env
    conn = _open_tmp_conn(db_path)
    try:
        row = conn.execute(
            "SELECT id, file_path, source, artifact_id FROM file_records "
            "WHERE artifact_id=?",
            ("art_xxxxxxxxxxxx",),
        ).fetchone()
        assert row is not None
        rec = dict(row)
    finally:
        conn.close()

    assert rec["source"] == "ai_image"
    assert rec["file_path"] == "generated/img_xxxxxxxx.png"
    assert rec["artifact_id"] == "art_xxxxxxxxxxxx"
