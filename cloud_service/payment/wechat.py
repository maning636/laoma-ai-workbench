"""微信支付适配(APIv3 真实实现 + mock 降级)。

设计参考 `docs/dev-reports/2026-10-13-saas-c-class-design.md` §5.2:
  - Native(扫码)→ 返回 `code_url`,前端渲染为二维码图片。
  - 回调:Wechatpay-* 头验签 + `resource` AES-256-GCM 解密。
  - 查单 / 退款 / 交易账单下载:全部走 APIv3。

安全:
  - 商户参数 `CLOUD_WECHAT_*` 一律 env 注入;私钥 / APIv3 密钥**只存路径与密钥名**,
    绝不打印或写进仓库。
  - 未配置真实参数(见 `_is_real_configured`)时**自动降级 mock**,行为与旧版一致,
    既有测试(`test_payment.py` / `test_payment_leftover.py`)保持通过。

真实渠道对接(APIv3):
  1. `create_payment` → `POST /v3/pay/transactions/native` → 拿 `code_url`。
  2. `verify_callback` → 校验 `Wechatpay-Timestamp`/`Nonce`/`Signature` → 用
     **微信支付平台证书**做 SHA256withRSA 验签 → 用 APIv3 密钥做 AES-256-GCM
     解密 `resource.ciphertext` → 校验 `out_trade_no` / 金额 / `trade_state`。
  3. `query_order` → `GET /v3/pay/transactions/out-trade-no/{out_trade_no}?mchid=`。
  4. `refund` → `POST /v3/refund/domestic/refunds`。
  5. `fetch_bill` → `GET /v3/billdownload/tradebill` 拿 `download_url` 与
     平台响应头 SHA256/MD5,下载后**自行校验哈希**再逐行解析 CSV。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    load_pem_private_key,
    load_pem_public_key,
)

from .adapter import (
    PaymentAdapter,
    _get_str,
    _mock_sign,
    _verify_sig,
    register_adapter,
)

MOCK_SECRET = "__MOCK__WECHAT_SECRET__"
MOCK_APP_ID = "MOCK_WECHAT_APP_ID"
MOCK_MCHID = "MOCK_MCH_ID"

# APIv3 真实接口基址(生产 / 沙箱共用)
WECHAT_API_BASE = "https://api.mch.weixin.qq.com"
WECHAT_API_SANDBOX = "https://api.mch.weixin.qq.com"  # 目前沙箱未提供独立域名

_TIMEOUT_SEC = 15.0
_TS_SKEW_SEC = 300  # APIv3 时间戳允许 ±5 分钟


# ──────────────────────────────────────────────────────────────
# 通用工具:签名 / 验签 / AES-GCM 加解密
# ──────────────────────────────────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _rsa_sign(payload: bytes, private_pem: bytes) -> bytes:
    """SHA256withRSA 签名(即 PKCS1v15 + SHA256),返回原始签名字节。"""
    key = load_pem_private_key(private_pem, password=None)
    return key.sign(payload, padding.PKCS1v15(), hashes.SHA256())


def _rsa_verify(
    signature_b64: str,
    payload: bytes,
    public_pem: bytes,
) -> bool:
    """校验 SHA256withRSA 签名(常量时间比较,防时序攻击)。"""
    try:
        key = load_pem_public_key(public_pem)
        sig = _b64url_decode(signature_b64)
        key.verify(sig, payload, padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        return False
    return True


def aes_gcm_encrypt(
    key: bytes,
    nonce_b64: str,
    associated_data: str,
    plaintext: bytes,
) -> str:
    """AES-256-GCM 加密(与微信 APIv3 一致)。

    - `nonce_b64`: base64url(12B nonce)
    - `associated_data`: GCM 关联数据(通常是 request_id)
    - 返回 `base64(ciphertext || tag)` 字符串,直接放入 `resource.ciphertext`。
    """
    assert len(key) == 32, "APIv3 key must be 32 bytes"
    nonce = _b64url_decode(nonce_b64)
    if len(nonce) != 12:
        nonce = nonce[:12].ljust(12, b"\x00")
    ct = AESGCM(key).encrypt(
        nonce,
        plaintext,
        associated_data.encode("utf-8") if associated_data else None,
    )
    # AESGCM.encrypt 已经返回 ct||tag(最后 16 字节是 tag)
    return _b64url_encode(ct)


def aes_gcm_decrypt(
    key: bytes,
    nonce_b64: str,
    associated_data: str,
    ciphertext_b64: str,
) -> bytes:
    """AES-256-GCM 解密(与微信 APIv3 一致)。

    - `ciphertext_b64` = base64url(ct || tag) 原始密文字节,不含分隔符。
    - 任何异常返回 `b""`(上层视作失败,不抛)。
    """
    if len(key) != 32:
        return b""
    try:
        nonce = _b64url_decode(nonce_b64)
        if len(nonce) != 12:
            nonce = nonce[:12].ljust(12, b"\x00")
        raw = _b64url_decode(ciphertext_b64)
        if len(raw) < 16:
            return b""
        return AESGCM(key).decrypt(
            nonce,
            raw,
            associated_data.encode("utf-8") if associated_data else None,
        )
    except Exception:
        return b""


def _mock_sign_local(secret: str, payload: dict[str, Any]) -> str:
    """与 adapter._mock_sign 相同的 HMAC-SHA256 mock 签名(便于本模块自测)。"""
    return _mock_sign(secret, payload)


# ──────────────────────────────────────────────────────────────
# 主适配类
# ──────────────────────────────────────────────────────────────

class WechatAdapter(PaymentAdapter):
    """微信支付适配:APIv3 真实实现 + 未配置时自动降级 mock。"""

    name = "wechat"

    def __init__(
        self,
        *,
        app_id: str = "",
        mch_id: str = "",
        api_v3_key: str = "",
        mch_serial_no: str = "",
        mch_private_key_path: str = "",
        wechat_public_key_path: str = "",
        notify_url: str = "",
        sandbox: bool = False,
        client: httpx.Client | None = None,
        _force_real: bool | None = None,
    ) -> None:
        # env 优先从构造参数取,便于单测注入;缺省从 os.getenv
        self.app_id = app_id or _get_str("CLOUD_WECHAT_APP_ID") or MOCK_APP_ID
        self.mch_id = mch_id or _get_str("CLOUD_WECHAT_MCHID") or MOCK_MCHID
        # APIv3 密钥:必须是 32 字节字符串(即 32 位 ASCII/中文,不含 BOM)
        self.api_v3_key = api_v3_key or _get_str("CLOUD_WECHAT_API_V3_KEY")
        self.mch_serial_no = mch_serial_no or _get_str("CLOUD_WECHAT_MCH_SERIAL_NO")
        self.mch_private_key_path = (
            mch_private_key_path
            or _get_str("CLOUD_WECHAT_MCH_PRIVATE_KEY_PATH")
        )
        self.wechat_public_key_path = (
            wechat_public_key_path
            or _get_str("CLOUD_WECHAT_WECHAT_PUBLIC_KEY_PATH")
        )
        self.notify_url = notify_url or _get_str("CLOUD_WECHAT_NOTIFY_URL")
        self.sandbox = sandbox if sandbox else (
            _get_str("CLOUD_WECHAT_SANDBOX", "1").lower() in {"1", "true", "yes"}
        )
        # mock 阶段回调验签密钥(真实环境走 RSA,不再使用)
        self._sign_secret = (
            _get_str("CLOUD_WECHAT_API_V3_KEY")
            or _get_str("CLOUD_WECHAT_API_SECRET")
            or MOCK_SECRET
        )
        # HTTP 客户端(单测可注入 MockTransport)
        if client is not None:
            self._http = client
        else:
            try:
                self._http = httpx.Client(
                    base_url=WECHAT_API_BASE,
                    timeout=_TIMEOUT_SEC,
                )
            except Exception:  # pragma: no cover - 罕见,防止启动期炸
                self._http = None

        # 真实模式判定:env 或显式 _force_real 都算;否则降级 mock
        self.is_real = bool(_force_real) if _force_real is not None else _is_real_configured({
            "app_id": self.app_id,
            "mch_id": self.mch_id,
            "api_v3_key": self.api_v3_key,
            "mch_serial_no": self.mch_serial_no,
            "mch_private_key_path": self.mch_private_key_path,
            "wechat_public_key_path": self.wechat_public_key_path,
            "notify_url": self.notify_url,
        })

    # ─────────────────────────────────────────────────────────
    # 便捷工厂 / 关闭
    # ─────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, client: httpx.Client | None = None) -> "WechatAdapter":
        """从 env 重新构造一次(用于测试或热切换密钥)。"""
        return cls(client=client)

    def close(self) -> None:
        if self._http is not None:
            try:
                self._http.close()
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────
    # 内部:签名头构造
    # ─────────────────────────────────────────────────────────

    def _sign_headers(self, method: str, url_path: str, body: str) -> dict[str, str]:
        """构造 APIv3 Authorization 头:

        Authorization: WECHATPAY2-SHA256-RSA2048 mchid="<MCHID>",
                       nonce_str="<NONCE>",
                       timestamp="<TS>",
                       serial_no="<SERIAL_NO>",
                       signature="<BASE64URL(SHA256withRSA(...))>"

        message = "{method}\n{url_path}\n{timestamp}\n{nonce_str}\n{body}\n"
        """
        import time
        import uuid

        ts = str(int(time.time()))
        nonce = uuid.uuid4().hex
        message = f"{method.upper()}\n{url_path}\n{ts}\n{nonce}\n{body}\n"
        priv_pem = _read_pem(self.mch_private_key_path)
        if not priv_pem:
            raise RuntimeError("mch private key unreadable")
        sig = _b64url_encode(_rsa_sign(message.encode("utf-8"), priv_pem))
        return {
            "Authorization": (
                'WECHATPAY2-SHA256-RSA2048 mchid="%s",nonce_str="%s",'
                'timestamp="%s",serial_no="%s",signature="%s"'
                % (self.mch_id, nonce, ts, self.mch_serial_no, sig)
            ),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ─────────────────────────────────────────────────────────
    # 公共 API
    # ─────────────────────────────────────────────────────────

    def create_payment(
        self,
        order_no: str,
        amount: float,
        plan: str,
        days: int,
        notify_url: str,
        return_url: str,
    ) -> dict[str, Any]:
        """构造 Native 扫码支付参数。

        - 真实模式:调 `POST /v3/pay/transactions/native`,回 `code_url`。
        - Mock 模式:签名只覆盖业务字段,拼一个模拟的 `code_url`(形似真实)
          以便前端本地渲染二维码。
        """
        total_yuan = round(float(amount), 2)
        total_fen = int(round(total_yuan * 100))
        description = f"Prism-Fusion {plan} {days}d"

        if not self.is_real:
            return self._create_payment_mock(
                order_no=order_no,
                total_yuan=total_yuan,
                total_fen=total_fen,
                description=description,
                plan=plan,
                days=days,
                notify_url=notify_url,
                return_url=return_url,
            )

        # ── 真实模式 ────────────────────────────────────────
        body = {
            "appid": self.app_id,
            "mchid": self.mch_id,
            "description": description[:32],
            "out_trade_no": order_no,
            "notify_url": notify_url,
            "amount": {
                "total": total_fen,
                "currency": "CNY",
            },
            "scene_info": {
                "payer_client_ip": _get_str("CLOUD_PAYMENT_CLIENT_IP") or "127.0.0.1",
            },
        }
        body_str = _json_dumps(body)
        path = "/v3/pay/transactions/native"
        try:
            headers = self._sign_headers("POST", path, body_str)
        except Exception as e:
            # 本地开发期密钥丢失:显式抛,不做静默降级(下单要真实钱,不能让调用方误以为成功了)
            raise RuntimeError(f"wechat real create_payment sign failed: {e}") from e

        if self._http is None:
            raise RuntimeError("wechat httpx client unavailable")
        resp = self._http.request("POST", path, content=body_str, headers=headers)
        if resp.status_code // 100 != 2:
            raise RuntimeError(
                f"wechat native create failed: http={resp.status_code} "
                f"body={resp.text[:200]!r}"
            )
        data = resp.json()
        code_url = str(data.get("code_url") or "")
        if not code_url:
            raise RuntimeError(f"wechat native create returned no code_url: {data!r}")
        return {
            "channel": "wechat",
            "order_no": order_no,
            "amount": total_yuan,
            "amount_fen": total_fen,
            "pay_type": "qrcode",
            "code_url": code_url,
            "prepay_id": str(data.get("prepay_id") or ""),
            "expires_in": 600,
            "sandbox": self.sandbox,
        }

    def verify_callback(
        self,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """验签 + 解析回调。

        **真实模式**(body 已解密 resource 或带 `_headers`/`headers` 参数):
          - 需要 header: `Wechatpay-Timestamp` / `Wechatpay-Nonce` /
            `Wechatpay-Serial` / `Wechatpay-Signature`
          - 校验签名(WECHATPAY2-SHA256-RSA2048):
            `message = "{timestamp}\\n{nonce}\\n{raw_body}\\n"`
          - 用 APIv3 密钥 AES-256-GCM 解密 `resource.ciphertext`(nonce=resource.nonce,
            associated_data=resource.associated_data)。
          - 校验 `out_trade_no` / `amount.total` / `trade_state`。
          - 任何一步失败都返回 `(False, {})`,**不泄露内部字段**。

        **Mock 模式**(旧版结构,`body.sign` 存在):走 HMAC mock 验签,行为与旧版一致。
        """
        # ── 真实模式 ────────────────────────────────────────
        if self.is_real:
            return self._verify_callback_real(body=body, headers=headers)

        # ── Mock 模式 ───────────────────────────────────────
        out_trade_no = str(body.get("out_trade_no") or "").strip()
        transaction_id = str(body.get("transaction_id") or "").strip()
        trade_state = str(body.get("trade_state") or "").strip()
        sign = str(body.get("sign") or "").strip()
        plan = str(body.get("plan") or "").strip()
        days = body.get("days")
        notify_url = str(body.get("notify_url") or "").strip()
        return_url = str(body.get("return_url") or "").strip()

        if trade_state != "SUCCESS":
            return False, {}
        if not out_trade_no or not transaction_id:
            return False, {}

        total_fen_raw = body.get("total_fen")
        try:
            total_fen = int(total_fen_raw)
        except (TypeError, ValueError):
            return False, {}

        sign_payload = {
            "out_trade_no": out_trade_no,
            "total_fen": str(total_fen),
            "plan": plan,
            "days": str(days),
            "notify_url": notify_url,
            "return_url": return_url,
        }
        if not _verify_sig(self._sign_secret, sign_payload, sign):
            return False, {}

        return True, {
            "out_trade_no": out_trade_no,
            "pay_trade_no": transaction_id,
            "amount": round(total_fen / 100, 2),
        }

    # ─────────────────────────────────────────────────────────
    # query_order / refund / fetch_bill
    # ─────────────────────────────────────────────────────────

    def query_order(self, order_no: str) -> tuple[bool, dict[str, Any]]:
        """按 `out_trade_no` 查单(默认 mock,回空字段)。"""
        if not self.is_real:
            return True, {
                "out_trade_no": order_no,
                "trade_state": "NOTPAY",
                "pay_type": "qrcode",
            }
        path = f"/v3/pay/transactions/out-trade-no/{order_no}?mchid={self.mch_id}"
        body_str = ""
        headers = self._sign_headers("GET", path, body_str)
        if self._http is None:
            raise RuntimeError("wechat httpx client unavailable")
        resp = self._http.request("GET", path, headers=headers)
        if resp.status_code // 100 != 2:
            return False, {"error": f"http={resp.status_code} body={resp.text[:200]!r}"}
        data = resp.json()
        amt = data.get("amount") or {}
        out = dict(data)
        out["amount"] = round(int(amt.get("total", 0)) / 100, 2)
        return True, out

    def refund(
        self,
        *,
        order_no: str,
        pay_trade_no: str,
        amount: float,
        order_amount: float | None = None,
        reason: str = "",
    ) -> tuple[bool, str, dict[str, Any]]:
        """发起退款。

        - Mock 模式:与基类一致,直接回显。
        - 真实模式:`POST /v3/refund/domestic/refunds`,金额单位**分**,整数。

        `order_amount` 说明:
          微信 APIv3 的 `amount.total` 必须是**原订单金额(分)**,
          部分退款时若 `total == refund` 会被微信拒(要求 total > refund)。
          调用方(router)应从 Order 表读原订单金额并传入;
          缺省 `None` 时回退到 `amount`(保持与旧测试 / 全额退款的兼容)。
        """
        refund_fen = int(round(float(amount) * 100))
        if refund_fen <= 0:
            return False, "refund amount must be > 0", {}
        # order_amount 缺省回退到 amount(兼容旧的 3 参数调用)
        total_fen = int(round(float(order_amount) * 100)) if order_amount is not None else refund_fen
        if not self.is_real:
            return super().refund(
                order_no=order_no,
                pay_trade_no=pay_trade_no,
                amount=amount,
                order_amount=order_amount,
                reason=reason,
            )

        body = {
            "transaction_id": pay_trade_no,
            "out_trade_no": order_no,
            "out_refund_no": f"RF_{order_no}_{refund_fen}",
            "amount": {
                "refund": refund_fen,
                "total": total_fen,
                "currency": "CNY",
            },
        }
        if reason:
            body["reason"] = reason
        body_str = _json_dumps(body)
        path = "/v3/refund/domestic/refunds"
        headers = self._sign_headers("POST", path, body_str)
        if self._http is None:
            raise RuntimeError("wechat httpx client unavailable")
        resp = self._http.request("POST", path, content=body_str, headers=headers)
        if resp.status_code // 100 != 2:
            return False, f"http={resp.status_code} body={resp.text[:200]!r}", {}
        data = resp.json()
        status = str(data.get("status") or "").upper()
        # SUCCESS / PROCESSING 都算受理;ACCEPTANCE 已弃用但保留兼容
        if status not in {"SUCCESS", "PROCESSING", "ACCEPTANCE"}:
            return False, f"refund status={status}", data
        return True, "refund accepted", {
            "channel": self.name,
            "refund_trade_no": str(data.get("refund_id") or ""),
            "refund_amount": round(refund_fen / 100, 2),
            "status": status,
        }

    def fetch_bill(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """拉取交易账单(对账用)。

        - Mock 模式:返回空 list(与基类一致)。
        - 真实模式:`GET /v3/billdownload/tradebill` → 取 `download_url` 与
          平台响应头 `Wechatpay-Timestamp/Nonce/Signature` 之外的 `X-*` 头
          中的 `hash`(微信返回明文 SHA256,与文件内容比对)。
          下载后按 CSV 逐行解析,仅提取业务需要的 5 个字段:
            `out_trade_no / transaction_id / amount / trade_time / trade_type`
        """
        if not self.is_real:
            return []
        if self._http is None:
            raise RuntimeError("wechat httpx client unavailable")

        path = "/v3/billdownload/tradebill?bill_date={}".format(start_date)
        headers = self._sign_headers("GET", path, "")
        resp = self._http.request("GET", path, headers=headers)
        if resp.status_code // 100 != 2:
            return []
        data = resp.json()
        download_url = str(data.get("download_url") or "")
        if not download_url:
            return []
        expected_hash = str(resp.headers.get("Hash") or resp.headers.get("hash") or "")

        # 下载账单(HTTP(S))—— 不经过微信签名头
        bill_resp = httpx.get(download_url, timeout=60.0, follow_redirects=True)
        if bill_resp.status_code // 100 != 2:
            return []
        raw = bill_resp.content
        if expected_hash:
            # 微信官方文档:账单文件的 hash 校验使用 SHA256,十六进制小写
            digest = hashlib.sha256(raw).hexdigest()
            if digest != expected_hash.lower():
                return []

        rows = _parse_trade_bill_csv(raw.decode("utf-8", errors="replace"))
        # 简单按日期过滤(账单文件一般已按日期切分,这里做兜底)
        if end_date and end_date != start_date:
            rows = [r for r in rows if (r.get("trade_time") or "") <= end_date + " 23:59:59"]
        return rows

    # ─────────────────────────────────────────────────────────
    # 内部实现:mock 下单 / 真实回调
    # ─────────────────────────────────────────────────────────

    def _create_payment_mock(
        self,
        *,
        order_no: str,
        total_yuan: float,
        total_fen: int,
        description: str,
        plan: str,
        days: int,
        notify_url: str,
        return_url: str,
    ) -> dict[str, Any]:
        """Mock 阶段:签名字段与旧版完全一致(既有测试依赖)。"""
        sign_payload = {
            "out_trade_no": order_no,
            "total_fen": str(total_fen),
            "plan": plan,
            "days": str(days),
            "notify_url": notify_url,
            "return_url": return_url,
        }
        sign = _mock_sign(self._sign_secret, sign_payload)
        code_url = (
            "weixin://wxpay/bizpayurl?"
            f"appid={self.app_id}&mch_id={self.mch_id}"
            f"&out_trade_no={order_no}&total_fee={total_fen}"
            f"&description={description}&sign={sign}&sandbox={1 if self.sandbox else 0}"
        )
        return {
            "channel": "wechat",
            "order_no": order_no,
            "amount": total_yuan,
            "amount_fen": total_fen,
            "pay_type": "qrcode",
            "code_url": code_url,
            "expires_in": 600,
            "sandbox": self.sandbox,
        }

    def _verify_callback_real(
        self,
        *,
        body: dict[str, Any],
        headers: dict[str, str] | None,
    ) -> tuple[bool, dict[str, Any]]:
        """真实 APIv3 回调验签 + 解密。"""
        if headers is None:
            # router 若直接把 headers 塞进 body 也支持(便于测试)
            headers = (
                body.get("_headers")
                or body.get("headers")
                or {}
            )
        # 大小写不敏感地取头
        def _h(name: str) -> str:
            for k, v in headers.items():
                if k.lower() == name.lower():
                    return str(v)
            return ""

        ts = _h("Wechatpay-Timestamp")
        nonce = _h("Wechatpay-Nonce")
        serial = _h("Wechatpay-Serial")
        sig = _h("Wechatpay-Signature")
        if not (ts and nonce and serial and sig):
            return False, {}

        # 时间戳窗口校验(默认 ±5min,防止重放)
        try:
            if abs(int(ts) - int(_time_epoch())) > _TS_SKEW_SEC:
                return False, {}
        except Exception:
            return False, {}

        # 用平台证书/公钥做 SHA256withRSA 验签
        platform_pem = _read_pem(self.wechat_public_key_path)
        if not platform_pem:
            return False, {}
        # body 必须是**原始** JSON 字符串;若 body 已经被反序列化成 dict,
        # 我们重新 dumps(sort_keys=False, separators) 保持与请求体一致
        raw_body = _json_dumps(body)
        message = f"{ts}\n{nonce}\n{raw_body}\n"
        if not _rsa_verify(sig, message.encode("utf-8"), platform_pem):
            return False, {}

        # 解密 resource
        resource = body.get("resource") or {}
        nonce_b64 = str(resource.get("nonce") or "")
        associated = str(resource.get("associated_data") or "")
        ciphertext = str(resource.get("ciphertext") or "")
        if not (nonce_b64 and ciphertext):
            return False, {}
        api_v3_key_b = self.api_v3_key.encode("utf-8") if isinstance(self.api_v3_key, str) else self.api_v3_key
        if len(api_v3_key_b) != 32:
            return False, {}
        plaintext = aes_gcm_decrypt(api_v3_key_b, nonce_b64, associated, ciphertext)
        if not plaintext:
            return False, {}
        try:
            trade_data = json.loads(plaintext.decode("utf-8"))
        except Exception:
            return False, {}

        trade_state = str(trade_data.get("trade_state") or "").strip()
        if trade_state != "SUCCESS":
            return False, {}
        out_trade_no = str(trade_data.get("out_trade_no") or "").strip()
        transaction_id = str(trade_data.get("transaction_id") or "").strip()
        if not (out_trade_no and transaction_id):
            return False, {}
        amount_obj = trade_data.get("amount") or {}
        try:
            total_fen = int(amount_obj.get("total"))
        except (TypeError, ValueError):
            return False, {}
        if total_fen <= 0:
            return False, {}

        return True, {
            "out_trade_no": out_trade_no,
            "pay_trade_no": transaction_id,
            "amount": round(total_fen / 100, 2),
        }


# ──────────────────────────────────────────────────────────────
# 模块级辅助
# ──────────────────────────────────────────────────────────────

def _is_real_configured(env: dict[str, str]) -> bool:
    """判定是否走真实 APIv3。

    降级到 mock 的必要条件(**任一缺失即降级**):
      - `app_id` 缺失或仍是 `MOCK_WECHAT_APP_ID`
      - `mch_id` 缺失或仍是 `MOCK_MCH_ID`
      - `api_v3_key` 长度不是 32
      - `mch_serial_no` 缺失
      - `mch_private_key_path` 缺失或读不到非空 PEM
      - `wechat_public_key_path` 缺失或读不到非空 PEM
      - `notify_url` 缺失(无法完成真实回调)
    """
    if not env["app_id"] or env["app_id"] == MOCK_APP_ID:
        return False
    if not env["mch_id"] or env["mch_id"] == MOCK_MCHID:
        return False
    if len(env["api_v3_key"].encode("utf-8")) != 32:
        return False
    if not env["mch_serial_no"]:
        return False
    if not _read_pem(env["mch_private_key_path"]):
        return False
    if not _read_pem(env["wechat_public_key_path"]):
        return False
    if not env["notify_url"]:
        return False
    return True


def _read_pem(path: str) -> bytes:
    """安全读取 PEM 文件;文件不存在/读空/空字节时返回 `b""`(不打印内容)。

    注:仅做非空校验,不校验 PEM 结构;结构错误在签名/验签处会自然失败。
    """
    if not path:
        return b""
    try:
        with open(path, "rb") as f:
            data = f.read()
        # 简单校验:PEM 至少应包含 BEGIN/END 标记,避免把普通文本当密钥用
        if len(data) < 32:
            return b""
        text = data.decode("utf-8", errors="ignore")
        if "BEGIN" not in text or "END" not in text:
            return b""
        return data
    except Exception:
        return b""


def _json_dumps(obj: Any) -> str:
    """与微信官方一致的 JSON 序列化(紧凑、UTF-8、preserve order)。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _parse_trade_bill_csv(text: str) -> list[dict[str, Any]]:
    """把微信交易账单 CSV 解析成简化 dict 列表。

    微信账单格式(v3 通用版):
      - 首行/若干行以 `#` 或 `备注:` 开头(跳过)
      - 表头行:中英文列名(交易时间 / 商户订单号 / 微信支付单号 / ...)
      - 数据行:逗号分隔
    通过**表头索引**定位需要的列,不同版本/币种可能列顺序不同。
    """
    import csv
    import io

    rows: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(text))

    # 定位表头
    header: list[str] = []
    for row in reader:
        if not row:
            continue
        head0 = (row[0] or "").strip()
        if head0.startswith("#") or head0.startswith("备注"):
            continue
        if "交易完成时间" in row[0] or "交易时间" in row[0] or "商户订单号" in row[0]:
            header = [c.strip() for c in row]
            break

    if not header:
        return []

    # 找列索引(支持中英文变体)
    def _col(*keywords: str) -> int:
        for i, h in enumerate(header):
            for kw in keywords:
                if kw in h:
                    return i
        return -1

    idx_time = _col("交易完成时间", "交易时间")
    idx_type = _col("交易类型")
    idx_out = _col("商户订单号")
    idx_amt = _col("用户实付金额", "用户支付金额", "实付金额")
    idx_tx = _col("微信支付单号", "微信订单号")

    for row in reader:
        if not row or (row[0] or "").strip().startswith("#"):
            continue
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))

        def _val(idx: int) -> str:
            if idx < 0 or idx >= len(row):
                return ""
            return (row[idx] or "").strip()

        out_trade_no = _val(idx_out)
        tx_id = _val(idx_tx)
        if not (out_trade_no or tx_id):
            continue

        amount_raw = _val(idx_amt).lstrip("￥¥-")
        try:
            amount = round(abs(float(amount_raw)), 2) if amount_raw else 0.0
        except Exception:
            amount = 0.0

        type_raw = _val(idx_type)
        trade_type = "refund" if ("退" in type_raw) else "payment"

        rows.append({
            "out_trade_no": out_trade_no,
            "pay_trade_no": tx_id,
            "amount": amount,
            "trade_time": _val(idx_time),
            "trade_type": trade_type,
            "channel": "wechat",
        })
    return rows


def _time_epoch() -> int:
    import time
    return int(time.time())


# ──────────────────────────────────────────────────────────────
# 注册 & 导出
# ──────────────────────────────────────────────────────────────

register_adapter(WechatAdapter())

__all__ = [
    "WechatAdapter",
    "MOCK_SECRET",
    "MOCK_APP_ID",
    "MOCK_MCHID",
    "_is_real_configured",
    "aes_gcm_decrypt",
    "aes_gcm_encrypt",
    "_rsa_sign",
    "_rsa_verify",
    "_mock_sign_local",
]
