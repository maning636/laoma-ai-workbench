"""C12 · 端到端 TestClient 测试(不启动服务,不落仓库文件)。

用法:
  python -c "import sys; sys.path.insert(0,'.'); import tempfile,os; os.environ['CLOUD_DB_URL']='sqlite:///'+tempfile.NamedTemporaryFile(delete=False).name; from cloud_service.test_e2e import run; run()"

或者直接跑:
  python cloud_service/test_e2e.py

覆盖:register → login → me → refresh → me;并验证错误路径(重复注册、密码错、access 当 refresh)。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ── 用临时 SQLite 文件,避免污染仓库 ────────────────────────────
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["CLOUD_DB_URL"] = f"sqlite:///{_tmp.name}"
os.environ.pop("CLOUD_ACCESS_TOKEN_EXPIRE_MINUTES", None)

# 确保能导入仓库根
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def run() -> int:
    """跑完整端到端,返回 0 = 全部通过,非 0 = 失败计数。"""
    from fastapi.testclient import TestClient

    from cloud_service.main import app

    fails = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal fails
        tag = "PASS" if cond else "FAIL"
        print(f"[{tag}] {label}" + (f" — {extra}" if extra else ""))
        if not cond:
            fails += 1

    with TestClient(app) as client:
        # 健康检查
        r = client.get("/health")
        check("GET /health", r.status_code == 200 and r.json().get("status") == "ok",
              f"status={r.status_code}")

        # 注册前:me 应 401
        r = client.get("/cloud/auth/me")
        check("GET /me without token -> 401", r.status_code == 401, f"status={r.status_code}")

        # 注册
        r = client.post("/cloud/auth/register", json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "supers3cret",
        })
        check("POST /register alice", r.status_code == 201,
              f"status={r.status_code} body={r.text[:120]}")
        body = r.json()
        check("register returns id/username", body.get("username") == "alice"
              and body.get("id", 0) > 0)

        # 重复注册 → 409
        r = client.post("/cloud/auth/register", json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "supers3cret",
        })
        check("duplicate register -> 409", r.status_code == 409, f"status={r.status_code}")

        # 弱密码 → 422
        r = client.post("/cloud/auth/register", json={
            "username": "bob",
            "email": "bob@example.com",
            "password": "short",
        })
        check("weak password -> 422", r.status_code == 422, f"status={r.status_code}")

        # 密码错 → 401
        r = client.post("/cloud/auth/login", json={
            "username": "alice",
            "password": "wrongpass123",
        })
        check("login wrong password -> 401", r.status_code == 401, f"status={r.status_code}")

        # 正确登录
        r = client.post("/cloud/auth/login", json={
            "username": "alice",
            "password": "supers3cret",
        })
        check("login alice", r.status_code == 200, f"status={r.status_code}")
        tokens = r.json()
        access = tokens.get("access_token", "")
        refresh = tokens.get("refresh_token", "")
        check("login returns access + refresh + expires_in",
              bool(access) and bool(refresh) and tokens.get("expires_in", 0) > 0,
              f"access_len={len(access)} refresh_len={len(refresh)} ttl={tokens.get('expires_in')}s")

        # me with access token
        r = client.get("/cloud/auth/me", headers={"Authorization": f"Bearer {access}"})
        check("GET /me with access", r.status_code == 200, f"status={r.status_code}")
        me = r.json()
        check("me.username == alice", me.get("username") == "alice",
              f"body={me}")
        check("me does NOT leak password_hash", "password_hash" not in me)

        # refresh endpoint with refresh token
        r = client.post("/cloud/auth/refresh", json={"refresh_token": refresh})
        check("POST /refresh with refresh", r.status_code == 200, f"status={r.status_code}")
        new_access = r.json().get("access_token", "")
        check("refresh returns new access", bool(new_access))

        # new access works for /me
        r = client.get("/cloud/auth/me", headers={"Authorization": f"Bearer {new_access}"})
        check("new access still works for /me", r.status_code == 200, f"status={r.status_code}")

        # 用 access token 去当 refresh token → 401
        r = client.post("/cloud/auth/refresh", json={"refresh_token": access})
        check("access as refresh -> 401", r.status_code == 401, f"status={r.status_code}")

        # 用垃圾 token → 401
        r = client.post("/cloud/auth/refresh", json={"refresh_token": "not-a-token"})
        check("garbage refresh -> 401", r.status_code == 401, f"status={r.status_code}")

        # 用 refresh token 直接调 /me → 401(type != access)
        r = client.get("/cloud/auth/me", headers={"Authorization": f"Bearer {refresh}"})
        check("refresh as access -> 401", r.status_code == 401, f"status={r.status_code}")

    try:
        Path(_tmp.name).unlink(missing_ok=True)
    except OSError:
        pass

    return fails


if __name__ == "__main__":
    rc = run()
    print(f"\n{'ALL TESTS PASSED' if rc == 0 else f'{rc} TEST(S) FAILED'}")
    sys.exit(0 if rc == 0 else 1)
