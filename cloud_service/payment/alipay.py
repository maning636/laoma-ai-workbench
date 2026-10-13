"""支付宝适配(沙箱 / mock,C19)。

设计参考 `docs/dev-reports/2026-10-13-saas-c-class-design.md` §5.2:
  - 电脑网站支付(`alipay.trade.page.pay`)→ 返回 `<form>` HTML,前端跳转
  - 当面付 / 扫码 → 返回二维码 URL(mock,本迭代未生成实际 QR 图片)

安全:
  - 商户参数 `CLOUD_ALIPAY_APP_ID` / `CLOUD_ALIPAY_PRIVATE_KEY` /
    `CLOUD_ALIPAY_PUBLIC_KEY`(沙箱)一律 env 注入,不硬编码。
  - 未配置真实参数时,fallback 到 mock secret(`__MOCK__ALIPAY_SECRET__`),
    仅用于本地开发 / 单测,不用于生产。

真实渠道对接(后续):
  1. `create_payment` → 组装 `alipay.trade.page.pay` 请求 → 用商户私钥 RSA2 签名
     → 请求 openapi.alipay.com → 拿到 form_html 或 qr_code 返回前端。
  2. `verify_callback` → 用支付宝公钥 RSA2 验签 → 解析 `trade_no` /
     `out_trade_no` / `total_amount` / `trade_status`。
"""

from __future__ import annotations

from typing import Any

from .adapter import (
    PaymentAdapter,
    _get_str,
    _mock_sign,
    _verify_sig,
    register_adapter,
)

MOCK_SECRET = "__MOCK__ALIPAY_SECRET__"


class AlipayAdapter(PaymentAdapter):
    """支付宝适配(mock / 沙箱)。"""

    name = "alipay"

    def __init__(self) -> None:
        # 真实参数: CLOUD_ALIPAY_APP_ID / CLOUD_ALIPAY_PRIVATE_KEY / CLOUD_ALIPAY_PUBLIC_KEY
        # 签名密钥(回调验签): CLOUD_ALIPAY_APP_PUBLIC_KEY 或 CLOUD_ALIPAY_SECRET
        # 未配置时全部走 mock,保证本地/测试可用。
        self.app_id = _get_str("CLOUD_ALIPAY_APP_ID") or "MOCK_ALIPAY_APP_ID"
        self.sandbox = _get_str("CLOUD_ALIPAY_SANDBOX", "1").lower() in {"1", "true", "yes"}
        self._sign_secret = (
            _get_str("CLOUD_ALIPAY_APP_PUBLIC_KEY")
            or _get_str("CLOUD_ALIPAY_SECRET")
            or MOCK_SECRET
        )

    def create_payment(
        self,
        order_no: str,
        amount: float,
        plan: str,
        days: int,
        notify_url: str,
        return_url: str,
    ) -> dict[str, Any]:
        """构造电脑网站支付(<form> HTML)或扫码 URL。

        签名 payload 只包含业务字段(便于沙箱 / mock 复现,与 verify_callback 对齐):
          `out_trade_no / total_amount / plan / days / notify_url / return_url`
        """
        total_yuan = round(float(amount), 2)
        subject = f"Prism-Fusion {plan} {days}d"

        sign_payload = {
            "out_trade_no": order_no,
            "total_amount": f"{total_yuan:.2f}",
            "plan": plan,
            "days": str(days),
            "notify_url": notify_url,
            "return_url": return_url,
        }
        sign = _mock_sign(self._sign_secret, sign_payload)

        form_html = (
            '<form method="post" action="https://openapi-sandbox.dl.alipaydev.com/gateway.do">'
            '<!-- MOCK: 沙箱 / 本地开发占位,生产下由 adapter 请求 openapi 后生成 -->'
            f'<input type="hidden" name="app_id" value="{self.app_id}"/>'
            f'<input type="hidden" name="method" value="alipay.trade.page.pay"/>'
            f'<input type="hidden" name="out_trade_no" value="{order_no}"/>'
            f'<input type="hidden" name="total_amount" value="{total_yuan:.2f}"/>'
            f'<input type="hidden" name="subject" value="{subject}"/>'
            f'<input type="hidden" name="notify_url" value="{notify_url}"/>'
            f'<input type="hidden" name="return_url" value="{return_url}"/>'
            f'<input type="hidden" name="sign" value="{sign}"/>'
            '<button type="submit">去支付宝支付</button>'
            '</form>'
        )

        return {
            "channel": "alipay",
            "order_no": order_no,
            "amount": total_yuan,
            "pay_type": "form",
            "form_html": form_html,
            "expires_in": 3600,
            "sandbox": self.sandbox,
        }

    def verify_callback(self, body: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """验签支付宝回调。

        期望 body 字段:
          - out_trade_no : 商户订单号(= Order.order_no)
          - trade_no     : 支付宝交易号
          - total_amount : 支付金额(元)
          - plan         : 订阅套餐
          - days         : 订阅天数
          - notify_url   : 回调地址
          - return_url   : 支付完成后跳转地址
          - trade_status : TRADE_SUCCESS / WAIT_BUYER_PAY / TRADE_CLOSED
          - sign         : 商户签名

        签名 payload 只取业务字段(与 create_payment 对齐):
          `out_trade_no / total_amount / plan / days / notify_url / return_url`
        """
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


register_adapter(AlipayAdapter())


__all__ = ["AlipayAdapter", "MOCK_SECRET"]
