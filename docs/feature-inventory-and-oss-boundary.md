# Prism-Fusion 功能清单与开源边界（待马哥勾选）

> **用途**：把「哪些功能开源、哪些要注册码解锁」一次性摆清楚，你勾选后我据此产出 feature gate 矩阵、注册码模块、对外文案与安装器打包。
>
> - 生成时间：2026-10-22 ｜ 代码版本：基线 `09e12c1` ＋ 本轮「统一产物总线」改动
> - 数据来源：后端**运行时 OpenAPI 真源**（`http://127.0.0.1:7000/api/openapi.json`，485 端点组 / 553 操作）+ 前端路由 **import 闭包**（页面 → Next 代理 → 后端）
> - **勾选方式**：把「**你选**」列填成 `开源` / `注册码` / `不做`（可只写序号，如"3、5、7 注册码，其余开源"），回我即可。
>   **更省事的做法**：用 Word 版《开源边界拍板表》填写后把文件发回即可 —— `docs/oss-boundary-decision-form.docx`（含总体决策 10 项 + 功能清单 55 项 + 能力域 54 项 + 运维待办 7 项），我会用脚本读出你的勾选结果回填本表。
> - 「**建议**」列只是我的推荐，**以你的勾选为准**；本文档不替你做商业决定。

---

## 0. 现状速览（先对齐事实）

| 事实 | 数值 | 说明 |
|---|---|---|
| 侧边栏分组 | **14 组 / 55 条链接** | 源码现状 `prism_frontend/src/components/layout/sidebar-new.tsx` |
| 路由覆盖 | **51 / 52** | 仅 `/login` 不入栏（登录页本就不该出现在侧边栏） |
| 你看到的「20 多个」 | **旧安装包** | Community 安装器构建于 2026-10-21 **20:38**、Pro 版 **20:54**，都早于侧边栏全量化提交 `3415123`（当天 21:5x）→ 装出来的就是老侧边栏，**重新打包即解决**（见 §5-5） |
| 后端端点组 | **485 组 / 553 操作** | 运行时真源 |
| 前端已触达 | **171 组** | 页面 import 闭包计算 |
| **未触达** | **314 组 / 54 个能力域** | 有后端能力但**没有前端入口** —— 这是"开不开放"的主要议题（§2） |
| 现有授权机制 | **注册 + 订阅 + 心跳** | `cloud_service/billing/feature_gate.py`，11 个 flag，**基于云端订阅判定，没有"注册码"**（§3） |
| 拍板结果 | **已回（2026-10-22）** | 10 项总体决策 + 109 项逐项选择已落表，逐项按「当前建议」兜底；结论见 §7 |
| 功能之间的串联 | **统一产物总线** | 2026-10-22 新增：`artifact_id`（`art_*`）+ 阶段机 + 血缘，把生图 / 上传 / 渲染 / 审核 / 发布串成一条流水线（详见 [2026-10-22-unified-artifact-bus.md](dev-reports/2026-10-22-unified-artifact-bus.md)） |

---

## 1. 功能清单（侧边栏 55 项）

> 「后端依赖」= 该页面（含其 import 闭包）触达的后端端点组数，**含公共依赖端点**，故数字偏大；0 表示纯前端或兼容跳转页。

