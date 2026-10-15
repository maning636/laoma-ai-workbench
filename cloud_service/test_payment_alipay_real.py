"""C19 遗留补齐 · 支付宝 OpenAPI 真实对接单元测试。

覆盖:
  1. 签名构造: `_build_sign_str` 参数排序与排除规则(剔除 `sign` /
     `sign_type`、空值不参与)；RSA2(SHA256withRSA)签名可被对应公钥验证。
  2. 回调验签:合法回调通过 / 篡改金额或签名 → 拒绝 / trade_status 非成功态 →
     不置 paid / form-urlencoded 原始字符串输入也能验签。
  3. 下单:金额按"元"格式化为两位小数字符串(`total_amount=99.00`)、
     `out_trade_no` / `notify_url` / `return_url` 传递正确、form 里签名正确。
  4. 查单:`alipay.trade.query` 请求/响应。
  5. 退款:部分退款 `refund_amount` 与 `out_request_no`(幂等)传递正确、
     `fund_change=false` → 拒绝。
  6. 账单:mock transport 校验 downloadurl 请求,下载 CSV 后表头定位列解析。
  7. 降级:缺 APPID/密钥 → 自动降级 mock,行为与旧版一致。

严格本地:所有 HTTP 走 httpx.MockTransport,零联网。

用法(仓库根):
  python cloud_service/test_payment_alipay_real.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

# ── 隔离:临时 SQLite + 显式 admin token ────────────────────────
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["CLOUD_DB_URL"] = f"sqlite:///{_tmp.name}"
os.environ["CLOUD_PAYMENT_NOTIFY_URL"] = "https://example.com/cloud/payment/callback/alipay"
os.environ["CLOUD_PAYMENT_RETURN_URL"] = "/payment/success"

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# 清空可能的真实凭据,确保默认走 mock 降级(除非用例显式注入)
for _k in list(os.environ):
    if _k.startswith("CLOUD_ALIPAY_"):
        del os.environ[_k]


# ──────────────────────────────────────────────────────────────
# 密钥工具(测试内一次性生成内存 RSA + 写临时 PEM)
# ──────────────────────────────────────────────────────────────

def _gen_rsa_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def _write_pem(data: bytes, prefix: str = "ali_") -> str:
    fd, path = tempfile.mkstemp(suffix=".pem", prefix=prefix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ──────────────────────────────────────────────────────────────
# 测试入口
# ──────────────────────────────────────────────────────────────

def run() -> int:
    import httpx
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cloud_service.payment.alipay import (
        AlipayAdapter,
        _build_sign_str,
        _rsa2_sign,
        _rsa2_verify,
    )

    fails = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal fails
        tag = "PASS" if cond else "FAIL"
        print(f"[{tag}] {label}" + (f" — {extra}" if extra else ""))
        if not cond:
            fails += 1

    priv_pem, pub_pem = _gen_rsa_keys()
    priv_path = _write_pem(priv_pem, prefix="alipriv_")
    pub_path = _write_pem(pub_pem, prefix="alipub_")

    # ══════════════════════════════════════════════════════════
    # 用例 0: 待签串构造 & RSA2 签名/验签原语
    # ══════════════════════════════════════════════════════════
    params = {
        "app_id": "2021000000000001",
        "method": "alipay.trade.page.pay",
        "sign_type": "RSA2",       # 应被剔除
        "format": "json",
        "charset": "utf-8",
        "sign": "SHOULD_BE_EXCLUDED",  # 应被剔除
        "out_trade_no": "PF_XYZ_001",
        "total_amount": "99.00",
        "empty": "",              # 应被剔除
        "none_val": None,         # 应被剔除
        "subject": "Prism-Fusion pro 30d",
    }
    sign_str = _build_sign_str(params)
    expected = (
        "app_id=2021000000000001&charset=utf-8&format=json"
        "&method=alipay.trade.page.pay&out_trade_no=PF_XYZ_001"
        "&subject=Prism-Fusion pro 30d&total_amount=99.00"
    )
    check("sign_str excludes sign/sign_type/empty/none", sign_str == expected,
          f"got={sign_str!r}")
    check("sign_str is key-ascending", sign_str.index("app_id=") < sign_str.index("charset=")
          < sign_str.index("method="),
          f"got={sign_str!r}")

    # RSA2 签名 → 用公钥验证
    sig = _rsa2_sign(sign_str, priv_pem)
    check("rsa2 sign produces non-empty base64", bool(sig), f"len={len(sig)}")
    check("rsa2 sign is base64 encodable",
          base64.b64encode(base64.b64decode(sig)) == sig.encode("ascii"))
    check("rsa2 verify(own signature) ok",
          _rsa2_verify(sig, sign_str, pub_pem) is True)
    check("rsa2 verify(tampered sign_str) reject",
          _rsa2_verify(sig, sign_str + "x", pub_pem) is False)
    tampered_sig = _b64(bytes([b ^ 0xFF for b in base64.b64decode(sig)]))
    check("rsa2 verify(tampered signature) reject",
          _rsa2_verify(tampered_sig, sign_str, pub_pem) is False)
    other_priv, other_pub = _gen_rsa_keys()
    sig_other = _rsa2_sign(sign_str, other_priv)
    check("rsa2 verify(wrong key) reject",
          _rsa2_verify(sig_other, sign_str, pub_pem) is False)

    # ══════════════════════════════════════════════════════════
    # 用例 1: 真实模式下单(create_payment)
    # ══════════════════════════════════════════════════════════
    captured: dict[str, Any] = {}

    def page_handler(request: httpx.Request) -> httpx.Response:
        # 电脑网站支付是商户自己渲染 form,不会真的调 gateway
        # (但 create_payment 内部不会调 HTTP,所以这个 handler 只作兜底)
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={})

    adp = AlipayAdapter(
        app_id="2021000000000001",
        app_private_key_path=priv_path,
        alipay_public_key_path=pub_path,
        sandbox=False,
        client=httpx.Client(transport=httpx.MockTransport(page_handler)),
    )
    check("real mode detected", adp.is_real is True, f"is_real={adp.is_real}")

    pp = adp.create_payment(
        order_no="PF_XYZ_001",
        amount=99.00,
        plan="pro",
        days=30,
        notify_url="https://example.com/cloud/payment/callback/alipay",
        return_url="/payment/success",
    )
    check("create returns channel=alipay", pp.get("channel") == "alipay")
    check("create returns pay_type=form", pp.get("pay_type") == "form")
    check("create returns amount=99.0 (float)", pp.get("amount") == 99.0,
          f"amount={pp.get('amount')!r}")
    check("create returns sandbox=False", pp.get("sandbox") is False,
          f"sandbox={pp.get('sandbox')!r}")
    check("create returns gateway_url (prod, sandbox=False)",
          pp.get("gateway_url", "").startswith("https://openapi.alipay.com"),
          f"gw={pp.get('gateway_url')}")

    form = pp.get("form_html", "")
    check("create form_html non-empty", bool(form))
    check("create form contains method=alipay.trade.page.pay",
          'name="method" value="alipay.trade.page.pay"' in form,
          f"form={form[:200]}")
    check("create form total_amount=99.00 (元, 2dp string)",
          'name="total_amount" value="99.00"' in form,
          f"form={form[:400]}")
    check("create form out_trade_no",
          'name="out_trade_no" value="PF_XYZ_001"' in form)
    check("create form notify_url",
          'name="notify_url" value="https://example.com/cloud/payment/callback/alipay"'
          in form)
    check("create form return_url",
          'name="return_url" value="/payment/success"' in form)
    check("create form app_id",
          'name="app_id" value="2021000000000001"' in form)
    check("create form sign_type=RSA2",
          'name="sign_type" value="RSA2"' in form)
    check("create form contains sign",
          'name="sign" value="' in form)

    # 从 form 中反解析全部参数,验证签名可以被对应公钥验证
    def _extract_form_inputs(html: str) -> dict[str, str]:
        import re
        out: dict[str, str] = {}
        for m in re.finditer(
            r'<input\s+type="hidden"\s+name="([^"]+)"\s+value="([^"]*)"', html
        ):
            out[m.group(1)] = m.group(2)
        return out

    form_params = _extract_form_inputs(form)
    check("form parses all key params",
          all(k in form_params for k in (
              "app_id", "method", "format", "charset", "sign_type",
              "timestamp", "version", "out_trade_no", "total_amount",
              "subject", "notify_url", "return_url", "sign",
          )),
          f"keys={list(form_params.keys())}")
    check("form does not include sign_type in sign_str computation",
          "sign_type=" not in _build_sign_str(form_params))
    check("form sign verifiable by alipay public key",
          _rsa2_verify(
              form_params["sign"],
              _build_sign_str(form_params),
              pub_pem,
          ) is True,
          f"sign={form_params.get('sign','')[:40]}...")

    # ══════════════════════════════════════════════════════════
    # 用例 2: 真实回调验签(_verify_callback_real)
    # ══════════════════════════════════════════════════════════
    # 在真实支付宝体系中,下单签名用「应用私钥」,回调签名用「支付宝私钥」;
    # 我们用一个独立的 test_alipay 密钥对来模拟支付宝平台,并让 adapter 走
    # 真实模式(通过 _force_real=True + 内联密钥)来验证验签路径。
    ta_priv, ta_pub = _gen_rsa_keys()
    ta_priv_path = _write_pem(ta_priv, prefix="alia_")
    ta_pub_b64 = pub_pem.decode("utf-8")  # 复用 pub_pem 作支付宝公钥的字符串形式

    adp_cb = AlipayAdapter(
        app_id="2021000000000001",
        app_private_key=priv_pem.decode("utf-8"),
        alipay_public_key=ta_pub.decode("utf-8"),
        sandbox=False,
        client=httpx.Client(transport=httpx.MockTransport(page_handler)),
        _force_real=True,
    )
    check("callback adapter is_real", adp_cb.is_real is True)

    def _mk_alipay_callback(
        *,
        tamper_sign: bool = False,
        tamper_amount: bool = False,
        trade_status: str = "TRADE_SUCCESS",
    ) -> dict[str, str]:
        """构造一份合法的支付宝回调 body(form-urlencoded 解析后)。

        `tamper_amount=True` 时:先按 `99.00` 签名,再把 body 中的 total_amount
        改成 `0.01`,以模拟"回调金额被中间人篡改"的场景 —— 此时验签失败。
        """
        body: dict[str, str] = {
            "app_id": "2021000000000001",
            "notify_time": "2026-10-16 12:00:00",
            "notify_type": "trade_status_sync",
            "notify_id": "CB_001",
            "sign_type": "RSA2",
            "out_trade_no": "PF_XYZ_001",
            "trade_no": "202609222200141234567890",
            "total_amount": "99.00",
            "trade_status": trade_status,
            "buyer_open_id": "2088xxxxxxxxxxxx",
            "receipt_amount": "99.00",
            "buyer_pay_amount": "99.00",
            "invoice_amount": "99.00",
            "point_amount": "0.00",
            "subject": "Prism-Fusion pro 30d",
            "body": "",           # 空值应被排除
        }
        sign_str = _build_sign_str(body)
        sig = _rsa2_sign(sign_str, ta_priv)  # 用「支付宝私钥」按 99.00 签名
        if tamper_sign:
            sig = _b64(bytes([b ^ 0xFF for b in base64.b64decode(sig)]))
        body["sign"] = sig
        if tamper_amount:
            # 篡改金额后签名不再匹配
            body["total_amount"] = "0.01"
        return body

    # 2a: 正常回调 → 通过
    cb = _mk_alipay_callback()
    ok, fields = adp_cb.verify_callback(cb)
    check("callback.real normal -> ok", ok is True, f"fields={fields}")
    check("callback.real normal out_trade_no",
          fields.get("out_trade_no") == "PF_XYZ_001", f"fields={fields}")
    check("callback.real normal pay_trade_no",
          fields.get("pay_trade_no") == "202609222200141234567890",
          f"fields={fields}")
    check("callback.real normal amount=99.0",
          fields.get("amount") == 99.0, f"fields={fields}")

    # 2b: 篡改签名 → 拒绝
    cb_bad_sig = _mk_alipay_callback(tamper_sign=True)
    ok, _ = adp_cb.verify_callback(cb_bad_sig)
    check("callback.real tampered sign -> reject", ok is False)

    # 2c: 篡改金额(body 中改 total_amount,但 sign 是原金额的) → 拒绝
    cb_bad_amt = _mk_alipay_callback(tamper_amount=True)
    ok, _ = adp_cb.verify_callback(cb_bad_amt)
    check("callback.real tampered amount -> reject", ok is False)

    # 2d: trade_status 非成功态 → 不置 paid
    for status in ("WAIT_BUYER_PAY", "TRADE_CLOSED", "TRADE_REFUND"):
        cb_status = _mk_alipay_callback(trade_status=status)
        ok, _ = adp_cb.verify_callback(cb_status)
        check(f"callback.real trade_status={status} -> reject", ok is False)

    # 2e: TRADE_FINISHED 也接受
    cb_finished = _mk_alipay_callback(trade_status="TRADE_FINISHED")
    ok, fields = adp_cb.verify_callback(cb_finished)
    check("callback.real TRADE_FINISHED accepted", ok is True, f"fields={fields}")

    # 2f: 用原始 form-urlencoded 字符串输入也验签
    raw_body = urllib.parse.urlencode(cb)
    ok, fields = adp_cb.verify_callback(raw_body)
    check("callback.real accepts raw form-urlencoded string", ok is True,
          f"fields={fields}")

    # 2g: 缺 out_trade_no / trade_no / sign → 拒绝
    cb_missing = dict(cb)
    cb_missing.pop("sign")
    ok, _ = adp_cb.verify_callback(cb_missing)
    check("callback.real missing sign -> reject", ok is False)

    # 2h: 使用错误的支付宝公钥(应用公钥)来验支付宝的签名 → 拒绝
    adp_wrong_pub = AlipayAdapter(
        app_id="2021000000000001",
        app_private_key=priv_pem.decode("utf-8"),
        alipay_public_key=pub_pem.decode("utf-8"),  # 不是支付宝的公钥
        sandbox=False,
        _force_real=True,
    )
    ok, _ = adp_wrong_pub.verify_callback(_mk_alipay_callback())
    check("callback.real wrong alipay public key -> reject", ok is False)

    # ══════════════════════════════════════════════════════════
    # 用例 3: 查单(alipay.trade.query)
    # ══════════════════════════════════════════════════════════
    query_captured: dict[str, Any] = {}

    def query_handler(request: httpx.Request) -> httpx.Response:
        query_captured["path"] = str(request.url)
        query_captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={
            "alipay.trade.query_response": {
                "code": "10000",
                "msg": "Success",
                "out_trade_no": "PF_XYZ_001",
                "trade_no": "202609222200141234567890",
                "total_amount": "99.00",
                "trade_status": "TRADE_SUCCESS",
                "buyer_pay_amount": "99.00",
            }
        })

    adp_q = AlipayAdapter(
        app_id="2021000000000001",
        app_private_key_path=priv_path,
        alipay_public_key_path=pub_path,
        sandbox=False,
        client=httpx.Client(
            transport=httpx.MockTransport(query_handler),
        ),
    )
    ok, fields = adp_q.query_order("PF_XYZ_001")
    check("query.real accepted", ok is True, f"fields={fields}")
    check("query.real returns out_trade_no",
          fields.get("out_trade_no") == "PF_XYZ_001", f"fields={fields}")
    check("query.real returns amount=99.00 (string, 元)",
          fields.get("total_amount") == "99.00", f"fields={fields}")
    body_qs = dict(urllib.parse.parse_qsl(query_captured["body"]))
    check("query body method=alipay.trade.query",
          body_qs.get("method") == "alipay.trade.query",
          f"body={query_captured['body'][:200]}")
    check("query body out_trade_no passed",
          body_qs.get("out_trade_no") == "PF_XYZ_001")
    check("query body has sign field",
          "sign=" in query_captured["body"])
    # 验证查询签名也可被公钥验证
    check("query sign verifiable by alipay public key",
          _rsa2_verify(body_qs["sign"], _build_sign_str(body_qs), pub_pem) is True)

    # 查单失败 → 返回 (False, {...})
    def query_fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "alipay.trade.query_response": {
                "code": "40006",
                "msg": "ORDER_NOT_EXISTS",
            }
        })

    adp_q_fail = AlipayAdapter(
        app_id="2021000000000001",
        app_private_key_path=priv_path,
        alipay_public_key_path=pub_path,
        sandbox=False,
        client=httpx.Client(transport=httpx.MockTransport(query_fail_handler)),
    )
    ok, fields = adp_q_fail.query_order("PF_GHOST")
    check("query.real failure returns ok=False", ok is False, f"fields={fields}")
    check("query.real failure includes code",
          "40006" in str(fields), f"fields={fields}")

    # ══════════════════════════════════════════════════════════
    # 用例 4: 退款(alipay.trade.refund)——部分退款 + 幂等
    # ══════════════════════════════════════════════════════════
    refund_captured: list[dict[str, Any]] = []

    def refund_handler(request: httpx.Request) -> httpx.Response:
        body_qs = dict(urllib.parse.parse_qsl(request.content.decode("utf-8")))
        refund_captured.append(body_qs)
        return httpx.Response(200, json={
            "alipay.trade.refund_response": {
                "code": "10000",
                "msg": "Success",
                "trade_no": "202609222200141234567890",
                "out_trade_no": "PF_REF",
                "refund_fee": "9.90",
                "fund_change": "true",
                "gmt_refund_pay": "2026-10-16 13:00:00",
            }
        })

    adp_refund = AlipayAdapter(
        app_id="2021000000000001",
        app_private_key_path=priv_path,
        alipay_public_key_path=pub_path,
        sandbox=False,
        client=httpx.Client(transport=httpx.MockTransport(refund_handler)),
    )
    ok, msg, fields = adp_refund.refund(
        order_no="PF_REF", pay_trade_no="202609222200141234567890",
        amount=9.90, reason="user-cancel",
    )
    check("refund.real accepted", ok is True, f"msg={msg} fields={fields}")
    check("refund.real returns refund_trade_no",
          fields.get("refund_trade_no") == "202609222200141234567890",
          f"fields={fields}")
    check("refund.real returns refund_amount=9.9",
          fields.get("refund_amount") == 9.90, f"fields={fields}")
    body = refund_captured[0]
    check("refund body method=alipay.trade.refund",
          body.get("method") == "alipay.trade.refund",
          f"body={body}")
    check("refund body out_trade_no",
          body.get("out_trade_no") == "PF_REF")
    check("refund body refund_amount=9.90 (元, 2dp string)",
          body.get("refund_amount") == "9.90", f"body={body}")
    check("refund body has out_request_no",
          body.get("out_request_no", "").startswith("RF_"),
          f"out_request_no={body.get('out_request_no')!r}")
    check("refund body refund_reason",
          body.get("refund_reason") == "user-cancel")
    check("refund body sign verifiable",
          _rsa2_verify(body["sign"], _build_sign_str(body), pub_pem) is True)

    # 幂等:同样的 (order_no, amount) 再次退款 → out_request_no 相同
    refund_captured.clear()
    ok, _, _ = adp_refund.refund(
        order_no="PF_REF", pay_trade_no="202609222200141234567890",
        amount=9.90, reason="retry",
    )
    body2 = refund_captured[0]
    check("refund idempotent: same out_request_no on retry",
          body["out_request_no"] == body2["out_request_no"],
          f"1={body['out_request_no']} 2={body2['out_request_no']}")

    # 金额<=0 → 拒绝(不发请求)
    refund_never: list[dict[str, str]] = []

    def refund_never_handler(request: httpx.Request) -> httpx.Response:
        refund_never.append(request.content.decode("utf-8"))
        return httpx.Response(200, json={})

    adp_refund_zero = AlipayAdapter(
        app_id="2021000000000001",
        app_private_key_path=priv_path,
        alipay_public_key_path=pub_path,
        sandbox=False,
        client=httpx.Client(transport=httpx.MockTransport(refund_never_handler)),
    )
    ok, msg, _ = adp_refund_zero.refund(
        order_no="X", pay_trade_no="T", amount=0.0,
    )
    check("refund amount<=0 rejected without request",
          ok is False and "refund amount must be > 0" in msg and not refund_never,
          f"msg={msg} n={len(refund_never)}")

    # fund_change=false → 拒绝
    def refund_no_fund_change(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "alipay.trade.refund_response": {
                "code": "10000", "msg": "Success",
                "trade_no": "T", "out_trade_no": "PF_REF",
                "refund_fee": "9.90", "fund_change": "false",
            }
        })

    adp_refund_nc = AlipayAdapter(
        app_id="2021000000000001",
        app_private_key_path=priv_path,
        alipay_public_key_path=pub_path,
        sandbox=False,
        client=httpx.Client(transport=httpx.MockTransport(refund_no_fund_change)),
    )
    ok, msg, _ = adp_refund_nc.refund(
        order_no="PF_REF", pay_trade_no="T", amount=9.90,
    )
    check("refund fund_change=false rejected", ok is False and "fund_change" in msg,
          f"msg={msg}")

    # 自定义 out_request_no 透传
    refund_captured.clear()
    ok, _, fields = adp_refund.refund(
        order_no="PF_REF2", pay_trade_no="T2", amount=5.00, out_request_no="CUSTOM_RF",
    )
    body3 = refund_captured[0]
    check("refund custom out_request_no honored",
          body3.get("out_request_no") == "CUSTOM_RF",
          f"body={body3}")

    # ══════════════════════════════════════════════════════════
    # 用例 5: fetch_bill 真实模式(downloadurl + CSV 解析)
    # ══════════════════════════════════════════════════════════
    bill_csv = (
        "# 支付宝交易账单\n"
        "备注:2026-10-15\n"
        "交易创建时间,交易完成时间,交易类型,商户订单号,支付宝交易号,买家实付金额,卖家实收金额,支付宝手续费,退款金额,交易状态,业务渠道,支付宝交易号,业务描述\n"
        "2026-10-15 09:00:00,2026-10-15 09:01:00,交易,PF_B1,202609222200141234567890,99.00,99.00,0.00,,交易成功,APP,202609222200141234567890,Prism-Fusion pro\n"
        "2026-10-15 11:00:00,2026-10-15 11:02:00,退款,PF_B2,202609222200141234567890,-1.00,-1.00,0.00,1.00,退款成功,APP,202609222200141234567890,退款\n"
    )
    bill_bytes = bill_csv.encode("utf-8")
    bill_url = "https://api.alipay.com/bill/20261015.csv?signed=x"

    def bill_gateway_handler(request: httpx.Request) -> httpx.Response:
        if "alipay.data.dataservice.bill.downloadurl.query" in request.content.decode("utf-8"):
            return httpx.Response(200, json={
                "alipay.data.dataservice.bill.downloadurl.query_response": {
                    "code": "10000", "msg": "Success",
                    "bill_date": "2026-10-15",
                    "bill_type": "trade",
                    "download_url": bill_url,
                }
            })
        return httpx.Response(404)

    adp_bill = AlipayAdapter(
        app_id="2021000000000001",
        app_private_key_path=priv_path,
        alipay_public_key_path=pub_path,
        sandbox=False,
        client=httpx.Client(transport=httpx.MockTransport(bill_gateway_handler)),
    )
    # fetch_bill 内部对下载 URL 直接 httpx.get;此处 monkeypatch
    import cloud_service.payment.alipay as _am
    _orig_get = _am.httpx.get
    _am.httpx.get = lambda url, **kw: httpx.Response(200, content=bill_bytes)  # type: ignore[assignment]
    try:
        rows = adp_bill.fetch_bill(start_date="2026-10-15", end_date="2026-10-15")
    finally:
        _am.httpx.get = _orig_get  # type: ignore[assignment]

    check("fetch_bill returns rows", len(rows) >= 2, f"n={len(rows)}")
    check("fetch_bill row has out_trade_no=PF_B1",
          any(r["out_trade_no"] == "PF_B1" for r in rows),
          f"rows={rows}")
    check("fetch_bill row has pay_trade_no",
          any(r["pay_trade_no"] == "202609222200141234567890" for r in rows))
    check("fetch_bill row amount correct (99.0)",
          any(abs(r["amount"] - 99.0) < 1e-6 for r in rows),
          f"rows={rows}")
    check("fetch_bill has trade_type payment",
          any(r["trade_type"] == "payment" for r in rows))
    check("fetch_bill has trade_type refund",
          any(r["trade_type"] == "refund" for r in rows))
    check("fetch_bill channel=alipay",
          all(r.get("channel") == "alipay" for r in rows))

    # 下载失败 → 返回空
    _am.httpx.get = lambda url, **kw: httpx.Response(500, content=b"")  # type: ignore[assignment]
    try:
        rows_bad = adp_bill.fetch_bill(start_date="2026-10-15", end_date="2026-10-15")
    finally:
        _am.httpx.get = _orig_get  # type: ignore[assignment]
    check("fetch_bill download failure -> empty", rows_bad == [],
          f"got={rows_bad}")

    # ══════════════════════════════════════════════════════════
    # 用例 6: 降级(mock 行为与旧版一致)
    # ══════════════════════════════════════════════════════════
    adp_mock = AlipayAdapter()  # 全部 env 默认(已清)
    check("mock detected when not configured",
          adp_mock.is_real is False, f"is_real={adp_mock.is_real}")
    check("mock app_id default",
          adp_mock.app_id == "MOCK_ALIPAY_APP_ID", f"id={adp_mock.app_id}")

    pp_mock = adp_mock.create_payment(
        order_no="PF_MOCK", amount=10.50, plan="pro", days=30,
        notify_url="https://n/cb", return_url="/ok",
    )
    check("mock create uses old form_html shape",
          'action="https://openapi-sandbox.dl.alipaydev.com/gateway.do"' in pp_mock["form_html"]
          and 'name="out_trade_no" value="PF_MOCK"' in pp_mock["form_html"]
          and 'name="total_amount" value="10.50"' in pp_mock["form_html"],
          f"form_html={pp_mock['form_html'][:200]}")

    # 老式 mock 回调:body 里带 HMAC mock 签名
    from cloud_service.payment.adapter import _mock_sign
    secret = adp_mock._sign_secret
    sign_payload = {
        "out_trade_no": "PF_MOCK",
        "total_amount": "10.50",
        "plan": "pro",
        "days": "30",
        "notify_url": "https://n/cb",
        "return_url": "/ok",
    }
    sign = _mock_sign(secret, sign_payload)
    cb = {
        "out_trade_no": "PF_MOCK",
        "trade_no": "MOCK_TX",
        "total_amount": "10.50",
        "trade_status": "TRADE_SUCCESS",
        "plan": "pro", "days": "30",
        "notify_url": "https://n/cb",
        "return_url": "/ok",
        "sign": sign,
    }
    ok, fields = adp_mock.verify_callback(cb)
    check("mock callback ok", ok is True, f"fields={fields}")
    check("mock callback out_trade_no",
          fields.get("out_trade_no") == "PF_MOCK")
    check("mock callback amount=10.5", fields.get("amount") == 10.5)

    # 篡改签名 → 拒绝
    cb_bad = dict(cb)
    cb_bad["sign"] = "tampered"
    ok, _ = adp_mock.verify_callback(cb_bad)
    check("mock callback bad sign -> reject", ok is False)

    # trade_status 非成功 → 拒绝
    cb_fail = dict(cb)
    cb_fail["trade_status"] = "WAIT_BUYER_PAY"
    ok, _ = adp_mock.verify_callback(cb_fail)
    check("mock callback WAIT_BUYER_PAY -> reject", ok is False)

    # refund mock 与基类一致
    ok, msg, fields = adp_mock.refund(
        order_no="PF_MOCK", pay_trade_no="MOCK_TX", amount=5.00,
    )
    check("mock refund still works", ok is True,
          f"msg={msg} fields={fields}")
    check("mock refund echoes refund_trade_no",
          str(fields.get("refund_trade_no", "")).startswith("REF_ALIPAY_"))

    # ══════════════════════════════════════════════════════════
    # 用例 7: _is_real_configured 边界
    # ══════════════════════════════════════════════════════════
    from cloud_service.payment.alipay import _is_real_configured
    base_env = {
        "app_id": "2021000000000001",
        "app_private_key_path": priv_path,
        "alipay_public_key_path": pub_path,
        "app_private_key_inline": "",
        "alipay_public_key_inline": "",
    }
    check("is_real_configured True when all set",
          _is_real_configured(base_env) is True)
    check("is_real_configured False when app_id=MOCK",
          _is_real_configured({**base_env, "app_id": "MOCK_ALIPAY_APP_ID"}) is False)
    check("is_real_configured False when app_id empty",
          _is_real_configured({**base_env, "app_id": ""}) is False)
    check("is_real_configured False when private key path missing",
          _is_real_configured({**base_env,
                               "app_private_key_path": "/tmp/not_exist.pem"}) is False)
    check("is_real_configured False when public key path missing",
          _is_real_configured({**base_env,
                               "alipay_public_key_path": "/tmp/not_exist.pem"}) is False)
    check("is_real_configured True with inline PEM",
          _is_real_configured({
              **base_env,
              "app_private_key_path": "",
              "alipay_public_key_path": "",
              "app_private_key_inline": priv_pem.decode("utf-8"),
              "alipay_public_key_inline": pub_pem.decode("utf-8"),
          }) is True)

    # 打印汇总
    print(f"\n{'ALL TESTS PASSED' if fails == 0 else f'{fails} TEST(S) FAILED'}")
    return fails


if __name__ == "__main__":
    rc = run()
    try:
        Path(_tmp.name).unlink(missing_ok=True)
    except OSError:
        pass
    print(f"\n{'ALL TESTS PASSED' if rc == 0 else f'{rc} TEST(S) FAILED'}")
    sys.exit(0 if rc == 0 else 1)
