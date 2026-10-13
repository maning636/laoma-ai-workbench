"""C13 · 订阅 + 用量计量 + License 校验。

端点(挂载于 `/cloud`):
  GET  /cloud/subscription         → 当前订阅状态 + 用量
  POST /cloud/usage/consume        → 消耗额度(超额度 402)
  POST /cloud/license/verify       → 客户端心跳校验
  POST /cloud/subscription/activate→ 模拟激活 pro(供 C19 支付集成前使用)

依赖:复用 C12 的 `db` / `auth.security` / `auth.router.get_current_user`。
"""