### 1.1 概览

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 1 | 仪表盘 | `/` | 账号总数、发布概览、快捷入口 | 25 | 已接后端 | 开源 | **开源** |
| 2 | 快速开始 | `/guide` | 新手向导与场景演示（含 Mock 选题环节） | 19 | 已接后端（部分演示流程） | 开源 | **开源** |
### 1.2 资源

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 3 | 账号管理 | `/account` | 多平台账号登录态、Cookie 校验、创作者后台、粉丝数据回填 | 29 | 已接后端 | 开源 | **开源** |
| 4 | 素材管理 | `/materials` | 素材库、AI 标题/标签润色、批量上传 | 22 | 已接后端 | 开源 | **开源** |
| 5 | 代理管理 | `/ip-pool` | IP 池增删绑定、导出、状态统计 | 8 | 已接后端 | 注册码 | **注册码** |
| 6 | 代理网关 | `/persona-proxy` | per-country 代理网关订阅与热重载 | 3 | 已接后端 | 注册码 | **注册码** |
| 7 | Persona | `/persona` | 浏览器身份/指纹/Profile 层 | 0 | 占位/重定向 | 注册码 | **注册码** |
### 1.3 内容

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 8 | 选题库 | `/ideas` | 选题灵感 CRUD | 1 | 已接后端 | 开源 | **开源** |
| 9 | 趋势热榜 | `/trends` | 全平台热榜聚合 | 1 | 已接后端（热榜数据源为占位） | 开源 | **开源** |
| 10 | 内容拆解 | `/breakdown` | 拆解爆款内容结构 | 2 | 已接后端 | 开源 | **开源** |
| 11 | 账号画像 | `/profile` | 账号内容画像与生成 | 3 | 已接后端 | 开源 | **开源** |
| 12 | 内容库 | `/easel-content` | 内容资产库（列表/预览/编辑/导出） | 4 | 已接后端 | 开源 | **开源** |
| 13 | 收件箱 | `/easel-inbox` | 创作收件箱、草稿导入 | 8 | 已接后端 | 开源 | **开源** |
| 14 | 创作工作台 | `/easel-workbench` | 素材 + 选题 + 技能编排工作台 | 6 | 已接后端（含占位文案） | 开源 | **开源** |
| 15 | 创作工坊 | `/workshop` | 工具调用工坊（脚本执行） | 2 | 已接后端 | 开源 | **开源** |
| 16 | CMS | `/cms` | 隐藏内容后台、浏览器无头/登录模式配置 | 2 | 已接后端 | 开源 | **开源** |
### 1.4 生成

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 17 | AI 生图 | `/fusion/image-studio` | 文生图/图生图，云端或本地 Key | 23 | 已接后端 | 注册码（云端生图） | **注册码** |
| 18 | 视频流水线 | `/video-pipeline` | 模板 → 渲染 → 成片 | 4 | 已接后端（模板库依赖外部目录 `E:\FDE\fde-landing-delivery`，本机缺失） | 注册码 | **注册码** |
| 19 | 图片编辑器 | `/tools/image-editor` | 图片裁剪/编辑 | 0 | 纯前端 | 开源 | **开源** |
### 1.5 产物

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 20 | 产物中心 | `/artifacts` | 统一产物 ID / 阶段流转 / 血缘（生图·上传·渲染·审核·发布串联） | 22 | 已接后端（本轮新建） | 开源 | **开源** |
### 1.6 分发

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 21 | 矩阵发布 | `/publish/matrix` | 多平台多账号同步发布编排 | 22 | 已接后端 | 开源 | **开源** |
| 22 | 发布中心 | `/publish` | 发布预设与批量发布入口 | 0 | 兼容跳转页 | 开源 | **开源** |
| 23 | 发布任务 | `/tasks/publish` | 发布任务列表/统计/取消 | 3 | 已接后端 | 开源 | **开源** |
| 24 | 分发记录 | `/tasks/distribution` | 扫码派发（二维码分发，依赖 TikHub） | 23 | 已接后端 | 开源 | **开源** |
| 25 | 营销活动 | `/campaigns` | 活动 → 任务包 → 发布任务整链 | 6 | 已接后端（本轮打通） | 注册码（增值能力） | **注册码** |
| 26 | 排期日历 | `/calendar` | 内容排期 | 2 | 已接后端 | 开源 | **开源** |
| 27 | 审核队列 | `/review` | 发布前审查：审核队列 / 内容版本审批 / 敏感词库 | 7 | 已接后端（本轮新建） | 开源 | **开源** |
| 28 | 任务管理 | `/tasks` | 任务总览与状态机 | 29 | 已接后端 | 开源 | **开源** |
### 1.7 数据

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 29 | 数据中心 | `/analytics` | 发布与内容数据总览、导出 | 4 | 已接后端 | 开源 | **开源** |
| 30 | 趋势分析 | `/analytics/trends` | 趋势图表锚点定位（本轮由空壳改为跳转 `#trend`） | 0 | 兼容跳转页 | 开源 | **开源** |
| 31 | 视频数据（父级） | `/analytics/videos` | 各平台视频数据汇总入口 | 0 | 父级入口 | 开源 | **开源** |
| 32 | 抖音视频数据 | `/analytics/videos/douyin` | 抖音作品数据采集与复盘 | 2 | 已接后端 | 开源 | **开源** |
| 33 | B 站视频数据 | `/analytics/videos/bilibili` | B 站作品数据 | 2 | 已接后端 | 开源 | **开源** |
| 34 | 快手视频数据 | `/analytics/videos/kuaishou` | 快手作品数据 | 2 | 已接后端 | 开源 | **开源** |
| 35 | 小红书视频数据 | `/analytics/videos/xiaohongshu` | 小红书笔记数据 | 2 | 已接后端 | 开源 | **开源** |
| 36 | 视频号视频数据 | `/analytics/videos/channels` | 视频号数据 | 2 | 已接后端 | 开源 | **开源** |
| 37 | TikTok 视频数据 | `/analytics/videos/tiktok` | TikTok 作品数据 | 2 | 已接后端 | 开源 | **开源** |
| 38 | YouTube 视频数据 | `/analytics/videos/youtube` | YouTube 频道数据 | 2 | 已接后端 | 开源 | **开源** |
### 1.8 智能（Hermes Agent）

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 39 | Hermes Agent | `/ai-agent` | Agent 控制台：脚本、上下文、运行时配置 | 24 | 已接后端 | 注册码 | **注册码** |
| 40 | Agent 控制台 | `/ai-agent` | 同上入口（子项） | 24 | 已接后端 | 注册码 | **注册码** |
| 41 | 提示词配置 | `/ai-agent/prompts` | Agent 提示词管理 | 18 | 已接后端 | 注册码 | **注册码** |
| 42 | 运行设置 | `/ai-agent/settings` | Hermes 运行时配置与连通性测试 | 21 | 已接后端 | 注册码 | **注册码** |
| 43 | HermesChat | `/hermes-chat` | 对话式生成（本轮改为原生 SSE 流式） | 24 | 已接后端 | 注册码 | **注册码** |
| 44 | AI 对话 | `/chat` | 通用 AI 对话（云端失败自动降级） | 22 | 已接后端 | 开源（基础版） | **开源** |
| 45 | 技能库 | `/skills` | 技能列表、刷新、共享脚本 | 3 | 已接后端 | 开源 | **开源** |
### 1.9 AI-Fusion

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 46 | 融合中心 | `/fusion` | 融合编排总入口 | 19 | 已接后端 | 开源 | **开源** |
| 47 | 风格库 | `/fusion/styles` | 内容风格模板 | 21 | 已接后端 | 开源 | **开源** |
| 48 | 内容审查 | `/fusion/moderation` | 敏感词与内容审查 | 20 | 已接后端 | 开源 | **开源** |
| 49 | 融合分析 | `/fusion/analytics` | 融合效果分析 | 20 | 已接后端 | 开源 | **开源** |
| 50 | 融合配置 | `/fusion/config` | 融合参数配置 | 19 | 已接后端 | 开源 | **开源** |
| 51 | 模型市场 | `/fusion/model-market` | 模型清单与切换 | 21 | 已接后端 | 注册码（云端模型） | **注册码** |
| 52 | 供应商配置 | `/fusion/providers` | AI 供应商/模型接入配置 | 20 | 已接后端 | 注册码 | **注册码** |
### 1.10 开发者工具

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 53 | 工具中心 | `/tools` | MCP 工具/技能安装与状态 | 27 | 已接后端 | 开源（安全面，建议加白名单） | **开源** |
| 54 | 演示控制台 | `/dashboard-demo` | 组件样例（**非真实数据**） | 0 | 演示 | 开源 | **开源** |
### 1.11 系统

| # | 功能 | 路由 | 一句话 | 后端依赖 | 当前状态 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 55 | 系统设置 | `/settings` | LLM/模型/通道/订阅/浏览器运行时/授权 | 45 | 已接后端 | 开源（注册码入口放这里） | **注册码** |
---

## 2. 有后端能力、但没有前端入口的 54 个能力域（314 端点组）

