"""PaymentAdapter 抽象(C19)。

两个具体实现:
  - `AlipayAdapter`  (支付宝,电脑网站支付 + 当面付 / 沙箱 mock)
  - `WechatAdapter`  (微信 Native 扫码 / 沙箱 mock)

安全约定:
  - 商户密钥**不硬编码**,一律走 env(`CLOUD_ALIPAY_*` / `CLOUD_WECHAT_*`)。
  - 沙箱 / mock 阶段用 HMAC-SHA256 + base64 简单模拟验签,
    真实渠道密钥接入后,把 `_sign` / `_verify` 内的算法换成官方 RSA / MD5 即可,
    调用方无感。
  - `create_payment` 不调外部商户接口;构造返回给客户端的支付参数(表单 / 二维码)。
    真实的支付宝 `alipay.trade.page.pay` / 微信 `NativeOrder` 网络调用留在后续集成。

调用方契约:
  adapter = get_adapter("alipay" | "wechat")
  pay_params = adapter.create_payment(order_no=..., amount=..., plan=..., days=...)
  ok, fields = adapter.verify_callback(body: dict)  # fields 里含 out_trade_no / pay_trade_no
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from abc import ABC, abstractmethod
from typing import Any


# ──────────────────────────────────────────────────────────────
# 通用工具: 商户参数 + 简单 HMAC 签名(mock 沙箱用)
# ──────────────────────────────────────────────────────────────

def _get_str(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _mock_sign(secret: str, payload: dict[str, Any]) -> str:
    """HMAC-SHA256 mock 签名。

    - 参数按键名字典序拼接 `k=v&k=v`,值为 str;跳过空值;
    - 输出 base64 便于 URL/HTML 承载(真实支付宝/微信用十六进制 / 直接 str)。
    - 生产环境请替换为官方算法(支付宝 RSA2 / 微信 MD5 / SHA256-RSA2048)。
    """
    items = sorted((k, str(v)) for k, v in payload.items() if v not in (None, ""))
    raw = "&".join(f"{k}={v}" for k, v in items)
    digest = hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _verify_sig(secret: str, payload: dict[str, Any], sign: str) -> bool:
    """常量时间比较,防时序攻击。"""
    if not sign:
        return False
    return hmac.compare_digest(_mock_sign(secret, payload), sign)


# ──────────────────────────────────────────────────────────────
# 抽象
# ──────────────────────────────────────────────────────────────

class PaymentAdapter(ABC):
    """支付渠道适配基类。"""

    #: 渠道名(alipay / wechat);供 router 校验与注册使用
    name: str = ""

    @abstractmethod
    def create_payment(
        self,
        order_no: str,
        amount: float,
        plan: str,
        days: int,
        notify_url: str,
        return_url: str,
    ) -> dict[str, Any]:
        """生成下单支付参数(不真正调用商户接口)。

        实现约定:签名 payload 至少包含
          `out_trade_no / total_amount / plan / days / notify_url / return_url`
        这样回调方用同一算法即可复原签名;若生产下商户 API 有固定字段集,
        在 adapter 内部映射,调用方无感。

        返回结构(供前端渲染):
          - alipay: `{pay_type: 'form', form_html: '<form ...>...</form>'}`
          - wechat: `{pay_type: 'qrcode', code_url: 'weixin://wxpay/...'}`
        """
        ...

    @abstractmethod
    def verify_callback(self, body: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """验签 + 解析回调。

        返回 `(ok, fields)`;`ok=False` 时字段可能被清空;
        `fields` 里至少包含:
          - `out_trade_no` : 商户订单号(对应 Order.order_no)
          - `pay_trade_no` : 渠道交易号(支付宝 trade_no / 微信 transaction_id)
          - `amount`       : 支付金额(元)
        """
        ...

    # ─────────────────────────────────────────────────────────
    # 退款 / 对账(mock 阶段;真实环境替换为商户接口)
    # ─────────────────────────────────────────────────────────

    def refund(
        self,
        *,
        order_no: str,
        pay_trade_no: str,
        amount: float,
        order_amount: float | None = None,
        reason: str = "",
    ) -> tuple[bool, str, dict[str, Any]]:
        """发起退款。默认实现为 mock:直接成功,回显一份 refund 单据。

        返回值:
          - `ok`            : 是否受理成功
          - `message`       : 简短描述(成功/失败原因)
          - `fields`        : 平台返回的补充字段(如 `refund_trade_no`)

        参数说明:
          - `amount`       : 本次退款金额(元)
          - `order_amount` : **原订单金额(元)**,可选;真实微信支付 APIv3
                             的 `amount.total` 需要原订单金额,部分退款时
                             微信会校验 `total >= refund`,与本次退款金额
                             不同时必须显式传入。缺省 `None` 时回退到
                             `amount`(向后兼容旧的 3 参数调用),保持
                             支付宝 adapter 与既有 mock 行为不变。
          - `reason`       : 可选退款原因文本,子类按需使用。

        真实环境应在子类覆盖本方法,调用支付宝 `alipay.trade.refund`
        或微信 v3 `POST /v3/refund/domestic/refunds`。
        """
        return True, "mock refund accepted", {
            "channel": self.name,
            "refund_trade_no": f"REF_{self.name.upper()}_{pay_trade_no}",
            "refund_amount": round(float(amount), 2),
        }

    def fetch_bill(self, *, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """拉取支付平台账单(对账用,mock)。

        返回形如真实"平台账单"的 list,每条含:
          - `out_trade_no` : 商户订单号
          - `pay_trade_no` : 渠道交易号
          - `amount`       : 支付金额(元)
          - `trade_time`   : 交易时间 ISO 字符串
          - `trade_type`   : "payment" | "refund"

        真实环境应调用支付宝"商户账户账单"下载 / 微信 v3 交易账单接口。
        """
        return []


# ──────────────────────────────────────────────────────────────
# 注册表
# ──────────────────────────────────────────────────────────────

_ADMAP: dict[str, PaymentAdapter] = {}


def register_adapter(adapter: PaymentAdapter) -> None:
    _ADMAP[adapter.name] = adapter


def get_adapter(name: str) -> PaymentAdapter | None:
    return _ADMAP.get(name)


__all__ = [
    "PaymentAdapter",
    "register_adapter",
    "get_adapter",
    "_mock_sign",
    "_verify_sig",
]
