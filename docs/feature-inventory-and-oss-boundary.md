# Prism-Fusion 功能清单与开源边界（待马哥勾选）

> **用途**：把「哪些功能开源、哪些要注册码解锁」一次性摆清楚，你勾选后我据此产出 feature gate 矩阵、注册码模块、对外文案与安装器打包。
>
> - 生成时间：2026-10-21 ｜ 代码版本：`c237474`
> - 数据来源：后端**运行时 OpenAPI 真源**（`http://127.0.0.1:7000/api/openapi.json`，478 端点组 / 545 操作）+ 前端路由 **import 闭包**（页面 → Next 代理 → 后端）
> - **勾选方式**：把「**你选**」列填成 `开源` / `注册码` / `不做`（可只写序号，如"3、5、7 注册码，其余开源"），回我即可。
> - 「**建议**」列只是我的推荐，**以你的勾选为准**；本文档不替你做商业决定。

---

## 0. 现状速览（先对齐事实）

| 事实 | 数值 | 说明 |
|---|---|---|
| 侧边栏分组 | **13 组 / 54 条链接** | 源码现状 `prism_frontend/src/components/layout/sidebar-new.tsx` |
| 路由覆盖 | **50 / 51** | 仅 `/login` 不入栏（登录页本就不该出现在侧边栏） |
| 你看到的「20 多个」 | **旧安装包** | Community 安装器构建于 2026-10-21 **20:38**、Pro 版 **20:54**，都早于侧边栏全量化提交 `3415123`（当天 21:5x）→ 装出来的就是老侧边栏，**重新打包即解决**（见 §5-5） |
| 后端端点组 | **478 组 / 545 操作** | 运行时真源 |
| 前端已触达 | **166 组** | 页面 import 闭包计算 |
| **未触达** | **312 组 / 53 个能力域** | 有后端能力但**没有前端入口** —— 这是"开不开放"的主要议题（§2） |
| 现有授权机制 | **注册 + 订阅 + 心跳** | `cloud_service/billing/feature_gate.py`，11 个 flag，**基于云端订阅判定，没有"注册码"**（§3） |

---

## 1. 功能清单（侧边栏 54 项）

> 「后端依赖」= 该页面（含其 import 闭包）触达的后端端点组数，**含公共依赖端点**，故数字偏大；0 表示纯前端或兼容跳转页。

### 1.1 概览

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 1 | 仪表盘 | `/` | 账号总数、发布概览、快捷入口 | 25 | 已接后端 | 开源 | |
| 2 | 快速开始 | `/guide` | 新手向导与场景演示（含 Mock 选题环节） | 19 | 已接后端（部分演示流程） | 开源 | |

### 1.2 资源

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 3 | 账号管理 | `/account` | 多平台账号登录态、Cookie 校验、创作者后台、粉丝数据回填 | 29 | 已接后端 | 开源 | |
| 4 | 素材管理 | `/materials` | 素材库、AI 标题/标签润色、批量上传 | 22 | 已接后端 | 开源 | |
| 5 | 代理管理 | `/ip-pool` | IP 池增删绑定、导出、状态统计 | 8 | 已接后端 | **注册码** | |
| 6 | 代理网关 | `/persona-proxy` | per-country 代理网关订阅与热重载 | 3 | 已接后端 | **注册码** | |
| 7 | Persona | `/persona` | 浏览器身份/指纹/Profile 层 | 0 | 占位/重定向 | **注册码** | |

### 1.3 内容

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 8 | 选题库 | `/ideas` | 选题灵感 CRUD | 1 | 已接后端 | 开源 | |
| 9 | 趋势热榜 | `/trends` | 全平台热榜聚合 | 1 | 已接后端（热榜数据源为占位） | 开源 | |
| 10 | 内容拆解 | `/breakdown` | 拆解爆款内容结构 | 2 | 已接后端 | 开源 | |
| 11 | 账号画像 | `/profile` | 账号内容画像与生成 | 3 | 已接后端 | 开源 | |
| 12 | 内容库 | `/easel-content` | 内容资产库（列表/预览/编辑/导出） | 4 | 已接后端 | 开源 | |
| 13 | 收件箱 | `/easel-inbox` | 创作收件箱、草稿导入 | 8 | 已接后端 | 开源 | |
| 14 | 创作工作台 | `/easel-workbench` | 素材 + 选题 + 技能编排工作台 | 6 | 已接后端（含占位文案） | 开源 | |
| 15 | 创作工坊 | `/workshop` | 工具调用工坊（脚本执行） | 2 | 已接后端 | 开源 | |
| 16 | CMS | `/cms` | 隐藏内容后台、浏览器无头/登录模式配置 | 2 | 已接后端 | 开源 | |

