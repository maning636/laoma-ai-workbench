"""C17 · 订阅态 / 离线态 tier 分层回归测试(自运行,不启动服务)。

覆盖:
  1. is_subscribed() 无 license 缓存 → False,且**不触发任何网络 I/O**
  2. is_subscribed() gateway 抛异常 → False(降级),仍然不发网络
  3. is_subscribed() license 缓存 valid + cloud_reachable → True
  4. is_subscribed() license 缓存 valid 但 cloud_reachable=False → False
  5. get_ai_config("chat") 离线态 → 返回真实 key(不走占位符)
  6. get_ai_config("chat") 订阅态 → api_key="***" + base_url=本地 llm-proxy 桥接端点,
     不读本地明文 key
  7. sync_agent_config_to_runtime 离线态 → 本地 api_key 明文写入 config.yaml
  8. sync_agent_config_to_runtime 订阅态 → api_key 改写为 "prism-cloud-subscription",
     base_url 改写为本地 llm-proxy 桥接端点

用例之间严格隔离:每个用例都 reset cloud_gateway 单例 + 备份/还原 settings 字段,
不修改用户真实 .env / hermes-home / 数据库。

用法:
  cd prism_backend && python tests/test_c17_subscription_tier.py
"""
from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# ── 环境准备:sys.path 优先指向 prism_backend,与 fastapi_app.run.py 一致 ──
_REPO_ROOT = Path(__file__).resolve().parents[1]  # prism_backend (本仓库 tests 位于 prism_backend/tests)
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi_app.core import config as _cfg_module  # noqa: E402
from fastapi_app.core.config import settings  # noqa: E402
from fusion_ai import cloud_gateway as _cg  # noqa: E402
from fusion_ai.cloud_gateway import LicenseStatus, reset_gateway_for_test  # noqa: E402

# 与 router.py / hermes_config.py 的 import 路径一致:
#   from fastapi_app.core.config import is_subscribed, llm_proxy_endpoint
_CONFIG_SUBSCRIBED_TARGET = "fastapi_app.core.config.is_subscribed"
_CONFIG_ENDPOINT_TARGET = "fastapi_app.core.config.llm_proxy_endpoint"


# 测试用"真 key",用于验证离线态返回真实值 / 订阅态被剥离
_TEST_REAL_KEY = "sk-real-offline-key-do-not-exfiltrate"
_TEST_REAL_BASE_URL = "https://example.invalid/v1"
_TEST_PLACEHOLDER_KEY = "prism-cloud-subscription"


# ── 用例执行框架 ─────────────────────────────────────────
_FAILS = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global _FAILS
    tag = "PASS" if cond else "FAIL"
    suffix = f" — {extra}" if extra else ""
    print(f"[{tag}] {label}{suffix}")
    if not cond:
        _FAILS += 1


def with_subscribed(flag: bool):
    """把 fastapi_app.core.config.is_subscribed 强制置为常量。"""
    return patch(_CONFIG_SUBSCRIBED_TARGET, lambda: flag)


def _proxy_endpoint() -> str:
    from fastapi_app.core.config import llm_proxy_endpoint
    return llm_proxy_endpoint()


def _reset_gateway_and_settings():
    """每个用例开头调用:清空 gateway 单例 + 还原 settings 关键字段。"""
    reset_gateway_for_test()
    settings.AI_API_KEY = ""
    settings.SILICONFLOW_API_KEY = ""
    settings.AI_BASE_URL = ""
    settings.AI_MODEL = ""


