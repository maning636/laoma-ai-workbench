"""模型供应商注册表 —— 后端测试（TDD）。

覆盖：
  1. Schema 表结构（model_providers）
  2. CRUD 全路径：创建 / 重名 409 / 更新 / 删除 / 被引用删除 409
  3. POST /test-connection（mock HTTP，成功/失败）
  4. GET /models（mock HTTP，成功/鉴权失败/错误）
  5. POST /apply-to/{service_type} 写入 ai_model_configs
  6. GET /model-configs/{service_type}/provider-link（软匹配/未匹配）
  7. api_key 输出打码（sk-****尾4位）

约定：
  - TestClient + tmp_path 临时 SQLite，不污染真实库
  - 自建最小 FastAPI app，只 include ai.router（不启 lifespan）
  - HTTP 外呼用 monkeypatch httpx.AsyncClient 拦截，不发真实请求
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("FEATURE_FLAGS_DISABLED", "1")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.core.config import settings
from fastapi_app.api.v1.ai.router import router as ai_router
from fastapi_app.api.v1.ai.providers_router import (
    router as ai_providers_router,
    model_configs_link_router as ai_model_configs_link_router,
)


# ---------------------------------------------------------------------------
# DB schema helpers
# ---------------------------------------------------------------------------

_AI_MODEL_CONFIGS_SCHEMA = """
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