### 1.4 生成

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 17 | AI 生图 | `/fusion/image-studio` | 文生图/图生图，云端或本地 Key | 22 | 已接后端 | **注册码**（云端生图） | |
| 18 | 视频流水线 | `/video-pipeline` | 模板 → 渲染 → 成片 | 4 | 已接后端（模板库依赖外部目录 `E:\FDE\fde-landing-delivery`，本机缺失） | **注册码** | |
| 19 | 图片编辑器 | `/tools/image-editor` | 图片裁剪/编辑 | 0 | 纯前端 | 开源 | |

### 1.5 分发

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 20 | 矩阵发布 | `/publish/matrix` | 多平台多账号同步发布编排 | 21 | 已接后端 | 开源 | |
| 21 | 发布中心 | `/publish` | 发布预设与批量发布入口 | 0 | 兼容跳转页 | 开源 | |
| 22 | 发布任务 | `/tasks/publish` | 发布任务列表/统计/取消 | 3 | 已接后端 | 开源 | |
| 23 | 分发记录 | `/tasks/distribution` | 扫码派发（二维码分发，依赖 TikHub） | 23 | 已接后端 | 开源 | |
| 24 | 营销活动 | `/campaigns` | 活动 → 任务包 → 发布任务整链 | 6 | 已接后端（本轮打通） | **注册码**（增值能力） | |
| 25 | 排期日历 | `/calendar` | 内容排期 | 2 | 已接后端 | 开源 | |
| 26 | 审核队列 | `/review` | 发布前审查：审核队列 / 内容版本审批 / 敏感词库 | 7 | 已接后端（本轮新建） | 开源 | |
| 27 | 任务管理 | `/tasks` | 任务总览与状态机 | 29 | 已接后端 | 开源 | |

### 1.6 数据

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 28 | 数据中心 | `/analytics` | 发布与内容数据总览、导出 | 4 | 已接后端 | 开源 | |
| 29 | 趋势分析 | `/analytics/trends` | 趋势图表锚点定位（本轮由空壳改为跳转 `#trend`） | 0 | 兼容跳转页 | 开源 | |
| 30 | 视频数据（父级） | `/analytics/videos` | 各平台视频数据汇总入口 | 0 | 父级入口 | 开源 | |
| 31 | 抖音视频数据 | `/analytics/videos/douyin` | 抖音作品数据采集与复盘 | 2 | 已接后端 | 开源 | |
| 32 | B 站视频数据 | `/analytics/videos/bilibili` | B 站作品数据 | 2 | 已接后端 | 开源 | |
| 33 | 快手视频数据 | `/analytics/videos/kuaishou` | 快手作品数据 | 2 | 已接后端 | 开源 | |
| 34 | 小红书视频数据 | `/analytics/videos/xiaohongshu` | 小红书笔记数据 | 2 | 已接后端 | 开源 | |
| 35 | 视频号视频数据 | `/analytics/videos/channels` | 视频号数据 | 2 | 已接后端 | 开源 | |
| 36 | TikTok 视频数据 | `/analytics/videos/tiktok` | TikTok 作品数据 | 2 | 已接后端 | 开源 | |
| 37 | YouTube 视频数据 | `/analytics/videos/youtube` | YouTube 频道数据 | 2 | 已接后端 | 开源 | |