> 这些功能**后端已经能跑**，只是没有界面入口。三种处理方式：**① 做入口并开源**、**② 做入口但要注册码**、**③ 不做入口（仅内部/运维用）**。
> 其中 `system` / `diagnostics` / `monitor` / `accounts` 运维工具这类，天然适合「不做入口」或只放 Pro。

| # | 能力域 | 端点组 | 操作 | 典型端点 | 一句话 | 建议 | **你选** |
|---|---|---|---|---|---|---|---|
| 1 | `fusion` | 25 | 31 | `/fusion/cloud-status`、`/fusion/providers/models` | 融合引擎：云端状态、供应商模型、编排配置 | 部分注册码 | **做入口但注册码** |
| 2 | `system` | 24 | 24 | `/system/browser-profiles/list`、`/system/browser-profiles/cleanup-old` | 浏览器运行时与系统运维 | 不做入口（Pro 内部） | **不做入口** |
| 3 | `accounts` | 18 | 19 | `/accounts/accounts/tools/backfill-user-ids`、`/clean-duplicates` | 账号运维工具（回填、去重、调试） | 不做入口 | **不做入口** |
| 4 | `platforms` | 16 | 16 | `/platforms/douyin/login`、`/platforms/douyin/verify-cookie` | 各平台登录/任务/Cookie 校验直连接口 | 不做入口（已被账号页封装） | **不做入口** |
| 5 | `agent` | 15 | 17 | `/agent/config/openclaw`、`/agent/config/hermes/update/check` | Agent 运行时配置与自检 | 注册码 | **做入口但注册码** |
| 6 | `tasks` | 13 | 14 | `/tasks/distribution`、`/tasks/distribution/claim/{id}` | 任务分发/认领/二维码派发 | 注册码 | **做入口但注册码** |
| 7 | `tikhub` | 12 | 12 | `/tikhub/health`、`/tikhub/kuaishou/user-posts` | TikHub 数据服务（快手/B站用户与作品） | 注册码（外部付费 API） | **做入口但注册码** |
| 8 | `files` | 11 | 13 | `/files/upload`、`/files/ai-cover-jobs/{id}` | 文件上传与 AI 封面任务 | 开源 | **做入口且开源** |
| 9 | `ai` | 11 | 11 | `/ai/llm-proxy/chat/completions`、`/ai/agent-chat` | LLM 代理与 agent-chat | 注册码 | **做入口但注册码** |
| 10 | `recovery` | 10 | 10 | `/recovery/health`、`/recovery/kuaishou/user-posts` | 数据回收（TikHub 快照） | 注册码 | **做入口且开源**（D7 不收进 Pro） |
| 11 | `ip-pool` | 10 | 10 | `/ip-pool/add`、`/ip-pool/bind-batch` | IP 池增删与绑定 | 注册码 | **做入口但注册码** |
| 12 | `receipts` | 10 | 11 | `/receipts/{id}`、`/receipts/stats` | 幂等回执 | 开源 | **做入口且开源** |
| 13 | `matrix` | 9 | 10 | `/matrix/generate_tasks`、`/matrix/tasks/pop` | 矩阵任务生成与消费 | 开源 | **做入口且开源** |
| 14 | `health` | 8 | 8 | `/health/dashboard`、`/health/scores/trend` | 健康评分与趋势 | 不做入口 | **不做入口** |
| 15 | `webhooks` | 7 | 10 | `/webhooks/subscriptions` | Webhook 订阅（对外事件） | 开源 | **做入口且开源** |
| 16 | `analytics` | 6 | 6 | `/analytics/video`、`/analytics/douyin-tiktok/collect` | 视频级采集与解析 | 开源 | **做入口且开源** |
| 17 | `video-pipeline` | 6 | 6 | `/video-pipeline/engines`、`/video-pipeline/run` | 视频引擎、模板 HTML、运行 | 注册码 | **做入口但注册码** |
| 18 | `review` | 6 | 6 | `/review/items/{id}/reject`、`/review/items/{id}/edit` | 审核条目编辑与驳回 | 开源（并入 /review） | **做入口且开源** |
| 19 | `dedup` | 6 | 6 | `/dedup/check`、`/dedup/records` | 内容查重 | 开源 | **做入口且开源** |
| 20 | `insights` | 5 | 5 | `/insights/collect`、`/insights/anomalies` | 异常与洞察 | 开源 | **做入口且开源** |
| 21 | `platform-fields` | 5 | 5 | `/platform-fields`、`/platform-fields/{id}/category/{x}` | 平台字段字典 | 不做入口 | **不做入口** |
| 22 | `selectors` | 5 | 5 | `/selectors/versions/{id}` | 选择器版本管理 | 不做入口 | **不做入口** |
| 23 | `ai-prompts` | 4 | 5 | `/ai-prompts/structure`、`/ai-prompts/config/{id}/reset` | 提示词结构与配置 | 注册码（云端 prompt 不开源） | **做入口但注册码**（D6 云端 prompt 不开源） |
| 24 | `dashboard` | 4 | 4 | `/dashboard/overview`、`/dashboard/tasks/summary` | 仪表盘聚合 | 开源 | **做入口且开源** |
| 25 | `concurrency` | 4 | 5 | `/concurrency/config`、`/concurrency/usage` | 并发配额与用量 | 不做入口 | **不做入口** |
| 26 | `task-state` | 4 | 6 | `/task-state`、`/task-state/validations` | 任务状态机与校验 | 不做入口 | **不做入口** |
| 27 | `content-variants` | 4 | 6 | `/content-variants/variants/{id}/approve` | 内容版本审批 | 开源（并入 /review） | **做入口且开源** |
| 28 | `matrix-groups` | 4 | 5 | `/matrix-groups/{id}/assign` | 矩阵分组与分配 | 开源 | **做入口且开源** |
| 29 | `campaigns` | 3 | 4 | `/campaigns/{id}/pause`、`/campaigns/{id}/resume` | 活动暂停/恢复/详情 | 注册码 | **做入口但注册码** |
| 30 | `auth` | 3 | 3 | `/auth/sessions/cleanup`、`/auth/login/browser/import-chrome` | 浏览器导入登录会话 | 开源 | **做入口且开源** |
| 31 | `publish` | 3 | 3 | `/publish/single`、`/publish/debug/capture` | 单条发布与发布调试截图 | 开源 | **做入口且开源** |
| 32 | `data` | 3 | 3 | `/data/health`、`/data/collect` | 数据健康与采集 | 不做入口 | **不做入口** |
| 33 | `persona` | 3 | 3 | `/persona/dashboard/start`、`/persona/dashboard/stop` | 指纹看板启停 | 注册码 | **做入口但注册码** |
| 34 | `easel` | 3 | 3 | `/easel/stop`、`/easel/outputs` | Easel 草稿与输出 | 开源 | **做入口且开源** |
| 35 | `content-library` | 3 | 3 | `/content-library/refresh`、`/content-library/profile/build/status` | 内容库刷新与画像构建 | 开源 | **做入口且开源** |
| 36 | `artifacts` | 3 | 3 | `/artifacts/{artifact_id}`、`/artifacts/{artifact_id}/promote`、`/artifacts/by-ref/{ref_type}/{ref_id}` | 统一产物总线的详情 / 阶段推进 / 按来源反查（主链路已接前端） | 开源（补前端入口即可） | **做入口且开源** |
| 37 | `diagnostics` | 3 | 4 | `/diagnostics/redact`、`/diagnostics/{id}` | 日志脱敏诊断 | 不做入口 | **不做入口** |
| 38 | `scripts` | 2 | 2 | `/scripts/list`、`/scripts/run` | 脚本列表与执行 | 注册码 | **做入口但注册码** |
| 39 | `manual-tasks` | 2 | 3 | `/manual-tasks/{id}/status` | 手动任务 | 不做入口 | **不做入口** |
| 40 | `plans` | 2 | 2 | `/plans/{id}/publish`、`/plans/{id}/packages` | 计划发布与任务包 | 注册码 | **做入口但注册码** |
| 41 | `cookies` | 2 | 2 | `/cookies/fast-verify`、`/cookies/fast-verify/batch` | Cookie 快速校验 | 开源 | **做入口且开源** |
| 42 | `mediacrawler` | 2 | 2 | `/mediacrawler/login/open` | 媒体爬虫登录 | 注册码 | **做入口但注册码** |
| 43 | `ai-design` | 2 | 3 | `/ai-design/agents/quota` | AI 设计 Agent 配额 | 注册码 | **做入口但注册码** |
| 44 | `login-check` | 2 | 2 | `/login-check`、`/login-check/batch` | 登录态检查 | 开源 | **做入口且开源** |
| 45 | `monitor` | 2 | 4 | `/monitor/events`、`/monitor/transitions` | 监控事件与状态迁移 | 不做入口 | **不做入口** |
| 46 | `/`（根路径） | 1 | 1 | `/` | 服务根 | 忽略 | **不做入口** |
| 47 | `/health` | 1 | 1 | `/health` | 健康检查 | 忽略 | **不做入口** |
| 48 | `task-packages` | 1 | 3 | `/task-packages/{id}` | 任务包 CRUD（**GET/PUT/DELETE 仍为空壳**） | 注册码 | **做入口但注册码** |
| 49 | `persona-proxy` | 1 | 1 | `/persona-proxy/meta` | 网关元信息 | 注册码 | **做入口但注册码** |
| 50 | `skills` | 1 | 1 | `/skills/{id}` | 技能详情 | 开源 | **做入口且开源** |
| 51 | `tools` | 1 | 1 | `/tools/{id}/status` | 工具状态 | 开源 | **做入口且开源** |
| 52 | `ccswitch` | 1 | 1 | `/ccswitch/current` | 当前 CC 切换 | 开源 | **做入口且开源** |
| 53 | `matrix-assignments` | 1 | 1 | `/matrix-assignments` | 矩阵分配 | 开源 | **做入口且开源** |
| 54 | `getFile` | 1 | 1 | `/getFile` | 文件读取 | 忽略 | **不做入口** |
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