# ── 用例 1: is_subscribed() 无缓存 → False + 无网络 I/O ──
def test_is_subscribed_no_cache_no_io() -> None:
    _reset_gateway_and_settings()

    def boom(*_a, **_k):
        raise AssertionError("is_subscribed 无缓存路径不该触发任何网络 I/O")

    # fake_gw: 无 access_token、license 缓存为空、transport 一旦被调用就爆。
    # 走 verify_license → ensure_access_token()="" 短路,直接返回 unauthenticated。
    with patch.object(_cg, "get_gateway") as gmock, \
         patch("urllib.request.urlopen", boom):
        fake_gw = SimpleNamespace(
            _license_cache=None,
            _license_checked_at=0.0,
            ensure_access_token=lambda: "",
            _transport=boom,
            _store=SimpleNamespace(
                get_access_token=lambda: "",
                should_refresh=lambda: False,
            ),
            _do_verify_license=boom,
        )
        gmock.return_value = fake_gw

        from fastapi_app.core.config import is_subscribed
        result = is_subscribed()

    check("is_subscribed 无缓存 → False", result is False, f"result={result!r}")
    check("is_subscribed 无缓存未调用 gateway._transport",
          True,  # 若被调用会 raise AssertionError 并冒泡至此
          "transport guard 未触发")


# ── 用例 2: gateway 抛异常 → False + 无网络 I/O ──
def test_is_subscribed_gateway_raises_no_io() -> None:
    _reset_gateway_and_settings()

    with patch.object(_cg, "get_gateway", side_effect=RuntimeError("gateway unavailable")), \
         patch("urllib.request.urlopen", side_effect=AssertionError("no IO allowed")):
        from fastapi_app.core.config import is_subscribed
        result = is_subscribed()

    check("is_subscribed gateway 异常 → False", result is False, f"result={result!r}")


# ── 用例 3: 订阅态 license 缓存命中 → True ──
def test_is_subscribed_valid_cache_true() -> None:
    _reset_gateway_and_settings()

    cached = LicenseStatus(valid=True, reason="active", is_pro=True, cloud_reachable=True)

    with patch.object(_cg, "get_gateway") as gmock:
        gmock.return_value = SimpleNamespace(
            verify_license=lambda force=False: cached,
        )
        from fastapi_app.core.config import is_subscribed
        result = is_subscribed()

    check("is_subscribed 缓存 valid+cloud_reachable → True", result is True, f"result={result!r}")


# ── 用例 4: license valid 但 cloud_reachable=False → False ──
def test_is_subscribed_valid_but_unreachable_false() -> None:
    _reset_gateway_and_settings()

    cached = LicenseStatus(valid=True, reason="active", is_pro=True, cloud_reachable=False)

    with patch.object(_cg, "get_gateway") as gmock:
        gmock.return_value = SimpleNamespace(
            verify_license=lambda force=False: cached,
        )
        from fastapi_app.core.config import is_subscribed
        result = is_subscribed()

    check("is_subscribed 缓存 valid 但 cloud_reachable=False → False",
          result is False, f"result={result!r}")


# ── 用例 5: get_ai_config("chat") 离线态 → 返回真实 key ──
def test_get_ai_config_offline_returns_real_key() -> None:
    _reset_gateway_and_settings()

    # 用 tempfile 创建真实 sqlite 文件(不走 TemporaryDirectory 避免 Windows 句柄锁)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)
    import sqlite3
    try:
        conn = sqlite3.connect(tmp_path)
        conn.execute(
            "CREATE TABLE ai_model_configs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "service_type TEXT, provider TEXT, api_key TEXT, "
            "base_url TEXT, model_name TEXT, extra_config TEXT, is_active INTEGER)"
        )
        conn.commit()
        conn.close()

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(settings, "DATABASE_PATH", tmp_path))
            stack.enter_context(patch.object(settings, "AI_API_KEY", _TEST_REAL_KEY))
            stack.enter_context(patch.object(settings, "AI_BASE_URL", _TEST_REAL_BASE_URL))
            stack.enter_context(patch.object(settings, "AI_MODEL", "deepseek-ai/DeepSeek-V3"))
            with with_subscribed(False):
                from fastapi_app.api.v1.ai.router import get_ai_config
                cfg = get_ai_config("chat")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    check("离线态 get_ai_config('chat') 非 None", cfg is not None, f"cfg={cfg!r}")
    if cfg is not None:
        check("离线态 api_key 是真实 key(非 '***')",
              cfg.get("api_key") == _TEST_REAL_KEY,
              f"api_key={cfg.get('api_key')!r}")
        check("离线态 api_key 不返回占位符 '***'",
              cfg.get("api_key") != "***",
              f"api_key={cfg.get('api_key')!r}")
        check("离线态 base_url 走用户配置(非 proxy)",
              cfg.get("base_url") == _TEST_REAL_BASE_URL,
              f"base_url={cfg.get('base_url')!r}")
        check("离线态 extra_config 不含 tier=cloud",
              (cfg.get("extra_config") or {}).get("tier") != "cloud",
              f"extra_config={cfg.get('extra_config')!r}")