### 1.7 智能（Hermes Agent）

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 38 | Hermes Agent | `/ai-agent` | Agent 控制台：脚本、上下文、运行时配置 | 24 | 已接后端 | **注册码** | |
| 39 | Agent 控制台 | `/ai-agent` | 同上入口（子项） | 24 | 已接后端 | **注册码** | |
| 40 | 提示词配置 | `/ai-agent/prompts` | Agent 提示词管理 | 18 | 已接后端 | **注册码** | |
| 41 | 运行设置 | `/ai-agent/settings` | Hermes 运行时配置与连通性测试 | 21 | 已接后端 | **注册码** | |
| 42 | HermesChat | `/hermes-chat` | 对话式生成（本轮改为原生 SSE 流式） | 24 | 已接后端 | **注册码** | |
| 43 | AI 对话 | `/chat` | 通用 AI 对话（云端失败自动降级） | 22 | 已接后端 | 开源（基础版） | |
| 44 | 技能库 | `/skills` | 技能列表、刷新、共享脚本 | 3 | 已接后端 | 开源 | |

### 1.8 AI-Fusion

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 45 | 融合中心 | `/fusion` | 融合编排总入口 | 19 | 已接后端 | 开源 | |
| 46 | 风格库 | `/fusion/styles` | 内容风格模板 | 21 | 已接后端 | 开源 | |
| 47 | 内容审查 | `/fusion/moderation` | 敏感词与内容审查 | 20 | 已接后端 | 开源 | |
| 48 | 融合分析 | `/fusion/analytics` | 融合效果分析 | 20 | 已接后端 | 开源 | |
| 49 | 融合配置 | `/fusion/config` | 融合参数配置 | 19 | 已接后端 | 开源 | |
| 50 | 模型市场 | `/fusion/model-market` | 模型清单与切换 | 21 | 已接后端 | **注册码**（云端模型） | |
| 51 | 供应商配置 | `/fusion/providers` | AI 供应商/模型接入配置 | 20 | 已接后端 | **注册码** | |

### 1.9 开发者工具

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 52 | 工具中心 | `/tools` | MCP 工具/技能安装与状态 | 27 | 已接后端 | 开源（**安全面，建议加白名单**） | |
| 53 | 演示控制台 | `/dashboard-demo` | 组件样例（**非真实数据**） | 0 | 演示 | 开源 | |

### 1.10 系统

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 54 | 系统设置 | `/settings` | LLM/模型/通道/订阅/浏览器运行时/授权 | 45 | 已接后端 | 开源（**注册码入口放这里**） | |

---

## 2. 有后端能力、但没有前端入口的 53 个能力域（312 端点组）

> 这些功能**后端已经能跑**，只是没有界面入口。三种处理方式：**① 做入口并开源**、**② 做入口但要注册码**、**③ 不做入口（仅内部/运维用）**。
> 其中 `system` / `diagnostics` / `monitor` / `accounts` 运维工具这类，天然适合「不做入口」或只放 Pro。

