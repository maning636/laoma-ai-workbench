"""
/system/health-check/fast 端点测试

目标：
  1) 200 OK，返回结构包含 mode/components/preflight/timestamp/status
  2) mode == "fast"
  3) 4 项快检 components（backend/redis/disk_space/dependencies）都在
  4) 不调用 DB SELECT 1、不触发 run_preflight_check()、不做 httpx.get 到 7001
     ——通过 monkeypatch 让任何 DB / preflight / worker HTTP 访问立即炸。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _assert_shape(body: dict):
    assert isinstance(body, dict)
    assert body.get("mode") == "fast"
    assert isinstance(body.get("status"), str) and body["status"] in (
        "healthy", "degraded", "unknown"
    )
    assert isinstance(body.get("components"), dict)
    for k in ("backend", "redis", "disk_space", "dependencies"):
        assert k in body["components"], f"missing component {k}"
    assert isinstance(body.get("preflight"), dict)
    assert "skipped" in body["preflight"]
    assert body.get("preflight", {}).get("skipped", [])
    assert "database" in body["preflight"]["skipped"]
    assert "ai_service" in body["preflight"]["skipped"]
    assert body.get("preflight", {}).get("hint")
    assert isinstance(body.get("timestamp"), str)


def test_health_check_fast_shape_and_no_heavy_calls(monkeypatch):
    """monkeypatch 所有重量级依赖为炸点，若被调用测试立即失败。"""
    import fastapi_app.api.v1.system.router as sys_router_mod

    # --- 1) DB: 阻断 main_db_pool.get_connection ---
    db_opened = {"hit": False}

    class _BoomConn:
        def __enter__(self): raise AssertionError("DB touched in fast mode")
        def __exit__(self, *a): return False

    class _BoomPool:
        def get_connection(self):
            db_opened["hit"] = True
            return _BoomConn()

    class _BoomDbSession:
        main_db_pool = _BoomPool()

    # fastapi_app.db.session 可能在多个测试间被 patch；这里直接替换 module 属性
    monkeypatch.setattr(
        "fastapi_app.db.session.main_db_pool", _BoomPool(), raising=False,
    )

    # --- 2) run_preflight_check: 立即炸 ---
    def _boom_preflight(*a, **kw):
        raise AssertionError("run_preflight_check must not be called in fast mode")
    monkeypatch.setattr(
        sys_router_mod, "run_preflight_check", _boom_preflight, raising=False,
    )

    # --- 3) httpx.get: 若真的走到 7001 worker 探测，也会挂 ---
    try:
        import httpx
        def _boom_httpx_get(*a, **kw):
            raise AssertionError("httpx.get must not be called in fast mode")
        monkeypatch.setattr(httpx, "get", _boom_httpx_get, raising=False)
    except Exception:
        pass

    # --- 4) AI 配置读取：阻断 get_ai_config ---
    try:
        import fastapi_app.api.v1.ai.router as ai_router
        def _boom_ai(*a, **kw):
            raise AssertionError("get_ai_config must not be called in fast mode")
        monkeypatch.setattr(ai_router, "get_ai_config", _boom_ai, raising=False)
    except Exception:
        pass

    from fastapi.testclient import TestClient
    from fastapi_app.main import app

    client = TestClient(app)
    r = client.get("/api/v1/system/health-check/fast")

    assert r.status_code == 200, r.text
    body = r.json()
    _assert_shape(body)

    # 关键断言：DB 完全没被打开
    assert db_opened["hit"] is False, "fast mode must NOT touch DB"


def test_health_check_fast_returns_valid_status_string(monkeypatch):
    """即便部分组件失败，status 也是三态之一。"""
    from fastapi.testclient import TestClient
    from fastapi_app.main import app
    client = TestClient(app)
    r = client.get("/api/v1/system/health-check/fast")
    assert r.status_code == 200
    assert r.json()["status"] in ("healthy", "degraded", "unknown")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL  {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