**✅ 马哥已定（2026-10-22）：选 C**（D1）。具体形态：把 `feature_gate.py` 的判定改成「**注册码授权条目 ∩ 订阅配额**」双维度 —— 本地注册码给出功能白名单，云端订阅给出额度（账号数/平台数/Agent 数/调用量）。这样你说的「大部分功能开放、少数要注册码」天然成立，且离线也能用。

### 3.4 必须先想清楚的两个问题（选完路线后我需要答案）

1. **注册码要不要绑机器？** 绑 → 难转手但可防共享；不绑 → 好卖但易被分享。
   → **✅ 已定（D2）：默认不绑机器（一码通用）；若后续启用绑定，允许用户自助解绑。**
2. **注册码的有效期策略？** 永久 / 固定期限（年卡）/ 按版本。以及到期后**已产生的数据是否还能查看**（建议能看不能新增，避免用户数据被锁死引发口碑问题）。
   → **✅ 已定（D3）：固定期限（年卡 / 季卡 / 月卡）。**
   → **✅ 已定（D4）：到期后已产生的数据「能看，不能新增」。**

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
| 建议改法 | — | README 改成两段：**①「我们基于什么」**（借鉴谱系 + 许可证）+ **②「我们在其上做了什么」**（按 §1 的 14 个分组给一张对照表，每项标注 开源/注册码），正好复用你这次的勾选结果 |

### 4.3 建议改法的简化版表格（已落进 README）

马哥反馈「原来的太复杂」后，README 改法压成**两张表**。表里的开放级别不是猜的 —— 全部来自
`cloud_service/billing/feature_gate.py` **已实现**的 11 个 flag（`max_accounts` 3→无限、
`max_platforms` 3→8、`agent_quota` 0→2、`data_recovery` / `persona` / `proxy_management` /
`stream_chat` 关闭→开启、`ai_mode` / `image_gen` 本地 Key→云端），因此是**事实陈述**而非预判；
等你勾选后若有调整，改的只是这两张表的个别单元格。

**表一 · 我们基于什么（借鉴与致谢）**