| # | 能力域 | 端点组 | 操作 | 典型端点 | 一句话 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 1 | `fusion` | 25 | 31 | `/fusion/cloud-status`、`/fusion/providers/models` | 融合引擎：云端状态、供应商模型、编排配置 | 部分注册码 | |
| 2 | `system` | 24 | 24 | `/system/browser-profiles/list`、`/system/browser-profiles/cleanup-old` | 浏览器运行时与系统运维 | 不做入口（Pro 内部） | |
| 3 | `accounts` | 18 | 19 | `/accounts/accounts/tools/backfill-user-ids`、`/clean-duplicates` | 账号运维工具（回填、去重、调试） | 不做入口 | |
| 4 | `platforms` | 16 | 16 | `/platforms/douyin/login`、`/platforms/douyin/verify-cookie` | 各平台登录/任务/Cookie 校验直连接口 | 不做入口（已被账号页封装） | |
| 5 | `agent` | 15 | 17 | `/agent/config/openclaw`、`/agent/config/hermes/update/check` | Agent 运行时配置与自检 | 注册码 | |
| 6 | `tasks` | 13 | 14 | `/tasks/distribution`、`/tasks/distribution/claim/{id}` | 任务分发/认领/二维码派发 | 注册码 | |
| 7 | `tikhub` | 12 | 12 | `/tikhub/health`、`/tikhub/kuaishou/user-posts` | TikHub 数据服务（快手/B站用户与作品） | 注册码（外部付费 API） | |
| 8 | `files` | 11 | 13 | `/files/upload`、`/files/ai-cover-jobs/{id}` | 文件上传与 AI 封面任务 | 开源 | |
| 9 | `ai` | 11 | 11 | `/ai/llm-proxy/chat/completions`、`/ai/agent-chat` | LLM 代理与 agent-chat | 注册码 | |
| 10 | `recovery` | 10 | 10 | `/recovery/health`、`/recovery/kuaishou/user-posts` | 数据回收（TikHub 快照） | 注册码 | |
| 11 | `ip-pool` | 10 | 10 | `/ip-pool/add`、`/ip-pool/bind-batch` | IP 池增删与绑定 | 注册码 | |
| 12 | `receipts` | 10 | 11 | `/receipts/{id}`、`/receipts/stats` | 幂等回执 | 开源 | |
| 13 | `matrix` | 9 | 10 | `/matrix/generate_tasks`、`/matrix/tasks/pop` | 矩阵任务生成与消费 | 开源 | |
| 14 | `health` | 8 | 8 | `/health/dashboard`、`/health/scores/trend` | 健康评分与趋势 | 不做入口 | |
| 15 | `webhooks` | 7 | 10 | `/webhooks/subscriptions` | Webhook 订阅（对外事件） | 开源 | |
| 16 | `analytics` | 6 | 6 | `/analytics/video`、`/analytics/douyin-tiktok/collect` | 视频级采集与解析 | 开源 | |
| 17 | `video-pipeline` | 6 | 6 | `/video-pipeline/engines`、`/video-pipeline/run` | 视频引擎、模板 HTML、运行 | 注册码 | |
| 18 | `review` | 6 | 6 | `/review/items/{id}/reject`、`/review/items/{id}/edit` | 审核条目编辑与驳回 | 开源（并入 /review） | |
| 19 | `dedup` | 6 | 6 | `/dedup/check`、`/dedup/records` | 内容查重 | 开源 | |
| 20 | `insights` | 5 | 5 | `/insights/collect`、`/insights/anomalies` | 异常与洞察 | 开源 | |
| 21 | `platform-fields` | 5 | 5 | `/platform-fields`、`/platform-fields/{id}/category/{x}` | 平台字段字典 | 不做入口 | |
| 22 | `selectors` | 5 | 5 | `/selectors/versions/{id}` | 选择器版本管理 | 不做入口 | |
| 23 | `ai-prompts` | 4 | 5 | `/ai-prompts/structure`、`/ai-prompts/config/{id}/reset` | 提示词结构与配置 | **注册码（云端 prompt 不开源）** | |
| 24 | `dashboard` | 4 | 4 | `/dashboard/overview`、`/dashboard/tasks/summary` | 仪表盘聚合 | 开源 | |
| 25 | `concurrency` | 4 | 5 | `/concurrency/config`、`/concurrency/usage` | 并发配额与用量 | 不做入口 | |
| 26 | `task-state` | 4 | 6 | `/task-state`、`/task-state/validations` | 任务状态机与校验 | 不做入口 | |
| 27 | `content-variants` | 4 | 6 | `/content-variants/variants/{id}/approve` | 内容版本审批 | 开源（并入 /review） | |
| 28 | `matrix-groups` | 4 | 5 | `/matrix-groups/{id}/assign` | 矩阵分组与分配 | 开源 | |
| 29 | `campaigns` | 3 | 4 | `/campaigns/{id}/pause`、`/campaigns/{id}/resume` | 活动暂停/恢复/详情 | 注册码 | |
| 30 | `auth` | 3 | 3 | `/auth/sessions/cleanup`、`/auth/login/browser/import-chrome` | 浏览器导入登录会话 | 开源 | |
| 31 | `publish` | 3 | 3 | `/publish/single`、`/publish/debug/capture` | 单条发布与发布调试截图 | 开源 | |
| 32 | `data` | 3 | 3 | `/data/health`、`/data/collect` | 数据健康与采集 | 不做入口 | |
| 33 | `persona` | 3 | 3 | `/persona/dashboard/start`、`/persona/dashboard/stop` | 指纹看板启停 | 注册码 | |
| 34 | `easel` | 3 | 3 | `/easel/stop`、`/easel/outputs` | Easel 草稿与输出 | 开源 | |
| 35 | `content-library` | 3 | 3 | `/content-library/refresh`、`/content-library/profile/build/status` | 内容库刷新与画像构建 | 开源 | |
| 36 | `diagnostics` | 3 | 4 | `/diagnostics/redact`、`/diagnostics/{id}` | 日志脱敏诊断 | 不做入口 | |
| 37 | `scripts` | 2 | 2 | `/scripts/list`、`/scripts/run` | 脚本列表与执行 | 注册码 | |
| 38 | `manual-tasks` | 2 | 3 | `/manual-tasks/{id}/status` | 手动任务 | 不做入口 | |
| 39 | `plans` | 2 | 2 | `/plans/{id}/publish`、`/plans/{id}/packages` | 计划发布与任务包 | 注册码 | |
| 40 | `task-packages` | 2 | 5 | `/task-packages`、`/task-packages/{id}` | 任务包 CRUD（**GET/PUT/DELETE 仍为空壳**） | 注册码 | |
| 41 | `cookies` | 2 | 2 | `/cookies/fast-verify`、`/cookies/fast-verify/batch` | Cookie 快速校验 | 开源 | |
| 42 | `mediacrawler` | 2 | 2 | `/mediacrawler/login/open` | 媒体爬虫登录 | 注册码 | |
| 43 | `ai-design` | 2 | 3 | `/ai-design/agents/quota` | AI 设计 Agent 配额 | 注册码 | |
| 44 | `login-check` | 2 | 2 | `/login-check`、`/login-check/batch` | 登录态检查 | 开源 | |
| 45 | `monitor` | 2 | 4 | `/monitor/events`、`/monitor/transitions` | 监控事件与状态迁移 | 不做入口 | |
| 46 | `/`（根路径） | 1 | 1 | `/` | 服务根 | 忽略 | |
| 47 | `/health` | 1 | 1 | `/health` | 健康检查 | 忽略 | |
| 48 | `persona-proxy` | 1 | 1 | `/persona-proxy/meta` | 网关元信息 | 注册码 | |
| 49 | `skills` | 1 | 1 | `/skills/{id}` | 技能详情 | 开源 | |
| 50 | `tools` | 1 | 1 | `/tools/{id}/status` | 工具状态 | 开源 | |
| 51 | `ccswitch` | 1 | 1 | `/ccswitch/current` | 当前 CC 切换 | 开源 | |
| 52 | `matrix-assignments` | 1 | 1 | `/matrix-assignments` | 矩阵分配 | 开源 | |
| 53 | `getFile` | 1 | 1 | `/getFile` | 文件读取 | 忽略 | |

