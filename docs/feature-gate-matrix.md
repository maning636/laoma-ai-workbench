# Feature Gate 矩阵（拍板落地版）

> 生成时间：2026-10-22 ｜ 数据源：`docs/feature-inventory-and-oss-boundary.md` §1/§2「你选」列 + 拍板结论 D1–D10
> 机器可读版本：`docs/feature-gate-matrix.json`（与本文件同源生成，改一处两处一起变）
> 定位：**自媒体矩阵发布 + AI 生图/生视频内容生产平台**

---

## 0. 判定模型（D1 = C 双轨）

```
allowed(功能) = 注册码授权条目（本地校验） ∩ 订阅配额（云端）
```

| 规则 | 结论 | 依据 |
|---|---|---|
| 判定公式 | 注册码给**白名单**（能不能用）∩ 云端订阅给**额度**（能用多少） | D1 |
| 设备绑定 | **默认不绑**（一码通用）；若启用绑定则允许自助解绑 | D2 |
| 有效期 | **固定期限**（年卡 / 季卡 / 月卡），license 必带到期时间 | D3 |
| 到期语义 | 已产生数据**能看，不能新增** | D4 |
| 平台数 | **不承诺具体数量**，只写「多平台」 | D5 |
| 云端 prompt | **移出开源树**，只在 Pro 包提供（新增 flag `cloud_prompt`） | D6 |
| 数据回收 | **不收进 Pro**，社区版即可用（flag `data_recovery` Community 已改 true） | D7 |
| 平台细粒度 API | 不给前端入口 | D8 |
| 版权署名 | 保持「老马AI工作台（Prism-Fusion）贡献者」 | D9 |
| README 开放级别 | 按现状不调整 | D10 |

## 1. Flag 真源表（10 个既有 + 2 个新增）

| flag | 类型 | Community | Pro | 注册码条目 | 状态 | 说明 |
|---|---|---|---|---|---|---|
| `max_accounts` | numeric | `3` | `-1` | `core` | 已实现 | 账号数配额，云端订阅维度 |
| `max_platforms` | numeric | `3` | `8` | `multi_platform` | 已实现 | D5：对外不承诺具体数量（README/前端文案统一写「多平台」）；此值为内部配额，随版本扩充 |
| `ai_mode` | mode | `local_key` | `cloud` | `ai_cloud` | 已实现 | 云端模式需 ai_cloud 条目 |
| `image_gen` | mode | `local_key` | `cloud` | `ai_cloud` | 已实现 | 云端生图需 ai_cloud 条目 |
| `agent_quota` | numeric | `0` | `2` | `agent` | 已实现 | 0 = 禁用 |
| `data_recovery` | bool | `True` | `True` | `core` | 已实现 | D7：不收进 Pro，社区版即可用（已同步改云端 / 客户端 / 前端三处） |
| `persona` | bool | `False` | `True` | `persona` | 已实现 |  |
| `proxy_management` | bool | `False` | `True` | `persona` | 已实现 |  |
| `stream_chat` | bool | `False` | `True` | `agent` | 已实现 |  |
| `team_members` | numeric | `1` | `1` | `core` | 已实现 |  |
| `cloud_prompt` | bool | `False` | `True` | `ai_cloud` | 新增待实现 | D6：云端 prompt 资产，随 prompts.py 移出开源树（B2） |
| `campaign_orchestration` | bool | `False` | `True` | `campaign` | 新增待实现 | 新增：营销活动与任务包编排（注册码授权） |

> ✅ **D7 已落代码**：`data_recovery` 的 Community 值已在云端实现 / 客户端实现 / 前端默认三处同步为 `true`；D5 已把 Pro 平台数对外文案从「8 平台」改为「多平台」，内部配额值不变。

> 🔍 **代码交叉校验**（生成时自动回读代码，缺 flag 或口径不符直接报错）：
>
> - `cloud_service/billing/feature_gate.py`（云端实现）：10 个 flag 全部对齐
> - `prism_backend/fastapi_app/api/billing_client.py`（客户端实现）：10 个 flag 全部对齐
> - `prism_frontend/src/lib/plan-flags.ts`（前端默认）：10 个 flag 全部对齐

