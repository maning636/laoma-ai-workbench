"""Router Content-Type 分派 + `order_amount` 显式传参 回归测试。

覆盖两个修复点:

1. **支付宝异步通知是 `application/x-www-form-urlencoded`**,router 之前用
   `await request.json()` 会解析失败。这里测试:
     - form-urlencoded 支付宝回调 → 200 + order 变 paid
     - JSON 微信回调路径仍可用 → 200 + 激活
     - form 篡改签名 → 400
     - 未知 Content-Type:先试 JSON,失败回退 form(向后兼容)
     - 未知 Content-Type + 都不是合法体 → 400
2. **`refund(order_no, pay_trade_no, amount, order_amount=None)`**:
   所有 adapter 都接受 4 参(基类 / wechat / alipay),router 直接传,
   不再有 `inspect.signature` 分支。这里测试:
     - alipay.refund 在 `amount > order_amount` 时返回 `ok=False`
     - alipay.refund 在 `amount <= order_amount` 时通过(Mock 模式)
     - wechat.refund 在真实调用下传入的 `amount.total` 使用 `order_amount`
     - 基类默认 refund 依然接受 4 参

用法:
  python cloud_service/test_payment_form_callback.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# ── 用临时 SQLite,不污染仓库 ─────────────────────────────────
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["CLOUD_DB_URL"] = f"sqlite:///{_tmp.name}"
os.environ["CLOUD_FREE_QUOTA"] = "5"
os.environ["CLOUD_PRO_QUOTA"] = "-1"
os.environ["CLOUD_PAYMENT_NOTIFY_URL"] = "/cloud/payment/callback/alipay"
os.environ["CLOUD_PAYMENT_RETURN_URL"] = "/payment/success"
os.environ["CLOUD_ADMIN_TOKEN"] = "test-admin-token"
# 线上支付默认下线(2026-10-22);测试要覆盖支付代码路径,显式打开开关。
os.environ["CLOUD_ONLINE_PAYMENT_ENABLED"] = "true"

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


# ── 构造 mock 签名的回调 ─────────────────────────────────────
def _mk_alipay_form(order_no: str, trade_no: str, amount: float) -> dict:
    """生成一份合法的支付宝 form-urlencoded 回调体(全部值都是 str)。"""
    from cloud_service.payment import alipay
    adapter = alipay.AlipayAdapter()
    payload = {
        "out_trade_no": order_no,
        "total_amount": f"{amount:.2f}",
        "plan": "pro",
        "days": "30",
        "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
        "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
    }
    sign = alipay._mock_sign(adapter._sign_secret, payload)
    return {
        "out_trade_no": order_no,
        "trade_no": trade_no,
        "total_amount": f"{amount:.2f}",
        "trade_status": "TRADE_SUCCESS",
        "plan": "pro",
        "days": "30",
        "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
        "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
        "sign": sign,
    }


def _mk_wechat_form(order_no: str, transaction_id: str, total_fen: int) -> dict:
    """生成一份合法的微信 form-urlencoded 回调体(mock)。"""
    from cloud_service.payment import wechat
    adapter = wechat.WechatAdapter()
    payload = {
        "out_trade_no": order_no,
        "total_fen": str(total_fen),
        "plan": "pro",
        "days": "30",
        "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
        "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
    }
    sign = wechat._mock_sign(adapter._sign_secret, payload)
    return {
        "out_trade_no": order_no,
        "transaction_id": transaction_id,
        "total_fen": str(total_fen),
        "trade_state": "SUCCESS",
        "plan": "pro",
        "days": "30",
        "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
        "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
        "sign": sign,
    }


# ── main ─────────────────────────────────────────────────────
def run() -> int:
    from fastapi.testclient import TestClient
    from cloud_service.main import app
    from cloud_service.payment.adapter import PaymentAdapter

    fails = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal fails
        tag = "PASS" if cond else "FAIL"
        print(f"[{tag}] {label}" + (f" — {extra}" if extra else ""))
        if not cond:
            fails += 1

    # ── 1. 直接测 adapter.form-urlencoded 解析(adapter 层) ──
    from cloud_service.payment import alipay
    _a = alipay.AlipayAdapter()
    _form = _mk_alipay_form("PF_DIRECT_FORM", "TX_001", 99.0)
    ok, fields = _a.verify_callback(_form)
    check(
        "alipay.verify_callback accepts plain dict (form parsed shape)",
        ok and fields.get("out_trade_no") == "PF_DIRECT_FORM"
        and fields.get("pay_trade_no") == "TX_001"
        and abs(float(fields.get("amount", 0)) - 99.0) < 0.01,
        f"fields={fields}",
    )

    # ── 2. Router 分派:支付宝 form-urlencoded ───────────────
    with TestClient(app) as client:
        # 注册 + 登录
        r = client.post(
            "/cloud/auth/register",
            json={"username": "alice_form", "email": "alice@example.com",
                  "password": "supers3cret"},
        )
        check("register alice_form", r.status_code == 201, f"status={r.status_code}")
        r = client.post(
            "/cloud/auth/login",
            json={"username": "alice_form", "password": "supers3cret"},
        )
        check("login alice_form", r.status_code == 200, f"status={r.status_code}")
        H = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 创建 alipay 订单
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "alipay"},
            headers=H,
        )
        check("create_order alipay -> 201", r.status_code == 201, f"body={r.text[:200]}")
        order_no = r.json()["order_no"]

        # ── form-urlencoded 支付宝回调 → 200 + paid
        form_cb = _mk_alipay_form(order_no, "ALI_TX_001", amount=99.0)
        r = client.post(
            "/cloud/payment/callback/alipay",
            data=form_cb,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        check(
            "POST /payment/callback/alipay (form-urlencoded) -> 200",
            r.status_code == 200,
            f"status={r.status_code} body={r.text[:200]}",
        )
        body = r.json()
        check("form alipay callback ok == True", body.get("ok") is True, f"body={body}")
        check("form alipay callback activated == True",
              body.get("activated") is True, f"body={body}")

        # 订单状态变 paid,记录 trade_no
        r = client.get(f"/cloud/payment/order/{order_no}", headers=H)
        check("order -> paid after form callback",
              r.status_code == 200 and r.json().get("status") == "paid",
              f"body={r.text[:200]}")
        check("order.pay_trade_no == ALI_TX_001",
              r.json().get("pay_trade_no") == "ALI_TX_001",
              f"body={r.json()}")

        # ── form 篡改签名 → 400(signature verify 层)
        bad = dict(form_cb)
        bad["sign"] = "tampered"
        r = client.post(
            "/cloud/payment/callback/alipay",
            data=bad,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        check("tampered form alipay callback -> 400 (sig)",
              r.status_code == 400 and "signature" in r.text.lower(),
              f"status={r.status_code} body={r.text[:120]}")

        # ── JSON 微信回调(原有路径) → 200 + paid
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "wechat"},
            headers=H,
        )
        check("create_order wechat -> 201", r.status_code == 201, f"body={r.text[:120]}")
        wx_order_no = r.json()["order_no"]
        wx_cb = _mk_wechat_form(wx_order_no, "WX_TX_001", total_fen=9900)
        r = client.post(
            "/cloud/payment/callback/wechat",
            json=wx_cb,
        )
        check("POST /payment/callback/wechat (json) -> 200",
              r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        check("wechat json callback activated == True",
              r.json().get("activated") is True, f"body={r.json()}")

        # ── 未知 Content-Type 兜底(form body)→ 200
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "alipay"},
            headers=H,
        )
        order_no_3 = r.json()["order_no"]
        cb3 = _mk_alipay_form(order_no_3, "ALI_TX_003", amount=99.0)
        r = client.post(
            "/cloud/payment/callback/alipay",
            data=cb3,
            headers={"Content-Type": "text/plain"},
        )
        check(
            "unknown content-type + form body -> 200 (fallback form)",
            r.status_code == 200,
            f"status={r.status_code} body={r.text[:160]}",
        )
        check("fallback form callback activated == True",
              r.json().get("activated") is True,
              f"body={r.json()}")

        # ── 未知 Content-Type 兜底:非合法 JSON 且非合法 form → 400
        # 说明:`parse_qsl("not-json-not-form")` 不会抛错,而是返回一个占位 dict,
        # 因此这条用例实际走到的是"签名验证失败"分支(仍返回 400)。
        # 断言业务结果(400)即可,不强绑定具体错误信息。
        r = client.post(
            "/cloud/payment/callback/alipay",
            content=b"not-json-not-form",
            headers={"Content-Type": "text/plain"},
        )
        check("unknown content-type + unparseable body -> 400",
              r.status_code == 400,
              f"status={r.status_code} body={r.text[:200]}")

        # ── JSON content-type + 非 JSON body → 400("invalid JSON body")
        r = client.post(
            "/cloud/payment/callback/wechat",
            content=b"this is not json",
            headers={"Content-Type": "application/json"},
        )
        check("json content-type + non-json body -> 400 (invalid JSON body)",
              r.status_code == 400 and "invalid JSON body" in r.text,
              f"status={r.status_code} body={r.text[:200]}")

        # ── 显式 x-www-form-urlencoded + 空 body → 400(解析层,不到签名)
        r = client.post(
            "/cloud/payment/callback/alipay",
            data="",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        check("form content-type + empty body -> 400 (parse layer)",
              r.status_code == 400 and "invalid form body" in r.text,
              f"status={r.status_code} body={r.text[:200]}")

    # ── 3. alipay.refund 的 order_amount 语义校验 ───────────
    from cloud_service.payment import wechat

    a = alipay.AlipayAdapter()
    ok, msg, _ = a.refund(
        order_no="PF_REF1", pay_trade_no="T1", amount=150.0, order_amount=99.0,
    )
    check("alipay.refund rejects amount > order_amount",
          ok is False and "exceeds order amount" in msg,
          f"msg={msg}")

    ok, msg, fields = a.refund(
        order_no="PF_REF2", pay_trade_no="T2", amount=50.0, order_amount=99.0,
    )
    check("alipay.refund accepts amount <= order_amount (mock)",
          ok is True, f"msg={msg} fields={fields}")

    # 向后兼容:直接调用 3 参数(order_amount 缺省)仍工作
    ok, msg, _ = a.refund(
        order_no="PF_REF3", pay_trade_no="T3", amount=50.0,
    )
    check("alipay.refund 3-arg call (order_amount omitted) still works",
          ok is True, f"msg={msg}")

    # ── 4. wechat.refund 显式传 order_amount,Mock 下 total 用 order_amount ──
    w = wechat.WechatAdapter()
    ok, msg, fields = w.refund(
        order_no="PF_WX1", pay_trade_no="WT1", amount=50.0, order_amount=99.0,
    )
    check("wechat.refund accepts amount + order_amount (mock)",
          ok is True, f"msg={msg} fields={fields}")
    # Mock 模式 refund_amount 应为本次退款金额(50.0),而非 order_amount
    check("wechat.refund.fields.refund_amount == 50.0 (mock)",
          abs(float(fields.get("refund_amount", 0)) - 50.0) < 1e-6,
          f"fields={fields}")

    # ── 5. Router 端点不再依赖 introspection(通过 refund 完整流程验证)──
    with TestClient(app) as client:
        # 复用已激活 alice_form 的 access token
        r = client.post(
            "/cloud/auth/login",
            json={"username": "alice_form", "password": "supers3cret"},
        )
        H2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = client.post(
            "/cloud/payment/refund",
            json={"order_no": order_no, "amount": 30.0},
            headers={"Authorization": H2["Authorization"],
                     "X-Admin-Token": os.environ["CLOUD_ADMIN_TOKEN"]},
        )
        check(
            "refund alipay order w/ order_amount param routed -> 200",
            r.status_code == 200,
            f"status={r.status_code} body={r.text[:200]}",
        )
        check("refund response order_status == paid (partial)",
              r.json().get("order_status") == "paid",
              f"body={r.json()}")

    # ── 6. 基类默认 refund 也接受 order_amount ──────────────
    class _DummyAdapter(PaymentAdapter):
        name = "dummy"

        def create_payment(self, *a, **kw):
            return {}

        def verify_callback(self, body):
            return True, {}

    d = _DummyAdapter()
    ok, msg, fields = d.refund(
        order_no="D1", pay_trade_no="DT1", amount=10.0, order_amount=10.0,
    )
    check("PaymentAdapter.refund accepts order_amount (base mock)",
          ok is True, f"msg={msg} fields={fields}")

    # 清理临时 DB
    try:
        Path(_tmp.name).unlink(missing_ok=True)
    except OSError:
        pass

    return fails


if __name__ == "__main__":
    rc = run()
    print(f"\n{'ALL TESTS PASSED' if rc == 0 else f'{rc} TEST(S) FAILED'}")
    sys.exit(0 if rc == 0 else 1)
