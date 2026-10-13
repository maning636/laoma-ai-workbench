"""C19 · 支付集成(支付宝 + 微信,沙箱 / mock)。

端点(挂载于 `/cloud`):
  POST /cloud/payment/create_order            → 创建订单,返回渠道支付参数
  POST /cloud/payment/callback/{channel}      → 支付回调(验签),激活订阅
  GET  /cloud/payment/order/{order_no}        → 查询订单状态
  POST /cloud/payment/refund                  → 管理员发起退款(JWT + X-Admin-Token)

模块:
  - `models.py`          : Order 表;状态机 created / paid / refunded / closed
  - `adapter.py`         : PaymentAdapter 抽象 + 退款 / 账单 mock 默认实现
  - `alipay.py` / `wechat.py` : 具体渠道适配(mock / 沙箱)
  - `router.py`          : 4 个 HTTP 端点
  - `reconciliation.py`  : 日终对账函数(本地 paid vs 平台账单 mock)
  - `scheduler.py`       : 订单超时关闭(close_expired_orders + asyncio task)

设计要点:
  - PaymentAdapter 抽象: `create_payment` / `verify_callback` / `refund` / `fetch_bill`
  - 密钥通过 env 注入,不落代码 / 仓库(沙箱 mock)。
  - 幂等: 同一 `order_no` 的重复回调不会重复激活订阅(检查 Order.status);
    已退款订单的迟到回调会返回 ok=False 且不激活。
  - 退款:admin token + JWT 双重门禁,复用 C12 `get_current_user` 与
    `llm_proxy` 的 `CLOUD_ADMIN_TOKEN` 模式;订阅撤销/缩短暂不主动做(见 router 注释)。
  - 超时:纯函数 `close_expired_orders(db, hours=24)`,可选挂 `close_expired_orders_task`。
"""

from . import models, schemas, adapter, alipay, wechat  # noqa: F401
from . import router, reconciliation, scheduler  # noqa: F401

__all__ = [
    "models",
    "schemas",
    "adapter",
    "alipay",
    "wechat",
    "router",
    "reconciliation",
    "scheduler",
]
