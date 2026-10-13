"""C19 · 支付集成(支付宝 + 微信,沙箱 / mock)。

端点(挂载于 `/cloud`):
  POST /cloud/payment/create_order            → 创建订单,返回渠道支付参数
  POST /cloud/payment/callback/{channel}      → 支付回调(验签),激活订阅
  GET  /cloud/payment/order/{order_no}        → 查询订单状态

设计要点:
  - PaymentAdapter 抽象: `create_payment` / `verify_callback`
  - 密钥通过 env 注入,不落代码 / 仓库(沙箱 mock)。
  - 幂等: 同一 `order_no` 的重复回调不会重复激活订阅(检查 Order.status)。
  - 复用 C12(JWT)+ C13(`billing.activate_subscription`)。
"""
