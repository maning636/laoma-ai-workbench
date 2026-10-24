# ADR 索引（Architecture Decision Records）

> 本仓库的关键架构决策记录。所有 ADR 均为**补录**（原始决策发生在开发期，未同步写入 ADR），状态标为「已接受（补录）」。

## 索引表

| 编号 | 标题 | 状态 | 日期 | 关联 commit |
|:---:|---|:---:|:---:|---|
| [ADR-0001](./0001-single-client-edition-model.md) | 商业分层改单一客户端 + 注册码∩订阅判档 | 已接受（补录） | 2026-10-23 | `e6c1925` `d264d4f` |
| [ADR-0002](./0002-remove-platform-payment.md) | 删除平台支付，改个人微信 + 人工发注册码 | 已接受（补录） | 2026-10-23 | `889b3ec` |
| [ADR-0003](./0003-generic-auto-update-channel.md) | 自动更新保留 generic 自建通道，不切 GitHub provider | 已接受（补录） | 2026-10-23 | P3=A |
| [ADR-0004](./0004-cloud-prompts-out-of-oss-tree.md) | 云端 prompt 正文移出开源树 | 已接受（补录） | 2026-10-22 | `7dd9237` |
| [ADR-0005](./0005-p7-three-state-gate.md) | P7 密钥未配置关入口 + `unknown ≠ unavailable` 三态 | 已接受（补录） | 2026-10-23 | `45e71e4` |
| [ADR-0006](./0006-douyin-http-login-banned-in-prod.md) | 抖音登录禁 HTTP 逆向，走浏览器 | 已接受（补录） | 2026-10-13 | `prism_backend/AGENTS.md` |
| [ADR-0007](./0007-ci-hard-gate-migration.md) | CI 从软门全改硬门 | 已接受（补录） | 2026-10-23 | `0df4683` `d1fee57` `206a202` `1f90fba` |
| [ADR-0008](./0008-soft-attribution-columns.md) | 数据层软关联归因列，不做强制迁移 | 已接受（补录） | 2026-10-22 | `e263a9d` |
| [ADR-0009](./0009-ci-release-fullchain.md) | CI 全链路发版 + 体积下限守卫 + SKIP_OBFUSCATE 口径 | 已接受（补录） | 2026-10-24 | `b98c95d` `538159c` `f5e8bd5` |
| [ADR-0010](./0010-conservative-size-reduction.md) | 包体瘦身保守原则：patchright/selenium 不排除 | 已接受（补录） | 2026-10-24 | `da46f91` |
| [ADR-0011](./0011-provider-registry-soft-link.md) | 模型供应商注册表 + 通道软关联不迁移 | 已接受（补录） | 2026-10-24 | `082abed` `0a2ddd6` |
| [ADR-0012](./0012-frontend-timeout-envelope.md) | 前端请求层统一 30s 超时 + envelope 兼容层 | 已接受（补录） | 2026-10-24 | `16ca1d6` `2c547c7` |

## 使用约定

1. **新增 ADR**：使用 `docs/engineering/NEW-PROJECT-KIT/templates/ADR-TEMPLATE.md` 模板
2. **状态标记**：提议中 → 已接受 → 已废弃 / 已替代（by ADR-xxx）
3. **补录**：历史决策追溯记录时，状态标为「已接受（补录）」，保留原始日期
4. **证据分级**：【已验证】/ 【已确认】/ 【推测】三档，见 `docs/handover/PROJECT-HANDOVER.md` §0.4

## 关联文档

- `docs/handover/PROJECT-HANDOVER.md` §4 关键技术决策台账（本 ADR 体系的原始来源）
- `docs/engineering/ENGINEERING-PLAYBOOK.md` — 工程体系总纲
- `docs/feature-inventory-and-oss-boundary.md` — 功能盘点与开源边界
