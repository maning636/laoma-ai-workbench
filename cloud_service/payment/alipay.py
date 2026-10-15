"""支付宝适配(OpenAPI 真实实现 + mock 降级)。

设计参考 `docs/dev-reports/2026-10-13-saas-c-class-design.md` §5.2:
  - 电脑网站支付(`alipay.trade.page.pay`)→ 商户侧构造参数 + RSA2 签名 →
    返回 `<form>` HTML,前端 render 后由浏览器 POST 到 gateway。
  - 回调:form-urlencoded body,用**支付宝公钥** RSA2 验签;
    `sign` / `sign_type` 需剔除后按参数名升序拼接待签串。
  - 查单 `alipay.trade.query` / 退款 `alipay.trade.refund` /
    账单 `alipay.data.dataservice.bill.downloadurl.query`。

安全:
  - 商户参数 `CLOUD_ALIPAY_*` 一律 env 注入;私钥 / 公钥**只存路径或独立字段**,
    绝不打印或写进仓库。
  - 未配置真实参数(见 `_is_real_configured`)时**自动降级 mock**,
    行为与旧版一致,既有测试(`test_payment.py` / `test_payment_leftour.py`)保持通过。

真实渠道对接(OpenAPI):
  1. `create_payment` → 组装 `alipay.trade.page.pay` 参数 → RSA2 签名 →
     返回 form_html(前端自动 submit,不需要商户后端代打 gateway)。
  2. `verify_callback` → 支付宝回调 form-urlencoded body,RSA2 验签 →
     校验 `out_trade_no` / `total_amount`(元)/ `trade_status`。
  3. `query_order` → POST `alipay.trade.query` → 返回支付宝返回的 trade 字段。
  4. `refund` → POST `alipay.trade.refund`(支持 `refund_amount` 部分退款、
     `out_request_no` 幂等)。
  5. `fetch_bill` → POST `alipay.data.dataservice.bill.downloadurl.query` →
     拿下载链接 → HTTP GET 下载 CSV → 尽力按表头定位列解析(见
     `_parse_trade_bill_csv`)。

与微信 APIv3 的差异:
  - **金额单位**:支付宝是"元"(两位小数字符串,`total_amount=99.00`);
    微信是"分"(整数,`amount.total=9900`)。
  - **回调编码**:支付宝是 form-urlencoded,`sign` / `sign_type` 内嵌 body 中;
    微信 APIv3 是 JSON + `Wechatpay-*` 头 + `resource` AES-256-GCM 解密。
  - **签名算法**:都是 RSA-SHA256(PKCS1v15 + SHA256);但载体不同——
    支付宝签"参数串(k=v&k=v)",微信签"method\npath\ntimestamp\nnonce\nbody\n"。
  - **无加密资源层**:支付宝明文返回 JSON,商户自己验签即可。
  - **网关模式**:支付宝 OpenAPI 用同一个 gateway.do + POST form-urlencoded;
    微信 APIv3 用独立 REST 路径 + JSON。
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import (
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

MOCK_SECRET = "__MOCK__ALIPAY_SECRET__"
MOCK_APP_ID = "MOCK_ALIPAY_APP_ID"

# OpenAPI 网关(生产 / 沙箱)
ALIPAY_GATEWAY = "https://openapi.alipay.com/gateway.do"
ALIPAY_GATEWAY_SANDBOX = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"

_SIGN_TYPE = "RSA2"  # SHA256withRSA
_TIMEOUT_SEC = 15.0
_TS_FMT = "%Y-%m-%d %H:%M:%S"


# ──────────────────────────────────────────────────────────────
# RSA2 签名 / 验签 / 待签串构造
# ──────────────────────────────────────────────────────────────

def _rsa2_sign(sign_str: str, private_pem: bytes) -> str:
    """SHA256withRSA 签名(即 PKCS1v15 + SHA256),返回 base64(标准)。"""
    key = load_pem_private_key(private_pem, password=None)
    sig = key.sign(sign_str.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode("ascii")


def _rsa2_verify(sign_b64: str, sign_str: str, public_pem: bytes) -> bool:
    """校验 RSA2 签名;任何异常返回 False(不抛、不打印密钥)。"""
    if not sign_b64:
        return False
    try:
        key = load_pem_public_key(public_pem)
        sig = base64.b64decode(sign_b64)
        key.verify(sig, sign_str.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        return False
    return True


def _build_sign_str(params: dict[str, Any]) -> str:
    """构造支付宝待签串。

    规则(与支付宝官方一致):
      - 排除 `sign` 和 `sign_type`;
      - 排除空值(`""` 或 `None`);
      - 按参数名升序拼接 `k=v&k=v`(不做 URL 编码,原值拼接)。
    """
    items: list[tuple[str, str]] = []
    for k in sorted(params.keys()):
        if k in ("sign", "sign_type"):
            continue
        v = params.get(k)
        if v is None:
            continue
        s = str(v)
        if s == "":
            continue
        items.append((k, s))
    return "&".join(f"{k}={v}" for k, v in items)


# ──────────────────────────────────────────────────────────────
# 主适配类
# ──────────────────────────────────────────────────────────────

class AlipayAdapter(PaymentAdapter):
    """支付宝适配:OpenAPI 真实实现 + 未配置时自动降级 mock。"""

    name = "alipay"

    def __init__(
        self,
        *,
        app_id: str = "",
        app_private_key_path: str = "",
        alipay_public_key_path: str = "",
        app_private_key: str = "",       # 内联 PEM(便于测试;生产推荐用路径)
        alipay_public_key: str = "",     # 内联 PEM
        gateway_url: str = "",
        sign_type: str = "",
        sandbox: bool | None = None,
        client: httpx.Client | None = None,
        _force_real: bool | None = None,
    ) -> None:
        self.app_id = app_id or _get_str("CLOUD_ALIPAY_APP_ID") or MOCK_APP_ID

        # 沙箱开关:默认沙箱(True),显式传 sandbox=False 覆盖为生产。
        # 保守策略:环境变量缺失时默认走沙箱,避免误把真实钱打到支付宝生产。
        # 生产环境需显式设置 `CLOUD_ALIPAY_SANDBOX=0` 或在 .env.example 中改。
        if sandbox is None:
            self.sandbox = _get_str("CLOUD_ALIPAY_SANDBOX", "1").lower() in {"1", "true", "yes"}
        else:
            self.sandbox = bool(sandbox)

        # 应用私钥(商户持有): 路径或内联 PEM,同时兼容旧 env 名
        self.app_private_key_path = (
            app_private_key_path
            or _get_str("CLOUD_ALIPAY_APP_PRIVATE_KEY_PATH")
            or _get_str("CLOUD_ALIPAY_PRIVATE_KEY_PATH")
        )
        self._app_private_key_inline = (
            app_private_key
            or _get_str("CLOUD_ALIPAY_APP_PRIVATE_KEY")
            or _get_str("CLOUD_ALIPAY_PRIVATE_KEY")
        )

        # 支付宝公钥(平台持有): 用来验签回调
        self.alipay_public_key_path = (
            alipay_public_key_path
            or _get_str("CLOUD_ALIPAY_ALIPAY_PUBLIC_KEY_PATH")
            or _get_str("CLOUD_ALIPAY_PUBLIC_KEY_PATH")
        )
        self._alipay_public_key_inline = (
            alipay_public_key
            or _get_str("CLOUD_ALIPAY_ALIPAY_PUBLIC_KEY")
            or _get_str("CLOUD_ALIPAY_PUBLIC_KEY")
        )
        # 兼容旧的 CLOUD_ALIPAY_APP_PUBLIC_KEY: 若其内容看起来是 PEM,也当作
        # 支付宝公钥使用(旧测试里该 env 通常只是随机字符串,不匹配 PEM 前缀,忽略)
        if not self._alipay_public_key_inline:
            v = _get_str("CLOUD_ALIPAY_APP_PUBLIC_KEY")
            if v and "-----BEGIN" in v:
                self._alipay_public_key_inline = v

        self.gateway_url = (
            gateway_url
            or _get_str("CLOUD_ALIPAY_GATEWAY_URL")
            or (ALIPAY_GATEWAY_SANDBOX if self.sandbox else ALIPAY_GATEWAY)
        )
        self.sign_type = sign_type or _get_str("CLOUD_ALIPAY_SIGN_TYPE") or _SIGN_TYPE

        # mock 阶段验签密钥(真实环境走 RSA2,不再使用)
        self._sign_secret = (
            _get_str("CLOUD_ALIPAY_APP_PUBLIC_KEY")
            or _get_str("CLOUD_ALIPAY_SECRET")
            or MOCK_SECRET
        )

        # HTTP 客户端(单测可注入 MockTransport)
        if client is not None:
            self._http = client
        else:
            try:
                self._http = httpx.Client(timeout=_TIMEOUT_SEC)
            except Exception:  # pragma: no cover - 罕见,防止启动期炸
                self._http = None

        # 真实模式判定: env 或显式 _force_real 都算;否则降级 mock
        self.is_real = (
            bool(_force_real)
            if _force_real is not None
            else _is_real_configured({
                "app_id": self.app_id,
                "app_private_key_path": self.app_private_key_path,
                "alipay_public_key_path": self.alipay_public_key_path,
                "app_private_key_inline": self._app_private_key_inline,
                "alipay_public_key_inline": self._alipay_public_key_inline,
            })
        )

    # ─────────────────────────────────────────────────────────
    # 便捷工厂 / 关闭
    # ─────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, client: httpx.Client | None = None) -> "AlipayAdapter":
        return cls(client=client)

    def close(self) -> None:
        if self._http is not None:
            try:
                self._http.close()
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────
    # 内部:密钥加载
    # ─────────────────────────────────────────────────────────

    def _load_private_key(self) -> bytes:
        if self._app_private_key_inline:
            raw = self._app_private_key_inline
            if "BEGIN" in raw and "END" in raw:
                return raw.encode("utf-8")
            return b""
        return _read_pem(self.app_private_key_path)

    def _load_public_key(self) -> bytes:
        if self._alipay_public_key_inline:
            raw = self._alipay_public_key_inline
            if "BEGIN" in raw and "END" in raw:
                return raw.encode("utf-8")
            return b""
        return _read_pem(self.alipay_public_key_path)

    # ─────────────────────────────────────────────────────────
    # 内部:OpenAPI gateway 调用
    # ─────────────────────────────────────────────────────────

    def _sign_params(self, params: dict[str, Any]) -> str:
        """用应用私钥对业务参数做 RSA2 签名,返回 base64 签名字符串。"""
        priv_pem = self._load_private_key()
        if not priv_pem:
            raise RuntimeError("alipay app private key unreadable")
        sign_str = _build_sign_str(params)
        return _rsa2_sign(sign_str, priv_pem)

    def _gateway_call(self, method: str, biz_params: dict[str, str]) -> dict[str, Any]:
        """POST form-urlencoded 到 gateway,返回整个 JSON 响应。

        业务约定:
          - 请求:公共参数 + 业务参数 + `sign`;
          - 响应:`{method}_response`: 业务结果 JSON + `code` / `msg`。
        """
        if self._http is None:
            raise RuntimeError("alipay httpx client unavailable")
        common: dict[str, str] = {
            "app_id": self.app_id,
            "method": method,
            "format": "json",
            "charset": "utf-8",
            "sign_type": self.sign_type,
            "timestamp": _alipay_ts(),
            "version": "1.0",
        }
        params: dict[str, Any] = {**common, **biz_params}
        params["sign"] = self._sign_params(params)

        body = urllib.parse.urlencode(params)
        resp = self._http.request(
            "POST",
            self.gateway_url,
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        )
        if resp.status_code // 100 != 2:
            raise RuntimeError(
                f"alipay gateway http={resp.status_code} method={method} "
                f"body={resp.text[:200]!r}"
            )
        try:
            return json.loads(resp.text)
        except Exception as e:
            raise RuntimeError(
                f"alipay gateway bad json method={method}: {e}; body={resp.text[:200]!r}"
            ) from e

    @staticmethod
    def _biz(response: dict[str, Any], method: str) -> dict[str, Any]:
        """从 gateway 响应中取出 `{method}_response` 业务字段。"""
        return response.get(f"{method}_response") or {}

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
        """构造电脑网站支付(<form> HTML)。

        - 真实模式:组装 `alipay.trade.page.pay` 全部参数 → RSA2 签名 →
          返回 form_html(前端 render 后浏览器自动 POST 到 gateway)。
        - Mock 模式:与旧版一致,用 HMAC mock 签名拼一份模拟 form,便于
          单测与本地开发。
        """
        total_yuan = round(float(amount), 2)
        total_yuan_str = f"{total_yuan:.2f}"
        subject = f"Prism-Fusion {plan} {days}d"

        if not self.is_real:
            return self._create_payment_mock(
                order_no=order_no,
                total_yuan_str=total_yuan_str,
                subject=subject,
                plan=plan,
                days=days,
                notify_url=notify_url,
                return_url=return_url,
            )

        # ── 真实模式 ────────────────────────────────────────
        biz_params: dict[str, str] = {
            "out_trade_no": order_no,
            "total_amount": total_yuan_str,
            "subject": subject,
            "product_code": "FAST_INSTANT_TRADE_PAY",
            "notify_url": notify_url,
            "return_url": return_url,
        }
        # 允许通过环境变量追加可选业务字段(便于生产扩展,不硬编码)
        _passback = _get_str("CLOUD_ALIPAY_PASSBACK_PARAMS")
        if _passback:
            biz_params["passback_params"] = _passback

        # 组装公共 + 业务参数,准备签名
        common: dict[str, str] = {
            "app_id": self.app_id,
            "method": "alipay.trade.page.pay",
            "format": "json",
            "charset": "utf-8",
            "sign_type": self.sign_type,
            "timestamp": _alipay_ts(),
            "version": "1.0",
        }
        params: dict[str, Any] = {**common, **biz_params}
        try:
            params["sign"] = self._sign_params(params)
        except Exception as e:
            # 生产下单,密钥丢失要显式抛,不做静默降级
            raise RuntimeError(f"alipay real create_payment sign failed: {e}") from e

        form_html = _render_form(self.gateway_url, params)
        return {
            "channel": "alipay",
            "order_no": order_no,
            "amount": total_yuan,
            "pay_type": "form",
            "form_html": form_html,
            "gateway_url": self.gateway_url,
            "method": "alipay.trade.page.pay",
            "expires_in": 3600,
            "sandbox": self.sandbox,
        }

    def verify_callback(
        self,
        body: dict[str, Any] | str,
        headers: dict[str, str] | None = None,  # 支付宝回调无签名头,参数在 body 中
    ) -> tuple[bool, dict[str, Any]]:
        """验签 + 解析回调。

        **真实模式**(body 里带 `sign` 且我们能加载支付宝公钥):
          - body 是 form-urlencoded 解析后的 dict,已包含 `sign` / `sign_type`;
            若调用方直接传原始 form-urlencoded 字符串也支持(会在内部 parse_qsl);
          - 剔除 `sign` / `sign_type` 及空值 → 按 key 升序拼接待签串;
          - 用支付宝公钥 RSA2 验签;
          - 校验 `out_trade_no` / `total_amount`(元)/ `trade_status`;
          - `trade_status` 需为 `TRADE_SUCCESS` 或 `TRADE_FINISHED`。
          - 任何一步失败 → `(False, {})`,不泄露内部字段。

        **Mock 模式**(旧版结构,`body.sign` 由 HMAC mock 生成):
          与旧版一致,行为完全兼容既有测试。
        """
        if isinstance(body, str):
            body = dict(urllib.parse.parse_qsl(body))

        if self.is_real:
            return self._verify_callback_real(body)

        # ── Mock 模式 ────────────────────────────────────────
        out_trade_no = str(body.get("out_trade_no") or "").strip()
        trade_no = str(body.get("trade_no") or "").strip()
        total_amount = body.get("total_amount")
        trade_status = str(body.get("trade_status") or "").strip()
        sign = str(body.get("sign") or "").strip()
        plan = str(body.get("plan") or "").strip()
        days = body.get("days")
        notify_url = str(body.get("notify_url") or "").strip()
        return_url = str(body.get("return_url") or "").strip()

        if trade_status != "TRADE_SUCCESS":
            return False, {}
        if not out_trade_no or not trade_no:
            return False, {}
        try:
            amount = round(float(total_amount), 2)
        except (TypeError, ValueError):
            return False, {}

        sign_payload = {
            "out_trade_no": out_trade_no,
            "total_amount": f"{amount:.2f}",
            "plan": plan,
            "days": str(days),
            "notify_url": notify_url,
            "return_url": return_url,
        }
        if not _verify_sig(self._sign_secret, sign_payload, sign):
            return False, {}

        return True, {
            "out_trade_no": out_trade_no,
            "pay_trade_no": trade_no,
            "amount": amount,
        }

    # ─────────────────────────────────────────────────────────
    # query_order / refund / fetch_bill
    # ─────────────────────────────────────────────────────────

    def query_order(self, order_no: str) -> tuple[bool, dict[str, Any]]:
        """按 `out_trade_no` 查单。

        - Mock:回一份 `trade_status=WAIT_BUYER_PAY` 的占位。
        - 真实:`POST alipay.trade.query`。
        """
        if not self.is_real:
            return True, {
                "out_trade_no": order_no,
                "trade_status": "WAIT_BUYER_PAY",
                "pay_type": "form",
            }

        biz: dict[str, str] = {"out_trade_no": order_no}
        _trade_no = _get_str("CLOUD_ALIPAY_QUERY_TRADE_NO")
        if _trade_no:
            biz["trade_no"] = _trade_no
        resp = self._gateway_call("alipay.trade.query", biz)
        data = self._biz(resp, "alipay.trade.query")
        code = str(data.get("code") or "")
        if code != "10000":  # 支付宝成功 code
            return False, {"error": f"code={code} msg={data.get('msg')!r}"}
        out = dict(data)
        # total_amount / refund_amount 支付宝已经是元,无需转换
        return True, out

    def refund(
        self,
        *,
        order_no: str,
        pay_trade_no: str,
        amount: float,
        reason: str = "",
        out_request_no: str = "",
        order_amount: float | None = None,   # 原订单金额;用于校验 amount <= order_amount(不参与支付宝请求体)
    ) -> tuple[bool, str, dict[str, Any]]:
        """发起退款。

        - Mock 模式:与基类一致,直接回显。
        - 真实模式:`POST alipay.trade.refund`,金额单位**元**(两位小数),
          `out_request_no` 保证**幂等**——同一 order_no + amount 每次生成同样的值。

        `order_amount` 参数:
          - 支付宝 OpenAPI 的 `alipay.trade.refund` 只需要 `refund_amount`
            (元),不接收原订单金额字段;因此**不参与请求体构造**;
          - 但为与微信 / 基类签名保持一致,并做一层防御性校验:
            若调用方传入了 `order_amount` 且 `amount > order_amount`
            → 拒绝(返回 `ok=False`),避免把超额退款发出去;
          - 缺省 `None` 时不校验,与基类 / 旧 3 参数调用兼容。
        """
        refund_yuan = round(float(amount), 2)
        if refund_yuan <= 0:
            return False, "refund amount must be > 0", {}
        # 防御性校验:退款金额不得超过原订单金额
        if order_amount is not None and refund_yuan > float(order_amount) + 1e-6:
            return (
                False,
                f"refund amount {refund_yuan} exceeds order amount {float(order_amount):.2f}",
                {},
            )
        if not self.is_real:
            return super().refund(
                order_no=order_no,
                pay_trade_no=pay_trade_no,
                amount=amount,
                order_amount=order_amount,
                reason=reason,
            )

        if not out_request_no:
            # 幂等:同一 order_no + 金额 = 同一 out_request_no,重试不会重复退款
            # 8 位十六进制后缀防不同用户 order_no 冲突
            import hashlib as _hl
            h = _hl.sha1(f"{order_no}|{refund_yuan:.2f}".encode("utf-8")).hexdigest()[:8]
            out_request_no = f"RF_{order_no}_{h}"

        biz: dict[str, str] = {
            "out_trade_no": order_no,
            "refund_amount": f"{refund_yuan:.2f}",
            "out_request_no": out_request_no,
            "query_options": "trade_no,refund_fee,gmt_refund_pay,fund_change",
        }
        if reason:
            biz["refund_reason"] = reason

        resp = self._gateway_call("alipay.trade.refund", biz)
        data = self._biz(resp, "alipay.trade.refund")
        code = str(data.get("code") or "")
        if code != "10000":
            return False, f"refund code={code} msg={data.get('msg')!r}", data
        fund_change = str(data.get("fund_change") or "").lower() == "true"
        if not fund_change:
            return False, "refund not fund_changed", data
        return True, "refund accepted", {
            "channel": self.name,
            "refund_trade_no": str(data.get("trade_no") or ""),
            "refund_amount": round(float(data.get("refund_fee") or refund_yuan), 2),
            "out_request_no": out_request_no,
            "fund_change": fund_change,
        }

    def fetch_bill(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """拉取交易账单(对账用)。

        - Mock 模式:返回空 list(与基类一致)。
        - 真实模式:`POST alipay.data.dataservice.bill.downloadurl.query`
          → 拿 `download_url` → HTTP GET 下载 → 按 CSV 表头定位列解析。

        日期格式:`YYYY-MM-DD`。若 `start_date == end_date`,只拉当日账单。
        账单类型固定 `trade`(交易账单)。
        """
        if not self.is_real:
            return []
        if self._http is None:
            raise RuntimeError("alipay httpx client unavailable")

        # 支付宝账单 downloadurl 查询只支持单日
        biz: dict[str, str] = {
            "bill_type": "trade",
            "bill_date": start_date,
        }
        try:
            resp = self._gateway_call(
                "alipay.data.dataservice.bill.downloadurl.query", biz
            )
        except RuntimeError:
            return []
        data = self._biz(resp, "alipay.data.dataservice.bill.downloadurl.query")
        code = str(data.get("code") or "")
        if code != "10000":
            return []
        download_url = str(data.get("download_url") or "").strip()
        if not download_url:
            return []

        # 下载 CSV(不经过支付宝签名;download_url 已带签名参数)
        try:
            bill_resp = httpx.get(download_url, timeout=60.0, follow_redirects=True)
        except Exception:
            return []
        if bill_resp.status_code // 100 != 2:
            return []
        raw = bill_resp.content
        text = raw.decode("utf-8-sig", errors="replace")
        rows = _parse_trade_bill_csv(text)
        # 简单按日期过滤(账单一般已按日期切分,这里做兜底)
        if end_date and end_date != start_date:
            rows = [r for r in rows if (r.get("trade_time") or "")[:10] <= end_date]
        return rows

    # ─────────────────────────────────────────────────────────
    # 内部实现:mock 下单 / 真实回调
    # ─────────────────────────────────────────────────────────

    def _create_payment_mock(
        self,
        *,
        order_no: str,
        total_yuan_str: str,
        subject: str,
        plan: str,
        days: int,
        notify_url: str,
        return_url: str,
    ) -> dict[str, Any]:
        """Mock 阶段:签名字段与旧版完全一致(既有测试依赖)。"""
        sign_payload = {
            "out_trade_no": order_no,
            "total_amount": total_yuan_str,
            "plan": plan,
            "days": str(days),
            "notify_url": notify_url,
            "return_url": return_url,
        }
        sign = _mock_sign(self._sign_secret, sign_payload)
        action = self.gateway_url
        form_html = (
            f'<form method="post" action="{action}">'
            '<!-- MOCK: 沙箱 / 本地开发占位,生产下由 adapter 请求 openapi 后生成 -->'
            f'<input type="hidden" name="app_id" value="{self.app_id}"/>'
            f'<input type="hidden" name="method" value="alipay.trade.page.pay"/>'
            f'<input type="hidden" name="out_trade_no" value="{order_no}"/>'
            f'<input type="hidden" name="total_amount" value="{total_yuan_str}"/>'
            f'<input type="hidden" name="subject" value="{_html_escape(subject)}"/>'
            f'<input type="hidden" name="notify_url" value="{notify_url}"/>'
            f'<input type="hidden" name="return_url" value="{return_url}"/>'
            f'<input type="hidden" name="sign" value="{sign}"/>'
            '<button type="submit">去支付宝支付</button>'
            '</form>'
        )
        return {
            "channel": "alipay",
            "order_no": order_no,
            "amount": float(total_yuan_str),
            "pay_type": "form",
            "form_html": form_html,
            "gateway_url": action,
            "method": "alipay.trade.page.pay",
            "expires_in": 3600,
            "sandbox": self.sandbox,
        }

    def _verify_callback_real(
        self,
        body: dict[str, Any] | str,
    ) -> tuple[bool, dict[str, Any]]:
        """真实 OpenAPI 回调验签(form-urlencoded,签名在 body 中)。

        `body` 允许两种形态:
          - dict:调用方已把 form-urlencoded 解析成 dict(推荐);
          - str :原始 form-urlencoded body(便于 router 未来升级)。
        """
        if isinstance(body, str):
            body = dict(urllib.parse.parse_qsl(body))
        out_trade_no = str(body.get("out_trade_no") or "").strip()
        trade_no = str(body.get("trade_no") or "").strip()
        total_amount_raw = body.get("total_amount") or ""
        trade_status = str(body.get("trade_status") or "").strip()
        sign = str(body.get("sign") or "").strip()

        if not (out_trade_no and trade_no and sign):
            return False, {}
        # 只接受终态成功;WAIT_BUYER_PAY / TRADE_CLOSED / TRADE_REFUND 一律拒绝
        if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            return False, {}

        try:
            amount = round(float(total_amount_raw), 2)
        except (TypeError, ValueError):
            return False, {}
        if amount <= 0:
            return False, {}

        # 构造待签串:剔除 sign/sign_type 与空值
        verify_params: dict[str, Any] = {
            k: v for k, v in body.items()
            if k not in ("sign", "sign_type") and v not in (None, "")
        }
        sign_str = _build_sign_str(verify_params)

        pub_pem = self._load_public_key()
        if not pub_pem:
            return False, {}
        if not _rsa2_verify(sign, sign_str, pub_pem):
            return False, {}

        return True, {
            "out_trade_no": out_trade_no,
            "pay_trade_no": trade_no,
            "amount": amount,
            "trade_status": trade_status,
        }


# ──────────────────────────────────────────────────────────────
# 模块级辅助
# ──────────────────────────────────────────────────────────────

def _is_real_configured(env: dict[str, str]) -> bool:
    """判定是否走真实 OpenAPI。

    降级到 mock 的必要条件(**任一缺失即降级**):
      - `app_id` 缺失或仍是 `MOCK_ALIPAY_APP_ID`
      - 应用私钥读不到(路径缺失或内联 PEM 非 PEM)
      - 支付宝公钥读不到(路径缺失或内联 PEM 非 PEM)
    """
    if not env["app_id"] or env["app_id"] == MOCK_APP_ID:
        return False
    if not _pem_loadable(env.get("app_private_key_inline", ""),
                         env.get("app_private_key_path", "")):
        return False
    if not _pem_loadable(env.get("alipay_public_key_inline", ""),
                         env.get("alipay_public_key_path", "")):
        return False
    return True


def _pem_loadable(inline: str, path: str) -> bool:
    """判断密钥是否可读:内联 PEM 优先,否则读文件。"""
    if inline:
        text = inline
    else:
        text = ""
        try:
            with open(path, "rb") as f:
                text = f.read().decode("utf-8", errors="ignore")
        except Exception:
            return False
    if len(text) < 32:
        return False
    return "BEGIN" in text and "END" in text


def _read_pem(path: str) -> bytes:
    """安全读取 PEM 文件;不存在/读空/非 PEM 时返回 `b""`(不打印内容)。"""
    if not path:
        return b""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) < 32:
            return b""
        text = data.decode("utf-8", errors="ignore")
        if "BEGIN" not in text or "END" not in text:
            return b""
        return data
    except Exception:
        return b""


def _alipay_ts() -> str:
    """支付宝时间戳格式:`YYYY-MM-DD HH:mm:ss`(东八区)。"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime(_TS_FMT)


