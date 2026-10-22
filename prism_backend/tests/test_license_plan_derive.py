"""注册码档位派生(`derive_plan`)与 `/effective-flags` 响应形状测试。

背景(2026-10-24):
  客户端合并成单一安装器后,要在客户端内体现「完整版 / 限制功能版」。
  判据必须来自**本地后端算好的最终交集**(注册码授权条目 ∩ 云端订阅配额),
  而不是前端各自去读云端 —— 否则「有注册码但还没同步云端」的用户会被误判成限制功能版。

本文件覆盖:
  1. `derive_plan()` 的档位派生规则
  2. `GET /api/v1/license/effective-flags` 的响应形状:
     必须带 `plan` / `flags`(12 项) / `upgrade_url`,且与云端 `/cloud/feature-flags` 同形

约定:
  - 不碰真实数据目录(用 tmp_path + monkeypatch)
  - 不联网(云端 flag 走 monkeypatch)

用法: cd prism_backend && python -m pytest tests/test_license_plan_derive.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("FEATURE_FLAGS_DISABLED", "1")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ⚠️ `fastapi_app.api.v1.license.__init__` 里 `from .router import router`,
#    于是包属性 `license.router` 指向 **APIRouter 实例**,不是子模块。
#    所以必须用 importlib 拿到真正的模块对象,monkeypatch 也只能按对象打补丁
#    (pytest 的字符串目标会走 getattr,拿到的是 APIRouter,没有这些函数名)。
import importlib  # noqa: E402

license_mod = importlib.import_module("fastapi_app.api.v1.license.router")

from fastapi_app.core import license as L  # noqa: E402
from fastapi_app.core.license_keys import FLAG_CAPACITY  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def keys():
    """测试用密钥对(现生成,不依赖仓库外的私钥文件)。"""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    return priv, pub_hex


@pytest.fixture()
def license_home(tmp_path, monkeypatch):
    """把 license 的存放目录指向 tmp_path。"""
    monkeypatch.setenv("LAOMA_DATA_DIR", str(tmp_path))
    return tmp_path


def _issue(priv, entitlements, *, days=30, grace=7):
    now = datetime.now(timezone.utc)
    payload = {
        "v": L.PAYLOAD_VERSION,
        "lid": "LIC-PLAN-0001",
        "ent": sorted(entitlements),
        "iat": now.isoformat(timespec="seconds"),
        "exp": (now + timedelta(days=days)).isoformat(timespec="seconds"),
        "grace": grace,
        "cust": "测试客户",
        "note": "",
    }
    return L.encode_license(payload, priv)


def _community_flags() -> dict:
    """Community 档的 flag 快照(与 FLAG_CAPACITY 的 community 列一致)。"""
    return {flag: spec[1] for flag, spec in FLAG_CAPACITY.items()}


def _pro_flags() -> dict:
    """Pro 档的 flag 快照(与 FLAG_CAPACITY 的 pro 列一致)。"""
    return {flag: spec[2] for flag, spec in FLAG_CAPACITY.items()}


# ── 1. derive_plan ──────────────────────────────────────────────────────────

class TestDerivePlan:
    def test_community_flags_gives_community(self):
        assert L.derive_plan(_community_flags()) == "community"

    def test_empty_flags_gives_community(self):
        assert L.derive_plan({}) == "community"

    def test_full_pro_flags_gives_pro(self):
        assert L.derive_plan(_pro_flags()) == "pro"

    def test_single_pro_reached_flag_gives_pro(self):
        """任一决定性 flag 达到 Pro 档即算 Pro 客户(其余能力由各 flag 如实呈现)。"""
        flags = _community_flags()
        flags["max_accounts"] = -1
        assert L.derive_plan(flags) == "pro"

    def test_two_tier_flags_are_not_decisive(self):
        """data_recovery / team_members 两档相同,不能作为判据。"""
        flags = _community_flags()
        assert flags["data_recovery"] is True and flags["team_members"] == 1
        assert L.derive_plan(flags) == "community"

    def test_bool_pro_flag_gives_pro(self):
        flags = _community_flags()
        flags["persona"] = True
        assert L.derive_plan(flags) == "pro"

    def test_mode_pro_flag_gives_pro(self):
        flags = _community_flags()
        flags["ai_mode"] = "cloud"
        assert L.derive_plan(flags) == "pro"


# ── 2. /effective-flags 响应形状 ───────────────────────────────────────────

def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(license_mod.router, prefix="/api/v1/license")
    return TestClient(app)


class TestEffectiveFlagsEndpoint:
    def test_no_license_returns_community_plan(self, license_home, monkeypatch):
        monkeypatch.setattr(license_mod, "_cloud_flags", lambda request: {})
        client = _make_client()
        r = client.get("/api/v1/license/effective-flags")
        assert r.status_code == 200
        data = r.json()
        assert data["plan"] == "community"
        assert data["cloudAvailable"] is False
        assert set(data["flags"]) == set(FLAG_CAPACITY)
        assert data["flags"]["agent_quota"] == 0

    def test_response_has_upgrade_url(self, license_home, monkeypatch):
        monkeypatch.setattr(license_mod, "_cloud_flags", lambda request: {})
        client = _make_client()
        data = client.get("/api/v1/license/effective-flags").json()
        assert data["upgrade_url"] == "/settings#contact"

    def test_pro_license_with_cloud_pro_gives_pro_plan(
        self, keys, license_home, monkeypatch
    ):
        """注册码(全条目) + 云端 Pro 订阅 → plan=pro,flag 全部到 Pro 档。"""
        priv, pub_hex = keys
        token = _issue(priv, [
            "core", "ai_cloud", "agent", "persona", "campaign", "multi_platform",
        ])
        L.save_license(token, public_key_hex=pub_hex)

        monkeypatch.setattr(
            license_mod, "load_license",
            lambda: L.verify_license(token, public_key_hex=pub_hex),
        )
        monkeypatch.setattr(
            license_mod, "_cloud_flags", lambda request: _pro_flags()
        )

        client = _make_client()
        data = client.get("/api/v1/license/effective-flags").json()
        assert data["plan"] == "pro"
        assert data["cloudAvailable"] is True
        assert data["flags"]["max_accounts"] == -1
        assert data["flags"]["agent_quota"] == 2
        assert data["flags"]["cloud_prompt"] is True
        assert data["flags"]["campaign_orchestration"] is True

    def test_pro_license_without_cloud_stays_community(
        self, keys, license_home, monkeypatch
    ):
        """云端不可达 → 交集落到 Community 档(保守,不擅自开云端能力)。"""
        priv, pub_hex = keys
        token = _issue(priv, [
            "core", "ai_cloud", "agent", "persona", "campaign", "multi_platform",
        ])
        L.save_license(token, public_key_hex=pub_hex)

        monkeypatch.setattr(
            license_mod, "load_license",
            lambda: L.verify_license(token, public_key_hex=pub_hex),
        )
        monkeypatch.setattr(license_mod, "_cloud_flags", lambda request: {})

        client = _make_client()
        data = client.get("/api/v1/license/effective-flags").json()
        assert data["plan"] == "community"
        assert data["flags"]["agent_quota"] == 0
        assert data["flags"]["max_accounts"] == 3
