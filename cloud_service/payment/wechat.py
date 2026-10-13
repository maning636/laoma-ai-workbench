"""微信支付适配(沙箱 / mock,C19)。

设计参考 `docs/dev-reports/2026-10-13-saas-c-class-design.md` §5.2:
  - Native(扫码) → 返回 `code_url`,前端渲染为二维码图片
  - JSAPI(Electron 内嵌)→ 返回预支付 id + 客户端参数

安全:
  - 商户参数 `CLOUD_WECHAT_APP_ID` / `CLOUD_WECHAT_MCHID` /
    `CLOUD_WECHAT_API_SECRET` / `CLOUD_WECHAT_API_V3_KEY` 一律 env 注入。
  - 未配置真实参数时,fallback 到 mock secret,仅用于本地开发 / 单测。

真实渠道对接(后续):
  1. `create_payment` → 组装 `POST /v3/pay/transactions/native` → 拿 `code_url`。
  2. `verify_callback` → 从 `Wechatpay-*` header 提取签名 →
     用商户证书 APIv3 密钥做 AES-256-GCM 解密 resource → 得到 `transaction_id` /
     `out_trade_no` / `amount` / `trade_state`。
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

MOCK_SECRET = "__MOCK__WECHAT_SECRET__"


class WechatAdapter(PaymentAdapter):
    """微信支付适配(mock / 沙箱)。"""

    name = "wechat"

    def __init__(self) -> None:
        self.app_id = _get_str("CLOUD_WECHAT_APP_ID") or "MOCK_WECHAT_APP_ID"
        self.mch_id = _get_str("CLOUD_WECHAT_MCHID") or "MOCK_MCH_ID"
        self.sandbox = _get_str("CLOUD_WECHAT_SANDBOX", "1").lower() in {"1", "true", "yes"}
        # 回调验签密钥(真实环境是 APIv3 密钥;mock 阶段是简单 secret)
        self._sign_secret = (
            _get_str("CLOUD_WECHAT_API_V3_KEY")
            or _get_str("CLOUD_WECHAT_API_SECRET")
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
        """构造 Native 扫码支付参数。

        签名 payload 只包含业务字段(便于沙箱 / mock 复现,与 verify_callback 对齐):
          `out_trade_no / total_fen / plan / days / notify_url / return_url`
        """
        total_yuan = round(float(amount), 2)
        # 微信 v3 接口要求 total 单位是"分",这里在返回体里同时给元 / 分,方便前端
        total_fen = int(round(total_yuan * 100))
        description = f"Prism-Fusion {plan} {days}d"

        sign_payload = {
            "out_trade_no": order_no,
            "total_fen": str(total_fen),
            "plan": plan,
            "days": str(days),
            "notify_url": notify_url,
            "return_url": return_url,
        }
        sign = _mock_sign(self._sign_secret, sign_payload)

        # mock: 构造形似真实 `code_url` 的字符串,前端拿去生成 QR 即可;
        # 真实场景下 URL 由微信 v3 接口返回,不能拼出来。
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

    def verify_callback(self, body: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """验签微信支付回调。

        期望 body 字段(已解密的 resource 结构;真实环境从 header 提取签名):
          - out_trade_no     : 商户订单号(= Order.order_no)
          - transaction_id   : 微信支付交易号
          - total_fen        : 支付金额(分)
          - plan             : 订阅套餐
          - days             : 订阅天数
          - notify_url       : 回调地址
          - return_url       : 支付完成后跳转地址
          - trade_state      : SUCCESS / NOTPAY / CLOSED / REFUND
          - sign             : 商户签名(mock 简化)

        签名 payload 只取业务字段(与 create_payment 对齐):
          `out_trade_no / total_fen / plan / days / notify_url / return_url`
        """
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


register_adapter(WechatAdapter())


__all__ = ["WechatAdapter", "MOCK_SECRET"]
