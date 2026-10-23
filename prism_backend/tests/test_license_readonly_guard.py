"""D4 只读守卫测试。

覆盖三件事:
  1. 拦截面表本身(`is_blocked_write`):该拦的拦、不该拦的放行;
  2. 中间件真实行为:到期 → 403;社区版 / 宽限期内 / 开关关掉 → 放行;
  3. 拦截表不腐烂:每条规则都必须对得上**真实存在的路由**。
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
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from fastapi_app.api.v1.license import guard as guard_mod  # noqa: E402
from fastapi_app.core import license as license_mod  # noqa: E402



# ──────────────────────────────────────────────────────────────
# 夹具:临时密钥对 + 临时数据目录
# ──────────────────────────────────────────────────────────────

@pytest.fixture()
def lic_env(tmp_path, monkeypatch):
    """把 license 落到临时目录,并把守卫用到的公钥换成临时公钥。"""
    monkeypatch.setenv("LAOMA_DATA_DIR", str(tmp_path / "data"))

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


    # 守卫模块里 `from ... import load_license` 是**按名导入**,
    # 所以这里替换 guard 模块里的那个名字即可让整条链用上临时公钥。
    real_load = license_mod.load_license

    def _load(**kwargs):
        kwargs.setdefault("public_key_hex", public_hex)
        return real_load(**kwargs)

    monkeypatch.setattr(guard_mod, "load_license", _load)

    return {"private_key": private_key, "public_hex": public_hex, "data_dir": tmp_path / "data"}


def _issue(env, *, expires_in_days: int, grace_days: int = 0,
           entitlements=("core",), customer: str = "测试用户") -> str:
    """签一个注册码(用临时私钥)。expires_in_days 为负数表示已过期。"""
    now = datetime.now(timezone.utc)
    payload = {
        "v": 1,
        "lid": "lic_test_0001",
        "ent": list(entitlements),
        "iat": (now - timedelta(days=30)).isoformat(timespec="seconds"),
        "exp": (now + timedelta(days=expires_in_days)).isoformat(timespec="seconds"),
        "grace": grace_days,
        "cust": customer,
        "note": "unit-test",
    }
    return license_mod.encode_license(payload, env["private_key"])


def _write_state(env, **kwargs):
    """把注册码落盘(走真实 save_license 逻辑)。"""
    token = _issue(env, **kwargs)
    state = license_mod.save_license(token, public_key_hex=env["public_hex"])
    assert state.valid, state.message
    return state


# ──────────────────────────────────────────────────────────────
# 1. 拦截面表
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/ai/chat"),
        ("POST", "/api/v1/campaigns/create"),
        ("POST", "/api/v1/campaigns/camp_123/execute"),
        ("POST", "/api/v1/plans"),
        ("PUT", "/api/v1/plans/plan_1"),
        ("POST", "/api/v1/publish/single"),
        ("POST", "/api/v1/publish/batch"),
        ("POST", "/api/v1/review/items/rv_1/approve"),
        ("POST", "/api/v1/artifacts"),
        ("POST", "/api/v1/artifacts/art_abc/submit-review"),
        ("POST", "/api/v1/files/upload"),
        ("POST", "/api/v1/video-pipeline/run"),
        ("POST", "/api/v1/workshop/run"),
        ("POST", "/api/v1/tasks/distribution"),
    ],
)
def test_blocked_paths_are_matched(method, path):
    assert guard_mod.is_blocked_write(method, path) is True


@pytest.mark.parametrize(
    "method,path",
    [
        # 读操作永远放行
        ("GET", "/api/v1/campaigns/create"),
        ("GET", "/api/v1/ai/chat"),
        ("GET", "/api/v1/artifacts"),
        # 停止类:必须放行,否则到期用户停不下正在跑的发布
        ("POST", "/api/v1/campaigns/camp_1/pause"),
        ("POST", "/api/v1/campaigns/camp_1/resume"),
        ("POST", "/api/v1/tasks/cancel/tk_1"),
        ("POST", "/api/v1/tasks/batch/cancel"),
        ("POST", "/api/v1/tasks/clear/all"),
        ("DELETE", "/api/v1/tasks/tk_1"),
        # 清理 / 导出 / 数据进出
        ("POST", "/api/v1/files/batch-delete"),
        ("DELETE", "/api/v1/files/f1"),
        ("POST", "/api/v1/data/collect"),
        ("POST", "/api/v1/recovery/collect"),
        ("POST", "/api/v1/analytics/collect/douyin"),
        # 登录 / 注册码 / 配置
        ("POST", "/api/v1/auth/login/browser/start"),
        ("POST", "/api/v1/license/activate"),
        ("DELETE", "/api/v1/license/"),
        ("POST", "/api/v1/system/clear-cache"),
        ("PUT", "/api/v1/ai-prompts/config/foo"),
        ("POST", "/api/v1/concurrency/config"),
        # 账号 / 平台接入
        ("POST", "/api/v1/accounts"),
        ("POST", "/api/v1/platforms/douyin/login"),
    ],
)
def test_allowed_paths_are_not_matched(method, path):
    assert guard_mod.is_blocked_write(method, path) is False


def test_read_methods_never_blocked():
    """读操作不在拦截面内(方法过滤在前面)。"""
    for _m, _p, in guard_mod.READ_ONLY_RULES:
        assert guard_mod.is_blocked_write("GET", _p) is False


# ──────────────────────────────────────────────────────────────
# 2. 中间件真实行为
# ──────────────────────────────────────────────────────────────

def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(guard_mod.ReadOnlyWriteGuard)

    @app.post("/api/v1/campaigns/create")
    def _create():
        return {"ok": True}

    @app.post("/api/v1/license/activate")
    def _activate():
        return {"ok": True}

    @app.get("/api/v1/artifacts")
    def _list():
        return {"ok": True}

    return app


def test_community_user_can_write(lic_env):
    """社区版(从没输过注册码)→ 写操作照常放行。"""
    client = TestClient(_make_app())
    resp = client.post("/api/v1/campaigns/create")
    assert resp.status_code == 200, resp.text


def test_expired_license_blocks_new_content(lic_env):
    """注册码过期且宽限期满 → 新增内容被 403 拦下。"""
    _write_state(lic_env, expires_in_days=-1, grace_days=0)
    client = TestClient(_make_app())
    resp = client.post("/api/v1/campaigns/create")
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["reason"] == "license_expired_read_only"
    assert detail["readOnly"] is True


def test_expired_license_still_allows_license_activate(lic_env):
    """到期用户必须还能输入新注册码 —— 否则锁死。"""
    _write_state(lic_env, expires_in_days=-1, grace_days=0)
    client = TestClient(_make_app())
    resp = client.post("/api/v1/license/activate")
    assert resp.status_code == 200, resp.text


def test_expired_license_still_allows_read(lic_env):
    """到期后读操作不受影响(能看)。"""
    _write_state(lic_env, expires_in_days=-1, grace_days=0)
    client = TestClient(_make_app())
    resp = client.get("/api/v1/artifacts")
    assert resp.status_code == 200, resp.text


def test_grace_period_can_write(lic_env):
    """宽限期内 → 仍可写。"""
    _write_state(lic_env, expires_in_days=-1, grace_days=7)
    client = TestClient(_make_app())
    resp = client.post("/api/v1/campaigns/create")
    assert resp.status_code == 200, resp.text


def test_kill_switch_disables_guard(lic_env, monkeypatch):
    """紧急停用开关。"""
    _write_state(lic_env, expires_in_days=-1, grace_days=0)
    monkeypatch.setenv(guard_mod.DISABLE_ENV, "0")
    client = TestClient(_make_app())
    resp = client.post("/api/v1/campaigns/create")
    assert resp.status_code == 200, resp.text


def test_guard_does_not_write_lastseen_on_block(lic_env):
    """只读拦截不该每次都回写 lastSeenAt(touch=False)。"""
    _write_state(lic_env, expires_in_days=-1, grace_days=0)
    path = license_mod.license_file_path()
    before = path.read_text(encoding="utf-8")
    client = TestClient(_make_app())
    client.post("/api/v1/campaigns/create")
    after = path.read_text(encoding="utf-8")
    assert before == after


# ──────────────────────────────────────────────────────────────
# 3. 接入真实 app:顺序 + 表不腐烂
# ──────────────────────────────────────────────────────────────

def test_real_app_registers_guard_innermost():
    """守卫必须**比**路径规范化中间件更内层,否则 `/api/v1/v1/` 形式会绕过。

    Starlette:`add_middleware` 是"后注册 = 更外层",user_middleware[0] 最外层。
    """
    from fastapi_app.main import app

    classes = [mw.cls for mw in app.user_middleware]
    assert guard_mod.ReadOnlyWriteGuard in classes, classes
    idx = classes.index(guard_mod.ReadOnlyWriteGuard)
    # 规范化中间件是 BaseHTTPMiddleware,必须在守卫**外层**(下标更小)
    from starlette.middleware.base import BaseHTTPMiddleware

    normalize_idx = [i for i, c in enumerate(classes) if c is BaseHTTPMiddleware]
    assert normalize_idx, classes
    assert min(normalize_idx) < idx, (
        f"规范化中间件必须跑在守卫前面,当前 classes={classes}"
    )


def test_real_app_blocks_rewritten_double_prefix(lic_env):
    """Next.js rewrite 产生的 `/api/v1/v1/...` 形式同样被拦。"""
    _write_state(lic_env, expires_in_days=-1, grace_days=0)
    from fastapi_app.main import app

    with TestClient(app) as client:
        resp = client.post("/api/v1/v1/campaigns/create")
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["reason"] == "license_expired_read_only"


def test_rules_match_real_routes():
    """拦截表不许腐烂:每条规则都要对得上真实路由。

    路由被改名/删除而规则没跟上 → 这条测试会红,提醒同步。

    ⚠️ 真实路由必须从 `app.openapi()["paths"]` 取,**不能**用 `app.routes`:
    新版 FastAPI 把 include_router 的子路由收进 `_IncludedRouter`,
    `app.routes` 里只剩 app 级路由(实测 8 条 path:`/`、`/api/docs`、`/health`…),
    子路由一条都看不到 —— 那样 73 条规则会被全部误判成"不存在"。
    对照:app.openapi()["paths"] 有 490 条,用它比是零缺失(护栏没漂移)。
    """
    from fastapi_app.main import app

    real = set(app.openapi()["paths"])
    missing = [
        (m, t) for (m, t) in guard_mod.READ_ONLY_RULES if t not in real
    ]
    assert not missing, f"拦截表里的路径在真实路由中不存在: {missing}"


def test_rules_cover_content_creation_domains():
    """兜底:主要"产内容"的入口都必须在拦截面内。"""
    must_block = [
        ("POST", "/api/v1/publish/single"),
        ("POST", "/api/v1/publish/batch"),
        ("POST", "/api/v1/campaigns/create"),
        ("POST", "/api/v1/ai/chat"),
        ("POST", "/api/v1/ai-design/generate"),
        ("POST", "/api/v1/fusion/images/generate"),
        ("POST", "/api/v1/files/upload"),
        ("POST", "/api/v1/video-pipeline/run"),
        ("POST", "/api/v1/workshop/run"),
        ("POST", "/api/v1/artifacts"),
    ]
    for method, path in must_block:
        assert guard_mod.is_blocked_write(method, path) is True, (method, path)