| 上游项目 | 许可证 | 我们拿走什么 | 我们自己加了什么 |
|---|---|---|---|
| social-auto-upload | MIT | 多平台发布适配器与 CLI 发布基础 | Web 工作台、账号体系、任务队列、审核与调度 |
| Douyin_TikTok_Download_API | Apache-2.0 | 抖音 / TikTok 解析与数据采集 | 统一的数据回收工作台与复盘看板 |
| HermesAgent（Nous Research） | MIT | 本地 AI Agent 运行时 | 对话式生成（HermesChat）、Agent 控制台与提示词体系 |
| Persona Studio | MIT | 浏览器身份 / 指纹 / Profile 层 | 代理网关、账号→身份→代理的固定绑定编排 |
| Easel（浙大 ZJU-REAL Lab） | Apache-2.0 | 内容创作工作台的 API 契约（仅参考，未 vendor 源码） | 内容库 / 收件箱 / 创作工作台 / 创作工坊 + 审核队列 |

谱系：`social-auto-upload (MIT)` → 本项目早期形态 `SynapseAutomation (Apache-2.0)` → **老马AI工作台 (AGPL-3.0)**。

**表二 · 我们在其上做了什么（新增能力与开放级别）**

| 能力组 | 新增能力 | 相对原项目 | Community | Pro |
|---|---|---|---|---|
| 概览 | 仪表盘、快速开始向导 | 全新 | 全部 | — |
| 资源 | 账号管理、素材库 | 沿用并重做 | 全部 | 账号数 3 → 无限 |
| 资源 | 代理管理、代理网关、Persona 指纹 | 全新 | — | 全部 |
| 内容 | 选题库、趋势热榜、内容拆解、账号画像、CMS | 全新 | 全部 | — |
| 内容 | 内容库、收件箱、创作工作台、创作工坊 | 全新 | 全部 | — |
| 生成 | AI 生图、视频流水线、图片编辑器 | 全新 | 本地自配 Key | 官方云端生图 / 渲染 |
| 产物 | 产物中心（统一产物 ID / 阶段流转 / 血缘） | 全新 | 全部 | — |
| 分发 | 矩阵发布、发布中心、发布任务、分发记录、排期日历、任务管理 | 沿用并重做 | 全部 | 平台数 3 → 8 |
| 分发 | 审核队列（队列 / 版本审批 / 敏感词库） | 全新 | 全部 | — |
| 分发 | 营销活动 + 任务包编排 | 全新 | — | 全部 |
| 数据 | 数据中心、趋势分析、各平台视频数据 | 数据回收扩到全部已接入平台 | 全部 | 数据回收增强 |
| 智能 | AI 对话、技能库 | 全新 | 全部 | — |
| 智能 | HermesChat 对话式生成 | 全新 | — | 流式对话 |
| 智能 | Agent 控制台、提示词配置、运行设置 | 全新 | — | Agent 配额 0 → 2 |
| AI-Fusion | 融合中心、风格库、内容审查、融合分析、融合配置 | 全新 | 全部 | — |
| AI-Fusion | 模型市场、供应商配置 | 全新 | — | 官方云端模型 |
| 开发者工具 | 工具中心（MCP / 技能）、演示控制台、系统设置 | 全新 | 全部 | 授权 / 订阅管理 |

> **为什么表里没有「营销活动」开源？** 因为它当前依赖任务包编排这条链路，是本次新增的增值能力；
> 若你希望开源，只需把该行 Community 改成「全部」。同理，`recovery` 域（数据回收）目前
> **未加 feature gate**（社区版可用），若要收进 Pro，需在 `recovery/router.py` 补 `_require_data_recovery`。

---

## 5. 开源前必须处理的一致性问题

| # | 问题 | 现状 | 谁来定 |
|---|---|---|---|
| 1 | NOTICE / VENDOR 许可证口径 | 已修（Apache-2.0 → AGPL-3.0，本项目与上游分段声明） | 你确认署名写法 |
| 2 | **「8 平台」三套口径** | README 写百家号 / 前端选知乎·头条·西瓜 / 后端实为百家号 | **✅ 已定（D5）：暂不承诺具体数量，README 与前端统一写「多平台」，等接入稳定后再写死数字** |
| 3 | `cloud_service/llm_proxy/prompts.py`（18KB / 381 行）是否留在开源树 | 目前留在树内，DB dump 的 `prompts` 表也在 | **✅ 已定（D6）：移出开源树，只在 Pro 包里提供**（下一批执行） |
| 4 | `/api/v1/recovery/*` 是否加 feature gate 收进 Pro | 本轮**未加**（纯本地快照、不消耗 TikHub 额度） | **✅ 已定（D7）：不收进 Pro，保持社区版可用** |
| 5 | **两个安装器必须重打包** | Community 构建于 2026-10-21 20:38、Pro 建于 10-16，**都早于当前 HEAD `c237474`**；你看到的旧侧边栏就是这么来的 | 我来打，你验 |
| 6 | 真实生产联调零验证 | 缺 `CLOUD_LLM_API_KEY`、支付宝/微信正式商户凭证与证书、TikHub Key → 支付与 TikHub 链路一次都没跑通 | **你**提供凭证 |
| 7 | 干净 VM 验证 | Community 安装器无代码签名（NotSigned），未在干净 Windows VM 完成装/启/卸/升验证 | 我来测 |
| 8 | 生成层统一产物 ID | ✅ **已落地**（2026-10-22）：统一产物总线 `art_*` + 阶段机 + 血缘，把生图 / 上传 / 渲染 / 审核 / 发布串成一条流水线（见 [dev-reports/2026-10-22-unified-artifact-bus.md](dev-reports/2026-10-22-unified-artifact-bus.md)）；**发布侧消费**（审核通过 → 一键发布）仍属下一阶段 | 已完成 |

---

## 6. 回执格式（已完成 · 2026-10-22）

> **首选**：直接在 `docs/oss-boundary-decision-form.docx` 里填好发回（Word 版逐项勾选表），
> 我用 `tmp/read_decision_form.py` 读出结果回填下表；下面这段是等价的纯文本回法。

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

## 7. 拍板结果（2026-10-22 已回）

> 来源：马哥在 `docs/oss-boundary-decision-form.docx`（Word 版拍板表）里的勾选，
> 由 `tmp/read_decision_form.py` 读出回填。**本节是后续所有工程实现的依据。**

