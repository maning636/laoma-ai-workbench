# ADR-0011: 模型供应商注册表 + 通道软关联不迁移

- **状态**：已接受（补录）
- **日期**：2026-10-24
- **决策者**：工作组
- **证据分级**：【已验证】

---

## 背景

2026-10-24 收官冲刺中，AI 模型配置散落在多个地方：

- `cloud_service/llm_proxy/` 中硬编码的 OpenAI/Anthropic 配置
- `prism_backend/fastapi_app/` 中的 `ai_model_configs` 表（每个用户自己的 key）
- 前端 `settings` 页里手写的模型下拉框

问题：

1. **通道与模型强耦合**：换供应商需改代码
2. **无统一注册表**：模型列表散落，前端下拉框与后端模型枚举不同步
3. **OpenRouter 风格前端不可复用**：用户无法自选供应商

**证据**：
- `git show --stat 082abed`：feat(providers): 模型供应商注册表——CRUD/测试连接/拉模型/应用到通道（后端）
- `git show --stat 0a2ddd6`：feat(providers): 供应商管理页——添加/测试/拉模型/应用通道（OpenRouter 风格前端）
- `git show --stat 6135391`：feat(links): L3-1 孤岛收编——ideas吃回收/campaigns接向导/providers导入通道

## 决策

**引入模型供应商注册表 + 通道软关联**：

- 后端新增 `providers` 表（CRUD、测试连接、拉模型列表、应用到通道）
- 前端设置页改为 OpenRouter 风格：用户添加供应商 → 测试连接 → 拉模型 → 选择应用到某个 AI 通道
- **通道与供应商软关联**：不强制迁移旧配置，`ai_model_configs` 表保留，新数据走 providers 表

**具体落地**：
- `082abed`：feat(providers): 模型供应商注册表（后端 CRUD/测试连接/拉模型/应用到通道）
- `0a2ddd6`：feat(providers): 供应商管理页（OpenRouter 风格前端）
- `f5aa955`：fix(providers): 前端字段契约对齐 + null 防御 + 编辑不篡改 enabled
- `6135391`：feat(links): L3-1 孤岛收编——providers 导入通道
- `f13dba9`：fix(links): L3 评审修复——apply-to 请求体携带 `model_name` + `from-performance` 503 语义

**软关联原则**：
- 新增 `provider_id` 软归因列（不建硬 FK，参考 ADR-0008）
- 旧 `ai_model_configs` 数据保留，前端读时优先用 providers 表，缺失时 fallback 到旧表

## 否掉了什么

| 方案 | 为什么否 |
|---|---|
| 硬迁移所有配置到 providers 表 | 破坏向后兼容，需迁移用户历史配置 |
| 保留现有分散配置 + 加一层适配 | 复杂度上升，且配置源多，用户困惑 |
| 用单一供应商（OpenAI only） | 用户需要自选供应商；且 OpenAI 在国内不可用 |
| 完全按通道独立配置（每个通道一个供应商） | 数据冗余，且用户管理成本高 |
| 强制迁移 + 清掉旧表 | 老用户数据丢失，商业风险 |

## 代价

**收益**：
- 供应商添加/测试/拉模型 全流程可复用
- 前端设置页与后端模型列表自动同步
- 用户可自选供应商，商业化灵活度高

**代价**：
- 双表并存（providers + ai_model_configs），应用层需处理 fallback
- 旧数据无 `provider_id` 归因，需按业务逻辑回查
- 前端字段契约需严格对齐（`f5aa955` 修过 null 防御与 enabled 篡改）

**已知副作用**：
- 部分旧数据（迁移前产生的）无归因列值，用户切换供应商时需手动重配
- 通道与供应商的软关联关系需在审计时特别注意（无硬 FK 约束）

## 未来复审触发条件

- 用户配置复杂度成为瓶颈（需引入预设供应商模板）
- 引入新的供应商协议（如 Anthropic 官方 API、DeepSeek 官方 API）
- 双表并存超过 3 个版本迭代，考虑收编到单一表

## 参考

- `git show --stat 082abed` `0a2ddd6` `f5aa955` `6135391` `f13dba9`
- ADR-0008（软关联归因列范式）