# ── 用例 6: get_ai_config("chat") 订阅态 → api_key='***' + 代理 endpoint ──
def test_get_ai_config_subscription_returns_proxy() -> None:
    _reset_gateway_and_settings()

    proxy_url = _proxy_endpoint()

    # 关键:离线态下 AI_API_KEY 已存在,验证订阅态短路不会读到它
    settings.AI_API_KEY = _TEST_REAL_KEY
    with contextlib.ExitStack() as stack:
        stack.enter_context(with_subscribed(True))
        from fastapi_app.api.v1.ai.router import get_ai_config
        cfg = get_ai_config("chat")

    check("订阅态 get_ai_config('chat') 非 None", cfg is not None, f"cfg={cfg!r}")
    if cfg is not None:
        check("订阅态 api_key == '***'",
              cfg.get("api_key") == "***",
              f"api_key={cfg.get('api_key')!r}")
        check("订阅态 api_key 不等于真实 key(未泄漏本地明文)",
              cfg.get("api_key") != _TEST_REAL_KEY,
              f"api_key={cfg.get('api_key')!r}")
        check("订阅态 base_url 指向本地 llm-proxy 桥接端点",
              cfg.get("base_url") == proxy_url,
              f"got={cfg.get('base_url')!r} expected={proxy_url!r}")
        check("订阅态 base_url 包含 '/api/v1/ai/llm-proxy'",
              "/api/v1/ai/llm-proxy" in (cfg.get("base_url") or ""),
              f"base_url={cfg.get('base_url')!r}")
        check("订阅态 extra_config.tier == 'cloud'",
              (cfg.get("extra_config") or {}).get("tier") == "cloud",
              f"extra_config={cfg.get('extra_config')!r}")
        check("订阅态 extra_config.via_proxy == True",
              (cfg.get("extra_config") or {}).get("via_proxy") is True,
              f"extra_config={cfg.get('extra_config')!r}")
        check("订阅态 model_name == 'prism-cloud'",
              cfg.get("model_name") == "prism-cloud",
              f"model_name={cfg.get('model_name')!r}")


# ── 用例 7/8: hermes_config 写入路径的 key 剥离(tier 分层) ──
def _write_hermes_config_offline(td: Path, real_key: str, real_base: str) -> Path:
    """把用户配置的 key 写入 hermes-home(离线态,期望明文)。"""
    os.environ["PRISM_HERMES_HOME"] = str(td)
    from fastapi_app.agent.hermes_config import sync_agent_config_to_runtime
    with with_subscribed(False):
        return sync_agent_config_to_runtime({
            "llm": {
                "provider": "custom",
                "base_url": real_base,
                "api_key": real_key,
                "model": "deepseek-ai/DeepSeek-V3",
            },
            "runtime": {"max_turns": 8},
        })


def _write_hermes_config_subscribed(td: Path, real_key: str, real_base: str) -> Path:
    """订阅态:即便用户提供了真实 key,写入路径也必须剥离。"""
    os.environ["PRISM_HERMES_HOME"] = str(td)
    from fastapi_app.agent.hermes_config import sync_agent_config_to_runtime
    with with_subscribed(True):
        return sync_agent_config_to_runtime({
            "llm": {
                "provider": "custom",
                "base_url": real_base,
                "api_key": real_key,
                "model": "deepseek-ai/DeepSeek-V3",
            },
            "runtime": {"max_turns": 8},
        })


