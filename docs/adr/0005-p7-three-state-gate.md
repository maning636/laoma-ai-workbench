# ADR-0005: P7 密钥未配置关入口 + `unknown ≠ unavailable` 三态

- **状态**：已接受（补录）
- **日期**：2026-10-23
- **决策者**：马哥（P7=B 拍板）
- **证据分级**：【已验证】

---

## 背景

2026-10-23 收官时，云端 AI 对话入口与 TikHub 数据采集入口依赖平台密钥（`CLOUD_LLM_API_KEY` / `TIKHUB_API_KEY`）。密钥未配置时若直接暴露入口，用户点击必然失败，产生误投诉。

**证据**：
- `docs/handover/PROJECT-HANDOVER.md` §4「P7=B」行、§4.1 三态判定表
- `docs/handover/PROJECT-HANDOVER.md` §7.1 第 3 项：P7 中文「未配置」提示不在已发布包内
- `git show --stat 45e71e4`：前端隐藏云端 AI / TikHub 入口 + 后端回中文「未配置」

## 决策

**不给密钥 → 显式关掉依赖平台密钥的入口**：云端订阅与账号体系保留，只关掉依赖平台密钥的部分（云端 AI 对话入口、TikHub 采集入口的「补全」按钮）。**必须保持三态判定**：

| 服务端返回 | 前端判定 | 行为 |
|---|---|---|
| `api_key_configured === false` / `tikhub_enabled === false` | `unavailable` | **隐藏入口** |
| 网络抖动 / 超时 / 5xx / 字段不认识 | `unknown` | **保持现状**（不隐藏） |
| 明确配置好了 | `available` | 正常显示 |

**具体落地**：
- `45e71e4`：P7 平台密钥未配置时关掉云端 AI / TikHub 入口并给出明确中文提示
- 后端 `cloud_service/llm_proxy/` 与 `tikhub` 配置端点返回 `api_key_configured` / `tikhub_enabled` 布尔字段
- 前端 `prism_frontend/src/lib/` 内封装三态判定；TikHub key 用户自己在设置页填，配置卡保留只隐藏「补全」按钮

## 否掉了什么

| 方案 | 为什么否 |
|---|---|
| 「功能全关」（订阅体系也砍掉） | 判档模型另一半（12 项 flag、`max_accounts`、`max_platforms`）被砍，商业化能力退化 |
| 隐藏入口但后端仍返回 500 | 用户点击看到报错，误投诉 |
| 密钥未配置时静默降级到开源功能 | 用户不知道云端功能存在，商业化转化损失 |
| `unknown` 也隐藏 | **头号线上事故**：网络抖动导致功能突然消失，用户以为账号出问题 |

## 代价

**收益**：
- 未配置密钥时不产生误投诉
- 订阅与账号体系保留，商业化能力不退化
- 三态判定明确，`unknown` 与 `unavailable` 分离避免误隐藏

**代价**：
- 前端需要处理三态；`unknown` 态下 UI 需保持现状（不隐藏但可能失败）
- 后端需在多个端点返回配置状态字段
- 中文「未配置」提示需在 Pro 打包时进包（当前 1.1.5 未含，1.1.6 才解决）

**已知副作用**：
- `unknown ≠ unavailable` 是「自动隐藏入口」类改动的**头号线上事故来源**；接手方若要扩展这套逻辑，务必保留这条语义
- 1.1.5 发布包不含 P7 提示，用户仍会看到失败态

## 未来复审触发条件

- `CLOUD_LLM_API_KEY` / `TIKHUB_API_KEY` 正式配置后（P7=B 语义消失）
- 新增依赖平台密钥的能力时（需按三态范式扩展）
- 云端 AI 商业化上线（用户可自选模型供应商时）

## 参考

- `docs/handover/PROJECT-HANDOVER.md` §4「P7=B」、§4.1 三态判定表
- `docs/feature-gate-matrix.md` — flag 真源表
- Commit: `45e71e4`