---

## 3. 注册码（授权码）：现状、缺口与三条路线

### 3.1 现状（已经有底子，不用从零开始）

`cloud_service/billing/feature_gate.py` 已实现一套 **Feature Gate**：

| flag | Community | Pro | 对应功能（§1 编号） |
|---|---|---|---|
| `max_accounts` | 3 | -1（无限） | #3 账号管理 |
| `max_platforms` | 3 | 8 | #20 矩阵发布 / §2-16 数据采集 |
| `ai_mode` | `local_key` | `cloud` | #43 AI 对话 |
| `image_gen` | `local_key` | `cloud` | #17 AI 生图 |
| `agent_quota` | 0（禁用） | 2 | #38–#41 Hermes Agent |
| `data_recovery` | false | true | §2-10 数据回收 |
| `persona` | false | true | #7 Persona / #6 代理网关 |
| `proxy_management` | false | true | #5 代理管理 |
| `stream_chat` | false | true | #42 HermesChat |
| `team_members` | 1 | 1（Team 档另议） | — |

判定链：**云端注册 → JWT → `Subscription` 表（`plan=pro` 且未过期）→ `check_feature` / `require_feature`（403 + 结构化升级提示）**；客户端 `useLicenseHeartbeat` 每 24h 校验一次。

**⚠️ 关键事实：现有机制是"注册 + 订阅"，不是"注册码"。** 你要的「输入注册码才能启动部分功能」，目前**没有任何实现**。

### 3.2 缺口