_MODEL_PROVIDERS_SCHEMA = """
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


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """把主库切到临时 SQLite，并预建 ai_model_configs + model_providers 表。"""
    db_path = tmp_path / "providers_test.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))
    # 确保 tests 走 sqlite 分支而不是 mysql
    monkeypatch.setattr(settings, "DATABASE_URL", "")
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_AI_MODEL_CONFIGS_SCHEMA)
    conn.executescript(_MODEL_PROVIDERS_SCHEMA)
    conn.commit()
    conn.close()
    yield db_path


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(ai_router, prefix="/api/v1")
    app.include_router(ai_providers_router, prefix="/api/v1")
    app.include_router(ai_model_configs_link_router, prefix="/api/v1")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# HTTP mock 基础设施（拦截 httpx.AsyncClient，不发真实请求）
# ---------------------------------------------------------------------------

class _MockResponse:
    def __init__(self, status_code: int, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text or json.dumps(self._json, ensure_ascii=False)

    def json(self):
        return self._json


class _MockAsyncClient:
    """最小 httpx.AsyncClient 替身，支持 async with + get/post。"""

    # 类属性，测试可覆盖
    default_get_response: _MockResponse | None = None
    default_post_response: _MockResponse | None = None
    call_log: list[dict] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self._started = False

    async def __aenter__(self):
        self._started = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None, **kwargs):
        _MockAsyncClient.call_log.append(
            {"method": "GET", "url": url, "headers": headers or {}, "kwargs": kwargs}
        )
        if _MockAsyncClient.default_get_response is not None:
            return _MockAsyncClient.default_get_response
        return _MockResponse(200, {"data": []})

    async def post(self, url, headers=None, json=None, **kwargs):
        _MockAsyncClient.call_log.append(
            {"method": "POST", "url": url, "headers": headers or {}, "kwargs": kwargs}
        )
        if _MockAsyncClient.default_post_response is not None:
            return _MockAsyncClient.default_post_response
        return _MockResponse(200, {"choices": [{"message": {"content": "pong"}}]})


@pytest.fixture
def mock_httpx(monkeypatch):
    """把 httpx.AsyncClient 换成 mock；每个测试前重置响应与日志。"""
    _MockAsyncClient.default_get_response = None
    _MockAsyncClient.default_post_response = None
    _MockAsyncClient.call_log = []
    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)
    yield _MockAsyncClient
    _MockAsyncClient.default_get_response = None
    _MockAsyncClient.default_post_response = None
    _MockAsyncClient.call_log = []


# ---------------------------------------------------------------------------
# 1. Schema 表结构
# ---------------------------------------------------------------------------

class TestSchema:
    def test_model_providers_table_has_required_columns(self, isolated_db):
        conn = sqlite3.connect(str(isolated_db))
        cursor = conn.execute("PRAGMA table_info(model_providers)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        required = {
            "id", "name", "base_url", "api_key",
            "enabled", "remark", "available_models",
            "created_at", "updated_at",
        }
        assert required.issubset(cols), f"缺少列：{required - cols}"

    def test_sa_models_defines_model_providers(self):
        from fastapi_app.db.sa_models import model_providers
        assert model_providers.name == "model_providers"
        col_names = {c.name for c in model_providers.columns}
        assert {"id", "name", "base_url", "api_key", "enabled"}.issubset(col_names)


# ---------------------------------------------------------------------------
# 2. CRUD
# ---------------------------------------------------------------------------

class TestCRUD:
    def test_create_provider(self, isolated_db, client):
        r = client.post("/api/v1/ai/providers", json={
            "name": "SiliconFlow",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "sk-sf-abcdef1234567890",
            "remark": "生产主通道",
        })
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body["status"] == "success"
        data = body["data"]
        assert data["id"] > 0
        assert data["name"] == "SiliconFlow"
        assert data["base_url"] == "https://api.siliconflow.cn/v1"
        # api_key 输出必须打码
        assert data["api_key"] == "sk-****7890"
        assert data["enabled"] is True

    def test_create_duplicate_name_returns_409(self, isolated_db, client):
        payload = {
            "name": "OpenAI",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-openai-1234abcd",
        }
        r1 = client.post("/api/v1/ai/providers", json=payload)
        assert r1.status_code in (200, 201)
        r2 = client.post("/api/v1/ai/providers", json=payload)
        assert r2.status_code == 409
        assert "name" in r2.json().get("detail", "") or "已存在" in r2.json().get("detail", "")

    def test_create_missing_name_returns_4xx(self, isolated_db, client):
        r = client.post("/api/v1/ai/providers", json={"base_url": "https://x.com"})
        assert r.status_code in (400, 422)

    def test_list_providers(self, isolated_db, client):
        client.post("/api/v1/ai/providers", json={
            "name": "A", "base_url": "https://a.example", "api_key": "sk-a-111122223333",
        })
        client.post("/api/v1/ai/providers", json={
            "name": "B", "base_url": "https://b.example", "api_key": "sk-b-aaaaaaaaaaaa",
        })
        r = client.get("/api/v1/ai/providers")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert len(body["data"]) == 2
        names = {p["name"] for p in body["data"]}
        assert names == {"A", "B"}
        # 每条返回都带 masked key
        for p in body["data"]:
            assert p["api_key"].startswith("sk-****")
            assert p["api_key"].endswith(p["name"] == "A" and "3333" or "aaaa")

    def test_update_provider(self, isolated_db, client):
        create = client.post("/api/v1/ai/providers", json={
            "name": "Old", "base_url": "https://old.example", "api_key": "sk-111111111111",
        }).json()["data"]
        r = client.put(f"/api/v1/ai/providers/{create['id']}", json={
            "name": "New",
            "remark": "备注更新",
            "enabled": False,
        })
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["name"] == "New"
        assert data["remark"] == "备注更新"
        assert data["enabled"] is False
        # 未改的 base_url 保持
        assert data["base_url"] == "https://old.example"

    def test_update_missing_returns_404(self, isolated_db, client):
        r = client.put("/api/v1/ai/providers/99999", json={"name": "X"})
        assert r.status_code == 404

    def test_delete_provider(self, isolated_db, client):
        created = client.post("/api/v1/ai/providers", json={
            "name": "ToDel", "base_url": "https://x.example", "api_key": "sk-del-99999999",
        }).json()["data"]
        r = client.delete(f"/api/v1/ai/providers/{created['id']}")
        assert r.status_code == 200
        # 已删除：再列不再出现
        lst = client.get("/api/v1/ai/providers").json()["data"]
        assert all(p["id"] != created["id"] for p in lst)

    def test_delete_missing_returns_404(self, isolated_db, client):
        r = client.delete("/api/v1/ai/providers/99999")
        assert r.status_code == 404

    def test_delete_referenced_provider_returns_409(self, isolated_db, client):
        # 先建 provider
        created = client.post("/api/v1/ai/providers", json={
            "name": "Referenced",
            "base_url": "https://ref.example/v1",
            "api_key": "sk-ref-abcdef1234567890",
        }).json()["data"]
        # 再把该供应商的三元组写进 ai_model_configs/chat
        client.post("/api/v1/ai/model-configs", json={
            "service_type": "chat",
            "provider": "Referenced",
            "api_key": "sk-ref-abcdef1234567890",
            "base_url": "https://ref.example/v1",
            "model_name": "gpt-4o",
        })
        r = client.delete(f"/api/v1/ai/providers/{created['id']}")
        assert r.status_code == 409
        body = r.json()
        # 409 响应必须带引用列表
        refs = body.get("detail", {}).get("references") or body.get("data", {}).get("references") or []
        if isinstance(refs, list):
            assert any((ref.get("service_type") == "chat") for ref in refs)


# ---------------------------------------------------------------------------
# 3. test-connection
# ---------------------------------------------------------------------------

class TestConnectionEndpoint:
    def test_ok_with_models_endpoint(self, isolated_db, client, mock_httpx):
        # 建 provider
        created = client.post("/api/v1/ai/providers", json={
            "name": "TestProv",
            "base_url": "https://testprov.example/v1",
            "api_key": "sk-tc-000000000000",
        }).json()["data"]
        # mock GET /v1/models
        mock_httpx.default_get_response = _MockResponse(
            200, {"data": [{"id": "m-1"}, {"id": "m-2"}]}
        )
        r = client.post(f"/api/v1/ai/providers/{created['id']}/test-connection")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "success"
        data = body["data"]
        assert data["ok"] is True
        assert isinstance(data["latency_ms"], int)
        assert data["model_count"] == 2

    def test_auth_failure(self, isolated_db, client, mock_httpx):
        created = client.post("/api/v1/ai/providers", json={
            "name": "BadAuth",
            "base_url": "https://bad.example/v1",
            "api_key": "sk-wrong",
        }).json()["data"]
        mock_httpx.default_get_response = _MockResponse(
            401, {"error": {"message": "invalid api key"}}
        )
        r = client.post(f"/api/v1/ai/providers/{created['id']}/test-connection")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["ok"] is False
        assert "鉴权" in (data.get("error") or "") or "401" in (data.get("error") or "")

    def test_provider_not_found(self, isolated_db, client):
        r = client.post("/api/v1/ai/providers/99999/test-connection")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 4. GET /models
# ---------------------------------------------------------------------------

class TestModelsEndpoint:
    def test_fetch_models_ok(self, isolated_db, client, mock_httpx):
        created = client.post("/api/v1/ai/providers", json={
            "name": "ModelProv",
            "base_url": "https://mp.example/v1",
            "api_key": "sk-mp-111111111111",
        }).json()["data"]
        mock_httpx.default_get_response = _MockResponse(
            200, {"data": [{"id": "gpt-4o"}, {"id": "deepseek-v3"}]}
        )
        r = client.get(f"/api/v1/ai/providers/{created['id']}/models")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        ids = [m["id"] if isinstance(m, dict) else m for m in data["models"]]
        assert set(ids) == {"gpt-4o", "deepseek-v3"}

    def test_fetch_models_returns_chinese_error_on_401(self, isolated_db, client, mock_httpx):
        created = client.post("/api/v1/ai/providers", json={
            "name": "BadKey",
            "base_url": "https://bk.example/v1",
            "api_key": "sk-1234567890ab",
        }).json()["data"]
        mock_httpx.default_get_response = _MockResponse(
            401, {"error": {"message": "unauthorized"}}
        )
        r = client.get(f"/api/v1/ai/providers/{created['id']}/models")
        assert r.status_code in (200, 401, 500), r.text
        # 返回体里应含中文错误信息
        body = r.json()
        combined = json.dumps(body, ensure_ascii=False)
        assert "鉴权" in combined or "失败" in combined or "错误" in combined


# ---------------------------------------------------------------------------
# 5. apply-to/{service_type}
# ---------------------------------------------------------------------------

class TestApplyTo:
    def test_apply_to_chat_writes_ai_model_configs(self, isolated_db, client):
        created = client.post("/api/v1/ai/providers", json={
            "name": "ChatProv",
            "base_url": "https://chatprov.example/v1",
            "api_key": "sk-ct-999988887777",
        }).json()["data"]
        r = client.post(
            f"/api/v1/ai/providers/{created['id']}/apply-to/chat",
            json={"model_name": "gpt-4o"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "success"

        # 通过现有 GET /model-configs/chat 验证写入值
        r2 = client.get("/api/v1/ai/model-configs/chat")
        assert r2.status_code == 200
        cfg = r2.json()["data"]
        assert cfg is not None
        assert cfg["provider"] == "ChatProv"
        assert cfg["base_url"] == "https://chatprov.example/v1"
        assert cfg["api_key"] == "sk-ct-999988887777"
        assert cfg["model_name"] == "gpt-4o"

    def test_apply_to_missing_model_name_returns_400(self, isolated_db, client):
        created = client.post("/api/v1/ai/providers", json={
            "name": "NoModel",
            "base_url": "https://nm.example",
            "api_key": "sk-nm-1234567890",
        }).json()["data"]
        r = client.post(f"/api/v1/ai/providers/{created['id']}/apply-to/chat", json={})
        assert r.status_code == 400

    def test_apply_to_missing_model_name_empty_string(self, isolated_db, client):
        created = client.post("/api/v1/ai/providers", json={
            "name": "EmptyModel",
            "base_url": "https://em.example",
            "api_key": "sk-em-aaaaaaaaaa",
        }).json()["data"]
        r = client.post(
            f"/api/v1/ai/providers/{created['id']}/apply-to/chat",
            json={"model_name": "   "},
        )
        assert r.status_code == 400

    def test_apply_to_missing_provider_returns_404(self, isolated_db, client):
        r = client.post(
            "/api/v1/ai/providers/99999/apply-to/chat",
            json={"model_name": "gpt-4o"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6. provider-link 软关联
# ---------------------------------------------------------------------------

class TestProviderLink:
    def test_match_returns_provider(self, isolated_db, client):
        created = client.post("/api/v1/ai/providers", json={
            "name": "Linked",
            "base_url": "https://linked.example/v1",
            "api_key": "sk-lk-1234567890ab",
        }).json()["data"]
        client.post("/api/v1/ai/model-configs", json={
            "service_type": "chat",
            "provider": "Linked",
            "api_key": "sk-lk-1234567890ab",
            "base_url": "https://linked.example/v1",
            "model_name": "gpt-4o",
        })
        r = client.get("/api/v1/ai/model-configs/chat/provider-link")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data is not None
        assert data["id"] == created["id"]
        assert data["name"] == "Linked"

    def test_no_match_returns_null(self, isolated_db, client):
        client.post("/api/v1/ai/providers", json={
            "name": "Unlinked",
            "base_url": "https://ul.example",
            "api_key": "sk-ul-ffffffffff",
        })
        # 通道配置对不上的
        client.post("/api/v1/ai/model-configs", json={
            "service_type": "chat",
            "provider": "openai",
            "api_key": "sk-other-key-1234",
            "base_url": "https://api.openai.com/v1",
            "model_name": "gpt-4o",
        })
        r = client.get("/api/v1/ai/model-configs/chat/provider-link")
        assert r.status_code == 200
        assert r.json()["data"] is None

    def test_no_config_returns_null(self, isolated_db, client):
        client.post("/api/v1/ai/providers", json={
            "name": "Orphan",
            "base_url": "https://orphan.example",
            "api_key": "sk-or-1234567890",
        })
        r = client.get("/api/v1/ai/model-configs/chat/provider-link")
        assert r.status_code == 200
        assert r.json()["data"] is None


# ---------------------------------------------------------------------------
# 7. 向后兼容：原 /model-configs 语义不动
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_model_configs_semantics_unchanged(self, isolated_db, client):
        # 老语义：直接 POST 一份平铺配置，GET 得到它
        r = client.post("/api/v1/ai/model-configs", json={
            "service_type": "speech_recognition",
            "provider": "openai_compatible",
            "api_key": "sk-legacy-1234567890",
            "base_url": "https://legacy.example/v1",
            "model_name": "SenseVoice",
        })
        assert r.status_code == 200
        r2 = client.get("/api/v1/ai/model-configs/speech_recognition")
        assert r2.status_code == 200
        data = r2.json()["data"]
        assert data["provider"] == "openai_compatible"
        assert data["api_key"] == "sk-legacy-1234567890"
        assert data["base_url"] == "https://legacy.example/v1"
        assert data["model_name"] == "SenseVoice"