### 7.1 总体决策

| # | 决策 | 结论 | 落地影响 |
|---|---|---|---|
| D1 | 注册码路线 | **C 双轨**：注册码解锁 + 订阅增值 | `feature_gate.py` 判定从「plan 常量」改为「**注册码授权条目 ∩ 订阅配额**」双维度 |
| D2 | 是否绑机器 | **默认不绑**（一码通用）；若启用绑定则允许自助解绑 | 注册码不写设备指纹；解绑开关留常量 |
| D3 | 有效期 | **固定期限**（年卡 / 季卡 / 月卡） | license 必带到期时间 |
| D4 | 到期后数据 | **能看，不能新增** | 到期后写操作拦截、读操作放行 |
| D5 | 8 平台口径 | **暂不承诺数量，只写「多平台」** | ✅ **已落代码**：README 引导句 / 两张表 / 场景说明与前端 badge 文案全部去掉写死的「8」；内部配额值不变 |
| D6 | `cloud_service/llm_proxy/prompts.py` | **移出开源树，只在 Pro 包提供** | ✅ **已落代码**（2026-10-23）：公开仓留 stub + 能力清单，模板正文走私有目录注入，见 §7.7 |
| D7 | `/api/v1/recovery/*` | **不收进 Pro，保持社区版可用** | ✅ **已落代码**：flag `data_recovery` 的 Community 值在云端实现 / 客户端实现 / 前端默认三处同步为 `true` |
| D8 | 平台细粒度 API 前端入口 | **不给，保持现状** | 账号页封装足够，不新增诊断页 |
| D9 | NOTICE 版权署名主体 | **保持**「老马AI工作台（Prism-Fusion）贡献者」 | NOTICE.txt 无需改动 |
| D10 | README 开放级别 | **按现状不调整** | 表二维持 feature gate 已实现的 11 个 flag 口径 |

### 7.2 逐项选择（109 项）

- **§1 功能清单 55 项**：拍板表里未逐项勾选 → **按「当前建议」列兜底**（含「注册码」→ 注册码，其余开源）。
- **§2 能力域 54 项**：同样未逐项勾选 → **按「当前建议」列兜底**，其中两处按 D6/D7 覆盖：
  - `recovery` → **做入口且开源**（D7 不收进 Pro）
  - `ai-prompts` → **做入口但注册码**（D6 云端 prompt 不开源）

> ⚠️ **兜底项是推断，不是你逐项确认过的**。若某一项与你的本意不符，直接说序号，我改。

### 7.3 运维与发布待办

| # | 事项 | 马哥的选择 | 状态 |
|---|---|---|---|
| 1 | 两个安装器重打包 | ☑ 同意重打包 | 待执行（Community 20:38 / Pro 10-16，均早于 HEAD） |
| 2 | 干净 Windows VM 验证 | **未勾** | 暂缓（无干净 VM 环境） |
| 3 | 真实生产联调凭证 | **未勾**（方式未填） | 暂缓 —— 支付 / TikHub 链路仍无真实验证 |
| 4 | 另一台电脑的仓库副本 | ☑ 冻结另一台 | 需人工介入：另一台电脑停止推送，或改用不同分支 |
| 5 | Pro 版是否现在发布 | ☑ 等边界定了再发 | 暂缓（依赖 D6 移动 + 真实 Key） |
| 6 | 功能清单文档落点 | ☑ 同意写回文档 | **已完成**（本文件 §1/§2「你选」列已回填） |
| 7 | 服务器工作副本同步 | ☑ 同意同步 | 待执行（快进 `/opt/prism-fusion`，不碰 Pay Skill 8090 / fde-api 8787 / nginx） |

### 7.4 由本节派生的待办批次

| 批次 | 内容 | 依赖 | 状态 |
|---|---|---|---|
| B1 | 注册码模块：签发端（Ed25519）+ 客户端输入入口（系统设置页）+ license 签名/校验 + 离线宽限 + 到期只读 | D1–D4 | ✅ **已完成**（2026-10-23，后端见 §7.9；前端入口见下） |
| B2 | `cloud_service/llm_proxy/prompts.py` 移出开源树，改 import 链与打包配置 | D6 | ✅ **已完成**（2026-10-23，方案 R2=A，见 §7.7） |
| B3 | README / 前端文案去掉写死的「8 平台」 | D5 | ✅ **已完成**（2026-10-22） |
| B4 | 两个安装器重打包 + 干净 VM 验证 | 待办 1、2 | 待执行（干净 VM 未勾） |
| B5 | 服务器工作副本同步 | 待办 7 | 待执行 |

### 7.5 本轮落地（2026-10-22）

**产出：feature gate 矩阵（机器可读 + 人读，同源生成）**

| 文件 | 说明 |
|---|---|
| `docs/feature-gate-matrix.json` | 机器可读矩阵：判定模型 / 12 个 flag / 6 个注册码条目 / 55 项功能 / 54 个能力域 |
| `docs/feature-gate-matrix.md` | 人读版，与 JSON 同源生成 |
| `scripts/docs/build_feature_gate_matrix.py` | 生成脚本：**生成时自动回读三处代码做交叉校验**（flag 缺失、或 `data_recovery` 不是 `true`，直接报错中止） |

**已改的代码（D5 / D7）**

| 文件 | 改动 | 依据 |
|---|---|---|
| `cloud_service/billing/feature_gate.py` | `COMMUNITY_FLAGS["data_recovery"]` `False` → `True` | D7 |
| `prism_backend/fastapi_app/api/billing_client.py` | 同上（客户端回落值） | D7 |
| `prism_frontend/src/lib/plan-flags.ts` | `DEFAULT_COMMUNITY_FLAGS.data_recovery` `false` → `true`；`platformsLabel` 对 Pro 改为「多」 | D7 / D5 |
| `prism_frontend/src/components/layout/plan-badge.tsx` | badge 文案「8 平台」→「多平台」 | D5 |
| `README.md` | 引导句 / 两张表 / 场景说明去掉写死的「8」；数据回收从「Pro 专属」改回「社区版基础可用」；D6 提示改为「已拍板」 | D5 / D7 / D6 |

