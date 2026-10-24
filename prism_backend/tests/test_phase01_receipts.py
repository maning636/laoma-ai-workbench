"""Phase 0.1 · 发布回执结构化 —— 盘点既有实现 + 补缺口。

覆盖（对齐 PLAN_verification_measures.md · Phase 0.1 验收标准）：
  1. `PublishReceipt` schema 字段完整性（task_id/status/platform_post_id/published_at/…）
  2. `ReceiptStatus` 枚举完整性（5 值）+ `ErrorCode` 枚举完整性
  3. `build_receipt()` 三状态组合：succeeded / failed_retryable / failed_final
  4. 条件必填校验：succeeded 需 platform_post_id + published_at；
     failed_* 需 error_code（Pydantic ValidationError）
  5. 非法数据 → ValidationError（状态非法、错误码非法）
  6. 集成：FastAPI TestClient GET /api/v1/receipts/{task_id}
     - 已存在 task_id → 200 + 完整 JSON
     - 不存在的 task_id → 404

约定：
  - 用临时 SQLite（monkeypatch settings.DATABASE_PATH），**不污染真实主库**；
  - 集成测试自建最小 FastAPI app（只 include receipts.router），不启 lifespan；
  - 单元测试直接构造对象，不依赖 DB。

用法：
  cd prism_backend && python -m pytest tests/test_phase01_receipts.py -v
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault("FEATURE_FLAGS_DISABLED", "1")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fastapi_app.core.config import settings
from fastapi_app.db.session import open_main_db
from fastapi_app.api.v1.receipts.router import router as receipts_router

from prism_core.receipts import (
    PublishReceipt,
    ReceiptStatus,
    ErrorCode,
    DiagnosticArtifact,
    build_success_receipt,
    build_error_receipt,
    save_receipt,
    get_receipt,
    list_receipts,
)


# ──────────────────────────────────────────────────────────────
# 常量：PLAN Phase 0.1 要求的 schema 字段
# ──────────────────────────────────────────────────────────────

REQUIRED_FIELDS = {
    "task_id",
    "status",
    "platform_post_id",
    "published_at",
    "error_code",
    "retryable",
    "requires_human_action",
}

EXPECTED_STATUSES = {
    ReceiptStatus.SUCCEEDED,
    ReceiptStatus.FAILED_RETRYABLE,
    ReceiptStatus.FAILED_FINAL,
    ReceiptStatus.CANCELLED,
    ReceiptStatus.RUNNING,
}


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """把主库切到临时 SQLite，避免污染真实数据目录。"""
    db_path = tmp_path / "receipts_test.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))
    # 保证表结构存在（save/get/list 内部会 _ensure_receipt_table，双保险）
    conn = open_main_db()
    conn.close()
    yield db_path


@pytest.fixture
def app():
    """最小 FastAPI app，只 include receipts 路由（不启 lifespan）。"""
    app = FastAPI()
    app.include_router(receipts_router, prefix="/api/v1")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ──────────────────────────────────────────────────────────────
# 1. Schema 字段完整性
# ──────────────────────────────────────────────────────────────

class TestSchemaFields:
    def test_publish_receipt_has_all_required_fields(self):
        """PLAN：task_id/status/platform_post_id/published_at 必填；
        error_code/retryable/requires_human_action 条件必填（字段必须存在）。"""
        model_fields = set(PublishReceipt.model_fields.keys())
        missing = REQUIRED_FIELDS - model_fields
        assert not missing, f"PublishReceipt 缺少 PLAN 要求的字段: {missing}"

    def test_receipt_status_enum_complete(self):
        assert set(ReceiptStatus) == EXPECTED_STATUSES
        assert {s.value for s in ReceiptStatus} == {
            "succeeded",
            "failed_retryable",
            "failed_final",
            "cancelled",
            "running",
        }

    def test_error_code_enum_has_core_values(self):
        vals = {e.value for e in ErrorCode}
        for expected in (
            "COOKIE_EXPIRED",
            "LOGIN_REQUIRED",
            "RATE_LIMITED",
            "CAPTCHA_REQUIRED",
            "UPLOAD_TIMEOUT",
            "INTERNAL_ERROR",
        ):
            assert expected in vals

    def test_diagnostic_artifact_fields(self):
        """PLAN Phase 2.2 也依赖 artifacts 结构；此处只锁 Phase 0.1 相关字段。"""
        fields = set(DiagnosticArtifact.model_fields.keys())
        assert {"screenshot_path", "dom_path", "log_path"} <= fields

    def test_default_factory_assigns_task_id(self):
        """task_id 默认生成，不传也能构造（内部系统用）。"""
        r = PublishReceipt()
        assert r.task_id.startswith("task_")
        assert len(r.task_id) > 5

    def test_full_valid_receipt_constructs(self):
        """succeeded 状态 + 全部 PLAN 必填字段 → 直接构造不抛异常。"""
        r = PublishReceipt(
            task_id="task_full_ok",
            status=ReceiptStatus.SUCCEEDED,
            platform=3,
            platform_name="douyin",
            account_id="acc_1",
            platform_post_id="post_123",
            published_at="2026-10-24T12:00:00+08:00",
            retryable=False,
            requires_human_action=False,
        )
        assert r.status == ReceiptStatus.SUCCEEDED
        assert r.platform_post_id == "post_123"
        assert r.published_at == "2026-10-24T12:00:00+08:00"


# ──────────────────────────────────────────────────────────────
# 2. 条件必填校验（Pydantic ValidationError）
# ──────────────────────────────────────────────────────────────

class TestConditionalValidation:
    def test_succeeded_requires_platform_post_id(self):
        with pytest.raises(ValidationError):
            PublishReceipt(
                status=ReceiptStatus.SUCCEEDED,
                platform_post_id=None,
                published_at="2026-10-24T12:00:00+08:00",
            )

    def test_succeeded_requires_published_at(self):
        with pytest.raises(ValidationError):
            PublishReceipt(
                status=ReceiptStatus.SUCCEEDED,
                platform_post_id="post_1",
                published_at=None,
            )

    def test_failed_retryable_requires_error_code(self):
        with pytest.raises(ValidationError):
            PublishReceipt(status=ReceiptStatus.FAILED_RETRYABLE, error_code=None)

    def test_failed_final_requires_error_code(self):
        with pytest.raises(ValidationError):
            PublishReceipt(status=ReceiptStatus.FAILED_FINAL, error_code=None)

    def test_running_and_cancelled_do_not_require_error_code(self):
        # 非终态/取消态不带 error_code 也不应报错
        PublishReceipt(status=ReceiptStatus.RUNNING)
        PublishReceipt(status=ReceiptStatus.CANCELLED)


# ──────────────────────────────────────────────────────────────
# 3. 非法数据 → ValidationError（pydantic 422 等价物）
# ──────────────────────────────────────────────────────────────

class TestIllegalData:
    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            PublishReceipt(status="not_a_status")

    def test_invalid_error_code_raises(self):
        with pytest.raises(ValidationError):
            PublishReceipt(
                status=ReceiptStatus.FAILED_FINAL,
                error_code="NOT_A_REAL_CODE",
            )

    def test_negative_attempt_raises_if_validated(self):
        # attempt 语义上 >= 0；负值必须被 pydantic 拒绝
        with pytest.raises(ValidationError):
            PublishReceipt(attempt=-1)


# ──────────────────────────────────────────────────────────────
# 4. build_receipt() 三状态组合
# ──────────────────────────────────────────────────────────────

class TestBuildReceiptFactory:
    def test_build_receipt_succeeded(self):
        from prism_core.receipts import build_receipt

        r = build_receipt(
            status="succeeded",
            platform=3,
            platform_name="douyin",
            account_id="acc_1",
            platform_post_id="post_456",
            video_url="https://example/v.mp4",
        )
        assert isinstance(r, PublishReceipt)
        assert r.status == ReceiptStatus.SUCCEEDED
        assert r.platform_post_id == "post_456"
        assert r.published_at, "succeeded 回执必须带 published_at"
        assert r.error_code is None
        assert r.retryable is False
        assert r.requires_human_action is False

    def test_build_receipt_failed_retryable(self):
        from prism_core.receipts import build_receipt

        r = build_receipt(
            status="failed_retryable",
            platform=3,
            platform_name="douyin",
            account_id="acc_1",
            error_code="UPLOAD_TIMEOUT",
            error_message="上传超时",
        )
        assert r.status == ReceiptStatus.FAILED_RETRYABLE
        assert r.error_code == ErrorCode.UPLOAD_TIMEOUT
        assert r.retryable is True
        assert r.requires_human_action is False

    def test_build_receipt_failed_final(self):
        from prism_core.receipts import build_receipt

        r = build_receipt(
            status="failed_final",
            platform=3,
            platform_name="douyin",
            account_id="acc_1",
            error_code="CAPTCHA_REQUIRED",
            error_message="需要人工介入",
            requires_human_action=True,
            artifacts=DiagnosticArtifact(screenshot_path="/tmp/a.png"),
        )
        assert r.status == ReceiptStatus.FAILED_FINAL
        assert r.error_code == ErrorCode.CAPTCHA_REQUIRED
        assert r.retryable is False
        assert r.requires_human_action is True
        assert r.artifacts is not None
        assert r.artifacts.screenshot_path == "/tmp/a.png"

    def test_build_receipt_succeeded_without_post_id_raises(self):
        """工厂应拒绝构造缺少关键字段的 succeeded 回执。"""
        from prism_core.receipts import build_receipt

        with pytest.raises((ValueError, ValidationError)):
            build_receipt(
                status="succeeded",
                platform=3,
                platform_name="douyin",
                account_id="acc_1",
                # platform_post_id 缺失
            )

    def test_build_receipt_failed_without_error_code_raises(self):
        from prism_core.receipts import build_receipt

        with pytest.raises((ValueError, ValidationError)):
            build_receipt(
                status="failed_final",
                platform=3,
                platform_name="douyin",
                account_id="acc_1",
                # error_code 缺失
            )

    def test_existing_builders_still_work(self):
        """向后兼容：既有 build_success_receipt / build_error_receipt 仍可用。"""
        s = build_success_receipt(
            platform=3, platform_name="douyin", account_id="acc_1",
            platform_post_id="p1",
        )
        assert s.status == ReceiptStatus.SUCCEEDED

        e = build_error_receipt(
            platform=3, platform_name="douyin", account_id="acc_1",
            error_code=ErrorCode.UPLOAD_TIMEOUT,
            error_message="x",
            retryable=True,
        )
        assert e.status == ReceiptStatus.FAILED_RETRYABLE


# ──────────────────────────────────────────────────────────────
# 5. 持久化 + 查询（内存 SQLite 隔离）
# ──────────────────────────────────────────────────────────────

class TestPersistence:
    def test_save_and_get_receipt_roundtrip(self, isolated_db):
        r = PublishReceipt(
            task_id="task_rt_1",
            status=ReceiptStatus.SUCCEEDED,
            platform=3,
            platform_name="douyin",
            account_id="acc_1",
            platform_post_id="post_789",
            published_at="2026-10-24T12:00:00+08:00",
        )
        save_receipt(r)
        got = get_receipt("task_rt_1")
        assert got is not None
        assert got.task_id == "task_rt_1"
        assert got.status == ReceiptStatus.SUCCEEDED
        assert got.platform_post_id == "post_789"

    def test_get_missing_returns_none(self, isolated_db):
        assert get_receipt(f"task_does_not_exist_{uuid.uuid4().hex[:8]}") is None

    def test_list_receipts_filters_by_status(self, isolated_db):
        save_receipt(PublishReceipt(
            task_id="task_l_a",
            status=ReceiptStatus.SUCCEEDED,
            platform_post_id="p_a",
            published_at="2026-10-24T12:00:00+08:00",
        ))
        save_receipt(PublishReceipt(
            task_id="task_l_b",
            status=ReceiptStatus.FAILED_FINAL,
            error_code=ErrorCode.UPLOAD_TIMEOUT,
        ))
        items = list_receipts(status="succeeded", limit=10)
        assert all(i.status == ReceiptStatus.SUCCEEDED for i in items)
        # 至少能看到我们保存的那条
        assert any(i.task_id == "task_l_a" for i in items)


# ──────────────────────────────────────────────────────────────
# 6. 集成：router GET /api/v1/receipts/{task_id}
# ──────────────────────────────────────────────────────────────

class TestRouterIntegration:
    def test_get_existing_receipt_returns_full_json(self, isolated_db, client):
        r = PublishReceipt(
            task_id="task_http_ok",
            status=ReceiptStatus.SUCCEEDED,
            platform=3,
            platform_name="douyin",
            account_id="acc_1",
            platform_post_id="post_abc",
            published_at="2026-10-24T12:00:00+08:00",
            video_url="https://example/v.mp4",
            attempt=2,
            idempotency_key="cmp:1:v1:a",
        )
        save_receipt(r)

        resp = client.get("/api/v1/receipts/task_http_ok")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # PLAN 验收：200 + 完整 JSON
        for field in (
            "task_id", "status", "platform", "platform_name", "account_id",
            "platform_post_id", "published_at", "video_url",
            "error_code", "error_message", "retryable",
            "requires_human_action", "attempt", "idempotency_key",
            "created_at", "updated_at",
        ):
            assert field in body, f"响应缺少字段 {field}"
        assert body["task_id"] == "task_http_ok"
        assert body["status"] == "succeeded"
        assert body["platform_post_id"] == "post_abc"
        assert body["published_at"] == "2026-10-24T12:00:00+08:00"
        assert body["attempt"] == 2
        assert body["idempotency_key"] == "cmp:1:v1:a"
        assert body["error_code"] is None
        assert body["retryable"] is False
        assert body["requires_human_action"] is False

    def test_get_missing_receipt_returns_404(self, isolated_db, client):
        resp = client.get("/api/v1/receipts/task_no_such_id")
        assert resp.status_code == 404

    def test_get_failed_receipt_returns_error_fields(self, isolated_db, client):
        r = PublishReceipt(
            task_id="task_http_fail",
            status=ReceiptStatus.FAILED_RETRYABLE,
            platform=3,
            platform_name="douyin",
            account_id="acc_1",
            error_code=ErrorCode.UPLOAD_TIMEOUT,
            error_message="上传超时",
            retryable=True,
            requires_human_action=False,
        )
        save_receipt(r)

        resp = client.get("/api/v1/receipts/task_http_fail")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "failed_retryable"
        assert body["error_code"] == "UPLOAD_TIMEOUT"
        assert body["retryable"] is True
        assert body["error_message"] == "上传超时"
