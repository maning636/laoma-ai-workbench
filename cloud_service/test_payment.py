"""C19 · Payment TestClient 集成测试(不启动服务,不落仓库文件)。

覆盖验收 4 项:
  1. 语法 + import(在命令行执行 `python -c "import ..."` 时另测,本脚本负责运行时导入)
  2. 端点定义(在命令行执行 `python -c "from cloud_service.main import app; ..."` 时另测)
  3. TestClient mock 流程(register→login→create_order→mock callback→order paid→订阅激活)
  4. 幂等:重复 callback 不重复激活

用法:
  python cloud_service/test_payment.py
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

# 便于测试:free quota 小,pro quota 无限
os.environ["CLOUD_FREE_QUOTA"] = "5"
os.environ["CLOUD_PRO_QUOTA"] = "-1"

# 回调 URL(与 mock 签名 payload 对齐)
os.environ["CLOUD_PAYMENT_NOTIFY_URL"] = "/cloud/payment/callback/alipay"
os.environ["CLOUD_PAYMENT_RETURN_URL"] = "/payment/success"

# 确保能导入仓库根
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def _mk_alipay_callback(order_no: str, trade_no: str, amount: float,
                        plan: str = "pro", days: int = 30) -> dict:
    """构造一份合法的支付宝回调 body(带 mock 签名)。"""
    from cloud_service.payment import alipay
    adapter = alipay.AlipayAdapter()
    payload = {
        "out_trade_no": order_no,
        "total_amount": f"{amount:.2f}",
        "plan": plan,
        "days": str(days),
        "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
        "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
    }
    sign = alipay._mock_sign(adapter._sign_secret, payload)
    return {
        "out_trade_no": order_no,
        "trade_no": trade_no,
        "total_amount": f"{amount:.2f}",
        "trade_status": "TRADE_SUCCESS",
        "plan": plan,
        "days": str(days),
        "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
        "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
        "sign": sign,
    }


def _mk_wechat_callback(order_no: str, transaction_id: str, total_fen: int,
                        plan: str = "pro", days: int = 30) -> dict:
    """构造一份合法的微信回调 body(带 mock 签名)。"""
    from cloud_service.payment import wechat
    adapter = wechat.WechatAdapter()
    payload = {
        "out_trade_no": order_no,
        "total_fen": str(total_fen),
        "plan": plan,
        "days": str(days),
        "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
        "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
    }
    sign = wechat._mock_sign(adapter._sign_secret, payload)
    return {
        "out_trade_no": order_no,
        "transaction_id": transaction_id,
        "total_fen": total_fen,
        "trade_state": "SUCCESS",
        "plan": plan,
        "days": str(days),
        "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
        "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
        "sign": sign,
    }


def run() -> int:
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
            json={"username": "dave", "email": "dave@example.com",
                  "password": "supers3cret"},
        )
        check("register dave", r.status_code == 201, f"status={r.status_code}")
        r = client.post(
            "/cloud/auth/login",
            json={"username": "dave", "password": "supers3cret"},
        )
        check("login dave", r.status_code == 200, f"status={r.status_code}")
        access = r.json().get("access_token", "")
        H = {"Authorization": f"Bearer {access}"}

        # ── 2. 创建订单(支付宝)────────────────────────
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "alipay"},
            headers=H,
        )
        check("POST /payment/create_order alipay -> 201",
              r.status_code == 201, f"status={r.status_code} body={r.text[:200]}")
        order_data = r.json()
        order_no = order_data.get("order_no", "")
        check("order_no non-empty", bool(order_no), f"body={order_data}")
        check("order.channel == alipay", order_data.get("channel") == "alipay")
        check("order.amount == 99.0", order_data.get("amount") == 99.0,
              f"amount={order_data.get('amount')}")
        pp = order_data.get("pay_params", {})
        check("pay_params.pay_type == form",
              pp.get("pay_type") == "form", f"pp={pp}")
        check("pay_params.form_html present",
              "form" in str(pp.get("form_html", "")), f"pp={pp}")

        # 无 JWT → 401
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "alipay"},
        )
        check("create_order without JWT -> 401", r.status_code == 401)

        # 不支持渠道 → 422
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "stripe"},
            headers=H,
        )
        check("create_order invalid channel -> 422", r.status_code == 422,
              f"status={r.status_code}")

        # ── 3. 查询订单(created 状态)──────────────────
        r = client.get(f"/cloud/payment/order/{order_no}", headers=H)
        check("GET /payment/order/{order_no} -> 200", r.status_code == 200,
              f"status={r.status_code}")
        check("order.status == created",
              r.json().get("status") == "created", f"body={r.json()}")

        # ── 4. 支付回调(支付宝 mock)──────────────────
        trade_no = "2026101300001"
        cb = _mk_alipay_callback(order_no, trade_no, amount=99.0)
        r = client.post("/cloud/payment/callback/alipay", json=cb)
        check("POST /payment/callback/alipay -> 200",
              r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        cb_resp = r.json()
        check("callback.ok == True", cb_resp.get("ok") is True)
        check("callback.activated == True", cb_resp.get("activated") is True)
        sub = cb_resp.get("subscription") or {}
        check("callback subscription.plan == pro",
              sub.get("plan") == "pro", f"sub={sub}")
        check("callback subscription.is_pro == True",
              sub.get("is_pro") is True, f"sub={sub}")

        # ── 5. 订单状态变 paid ────────────────────────
        r = client.get(f"/cloud/payment/order/{order_no}", headers=H)
        check("GET /payment/order -> paid", r.status_code == 200)
        d = r.json()
        check("order.status == paid", d.get("status") == "paid",
              f"body={d}")
        check("order.pay_trade_no filled",
              d.get("pay_trade_no") == trade_no, f"body={d}")
        check("order.paid_at is set", bool(d.get("paid_at")), f"body={d}")

        # ── 6. 订阅激活(通过 /cloud/subscription 复验)──
        r = client.get("/cloud/subscription", headers=H)
        check("GET /cloud/subscription -> 200", r.status_code == 200)
        s = r.json()
        check("subscription.plan == pro", s.get("plan") == "pro", f"body={s}")
        check("subscription.is_pro == True", s.get("is_pro") is True)
        check("subscription.quota == -1 (unlimited)",
              s.get("quota") == -1, f"body={s}")
        check("subscription.expire_at set", bool(s.get("expire_at")))

        # ── 7. 幂等:重复回调不重复激活 ────────────────
        r = client.post("/cloud/payment/callback/alipay", json=cb)
        check("duplicate callback -> 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        dup = r.json()
        check("duplicate callback.ok == True", dup.get("ok") is True)
        check("duplicate callback.activated == False (idempotent no-op)",
              dup.get("activated") is False, f"body={dup}")

        # 验证订阅 expire_at 未被重复延长:再抓一次订阅,应与第一次一致
        r1 = client.get("/cloud/subscription", headers=H)
        exp1 = r1.json().get("expire_at")
        # 再次回调,再抓一次
        client.post("/cloud/payment/callback/alipay", json=cb)
        r2 = client.get("/cloud/subscription", headers=H)
        exp2 = r2.json().get("expire_at")
        check("subscription expire_at unchanged after repeat callback",
              exp1 == exp2, f"exp1={exp1} exp2={exp2}")

        # ── 8. 签名错误 → 400 ─────────────────────────
        bad_cb = dict(cb)
        bad_cb["sign"] = "tampered"
        r = client.post("/cloud/payment/callback/alipay", json=bad_cb)
        check("callback with bad sign -> 400", r.status_code == 400,
              f"status={r.status_code}")

        # ── 9. 不存在订单 → 400 ──────────────────────
        from cloud_service.payment import alipay as _a
        adapter = _a.AlipayAdapter()
        payload = {
            "out_trade_no": "PF_NOSUCH_ORDER",
            "total_amount": "99.00",
            "plan": "pro",
            "days": "30",
            "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
            "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
        }
        _sign = _a._mock_sign(adapter._sign_secret, payload)
        ghost = {
            **payload,
            "trade_no": "GHOST1",
            "trade_status": "TRADE_SUCCESS",
            "sign": _sign,
        }
        r = client.post("/cloud/payment/callback/alipay", json=ghost)
        check("callback for nonexistent order -> 400", r.status_code == 400,
              f"status={r.status_code}")

        # ── 10. 微信通道完整流程(独立订单)──────────────
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "wechat"},
            headers=H,
        )
        check("POST /payment/create_order wechat -> 201",
              r.status_code == 201, f"status={r.status_code}")
        wx_order = r.json()
        wx_order_no = wx_order.get("order_no", "")
        check("wechat order_no non-empty", bool(wx_order_no))
        wx_pp = wx_order.get("pay_params", {})
        check("wechat pay_params.pay_type == qrcode",
              wx_pp.get("pay_type") == "qrcode", f"pp={wx_pp}")
        check("wechat pay_params.code_url present",
              "weixin://wxpay" in str(wx_pp.get("code_url", "")), f"pp={wx_pp}")

        wx_cb = _mk_wechat_callback(wx_order_no, "WX_TX_0001", total_fen=9900)
        r = client.post("/cloud/payment/callback/wechat", json=wx_cb)
        check("POST /payment/callback/wechat -> 200",
              r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        wx_resp = r.json()
        check("wechat callback.activated == True",
              wx_resp.get("activated") is True, f"body={wx_resp}")
        check("wechat callback subscription.plan == pro",
              (wx_resp.get("subscription") or {}).get("plan") == "pro")

        # 微信订单 → paid
        r = client.get(f"/cloud/payment/order/{wx_order_no}", headers=H)
        check("wechat order status == paid",
              r.json().get("status") == "paid", f"body={r.json()}")

        # ── 11. 订单归属:陌生人查询他人订单 → 404 ─────
        r2 = client.post(
            "/cloud/auth/register",
            json={"username": "eve", "email": "eve@example.com",
                  "password": "supers3cret"},
        )
        check("register eve", r2.status_code == 201)
        r2 = client.post(
            "/cloud/auth/login",
            json={"username": "eve", "password": "supers3cret"},
        )
        H_eve = {"Authorization": f"Bearer {r2.json()['access_token']}"}
        r = client.get(f"/cloud/payment/order/{order_no}", headers=H_eve)
        check("eve accessing dave's order -> 404", r.status_code == 404,
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