**回归**：pytest `147 passed + 1 skipped` ｜ tsc `0` 错 ｜ vitest `336/336`。

> ⚠️ **本轮未解决的既知缺陷**：前端 wizard 平台选择器（`prism_frontend/src/components/wizard/scenarios.tsx`）给的是
> 知乎 / 头条 / 西瓜，而后端适配器实际支持 抖音 / 快手 / 小红书 / B站 / 视频号 / TikTok / YouTube / 百家号。
> D5 只处置了「对外承诺多少数量」，选择器与后端不一致属于功能缺陷，等接入稳定后统一（对应 §5 项 2）。

### 7.6 第二轮待决（4 处尾巴）· 已定（2026-10-23）

> 来源：`docs/oss-boundary-round2-decision-form.docx` 的勾选。
> **口径：R1–R4 一律按建议执行**（马哥 2026-10-23 明确「一切按照你的兜底模式来」）。

| 项 | 已定结论 | 落地状态 |
|---|---|---|
| R1 | **A：默认不绑机器**（一码通用）。日后若启用绑定，允许用户自助解绑；开关常量只留一处 | ✅ 已落设计：license 不写设备指纹；绑定/解绑开关集中在注册码模块一处 |
| R2 | **A：公开仓只留 stub，Pro 打包时注入真实文件** | ✅ **已落代码**（B2，见 §7.7） |
| R3 | **A：按兜底**（§1 55 项 + §2 54 项沿用「当前建议」列） | ✅ 已落文档（**推断，非逐项确认**；B1 界面出来后可再调） |
| R4 | **往上推进**：本机能做的先做；干净 VM 与真实生产凭证仍需马哥提供 | ⚠️ 部分推进（见 §7.3 状态列） |

| 文件 | 说明 |
|---|---|
| `docs/oss-boundary-round2-decision-form.docx` | 第二轮待决表本体（4 项，含一屏看完的速览表） |
| `scripts/docs/build_pending_decision_form.py` | 生成脚本 |
| `scripts/docs/read_pending_decision_form.py` | 回读脚本：读出勾选结果，**逐框**判定勾选状态（并列框互不干扰） |
| `scripts/docs/test_pending_decision_form_roundtrip.py` | 往返测试：造填好的副本 → 回读 → 断言读出结果一致 |

**实测**：zip 完整 / 14 个 XML 部件全解析 / 3 张表（4 + 3 + 5 行）/ 页脚 PAGE 域在位；
往返测试全绿 —— 勾选、未勾互不干扰、选择行、批注、并列框拆分 均读得准。

### 7.7 B2 落地（2026-10-23）：云端 prompt 移出开源树

**方案（R2=A）**：公开仓保留「能力契约」，把「模板正文」挪进被 gitignore 的私有目录，Pro 部署时注入。

| 内容 | 开源仓 | Pro 部署 |
|---|---|---|
| `PromptDef` 数据结构 | ✅ | 同 |
| `BASIC_PROMPTS`（基础模板正文） | ✅ | 同 |
| `CLOUD_PROMPT_MANIFEST`（云端模板的**名字/描述/变量**，API 契约） | ✅ | 同 |
| `CLOUD_PROMPTS`（**云端模板正文**） | ❌ 空 | 由 `_pro_assets/prompts_cloud.py` 注入 |

| 文件 | 改动 |
|---|---|
| `cloud_service/llm_proxy/prompt_def.py` | **新增**：把 `PromptDef` 拆成零资产依赖的独立模块，私有资产因此可以做成「纯数据、零 import」 |
| `cloud_service/llm_proxy/prompts.py` | **重写为公开 stub**：`CLOUD_PROMPTS` 改动态加载；新增 `CLOUD_PROMPT_MANIFEST` / `is_pro_required()` / `list_prompt_manifest()` / `reload_cloud_prompts()`；函数 API 全部保留 |
| `cloud_service/llm_proxy/router.py` | 云端 prompt 缺失时返回 **403「需 Pro 版」**（不再是 404「不存在」）；`GET /cloud/llm/prompts` 改用 manifest，能力清单始终可见 |
| `cloud_service/llm_proxy/schemas.py` | `PromptListItem` 增 `available: bool`（当前部署能否拿到模板正文） |
| `cloud_service/test_llm.py` | 云端相关断言按「资产是否就绪」分支（403 时**不扣额度**，连带影响后面两处额度断言，已一并条件化） |
| `cloud_service/test_prompts_oss_boundary.py` | **新增**：开源边界测试 —— 公开源码不得含模板正文（base64 marker，避免自指假阳性）、私有目录必须被 gitignore、资产缺失/损坏时的降级行为 |
| `scripts/cloud/inject_pro_assets.py` | **新增**：注入脚本（`--source` / `--target` / `--check` / `--force` / `--list`），只放行 `.py/.json/.txt` |
| `.gitignore` | 排除 `/cloud_service/llm_proxy/_pro_assets/` |

**私有资产的版本化归宿**：`D:\Prism-Fusion-Backup\pro-assets\prompts_cloud.py`
（sha256 `da5a7ad66683a625fbb6780629a15e7c3211eb63ede98335f30e2f56301d6e30`，7,587 字节）。
Pro 部署时用注入脚本从该目录同步到目标树；`--check` 模式校验两边一致。

**实测**：

| 形态 | 结果 |
|---|---|
| 有资产（Pro / 本机） | `pytest cloud_service` → **11 passed**；云端 chat 200、扣 1 额度 |
| 无资产（开源仓） | `pytest cloud_service` → **11 passed**；云端 chat 403「需 Pro 版」、**不扣额度** |
| 资产文件与 git 原文 | AST 提取后**逐字段字节一致**（5 条模板、version/description/variables/template 全等） |

> ⚠️ **未做**：服务器侧的私有资产分发（裸仓 / 同步脚本）尚未落地，当前只有本机 D 盘一份；
> Pro 版安装包也还没重打包（见 B4）。在补上这两项之前，Pro 部署要靠人工拷贝资产文件。


### 7.8 P0 修复（2026-10-23）：付费 Pro 用户被静默降级成 Community

