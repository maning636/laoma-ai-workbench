"""C13 · Billing TestClient 集成测试(不启动服务,不落仓库文件)。

覆盖:register → login → GET /cloud/subscription → POST /cloud/usage/consume
→ POST /cloud/license/verify → 激活 pro → 再次消费。

用法:
  python cloud_service/test_billing.py
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

# 让 free quota 较小,便于验证超额场景
os.environ["CLOUD_FREE_QUOTA"] = "5"
os.environ["CLOUD_PRO_QUOTA"] = "-1"

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
        # ── 1. 注册 + 登录 ─────────────────────────────
        r = client.post(
            "/cloud/auth/register",
            json={
                "username": "carol",
                "email": "carol@example.com",
                "password": "supers3cret",
            },
        )
        check("POST /cloud/auth/register carol", r.status_code == 201,
              f"status={r.status_code} body={r.text[:120]}")

        r = client.post(
            "/cloud/auth/login",
            json={"username": "carol", "password": "supers3cret"},
        )
        check("POST /cloud/auth/login carol", r.status_code == 200,
              f"status={r.status_code}")
        tokens = r.json()
        access = tokens.get("access_token", "")
        check("login returns access_token", bool(access), f"len={len(access)}")
        H = {"Authorization": f"Bearer {access}"}

        # ── 2. GET /cloud/subscription(懒创建 free) ─────
        r = client.get("/cloud/subscription", headers=H)
        check("GET /cloud/subscription -> 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        sub = r.json()
        check("subscription.plan == free", sub.get("plan") == "free",
              f"body={sub}")
        check("subscription.status == active", sub.get("status") == "active",
              f"body={sub}")
        check("subscription.quota == 5 (free_quota env)", sub.get("quota") == 5,
              f"quota={sub.get('quota')}")
        check("subscription.used == 0", sub.get("used") == 0,
              f"used={sub.get('used')}")
        check("subscription.remaining == 5", sub.get("remaining") == 5,
              f"remaining={sub.get('remaining')}")
        check("subscription.is_pro == False", sub.get("is_pro") is False,
              f"is_pro={sub.get('is_pro')}")

        # 无 JWT → 401
        r = client.get("/cloud/subscription")
        check("GET /cloud/subscription without JWT -> 401", r.status_code == 401,
              f"status={r.status_code}")

        # ── 3. POST /cloud/usage/consume(累加) ─────────
        r = client.post("/cloud/usage/consume", json={"amount": 1}, headers=H)
        check("POST /cloud/usage/consume amount=1 -> 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        c1 = r.json()
        check("consume 1: used=1", c1.get("used") == 1, f"body={c1}")
        check("consume 1: remaining=4", c1.get("remaining") == 4, f"body={c1}")
        check("consume 1: period YYYY-MM", len(c1.get("period", "")) == 7,
              f"period={c1.get('period')}")

        # 再消费 3 个
        r = client.post("/cloud/usage/consume", json={"amount": 3}, headers=H)
        check("POST /cloud/usage/consume amount=3 -> 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        c2 = r.json()
        check("consume +3: used=4", c2.get("used") == 4, f"body={c2}")
        check("consume +3: remaining=1", c2.get("remaining") == 1, f"body={c2}")

        # GET /subscription 应能看到累计
        r = client.get("/cloud/subscription", headers=H)
        check("GET /cloud/subscription after consume: used=4",
              r.json().get("used") == 4, f"body={r.json()}")

        # ── 4. POST /cloud/license/verify(心跳) ─────────
        r = client.post("/cloud/license/verify", headers=H)
        check("POST /cloud/license/verify -> 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        lic = r.json()
        check("license.valid == True (free active)", lic.get("valid") is True,
              f"body={lic}")
        check("license.plan == free", lic.get("plan") == "free",
              f"plan={lic.get('plan')}")
        check("license.is_pro == False", lic.get("is_pro") is False,
              f"is_pro={lic.get('is_pro')}")
        check("license.remaining == 1", lic.get("remaining") == 1,
              f"remaining={lic.get('remaining')}")

        # ── 5. 超额 → 402 ──────────────────────────────
        r = client.post("/cloud/usage/consume", json={"amount": 5}, headers=H)
        check("POST /cloud/usage/consume overshoot -> 402",
              r.status_code == 402, f"status={r.status_code} body={r.text[:200]}")
        check("402 detail mentions quota exceeded",
              "quota" in r.text.lower() and "exceed" in r.text.lower(),
              f"detail={r.text}")

        # 验证超额后 used 保持 4(事务回滚)
        r = client.get("/cloud/subscription", headers=H)
        check("after 402: used stays 4 (rollback)", r.json().get("used") == 4,
              f"body={r.json()}")

        # ── 6. 激活 pro(C19 支付前的模拟端点) ───────────
        r = client.post(
            "/cloud/subscription/activate",
            json={"plan": "pro", "days": 30},
            headers=H,
        )
        check("POST /cloud/subscription/activate pro -> 200",
              r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        pro = r.json()
        check("pro.plan == pro", pro.get("plan") == "pro", f"body={pro}")
        check("pro.is_pro == True", pro.get("is_pro") is True,
              f"is_pro={pro.get('is_pro')}")
        check("pro.quota == -1 (unlimited)", pro.get("quota") == -1,
              f"quota={pro.get('quota')}")
        check("pro.remaining == -1 (unlimited)", pro.get("remaining") == -1,
              f"remaining={pro.get('remaining')}")
        check("pro.expire_at is set", bool(pro.get("expire_at")),
              f"expire_at={pro.get('expire_at')}")
        check("pro.used reset to 0 on activation", pro.get("used") == 0,
              f"used={pro.get('used')}")

        # ── 7. 激活后 license/verify 应返回 pro ─────────
        r = client.post("/cloud/license/verify", headers=H)
        check("license/verify after pro -> 200", r.status_code == 200,
              f"status={r.status_code}")
        lic2 = r.json()
        check("license.is_pro == True", lic2.get("is_pro") is True,
              f"body={lic2}")
        check("license.reason == active (pro)", lic2.get("reason") == "active",
              f"reason={lic2.get('reason')}")

        # ── 8. 无效 plan → 422 ────────────────────────
        r = client.post(
            "/cloud/subscription/activate",
            json={"plan": "enterprise", "days": 30},
            headers=H,
        )
        check("activate invalid plan -> 422", r.status_code == 422,
              f"status={r.status_code}")

        # ── 9. consume amount <= 0 → 422 ─────────────
        r = client.post("/cloud/usage/consume", json={"amount": 0}, headers=H)
        check("consume amount=0 -> 422", r.status_code == 422,
              f"status={r.status_code}")

        # ── 10. 无 JWT 的 consume → 401 ───────────────
        r = client.post("/cloud/usage/consume", json={"amount": 1})
        check("consume without JWT -> 401", r.status_code == 401,
              f"status={r.status_code}")

    try:
        Path(_tmp.name).unlink(missing_ok=True)
    except OSError:
        pass

    return fails


if __name__ == "__main__":
    rc = run()
    print(f"\n{'ALL TESTS PASSED' if rc == 0 else f'{rc} TEST(S) FAILED'}")
    sys.exit(0 if rc == 0 else 1)
