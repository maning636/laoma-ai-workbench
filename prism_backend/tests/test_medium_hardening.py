"""2026-10-19 medium-hardening · 独立测试。

覆盖 §3.2 的 4 项代码变更（第 5/6 项在别处已保证或无需变更）：
  1. Redis 幂等原子化：并发同 key 只允许 1 个首次请求执行
  2. CORS 白名单化：main.py 不再使用 `allow_origins=["*"]`
  3. 请求级限流：超过阈值返回 429（用内存 Redis fake 验证）
  4. prompt 长度上限：>10000 字符 → 400
  5. JWT user_id：伪造 Authorization → 401；无 header → 兼容 body

用法：
  cd prism_backend && python tests/test_medium_hardening.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

# 让 prism_backend 和 repo root 都可导入（cloud_service 在 repo root 下）
_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_TOP = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_TOP) not in sys.path:
    sys.path.insert(0, str(_REPO_TOP))

_FAILS = 0
_PASSES = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global _FAILS, _PASSES
    if cond:
        _PASSES += 1
        print(f"[PASS] {label}")
    else:
        _FAILS += 1
        print(f"[FAIL] {label}" + (f" -- {extra}" if extra else ""))


# ──────────────────────────────────────────────────────────────
# Fix #1 · Redis 幂等原子化（并发同 key 只放行 1 个）
# ──────────────────────────────────────────────────────────────


def test_1_idempotency_concurrent_single_winner() -> None:
    from fusion_ai import idempotency

    # 清空缓存（幂等模块的实际 API 是 clear_cache）
    idempotency.clear_cache()
    idempotency.force_memory_backend()  # 确保使用内存后端（无 Redis 时）

    # 用同一 (user_id, key) 并发发起 10 个 acquire
    N = 10
    results = []
    barrier = threading.Barrier(N)
    errors: list = []

    def worker(idx: int) -> None:
        try:
            barrier.wait()
            r = idempotency.acquire("u_concurrent", "key_1", ttl=60)
            results.append((idx, r))
        except Exception as e:
            errors.append((idx, e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check("idempotency 并发无异常", not errors, f"errors={errors}")

    firsts = [r for _, r in results if not r.seen_before]
    others = [r for _, r in results if r.seen_before]
    check(
        f"idempotency 并发 {N} 请求中恰好 1 个首次成功",
        len(firsts) == 1,
        f"firsts={len(firsts)}",
    )
    check(
        f"idempotency 并发 {N} 请求中其余均为 in_flight",
        len(others) == N - 1 and all(o.in_flight for o in others),
        f"others={len(others)}",
    )


def test_2_idempotency_set_nx_memory_backend_direct() -> None:
    """直接验证 _MemoryBackend.set_nx 的原子语义。"""
    from fusion_ai import idempotency

    b = idempotency._MemoryBackend()
    ok1 = b.set_nx("k1", "v1", ttl=60)
    ok2 = b.set_nx("k1", "v2", ttl=60)
    val = b.get("k1")
    check("memory backend set_nx 首次写入 True", ok1 is True, f"got={ok1}")
    check("memory backend set_nx 重复写入 False", ok2 is False, f"got={ok2}")
    check("memory backend set_nx 保留首次写入值", val == "v1", f"got={val!r}")

    # TTL 过期后可再次抢占
    b2 = idempotency._MemoryBackend()
    b2.set_nx("k2", "v_a", ttl=1)
    time.sleep(1.05)
    ok_after_ttl = b2.set_nx("k2", "v_b", ttl=60)
    val2 = b2.get("k2")
    check("memory backend set_nx TTL 过期后可重新抢占", ok_after_ttl is True)
    check("memory backend set_nx TTL 过期后覆盖旧值", val2 == "v_b")


# ──────────────────────────────────────────────────────────────
# Fix #2 · CORS 白名单化
# ──────────────────────────────────────────────────────────────


def test_3_cors_no_wildcard_in_prism_backend_main() -> None:
    """prism_backend/fastapi_app/main.py 不应再使用 allow_origins=["*"]。

    只检查实际 add_middleware 调用，忽略注释中的"改自 X" 之类说明。
    """
    main_path = _REPO_ROOT / "fastapi_app" / "main.py"
    src = main_path.read_text(encoding="utf-8")

    # 提取所有 `app.add_middleware(CORSMiddleware, ...)` 调用块
    # 简化：找到所有出现 allow_origins=... 的行，检查其中不含通配值
    import re
    allow_origins_lines = [
        line.strip() for line in src.splitlines()
        if "allow_origins" in line and not line.lstrip().startswith("#")
    ]
    check("main.py 至少一处 allow_origins 定义（非注释）",
          len(allow_origins_lines) >= 1,
          f"lines={allow_origins_lines}")
    wildcards = [
        ln for ln in allow_origins_lines
        if re.search(r'allow_origins\s*=\s*[\["\']\*', ln)
    ]
    check("main.py 无通配 allow_origins（非注释行）",
          not wildcards,
          f"wildcard_lines={wildcards}")
    check(
        "main.py 使用 settings.CORS_ORIGINS",
        "settings.CORS_ORIGINS" in src,
    )


def test_4_settings_cors_origins_defaults_to_local_dev() -> None:
    """settings.CORS_ORIGINS 默认覆盖本地开发，且绝不含 '*'。"""
    from fastapi_app.core.config import settings
    origins = settings.CORS_ORIGINS
    check("settings.CORS_ORIGINS 是列表", isinstance(origins, list))
    check(
        "settings.CORS_ORIGINS 不包含 '*'（通配）",
        "*" not in origins,
        f"origins={origins}",
    )
    # 至少覆盖一个本地开发来源
    has_local = any(
        "localhost" in o or "127.0.0.1" in o for o in origins
    )
    check("settings.CORS_ORIGINS 至少覆盖 localhost", has_local)


def test_5_cloud_service_cors_no_wildcard() -> None:
    """cloud_service/main.py 也不应包含 allow_origins=[\"*\"]（此前已合规）。"""
    # 通过 repo 根目录定位
    repo = _REPO_ROOT.parent  # prism_backend -> repo root
    cloud_main = repo / "cloud_service" / "main.py"
    src = cloud_main.read_text(encoding="utf-8")
    check(
        "cloud_service/main.py 不含 `allow_origins=[\"*\"]`",
        'allow_origins=["*"]' not in src and "allow_origins=['*']" not in src,
    )


# ──────────────────────────────────────────────────────────────
# Fix #3 · 请求级限流
# ──────────────────────────────────────────────────────────────


class _FakeRedis:
    """最小 Redis 替身：INCR + TTL + EXPIRE。用于验证限流逻辑。"""

    def __init__(self) -> None:
        self._d: Dict[str, int] = {}
        self._ttl: Dict[str, int] = {}

    def incr(self, key: str) -> int:
        self._d[key] = self._d.get(key, 0) + 1
        return self._d[key]

    def expire(self, key: str, seconds: int) -> bool:
        self._ttl[key] = int(seconds)
        return True

    def ttl(self, key: str) -> int:
        if key not in self._d:
            return -2
        return self._ttl.get(key, -1)


def test_6_rate_limit_middleware_blocks_over_limit() -> None:
    """限流 middleware 应把超限请求返回 429，正常请求放行。"""
    import asyncio as _aio
    from cloud_service.middleware.rate_limit import RateLimitMiddleware

    fake = _FakeRedis()

    async def _inner(scope, receive, send):
        msg = {"type": "http.response.start",
               "status": 200,
               "headers": [(b"content-type", b"application/json")]}
        await send(msg)
        await send({"type": "http.response.body", "body": b'{"ok":1}'})

    mw = RateLimitMiddleware(
        _inner,
        rules=[(("POST", "/cloud/points/freeze"), 3)],
        window_seconds=60,
        redis_url=None,
    )

    # 直接把 fake redis 注入 module-level `_try_get_redis`
    import cloud_service.middleware.rate_limit as rl_mod
    orig = rl_mod._try_get_redis
    rl_mod._try_get_redis = lambda *a, **k: fake

    try:
        captured = []

        async def _scope(method, path, user_hint=None, client_host=None):
            sc: Dict[str, Any] = {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": b"",
                "headers": [],
            }
            if user_hint:
                # Starlette Request.state 期望 scope["state"] 为 dict
                sc["state"] = {"user_id": user_hint}
            if client_host:
                sc["client"] = type("C", (), {"host": client_host})()

            async def _recv():
                return {"type": "http.request", "body": b""}

            async def _send(msg):
                # 只捕获 http.response.start（含 status）
                if msg.get("type") == "http.response.start":
                    captured.append((method, path, msg.get("status")))

            await mw(sc, _recv, _send)

        async def run():
            # 顺序执行：避免 asyncio.gather 并发导致 captured 顺序非确定
            seq = [
                ("POST", "/cloud/points/freeze", "u1"),
                ("POST", "/cloud/points/freeze", "u1"),
                ("POST", "/cloud/points/freeze", "u1"),
                ("POST", "/cloud/points/freeze", "u1"),  # 4th → 429
                ("POST", "/cloud/points/freeze", "u2"),   # 独立配额，放行
            ]
            for method, path, hint in seq:
                await _scope(method, path, user_hint=hint)

        captured.clear()
        _aio.run(run())
        statuses = [c[2] for c in captured]
        check("限流：前 3 次放行 (status=200)",
              statuses[:3] == [200, 200, 200],
              f"got={statuses[:3]}")
        check("限流：第 4 次触发 429",
              statuses[3] == 429,
              f"got={statuses[3]}")
        check("限流：其他用户不受影响",
              statuses[4] == 200,
              f"got={statuses[4]}")
    finally:
        rl_mod._try_get_redis = orig


def test_7_rate_limit_fallback_allow_when_redis_missing() -> None:
    """Redis 不可用时应降级放行（避免限流故障拖垮核心 API）。"""
    import asyncio as _aio
    from cloud_service.middleware.rate_limit import RateLimitMiddleware
    import cloud_service.middleware.rate_limit as rl_mod

    async def _inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = RateLimitMiddleware(_inner, rules=[(("POST", "/cloud/points/freeze"), 1)],
                             window_seconds=60)

    orig = rl_mod._try_get_redis
    rl_mod._try_get_redis = lambda *a, **k: None  # 模拟 Redis 不可用
    try:
        captured = []

        async def _scope():
            sc = {"type": "http", "method": "POST",
                  "path": "/cloud/points/freeze",
                  "query_string": b"", "headers": []}

            async def _recv():
                return {"type": "http.request", "body": b""}

            async def _send(msg):
                if msg.get("type") == "http.response.start":
                    captured.append(msg.get("status"))

            await mw(sc, _recv, _send)

        async def run():
            await _aio.gather(_scope(), _scope(), _scope())

        _aio.run(run())
        check("Redis 不可用降级：所有请求放行",
              captured == [200, 200, 200],
              f"got={captured}")
    finally:
        rl_mod._try_get_redis = orig


# ──────────────────────────────────────────────────────────────
# Fix #4 · prompt 长度上限
# ──────────────────────────────────────────────────────────────


def test_8_prompt_too_long_returns_400() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fusion_ai import ai_design

    app = FastAPI()
    app.include_router(ai_design.router, prefix="/api/v1")
    tc = TestClient(app)

    # 超长 prompt（> 10000）
    r = tc.post(
        "/api/v1/ai-design/generate",
        json={
            "model_key": "dall-e-3",
            "prompt": "x" * 10001,
            "count": 1,
            "user_id": "u1",
        },
    )
    check("prompt 超长返回 400", r.status_code == 400, f"got={r.status_code}")
    detail = r.json().get("detail", "")
    check("prompt 超长错误信息含 'too long'", "too long" in detail,
          f"detail={detail!r}")

    # 边界：正好 10000 应该放行（这里会走后续流程，可能返回 502/其他，
    # 但绝不能再是"too long"错误）
    r2 = tc.post(
        "/api/v1/ai-design/generate",
        json={
            "model_key": "dall-e-3",
            "prompt": "y" * 10000,
            "count": 1,
            "user_id": "u1",
        },
    )
    detail2 = r2.json().get("detail", "") if r2.content else ""
    check("prompt = 10000 字符不触发 'too long' 错误",
          "too long" not in detail2,
          f"status={r2.status_code} detail={detail2[:120]!r}")


# ──────────────────────────────────────────────────────────────
# Fix #5 · JWT user_id
# ──────────────────────────────────────────────────────────────


def test_9_fake_authorization_returns_401() -> None:
    """携带伪造 Authorization header → 401，不允许降级到 body.user_id。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fusion_ai import ai_design

    app = FastAPI()
    app.include_router(ai_design.router, prefix="/api/v1")
    tc = TestClient(app)

    r = tc.post(
        "/api/v1/ai-design/generate",
        json={
            "model_key": "dall-e-3",
            "prompt": "hello",
            "count": 1,
            "user_id": "alice",  # 伪造 body，但 header 已声明 → 拒绝
        },
        headers={"Authorization": "Bearer not.a.real.jwt"},
    )
    check("伪造 Authorization 返回 401", r.status_code == 401,
          f"got={r.status_code} body={r.json()}")


def test_10_missing_authorization_body_user_id_still_works() -> None:
    """无 Authorization header 时，body.user_id 仍被信任（兼容模式）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fusion_ai import ai_design
    from fusion_ai import image_gen_models

    # 隔离 DB
    try:
        image_gen_models.clear_all_records()
    except Exception:
        pass

    app = FastAPI()
    app.include_router(ai_design.router, prefix="/api/v1")
    tc = TestClient(app)

    # 不传 Authorization，走 body.user_id（旧行为）
    # 这里 provider 会失败，但只要 user_id 被正确解析（不 401）就 OK
    r = tc.post(
        "/api/v1/ai-design/generate",
        json={
            "model_key": "dall-e-3",
            "prompt": "hello world",
            "count": 1,
            "user_id": "compat_user",
        },
    )
    # 期待不是 401
    check("无 Authorization + body.user_id 不返回 401",
          r.status_code != 401,
          f"got={r.status_code}")


def test_11_valid_jwt_sets_user_id_from_sub() -> None:
    """合法 JWT 应把 sub 作为 user_id（忽略 body.user_id）。"""
    import os as _os
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fusion_ai import ai_design
    from fusion_ai import image_gen_models

    # 使用固定 JWT secret
    _os.environ["JWT_SECRET"] = "test-secret-medium-hardening"

    # 注入生成函数，捕获传入的 prompt / user 相关数据
    captured_user_id: list = []

    async def _fake_gen(model_def, prompt, size):
        return {"success": True, "url": "https://img.example/x.png"}

    # 用 mock points client 简化流程
    class _MockClient:
        def points_for_ai_image(self):
            return 1.5
        def freeze(self, **kw):
            return {"freezeTxId": 9001, "amount": kw.get("amount", 0)}
        def consume(self, txid, **kw):
            return {"ok": True, "consumeTxId": 9002}
        def rollback(self, txid, **kw):
            return {"ok": True}

    ai_design.set_generate_fn(_fake_gen)
    ai_design.set_points_client_provider(lambda: _MockClient())

    # 隔离 DB：drop 表 + 重新建表
    try:
        image_gen_models.drop_table_for_test()
    except Exception:
        pass
    try:
        image_gen_models.reset_ensured()
    except Exception:
        pass

    app = FastAPI()
    app.include_router(ai_design.router, prefix="/api/v1")
    tc = TestClient(app)

    # 生成合法 token（HS256）
    import jwt as _pyjwt
    token = _pyjwt.encode(
        {"sub": "jwt_user_42", "type": "access"},
        "test-secret-medium-hardening",
        algorithm="HS256",
    )

    r = tc.post(
        "/api/v1/ai-design/generate",
        json={
            "model_key": "dall-e-3",
            "prompt": "jwt test",
            "count": 1,
            "user_id": "spoofed_body_value",  # 应该被忽略
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        # 期望 200（生图成功）
        check("合法 JWT 请求返回 200", r.status_code == 200,
              f"got={r.status_code} body={r.text[:200]}")
        if r.status_code == 200:
            # 检查 DB 记录：user_id 应该是 jwt_user_42 而不是 spoofed_body_value
            rec = image_gen_models.list_records(user_id="jwt_user_42", current=1, size=5)
            found = rec.get("records") or []
            check("JWT 请求的记录归属 jwt_user_42（忽略 body.user_id）",
                  len(found) >= 1,
                  f"records={found}")
            spoofed = image_gen_models.list_records(
                user_id="spoofed_body_value", current=1, size=5
            )
            check("body.user_id 未被使用（spoofed_body_value 无记录）",
                  not (spoofed.get("records") or []),
                  f"spoofed_records={spoofed.get('records')}")
    finally:
        ai_design.reset_generate_fn()
        ai_design.reset_points_client_provider()
        try:
            image_gen_models.drop_table_for_test()
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────


def main() -> int:
    tests = [
        test_1_idempotency_concurrent_single_winner,
        test_2_idempotency_set_nx_memory_backend_direct,
        test_3_cors_no_wildcard_in_prism_backend_main,
        test_4_settings_cors_origins_defaults_to_local_dev,
        test_5_cloud_service_cors_no_wildcard,
        test_6_rate_limit_middleware_blocks_over_limit,
        test_7_rate_limit_fallback_allow_when_redis_missing,
        test_8_prompt_too_long_returns_400,
        test_9_fake_authorization_returns_401,
        test_10_missing_authorization_body_user_id_still_works,
        test_11_valid_jwt_sets_user_id_from_sub,
    ]

    for t in tests:
        try:
            t()
        except Exception as exc:
            global _FAILS
            _FAILS += 1
            print(f"[FAIL] {t.__name__} 抛出异常: {exc.__class__.__name__}: {exc}")
            import traceback
            traceback.print_exc()

    total = _PASSES + _FAILS
    print(f"\n{'=' * 60}")
    print(f"2026-10-19 medium-hardening: {total} checks, "
          f"PASS={_PASSES}, FAIL={_FAILS}")
    if _FAILS == 0:
        print("ALL TESTS PASSED")
        return 0
    print("SOME TESTS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