在推进 B2 过程中做代码勘察时发现的**独立于开源边界的商业级缺陷**，已修。

**症状**：`cloud_service/billing/feature_gate.py` 的 `_resolve_plan()` 里用了
`select(Subscription)`，但文件顶部**漏了 `from sqlalchemy import select`**。
`NameError` 被该函数的 `except Exception` 静默吞掉，`plan` 永远回落 `"community"`。

**影响**：`GET /cloud/feature-flags` 对**所有用户**下发 Community 档位 flag ——
付费 Pro 用户拿到的 `persona=False`、`proxy_management=False`、`stream_chat=False`、
`max_accounts=3`、`max_platforms=3`、`ai_mode="local_key"`、`agent_quota=0`。
**且没有任何报错**（这正是它能潜伏这么久的原因）。

**根因不是漏 import，而是异常边界太宽**：`except Exception` 把「编程错误」
（NameError/TypeError/AttributeError）和「运行时故障」（云端 DB 抖动）混为一谈，
于是 bug 被伪装成了"正常降级"。

| 改动 | 内容 |
|---|---|
| `cloud_service/billing/feature_gate.py` | 补 `from sqlalchemy import select`；`except Exception` → `except SQLAlchemyError`（只吞真正的 DB 故障，并记 warning 日志），编程错误直接向上抛 |
| `cloud_service/test_feature_gate_plan.py` | **新增**回归测试：Pro 订阅 → plan=pro 且 Pro flag 全部下发；过期/取消/free/无订阅 → community；**编程错误必须向上抛，不得伪装成降级** |

**实测**：修复前 `resolve_plan(active pro) = 'community'`（Pro flag 全错）；
修复后 `= 'pro'`，`persona=True / max_accounts=-1 / ai_mode=cloud / agent_quota=2` 全部正确。

> ⚠️ **该缺陷从初始提交 `ac8978e` 起就存在**，与本次开源边界改造无关。
> 若线上已有付费用户，其 Pro 权限一直未生效 —— 需要在部署修复后通知并补偿。

### 7.9 B1 落地（2026-10-23）：注册码模块 + D4 只读守卫**真正落地拦截**

§7.4 的 B1 此前只有「机制」没有「拦截」——`require_write_allowed` 写好了却没挂到任何路由上。
本轮把它变成**真拦截**，并补齐注册码签发端。

**注册码链路（离线可用）**

| 环节 | 文件 | 说明 |
|---|---|---|
| 签发端 | `scripts/license/keygen.py` | Ed25519 密钥对生成，**私钥默认落仓库外**，不入库、不进安装包 |
| 签发端 | `scripts/license/issue_license.py` | 年/季/月卡（365/90/30 天）或指定到期日、授权条目、宽限天数、客户名 |
| 客户端 | `prism_backend/fastapi_app/core/license_keys.py` | 公钥 + 6 个授权条目 + 12 个 flag 容量表 + flag→条目映射 |
| 客户端 | `prism_backend/fastapi_app/core/license.py` | 验签、状态机、本地存储（原子写）、时钟回拨防护（24h 容差） |
| API | `prism_backend/fastapi_app/api/v1/license/router.py` | `GET /status`、`POST /activate`、`DELETE /`、`GET /effective-flags` |

token 格式：`PRISM1.<payload_b64url>.<sig_b64url>`；状态机
`missing / active / grace / expired / invalid / not_yet_valid`。

**D1=C 双轨交集**（`effective_flags`）：数值取小、布尔取与、模式两边都 `cloud` 才 `cloud`。
flag→条目映射以**矩阵 §1「Flag 真源表」为准**（`max_platforms` → `multi_platform`，
`core` 只覆盖 `max_accounts` / `data_recovery` / `team_members`）——§2 表历史上把
`max_platforms` 也列进 `core`，与 §1 冲突，以 §1 为准。

**D4 只读守卫（本轮从「机制」变「拦截」）**

| 文件 | 内容 |
|---|---|
| `prism_backend/fastapi_app/api/v1/license/guard.py` | 拦截面表 `READ_ONLY_RULES`（唯一真源）+ `is_blocked_write()` + ASGI 中间件 `ReadOnlyWriteGuard` |
| `prism_backend/fastapi_app/main.py` | 注册中间件 —— **必须早于**路径规范化中间件，否则 `/api/v1/v1/…` 形式匹配不上拦截表直接绕过 |
| `prism_backend/tests/test_license_readonly_guard.py` | **48 passed**：拦截面表 / 中间件真实行为 / 真实 app 嵌套顺序 / 规则不腐烂 |

**拦截原则（刻意不扩大）**：拦「能产出新内容 / 推进新状态」的写操作；
**放行「管理、清理、导出、停止、登录、改配置」**——否则到期用户会被锁死在
停不下正在跑的发布、删不掉自己的文件、导不出数据，甚至**没法输入新注册码**。
因此 `/campaigns/{id}/pause`、`/tasks/cancel/*`、`/license/activate`、`/auth/*`、
`/system/*`、`/data/*`、`/recovery/*` 一律**不在**拦截面内。

拦截面以**真实路由表**（298 条写路由）为准逐条核对，不是凭印象列路径；
`test_rules_match_real_routes` 会在路由改名/删除而规则没跟上时直接红。

紧急停用开关：环境变量 `PRISM_LICENSE_READONLY_GUARD=0` 关闭整个守卫。

---

## 附：本文档的复现方式

```powershell
# feature gate 矩阵（生成时自动回读代码做交叉校验）
python scripts/docs/build_feature_gate_matrix.py

# 第二轮待决表（生成 / 回读 / 往返测试）
python scripts/docs/build_pending_decision_form.py
python scripts/docs/read_pending_decision_form.py
python scripts/docs/test_pending_decision_form_roundtrip.py

# 后端端点真源
& 'D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe' -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:7000/api/openapi.json',timeout=30)); print(len(d['paths']))"

# 侧边栏结构与路由清单
& 'D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe' 'D:\dim开发\Prism-Fusion\tmp\count_sidebar.py'

# 路由 → 后端端点 + Mock 标记明细
& 'D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe' 'D:\dim开发\Prism-Fusion\tmp\dump_route_facts.py'
```