## 2. 注册码条目（可组合的授权包）

| 条目键 | 名称 | 解锁 | 说明 |
|---|---|---|---|
| `core` | 基础包 | `max_accounts`、`max_platforms`、`team_members` | 全部开源功能（默认包含） |
| `ai_cloud` | 云端 AI | `ai_mode`、`image_gen`、`cloud_prompt` | 云端 prompt / 云端生图 / 云端模型（自配 key 走本地模式不需此条目） |
| `agent` | Agent 配额 | `agent_quota`、`stream_chat` | Hermes Agent 配额与流式对话 |
| `persona` | Persona 与代理 | `persona`、`proxy_management` | Persona 指纹 / 代理管理 / 代理网关 |
| `campaign` | 营销活动编排 | `campaign_orchestration` | 营销活动 → 任务包 → 发布任务整链 |
| `multi_platform` | 多平台发布 | `max_platforms` | 超出社区版 3 平台的发布能力（数量随版本扩充，不写死） |

## 3. 功能清单 55 项（按「你选」列）

| # | 功能 | 路由 | 我的选择 | 当前建议 |
|---|---|---|---|---|
| 1 | 仪表盘 | `/` | **开源** | 已接后端 |
| 2 | 快速开始 | `/guide` | **开源** | 已接后端（部分演示流程） |
| 3 | 账号管理 | `/account` | **开源** | 已接后端 |
| 4 | 素材管理 | `/materials` | **开源** | 已接后端 |
| 5 | 代理管理 | `/ip-pool` | **注册码** | 已接后端 |
| 6 | 代理网关 | `/persona-proxy` | **注册码** | 已接后端 |
| 7 | Persona | `/persona` | **注册码** | 占位/重定向 |
| 8 | 选题库 | `/ideas` | **开源** | 已接后端 |
| 9 | 趋势热榜 | `/trends` | **开源** | 已接后端（热榜数据源为占位） |
| 10 | 内容拆解 | `/breakdown` | **开源** | 已接后端 |
| 11 | 账号画像 | `/profile` | **开源** | 已接后端 |
| 12 | 内容库 | `/easel-content` | **开源** | 已接后端 |
| 13 | 收件箱 | `/easel-inbox` | **开源** | 已接后端 |
| 14 | 创作工作台 | `/easel-workbench` | **开源** | 已接后端（含占位文案） |
| 15 | 创作工坊 | `/workshop` | **开源** | 已接后端 |
| 16 | CMS | `/cms` | **开源** | 已接后端 |
| 17 | AI 生图 | `/fusion/image-studio` | **注册码** | 已接后端 |
| 18 | 视频流水线 | `/video-pipeline` | **注册码** | 已接后端（模板库依赖外部目录 `E:\FDE\fde-landing-delivery`，本机缺失） |
| 19 | 图片编辑器 | `/tools/image-editor` | **开源** | 纯前端 |
| 20 | 产物中心 | `/artifacts` | **开源** | 已接后端（本轮新建） |
| 21 | 矩阵发布 | `/publish/matrix` | **开源** | 已接后端 |
| 22 | 发布中心 | `/publish` | **开源** | 兼容跳转页 |
| 23 | 发布任务 | `/tasks/publish` | **开源** | 已接后端 |
| 24 | 分发记录 | `/tasks/distribution` | **开源** | 已接后端 |
| 25 | 营销活动 | `/campaigns` | **注册码** | 已接后端（本轮打通） |
| 26 | 排期日历 | `/calendar` | **开源** | 已接后端 |
| 27 | 审核队列 | `/review` | **开源** | 已接后端（本轮新建） |
| 28 | 任务管理 | `/tasks` | **开源** | 已接后端 |
| 29 | 数据中心 | `/analytics` | **开源** | 已接后端 |
| 30 | 趋势分析 | `/analytics/trends` | **开源** | 兼容跳转页 |
| 31 | 视频数据（父级） | `/analytics/videos` | **开源** | 父级入口 |
| 32 | 抖音视频数据 | `/analytics/videos/douyin` | **开源** | 已接后端 |
| 33 | B 站视频数据 | `/analytics/videos/bilibili` | **开源** | 已接后端 |
| 34 | 快手视频数据 | `/analytics/videos/kuaishou` | **开源** | 已接后端 |
| 35 | 小红书视频数据 | `/analytics/videos/xiaohongshu` | **开源** | 已接后端 |
| 36 | 视频号视频数据 | `/analytics/videos/channels` | **开源** | 已接后端 |
| 37 | TikTok 视频数据 | `/analytics/videos/tiktok` | **开源** | 已接后端 |
| 38 | YouTube 视频数据 | `/analytics/videos/youtube` | **开源** | 已接后端 |
| 39 | Hermes Agent | `/ai-agent` | **注册码** | 已接后端 |
| 40 | Agent 控制台 | `/ai-agent` | **注册码** | 已接后端 |
| 41 | 提示词配置 | `/ai-agent/prompts` | **注册码** | 已接后端 |
| 42 | 运行设置 | `/ai-agent/settings` | **注册码** | 已接后端 |
| 43 | HermesChat | `/hermes-chat` | **注册码** | 已接后端 |
| 44 | AI 对话 | `/chat` | **开源** | 已接后端 |
| 45 | 技能库 | `/skills` | **开源** | 已接后端 |
| 46 | 融合中心 | `/fusion` | **开源** | 已接后端 |
| 47 | 风格库 | `/fusion/styles` | **开源** | 已接后端 |
| 48 | 内容审查 | `/fusion/moderation` | **开源** | 已接后端 |
| 49 | 融合分析 | `/fusion/analytics` | **开源** | 已接后端 |
| 50 | 融合配置 | `/fusion/config` | **开源** | 已接后端 |
| 51 | 模型市场 | `/fusion/model-market` | **注册码** | 已接后端 |
| 52 | 供应商配置 | `/fusion/providers` | **注册码** | 已接后端 |
| 53 | 工具中心 | `/tools` | **开源** | 已接后端 |
| 54 | 演示控制台 | `/dashboard-demo` | **开源** | 演示 |
| 55 | 系统设置 | `/settings` | **注册码** | 已接后端 |