1. 没有授权码的**签发端**（谁生成、发给谁、有效期、绑定机器、离线宽限期）。
2. 没有客户端**输入与校验**入口（应放在 §1-54 系统设置里）。
3. Feature Gate 的 11 个 flag 是**按 plan 取常量**，不是**按注册码的授权范围取**。要支持"注册码只解锁某几项"，需要从「plan 维度」改成「**授权条目维度**」。

### 3.3 三条路线（请你选一条，我再动手）

| 路线 | 做法 | 优点 | 缺点 / 风险 |
|---|---|---|---|
| **A. 纯本地注册码** | 授权码用 Ed25519 私钥签名，客户端内置公钥校验 | 完全离线，私有化交付不依赖服务器 | **本地校验一定可被绕过**（改二进制/打补丁）。只适合锁"锦上添花"的功能，不适合锁核心价值 |
| **B. 云端注册码 + 本地缓存** | 注册码 → 云端校验 → 下发带签名的 license（含授权条目、到期时间）→ 本地缓存，周期续期 | 防伪强（服务端真源），支持解绑/续费 | 断网或服务器挂掉时需有离线宽限期（建议 7–14 天） |
| **C. 双轨：注册码解锁 + 订阅增值** | 注册码解锁"能不能用"（本地校验），订阅决定"能用多少"（云端配额） | 兼顾私有化交付与持续收入 | 两套判定要合并到同一个 `FeatureGate` 接口，工作量最大 |

**我的建议：C**。具体形态：把 `feature_gate.py` 的判定改成「**注册码授权条目 ∩ 订阅配额**」双维度 —— 本地注册码给出功能白名单，云端订阅给出额度（账号数/平台数/Agent 数/调用量）。这样你说的「大部分功能开放、少数要注册码」天然成立，且离线也能用。

### 3.4 必须先想清楚的两个问题（选完路线后我需要答案）

1. **注册码要不要绑机器？** 绑 → 难转手但可防共享；不绑 → 好卖但易被分享。
2. **注册码的有效期策略？** 永久 / 固定期限（年卡）/ 按版本。以及到期后**已产生的数据是否还能查看**（建议能看不能新增，避免用户数据被锁死引发口碑问题）。

---

## 4. 开源时必须写清的两份材料：现状与缺口

### 4.1 「对原项目的借鉴」——已有骨架，只差三处补齐

| 现状 | 位置 | 状态 |
|---|---|---|
| 借鉴声明（第三方清单） | `README.md` §项目支持与采用 | ✅ 已有，列了 5 个上游 |
| 借鉴方式（怎么用、用了什么） | `DEVELOPMENT-RECORD.md` §2.1 | ✅ 已有，4 个上游各自的"借鉴内容 + 采用方式" |
| 归属与许可证明细 | `NOTICE.txt` + `vendor/VENDOR.md` | ✅ **已修**：NOTICE 原头部仍是本项目早期形态的 `SynapseAutomation / Laihuijin / Apache-2.0`，与仓库 `LICENSE`（AGPL-3.0）冲突 —— 已拆成三段：① 本项目 AGPL-3.0 ② 本项目早期形态的历史 Apache-2.0 声明 ③ 第三方上游清单（并补上 NOTICE 漏掉的 Persona Studio）；`vendor/VENDOR.md`、`DEVELOPMENT-RECORD.md`、`HANDOFF.md` 里 4 处残留的「本项目 = Apache-2.0」表述一并改为 AGPL-3.0 |
| **原项目谱系** | ❌ 缺 | 需要在 README 写清一条链：**social-auto-upload (MIT，CLI 发布基础) → 本项目早期形态 SynapseAutomation (Apache-2.0, Laihiujin) → 老马AI工作台 (AGPL-3.0)**，并说明为什么整体选 AGPL-3.0（README §许可 已有 3 条理由） |
| **版权署名写法** | ⚠️ 待你确认 | NOTICE 里"本项目"署名用什么写法：`Copyright (c) 2026 老马AI工作台（Prism-Fusion）贡献者`（当前占位）/ `Laihiujin` / `maning636` / 公司主体名 |

### 4.2 「新功能展示」——已有底稿，但 README 的展示过时