def _html_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_form(gateway_url: str, params: dict[str, Any]) -> str:
    """把 OpenAPI 参数渲染成 POST form(字段顺序按 key 升序,便于人工核对)。"""
    parts: list[str] = [
        "<form method=\"post\" action=\"" + _html_escape(gateway_url) + "\">",
    ]
    for k in sorted(params.keys()):
        v = params.get(k)
        if v is None:
            continue
        s = _html_escape(str(v))
        parts.append(
            "<input type=\"hidden\" name=\"" + _html_escape(k) + "\" value=\"" + s + "\"/>"
        )
    parts.append("<button type=\"submit\">去支付宝支付</button>")
    parts.append("</form>")
    return "".join(parts)


def _parse_trade_bill_csv(text: str) -> list[dict[str, Any]]:
    """把支付宝交易账单 CSV 解析成简化 dict 列表。

    支付宝账单格式(v2,trade):
      - 首行/若干行以 `#` 或 `备注:` 开头(跳过)
      - 表头行含"商户订单号"关键字
      - 数据行:逗号分隔
    通过**表头索引**定位需要的列,不同版本列顺序可能不同。
    """
    rows: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(text))

    header: list[str] = []
    for row in reader:
        if not row:
            continue
        head0 = (row[0] or "").strip()
        if head0.startswith("#") or head0.startswith("备注"):
            continue
        # 表头行:任一列出现"商户订单号"或"支付宝交易号"关键字
        row_join = "|".join(row)
        if "商户订单号" in row_join or "支付宝交易号" in row_join:
            header = [c.strip() for c in row]
            break

    if not header:
        return []

    def _col(*keywords: str) -> int:
        for i, h in enumerate(header):
            for kw in keywords:
                if kw in h:
                    return i
        return -1

    idx_time = _col("交易完成时间", "交易时间", "交易创建时间")
    idx_type = _col("交易类型")
    idx_out = _col("商户订单号")
    idx_amt = _col("买家实付", "用户实付", "实付金额")
    idx_tx = _col("支付宝交易号", "支付宝订单号")

    for row in reader:
        if not row:
            continue
        head0 = (row[0] or "").strip()
        if head0.startswith("#") or head0.startswith("备注"):
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

        amount_raw = _val(idx_amt).lstrip("￥¥-").replace(",", "")
        try:
            amount = round(abs(float(amount_raw)), 2) if amount_raw else 0.0
        except Exception:
            amount = 0.0

        type_raw = _val(idx_type)
        trade_type = "refund" if ("退" in type_raw or "-" in _val(idx_amt)) else "payment"

        rows.append({
            "out_trade_no": out_trade_no,
            "pay_trade_no": tx_id,
            "amount": amount,
            "trade_time": _val(idx_time),
            "trade_type": trade_type,
            "channel": "alipay",
        })
    return rows


# ──────────────────────────────────────────────────────────────
# 注册 & 导出
# ──────────────────────────────────────────────────────────────

register_adapter(AlipayAdapter())

__all__ = [
    "AlipayAdapter",
    "MOCK_SECRET",
    "MOCK_APP_ID",
    "ALIPAY_GATEWAY",
    "ALIPAY_GATEWAY_SANDBOX",
    "_is_real_configured",
    "_build_sign_str",
    "_rsa2_sign",
    "_rsa2_verify",
    "_mock_sign",  # 保留旧测试兼容:alipay._mock_sign
    "_verify_sig",
]
