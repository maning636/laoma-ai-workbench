"""线下人工充值模式 · 端到端验收测试。

覆盖「平台支付彻底删除后,商业闭环仍然完整」这条主线:

  1. **平台支付端点已不存在** → `/cloud/payment/*` 与 `POST /cloud/points/recharge`
     一律 404(不是 403:能力被删除,而非被开关关闭);
  2. `GET /cloud/points/recharge/options` 保留为**人工充值对账用**的档位与赠送规则,
     渠道恒为 `manual_wechat`,且不再有 `paymentChannels` 字段;
  3. 「模拟激活订阅」端点生产默认关闭(否则任何人注册即得 Pro);
  4. **注册码激活仍能开通订阅 + 注入积分额度**(积分入账不依赖支付通道);
  5. 注册码重复同步 → 积分**不重复注入**(按 license_id 幂等);
  6. 管理端可随时增减/设定账户积分;
  7. 管理端 token 缺失或错误 → 拒绝(fail-closed)。

用法:
    python cloud_service/test_manual_recharge.py
    # 或:python -m pytest cloud_service/test_manual_recharge.py -q
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

os.environ["CLOUD_FREE_QUOTA"] = "5"
os.environ["CLOUD_PRO_QUOTA"] = "-1"
os.environ["CLOUD_ADMIN_TOKEN"] = "test-admin-token"

# ⚠️ 2026-10-23:平台支付已**彻底删除**,不再有 CLOUD_ONLINE_PAYMENT_ENABLED 开关。
# 这里显式清掉它,防止外部环境残留变量影响「端点不存在」这一断言。
os.environ.pop("CLOUD_ONLINE_PAYMENT_ENABLED", None)
# 「模拟激活订阅」端点也应保持关闭 —— 它正是要验证被拦住的那个。
os.environ.pop("CLOUD_DEV_ALLOW_SUBSCRIPTION_ACTIVATE", None)

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _make_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return private_key, public_hex


def _issue(private_key, **overrides) -> str:
    """签一个注册码 token(结构与正式签发脚本一致)。"""
    from cloud_service.billing import license_verify as lv

    payload = {
        "v": lv.PAYLOAD_VERSION,
        "lid": "LIC-TEST-000001",
        "ent": ["core", "ai_cloud"],
        "iat": "2026-01-01T00:00:00+00:00",
        "exp": "2027-01-01T00:00:00+00:00",
        "grace": 7,
        "cust": "测试客户",
        "note": "",
    }
    payload.update(overrides)
    body = lv.json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    body_b64 = lv._b64u_encode(body.encode("utf-8"))
    sig = private_key.sign(body_b64.encode("ascii"))
    return f"{lv.TOKEN_PREFIX}.{body_b64}.{lv._b64u_encode(sig)}"


def run() -> int:
    from fastapi.testclient import TestClient

    from cloud_service.auth.models import User
    from cloud_service.billing import license_activation as la
    from cloud_service.billing.models import Subscription
    from cloud_service.billing.points import get_account
    from cloud_service.db import SessionLocal, init_db
    from cloud_service.main import app

    failures = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal failures
        if cond:
            print(f"[PASS] {label}" + (f" — {extra}" if extra else ""))
        else:
            failures += 1
            print(f"[FAIL] {label}" + (f" — {extra}" if extra else ""))

    init_db()

    # ──────────────────────────────────────────────────────────
    # 1) 平台支付已彻底删除 → 支付端点全部 404(能力不存在)
    # ──────────────────────────────────────────────────────────
    with TestClient(app) as client:
        for method, path, payload in (
            ("POST", "/cloud/payment/create_order",
             {"plan": "pro", "days": 30, "channel": "alipay"}),
            ("POST", "/cloud/payment/callback/alipay",
             {"out_trade_no": "PF-X", "total_amount": "99.00", "sign": "x"}),
            ("GET", "/cloud/payment/order/PF-X", None),
            ("POST", "/cloud/payment/refund", {"order_no": "PF-X"}),
        ):
            fn = client.post if method == "POST" else client.get
            r = fn(path, json=payload) if payload is not None else fn(path)
            check(
                f"{method} {path} → 404(平台支付已删除)",
                r.status_code == 404,
                f"status={r.status_code} body={r.text[:120]}",
            )

        # ──────────────────────────────────────────────────────
        # 2) 在线充值订单端点也已删除;档位端点保留给人工充值对账
        # ──────────────────────────────────────────────────────
        reg = client.post(
            "/cloud/auth/register",
            json={"username": "alice", "email": "alice@example.com", "password": "Passw0rd!"},
        )
        check("注册用户 → 201", reg.status_code == 201, f"status={reg.status_code}")

        # 注册端点只返回用户信息,JWT 要单独登录取
        login = client.post(
            "/cloud/auth/login",
            json={"username": "alice", "password": "Passw0rd!"},
        )
        check("登录 → 200", login.status_code == 200, f"status={login.status_code}")
        token = login.json().get("access_token")
        check("登录返回 access_token", bool(token))
        H = {"Authorization": f"Bearer {token}"}

        r = client.post("/cloud/points/recharge", headers=H, json={"points": 3000, "channel": "alipay"})
        check(
            "POST /cloud/points/recharge → 404(在线充值已删除)",
            r.status_code == 404,
            f"status={r.status_code} body={r.text[:120]}",
        )

        # 档位与赠送规则仍在(运营侧人工收款 / 签发注册码时对账用)
        r = client.get("/cloud/points/recharge/options", headers=H)
        check(
            "GET /cloud/points/recharge/options → 200(保留档位与赠送规则)",
            r.status_code == 200,
            f"status={r.status_code} body={r.text[:160]}",
        )
        if r.status_code == 200:
            opts = r.json()
            check(
                "options.channels == ['manual_wechat']",
                opts.get("channels") == ["manual_wechat"],
                f"got={opts.get('channels')}",
            )
            check(
                "options 不再有 paymentChannels 字段",
                "paymentChannels" not in opts,
                f"keys={sorted(opts)}",
            )
            check(
                "options 有 5 档预设",
                len(opts.get("presets", [])) == 5,
                f"presets={opts.get('presets')}",
            )
            check(
                "options.notice 非空(人工充值说明)",
                bool(opts.get("notice")),
                f"notice={opts.get('notice')!r}",
            )

        # ──────────────────────────────────────────────────────
        # 3) 「模拟激活订阅」端点被拦住(否则注册即得 Pro)
        # ──────────────────────────────────────────────────────
        r = client.post("/cloud/subscription/activate", headers=H, json={"plan": "pro", "days": 30})
        check(
            "POST /cloud/subscription/activate → 403(生产默认关闭)",
            r.status_code == 403,
            f"status={r.status_code} body={r.text[:120]}",
        )

    # ──────────────────────────────────────────────────────────
    # 4) 注册码激活:开通订阅 + 注入积分(不依赖支付通道)
    # ──────────────────────────────────────────────────────────
    private_key, public_hex = _make_keypair()
    token_str = _issue(private_key, cr=2000)

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "alice").one()
        uid = user.id

        before = get_account(db, uid)
        check("激活前可用积分为 0", float(before["availablePoints"]) == 0.0,
              f"实际={before['availablePoints']}")

        result = la.activate_with_license(
            db, user, token_str, quota=-1, public_key_hex=public_hex,
        )
        check("注册码激活返回 ok 结构", "license" in result and "subscription" in result)
        check("本次注入积分 2000", float(result["creditsAdded"]) == 2000.0,
              f"实际={result['creditsAdded']}")
        check("账户可用积分变为 2000",
              float(result["points"]["availablePoints"]) == 2000.0,
              f"实际={result['points']['availablePoints']}")

        sub = db.query(Subscription).filter(Subscription.user_id == uid).one()
        check("订阅 plan=pro", sub.plan == "pro", f"实际={sub.plan}")
        check("订阅状态 active", sub.status == "active", f"实际={sub.status}")
        # 到期时间 = 注册码 exp(2027-01-01) + 宽限 7 天 = 2027-01-08
        check(
            "订阅到期 = 注册码到期日 + 宽限期(与桌面端只读切换点对齐)",
            sub.expire_at is not None
            and sub.expire_at.strftime("%Y-%m-%d") == "2027-01-08",
            f"实际={sub.expire_at}",
        )

        # ──────────────────────────────────────────────────────
        # 5) 幂等:同一注册码重复同步不重复加积分
        # ──────────────────────────────────────────────────────
        again = la.activate_with_license(
            db, user, token_str, quota=-1, public_key_hex=public_hex,
        )
        check("重复激活注入积分为 0", float(again["creditsAdded"]) == 0.0,
              f"实际={again['creditsAdded']}")
        check("重复激活标记 skipped", bool(again["creditsSkipped"]) is True)
        acct = get_account(db, uid)
        check("重复激活后余额仍为 2000",
              float(acct["availablePoints"]) == 2000.0,
              f"实际={acct['availablePoints']}")

        # ──────────────────────────────────────────────────────
        # 6) 非法注册码 → 明确报错,不抛未捕获异常
        # ──────────────────────────────────────────────────────
        try:
            la.activate_with_license(db, user, "PRISM1.bogus.sig", quota=-1,
                                     public_key_hex=public_hex)
        except la.LicenseActivationError:
            check("非法注册码被拒(LicenseActivationError)", True)
        else:
            check("非法注册码被拒(LicenseActivationError)", False)

    # ──────────────────────────────────────────────────────────
    # 7) 管理端:随时调整账户积分(add / set / 负数)
    # ──────────────────────────────────────────────────────────
    with TestClient(app) as client:
        admin = {"X-Admin-Token": "test-admin-token"}

        r = client.post("/cloud/admin/points/adjust", headers=admin,
                        json={"user_id": uid, "amount": 500, "note": "微信充值 500 积分"})
        check("管理端加积分 → 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            check("加积分后余额 2500", float(r.json()["points"]["availablePoints"]) == 2500.0,
                  f"实际={r.json()['points']['availablePoints']}")

        r = client.post("/cloud/admin/points/adjust", headers=admin,
                        json={"user_id": uid, "amount": -300, "note": "纠错扣回"})
        check("管理端扣积分 → 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            check("扣积分后余额 2200", float(r.json()["points"]["availablePoints"]) == 2200.0,
                  f"实际={r.json()['points']['availablePoints']}")

        r = client.post("/cloud/admin/points/adjust", headers=admin,
                        json={"user_id": uid, "mode": "set", "amount": 1000})
        check("管理端设定余额 → 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            check("设定后余额 1000", float(r.json()["points"]["availablePoints"]) == 1000.0,
                  f"实际={r.json()['points']['availablePoints']}")

        # 鉴权:错 token / 无 token
        r = client.post("/cloud/admin/points/adjust", headers={"X-Admin-Token": "wrong"},
                        json={"user_id": uid, "amount": 100})
        check("管理端错误 token → 403", r.status_code == 403, f"status={r.status_code}")

        r = client.post("/cloud/admin/points/adjust", json={"user_id": uid, "amount": 100})
        check("管理端无 token → 403", r.status_code == 403, f"status={r.status_code}")

        # 用户列表
        r = client.get("/cloud/admin/users", headers=admin)
        check("管理端用户列表 → 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200 and r.json().get("items"):
            item = r.json()["items"][0]
            check("用户列表含可用积分字段", "availablePoints" in item, str(item)[:120])

        # 订阅延长
        r = client.post("/cloud/admin/subscription/extend", headers=admin,
                        json={"user_id": uid, "days": 30})
        check("管理端延长订阅 → 200", r.status_code == 200, f"status={r.status_code}")

    print()
    print("RESULT:", "PASS" if failures == 0 else f"FAIL ({failures})")
    return failures


if __name__ == "__main__":
    sys.exit(run())