| 现状 | 位置 | 状态 |
|---|---|---|
| 在底座之上新增的功能（完整） | `DEVELOPMENT-RECORD.md` §3 | ✅ 已有底稿 |
| README「新功能集成」 | `README.md` §新功能集成 | ⚠️ **只列了 9 项且停在早期阶段**（Persona / 代理网关 / 代理管理 / 浏览器运行时 / 工具中心 / CMS / 登录体验 / 运行时锁 / TikTok-YouTube 采集），**缺**：Hermes Agent 与 HermesChat、AI 生图与视频流水线、图片编辑器、融合中心七件套、审核队列、营销活动与任务包、排期日历、创作工作台/内容库/收件箱/工坊、技能库、数据中心与趋势分析、去重与幂等回执、Webhook 等 |
| 建议改法 | — | README 改成两段：**①「我们基于什么」**（借鉴谱系 + 许可证）+ **②「我们在其上做了什么」**（按 §1 的 13 个分组给一张对照表，每项标注 开源/注册码），正好复用你这次的勾选结果 |

---

## 5. 开源前必须处理的一致性问题

| # | 问题 | 现状 | 谁来定 |
|---|---|---|---|
| 1 | NOTICE / VENDOR 许可证口径 | 已修（Apache-2.0 → AGPL-3.0，本项目与上游分段声明） | 你确认署名写法 |
| 2 | **「8 平台」三套口径** | README 写百家号 / 前端选知乎·头条·西瓜 / 后端实为百家号 | **你**（涉 Pro 付费承诺） |
| 3 | `cloud_service/llm_proxy/prompts.py`（18KB / 381 行）是否留在开源树 | 目前留在树内，DB dump 的 `prompts` 表也在 | **你**（Open Core 边界） |
| 4 | `/api/v1/recovery/*` 是否加 feature gate 收进 Pro | 本轮**未加**（纯本地快照、不消耗 TikHub 额度） | **你**（§2-10） |
| 5 | **两个安装器必须重打包** | Community 构建于 2026-10-21 20:38、Pro 建于 10-16，**都早于当前 HEAD `c237474`**；你看到的旧侧边栏就是这么来的 | 我来打，你验 |
| 6 | 真实生产联调零验证 | 缺 `CLOUD_LLM_API_KEY`、支付宝/微信正式商户凭证与证书、TikHub Key → 支付与 TikHub 链路一次都没跑通 | **你**提供凭证 |
| 7 | 干净 VM 验证 | Community 安装器无代码签名（NotSigned），未在干净 Windows VM 完成装/启/卸/升验证 | 我来测 |
| 8 | 生成层统一产物 ID | 「生图/生视频 → 审查」还不能自动衔接（审查目前是"发布前审查"） | 开发优先级，下一阶段第一项 |

---

## 6. 回执格式（你只需回这段）

```
§1 功能清单：
  开源：1,2,3,4,8,9,10,11,12,13,14,15,16,19,20,21,22,23,25,26,27,28,29,30-37,43,44,45,46,47,48,49,52,53,54
  注册码：5,6,7,17,18,24,38,39,40,41,42,50,51
  不做：
§2 能力域：
  做入口且开源：
  做入口但注册码：
  不做入口：
§3 注册码路线：A / B / C
  绑机器：是 / 否
  有效期：永久 / 年卡 / 按版本
§4 署名写法：
§5 待拍板项：2 / 3 / 4 的结论
```

收到后我会一次交付：**feature gate 矩阵落地**（把 §1/§2 映射成 `COMMUNITY_FLAGS`/`PRO_FLAGS`/注册码条目）+ **注册码模块**（签发端 + 客户端输入 + 离线宽限）+ **README 开源章节改写**（借鉴谱系 + 新功能展示）+ **两个安装器重打包**。

---

## 附：本文档的复现方式

```powershell
# 后端端点真源
& 'D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe' -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:7000/api/openapi.json',timeout=30)); print(len(d['paths']))"

# 侧边栏结构与路由清单
& 'D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe' 'D:\dim开发\Prism-Fusion\tmp\count_sidebar.py'

# 路由 → 后端端点 + Mock 标记明细
& 'D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe' 'D:\dim开发\Prism-Fusion\tmp\dump_route_facts.py'
```