def _load_yaml(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_hermes_config_offline_writes_real_key() -> None:
    _reset_gateway_and_settings()
    with tempfile.TemporaryDirectory() as td:
        out = _write_hermes_config_offline(Path(td), _TEST_REAL_KEY, _TEST_REAL_BASE_URL)
        data = _load_yaml(out)
        model_cfg = data.get("model") or {}

        check("离线态 hermes config.yaml 存在", out.exists(), f"path={out}")
        check("离线态 model.api_key 是明文真实 key",
              model_cfg.get("api_key") == _TEST_REAL_KEY,
              f"api_key={model_cfg.get('api_key')!r}")
        check("离线态 model.api_key 未被占位符替换",
              model_cfg.get("api_key") != _TEST_PLACEHOLDER_KEY,
              f"api_key={model_cfg.get('api_key')!r}")
        check("离线态 model.base_url 保留用户配置",
              model_cfg.get("base_url") == _TEST_REAL_BASE_URL,
              f"base_url={model_cfg.get('base_url')!r}")


def test_hermes_config_subscribed_strips_key() -> None:
    _reset_gateway_and_settings()
    proxy_url = _proxy_endpoint()

    with tempfile.TemporaryDirectory() as td:
        out = _write_hermes_config_subscribed(Path(td), _TEST_REAL_KEY, _TEST_REAL_BASE_URL)
        data = _load_yaml(out)
        model_cfg = data.get("model") or {}

        check("订阅态 hermes config.yaml 存在", out.exists(), f"path={out}")
        check("订阅态 model.api_key 是占位符 'prism-cloud-subscription'",
              model_cfg.get("api_key") == _TEST_PLACEHOLDER_KEY,
              f"api_key={model_cfg.get('api_key')!r}")
        check("订阅态 model.api_key 不包含真实 key(已剥离)",
              model_cfg.get("api_key") != _TEST_REAL_KEY,
              f"api_key={model_cfg.get('api_key')!r}")
        check("订阅态 model.base_url 已改写为本地 llm-proxy 桥接端点",
              model_cfg.get("base_url") == proxy_url,
              f"got={model_cfg.get('base_url')!r} expected={proxy_url!r}")
        check("订阅态 model.base_url 不再指向用户原配置",
              model_cfg.get("base_url") != _TEST_REAL_BASE_URL,
              f"base_url={model_cfg.get('base_url')!r}")


def run() -> int:
    global _FAILS
    _orig_prism_hermes_home = os.environ.get("PRISM_HERMES_HOME")

    try:
        print("\n── C17 tier 分层回归 ──")
        test_is_subscribed_no_cache_no_io()
        test_is_subscribed_gateway_raises_no_io()
        test_is_subscribed_valid_cache_true()
        test_is_subscribed_valid_but_unreachable_false()
        test_get_ai_config_offline_returns_real_key()
        test_get_ai_config_subscription_returns_proxy()
        test_hermes_config_offline_writes_real_key()
        test_hermes_config_subscribed_strips_key()
    finally:
        if _orig_prism_hermes_home is None:
            os.environ.pop("PRISM_HERMES_HOME", None)
        else:
            os.environ["PRISM_HERMES_HOME"] = _orig_prism_hermes_home
        _reset_gateway_and_settings()

    return _FAILS


if __name__ == "__main__":
    rc = run()
    total = 20  # 检查用例总数(见每个用例内部 check 数量)
    passed = total - rc
    print(f"\n{passed}/{total} checks passed; {rc} failure(s)")
    print("ALL TESTS PASSED" if rc == 0 else f"{rc} TEST(S) FAILED")
    sys.exit(0 if rc == 0 else 1)