## 4. 无入口能力域 54 项（按「你选」列）

| # | 能力域 | 组 | 操作 | 我的选择 | 当前建议 |
|---|---|---|---|---|---|
| 1 | `fusion` | 25 | 31 | **做入口但注册码** | 部分注册码 |
| 2 | `system` | 24 | 24 | **不做入口** | 不做入口（Pro 内部） |
| 3 | `accounts` | 18 | 19 | **不做入口** | 不做入口 |
| 4 | `platforms` | 16 | 16 | **不做入口** | 不做入口（已被账号页封装） |
| 5 | `agent` | 15 | 17 | **做入口但注册码** | 注册码 |
| 6 | `tasks` | 13 | 14 | **做入口但注册码** | 注册码 |
| 7 | `tikhub` | 12 | 12 | **做入口但注册码** | 注册码（外部付费 API） |
| 8 | `files` | 11 | 13 | **做入口且开源** | 开源 |
| 9 | `ai` | 11 | 11 | **做入口但注册码** | 注册码 |
| 10 | `recovery` | 10 | 10 | **做入口且开源** | 注册码 |
| 11 | `ip-pool` | 10 | 10 | **做入口但注册码** | 注册码 |
| 12 | `receipts` | 10 | 11 | **做入口且开源** | 开源 |
| 13 | `matrix` | 9 | 10 | **做入口且开源** | 开源 |
| 14 | `health` | 8 | 8 | **不做入口** | 不做入口 |
| 15 | `webhooks` | 7 | 10 | **做入口且开源** | 开源 |
| 16 | `analytics` | 6 | 6 | **做入口且开源** | 开源 |
| 17 | `video-pipeline` | 6 | 6 | **做入口但注册码** | 注册码 |
| 18 | `review` | 6 | 6 | **做入口且开源** | 开源（并入 /review） |
| 19 | `dedup` | 6 | 6 | **做入口且开源** | 开源 |
| 20 | `insights` | 5 | 5 | **做入口且开源** | 开源 |
| 21 | `platform-fields` | 5 | 5 | **不做入口** | 不做入口 |
| 22 | `selectors` | 5 | 5 | **不做入口** | 不做入口 |
| 23 | `ai-prompts` | 4 | 5 | **做入口但注册码** | 注册码（云端 prompt 不开源） |
| 24 | `dashboard` | 4 | 4 | **做入口且开源** | 开源 |
| 25 | `concurrency` | 4 | 5 | **不做入口** | 不做入口 |
| 26 | `task-state` | 4 | 6 | **不做入口** | 不做入口 |
| 27 | `content-variants` | 4 | 6 | **做入口且开源** | 开源（并入 /review） |
| 28 | `matrix-groups` | 4 | 5 | **做入口且开源** | 开源 |
| 29 | `campaigns` | 3 | 4 | **做入口但注册码** | 注册码 |
| 30 | `auth` | 3 | 3 | **做入口且开源** | 开源 |
| 31 | `publish` | 3 | 3 | **做入口且开源** | 开源 |
| 32 | `data` | 3 | 3 | **不做入口** | 不做入口 |
| 33 | `persona` | 3 | 3 | **做入口但注册码** | 注册码 |
| 34 | `easel` | 3 | 3 | **做入口且开源** | 开源 |
| 35 | `content-library` | 3 | 3 | **做入口且开源** | 开源 |
| 36 | `artifacts` | 3 | 3 | **做入口且开源** | 开源（补前端入口即可） |
| 37 | `diagnostics` | 3 | 4 | **不做入口** | 不做入口 |
| 38 | `scripts` | 2 | 2 | **做入口但注册码** | 注册码 |
| 39 | `manual-tasks` | 2 | 3 | **不做入口** | 不做入口 |
| 40 | `plans` | 2 | 2 | **做入口但注册码** | 注册码 |
| 41 | `cookies` | 2 | 2 | **做入口且开源** | 开源 |
| 42 | `mediacrawler` | 2 | 2 | **做入口但注册码** | 注册码 |
| 43 | `ai-design` | 2 | 3 | **做入口但注册码** | 注册码 |
| 44 | `login-check` | 2 | 2 | **做入口且开源** | 开源 |
| 45 | `monitor` | 2 | 4 | **不做入口** | 不做入口 |
| 46 | `/` | 1 | 1 | **不做入口** | 忽略 |
| 47 | `/health` | 1 | 1 | **不做入口** | 忽略 |
| 48 | `task-packages` | 1 | 3 | **做入口但注册码** | 注册码 |
| 49 | `persona-proxy` | 1 | 1 | **做入口但注册码** | 注册码 |
| 50 | `skills` | 1 | 1 | **做入口且开源** | 开源 |
| 51 | `tools` | 1 | 1 | **做入口且开源** | 开源 |
| 52 | `ccswitch` | 1 | 1 | **做入口且开源** | 开源 |
| 53 | `matrix-assignments` | 1 | 1 | **做入口且开源** | 开源 |
| 54 | `getFile` | 1 | 1 | **不做入口** | 忽略 |

---

## 5. 统计

| 维度 | 分布 |
|---|---|
| §1 功能清单 | **开源 41** ｜ **注册码 14** |
| §2 能力域 | **不做入口 15** ｜ **做入口且开源 23** ｜ **做入口但注册码 16** |

> §1 / §2 逐项选择为**按「当前建议」兜底**（拍板表里未逐项勾选），
> 其中 `recovery`（D7）、`ai-prompts`（D6）按拍板结论覆盖。
