# LaomaAI-Fusion 工作台开发记录

> 本文档面向未来接手项目的 AI Agent 和公司程序员，完整记录 LaomaAI-Fusion 工作台的
> 技术演进、功能模块、架构决策与开发历程。

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 借鉴与底座](#2-借鉴与底座)
- [3. 在底座之上新增的功能](#3-在底座之上新增的功能)
- [4. 基于 Hermes 的相关工作](#4-基于-hermes-的相关工作)
- [5. 前端页面与功能模块详解](#5-前端页面与功能模块详解)
- [6. 后端模块详解](#6-后端模块详解)
- [7. 架构设计](#7-架构设计)
- [8. 品牌重命名记录（老马AI工作台 → 老马AI研习社）](#8-品牌重命名记录prism--老马ai研习社)
- [9. 已知问题与修复记录](#9-已知问题与修复记录)
- [10. 开发约定与规范](#10-开发约定与规范)
- [11. 部署与启动](#11-部署与启动)
- [12. 开源项目引用](#12-开源项目引用)
- [13. 附录：关键文件索引](#13-附录关键文件索引)

---

## 1. 项目概述

**LaomaAI-Fusion**（品牌名：老马AI研习社）是一个 AI 驱动的多平台内容编排与自动化发布系统。
面向多账号、多素材、多平台的内容分发场景，提供从计划生成、任务调度到执行监控与数据回收的全链路能力。

### 1.1 核心定位

- **矩阵投放 / 分发中台**：把「账号、素材、计划、排期、执行、监控、回收」统一到可编排的任务系统中。
- **AI 内容编排引擎**：内置 HermesAgent（AI Agent），支持自然语言驱动的内容生成与投放。
- **可自托管**：FastAPI + Next.js + Celery/Redis + Patchright + Persona Studio，可本地或私有化部署。

### 1.2 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 16 (Turbopack) + TypeScript + Tailwind CSS |
| 后端 | FastAPI (Python 3.11+) |
| 任务队列 | Celery + Redis |
| 浏览器自动化 | Patchright (Playwright fork) |
| 桌面端 | Electron |
| AI Agent | HermesAgent (NousResearch) |
| 身份管理 | Persona Studio |
| 代理网关 | mihomo |
| 数据模型 | 商汤 SenseNova (GLM-5.2) |

### 1.3 服务端口

| 服务 | 端口 |
|---|---|
| FastAPI 后端 | 7000 |
| Next.js 前端 | 3000 |
| Automation Worker | 7001 |
| Supervisor API | 7002 |
| Persona API | 8787 |
| Persona per-country 代理网关 | 7771–7776 |
| Hermes Dashboard | 9119 |
| Hermes WebUI | 9131 |
| Redis | 6379 |

---

## 2. 借鉴与底座

### 2.1 主要借鉴项目

LaomaAI-Fusion 的建设受益于开源生态，以下项目的代码、架构或实现思路被采用或参考：

#### 2.1.1 social-auto-upload (SAU)

- **GitHub**: https://github.com/dreammis/social-auto-upload
- **许可证**: MIT
- **借鉴内容**: 上游 CLI 自动发布基础架构
- **采用方式**: SAU 提供了 YouTube、TikTok 与 CLI 自动发布的基础能力，
  老马AI工作台将其作为「平台能力补充」接入，而非复制其独立 Web 或运行架构。
  所有平台实现统一的 Adapter Contract。

#### 2.1.2 Douyin_TikTok_Download_API

- **GitHub**: https://github.com/Evil0ctal/Douyin_TikTok_Download_API
- **许可证**: Apache License 2.0
- **借鉴内容**: 抖音 / TikTok 解析与数据能力参考
- **采用方式**: 用于数据回收阶段，支持抖音、B 站、TikTok 的视频数据采集。

#### 2.1.3 HermesAgent

- **GitHub**: https://github.com/nousresearch/hermes-agent
- **许可证**: MIT
- **借鉴内容**: 本地 AI Agent 运行时与集成参考
- **采用方式**: 作为内置 AI Agent 运行时，深度集成到 老马AI工作台的编排流程中。
  详见 [第 4 节](#4-基于-hermes-的相关工作)。

#### 2.1.4 Persona Studio

- **GitHub**: https://github.com/TechQaiser/persona-studio
- **许可证**: MIT
- **借鉴内容**: 浏览器身份 / 指纹 / Profile 层
- **采用方式**: 作为 老马AI工作台的 Browser Identity / Fingerprint / Profile 层。
  提供相干指纹生成、Profile 持久化、持久会话等能力。
  不自研指纹、Profile 存储、指纹伪造，全部交给 Persona Studio。

---

## 3. 在底座之上新增的功能

### 3.1 核心能力（矩阵投放闭环）

#### 3.1.1 投：矩阵发布与调度

- 多平台、多账号、多素材组合发布。
- 批量生成任务、统一入队、并发调度。
- 定时发布、结果回传、失败重试。

#### 3.1.2 管：账号与任务运营

- 账号绑定、状态监控、异常提醒。
- 任务队列看板、执行日志可视化。
- 每账号固定身份绑定（账号 → 浏览器身份 → 固定代理 → 浏览器执行）。

#### 3.1.3 回：数据回收

- 当前支持：抖音、B 站、TikTok、YouTube。
- 预留可扩展：快手、小红书、视频号等。

#### 3.1.4 编：AI 编排加速

- 内置 HermesAgent AiAgent 助手（装备 Computer Use、各类 MCP、Skill、长记忆、多 Agent）。
- 自然语言生成/润色标题、标签、话题等投放配置。
- 支持"一句话投放"。

### 3.2 新增功能模块详解

#### 3.2.1 Persona Studio —— 浏览器身份层

集成 Persona Studio 作为 老马AI工作台的 **Browser Identity / Fingerprint / Profile 层**：

- **相干指纹生成**：OS / UA / GPU / 屏幕 / 时区 / 语言彼此一致，避免"macOS UA 配 NVIDIA GPU"这类一眼假组合。
- **Profile 持久化**：Cookie / LocalStorage / IndexedDB 随 Profile 留存，登录一次、下次启动仍在。
- **持久会话**：账号登录态跨任务复用，无需重复扫码。
- **引擎可选**：`cloak`(CloakBrowser) / `camoufox` / `patchright` / `playwright`（默认 `patchright`）。
- **代理注入 + 出口 IP / 泄漏检测**。

**关键设计**：
- 账号表 `cookie_accounts` 增加 `persona_profile_id`（默认 = account_id）、`browser_backend`（patchright / persona）、`proxy_id`。
- 一个 老马AI工作台 账号 ↔ 一个 Persona Profile。
- 不安装 Persona 时自动回退 **Patchright 直连模式**（每账号独立 `data/browser_profiles/<account>/` persistent context），功能不中断，仅少相干指纹/持久会话增强。
- Persona serve：`http://127.0.0.1:8787`（`PERSONA_API_URL`）。

#### 3.2.2 per-country 代理网关

独立的官方 **mihomo** 网关（`tools/persona-studio/proxies/`）提供 **将订阅遍历映射为 HTTP/SOCKS mixed 端口**，各路由到一个地区节点：

| 地区 | 端口 | locale / 时区对齐 |
|---|---|---|
| 直连 | — | 本机网络 + 本机 locale/时区 |
| 🇸🇬 新加坡 (sg) | 7771 | en-SG / Asia/Singapore |
| 🇯🇵 日本 (jp) | 7772 | ja-JP / Asia/Tokyo |
| 🇺🇸 美国 (us) | 7773 | en-US / America/New_York |
| 🇩🇪 德国 (de) | 7774 | de-DE / Europe/Berlin |
| 🇹🇼 台湾 (tw) | 7775 | zh-TW / Asia/Taipei |
| 🇭🇰 香港 (hk) | 7776 | zh-HK / Asia/Hong_Kong |

- 账号通过 `GET/PUT /api/v1/accounts/{id}/persona-proxy` 绑定地区。
- 进程启动浏览器时，按绑定注入对应代理，并按 country 对齐 **locale / 时区 / 国家**，让指纹更真实。
- 未绑定地区（direct）或未勾选时，回退到 **IP 池代理**（Proxy Manager 的 sticky 绑定）。

#### 3.2.3 代理管理（Proxy Manager / IP 池）

老马AI工作台 自研的代理管理：
- 登记标准 HTTP/SOCKS5 endpoint，自动健康检测（延迟 / 可用性）。
- **sticky 固定绑定**：`proxy_id` 权威落账号表，同一账号始终走同一代理。
- 批量导入 / 导出、自动绑定（从空闲池按 region 匹配）、`max_bindings` 上限。
- 每账号环境视图（`GET /api/v1/accounts/{id}/environment`）：展示 Browser + Proxy + Runtime 状态。

> 3Proxy / gluetun / sing-box 等只产出标准 HTTP/SOCKS5 endpoint 登记进 Proxy Manager，不进入 老马AI工作台 核心业务。

#### 3.2.4 浏览器运行时管理

设置页「浏览器管理」提供：
- **运行时检测**：Patchright 是否安装、当前采用哪种运行时。
- **浏览器资源**：Chromium / Firefox 的安装、卸载与版本识别，可一键 `patchright install`。
- **系统 Chrome 优先**：倾向于使用本机 Chrome，而非下载的 Chromium。
- **无头/有人头运行**：写入 `.env` 的 `PLAYWRIGHT_HEADLESS`，web 设置页可切换。
- **进程管理**：重启、停止与退出 Supervisord / PM2 管理的进程。
- **数据清理**：素材、账号与 Cookies、浏览器数据、缓存。
- **应急工具**：系统自检、日志导出、强制停止。

#### 3.2.5 开发者工具中心

`/tools` 页面统一管理可一键安装的开发工具，按 **skill / MCP / 插件 / 组件** 分类：
- 已收录：`deepseek-harness`、`ccswitch`、`computer-use-linux`、`hermes-agent`、`persona-studio`。
- **一键安装 / 卸载**：克隆 + 构建（如 persona dashboard 构建）。
- **启动 / 调用**：已装桌面应用（如 CC Switch）可从 老马AI工作台 直接打开。
- **Hermes 技能软启用 / 停用**：技能（`SKILL.md`）在 `active` 与 `_disabled` 目录间移动，**不物理删除**。
- 后端：`GET /api/v1/tools`、`/{id}/install`、`/{id}/uninstall`、`/{id}/launch`、`/{id}/build`、`/{id}/toggle`。

#### 3.2.6 CMS 隐藏后台

`/cms` 隐藏管理后台，集中控制运行开关（修改后需重启后端生效）：
- **抖音登录模式**：`browser`（正式 / 当前模拟）↔ `http`（逆向 HTTP 测试）。
- **浏览器后端**：`patchright` / `persona`。
- **无头模式**：`PLAYWRIGHT_HEADLESS`。
- 相关 `.env`：`LAOMA_DOUYIN_LOGIN_MODE`、`LAOMA_BROWSER_BACKEND_DEFAULT`。

#### 3.2.7 账号登录体验改进

- **二维码登录**：支持取消（停止连接/轮询）与重试。
- **从本机 Chrome 导入**：复制本机 Chrome 的 Cookies/Local State 到 老马AI工作台 专用 profile（非无痕），无需关闭 Chrome。
- **TikTok / YouTube**：恢复上游 SAU 交互式登录，修复 `--no-sandbox` 崩溃、cookie 抓取与账号入库。
- **Toast 自动关闭**：修复 Radix 暂停态导致通知不自动关闭的问题。

#### 3.2.8 每账号运行时锁

Redis 每账号 Browser Runtime 分布式锁（`runtime_lock_service`）：
- 保证同一账号的浏览器任务串行执行，避免并发互踩。
- 心跳续期，异常自动释放。

#### 3.2.9 TikTok / YouTube 数据采集 + TikHub 账号信息自动回填

- **TikTok 视频数据采集**：通过 TikHub Web API 自动把账号数字 uid 解析为完整 secUid，拉取作品列表。
- **YouTube 视频数据采集**：通过 TikHub 频道 API 拉取频道视频列表。
- **账号信息自动回填**：TikTok / YouTube 浏览器登录成功后，自动用 TikHub 反查账号真实资料。
- **YouTube 频道注册解析**：添加 YouTube 账号时支持直接填频道名 / @handle / 频道链接，一键解析。
- 依赖 TikHub API Key（`ai_model_configs` 表配置）。

#### 3.2.10 Fusion AI 模块（LaomaAI-Fusion 核心 AI 能力）

`prism_backend/fusion_ai/` 目录下的 AI 能力模块，统一挂载到 `/api/fusion/*`：

| 模块 | 功能 | 优先级 |
|---|---|---|
| `provider_registry` | Provider 注册表（模型提供商管理） | P0 |
| `platform_styles` | 平台差异化风格（不同平台文案风格适配） | P0 |
| `image_generators` | AI 生图（多模型支持） | P0 |
| `hot_topics` | 热点话题（实时热点抓取） | P0 |
| `content_moderator` | 三层内容审核（敏感词/政策/合规） | P0 |
| `model_market` | 模型广场（模型推荐与 API Key 管理） | P1 |
| `skill_workshop` | 技能工坊（可复用的内容生成技能链） | P1 |
| `cognition` | 认知系统（内容 DNA 分析、受众画像推断） | P1 |
| `nl_query` | NL→SQL 数据分析（自然语言查询数据） | P1 |
| `config_center` | 前台配置中心（敏感词/风格覆盖统一入口） | P1 |
| `breakdown` | 内容拆解（商汤 SenseNova 直连，把选题拆成结构化 JSON） | P0 |

#### 3.2.11 内容拆解（Breakdown）

基于商汤 SenseNova（GLM-5.2）的内容拆解功能：
- 把选题/文案拆成结构化 JSON（summary/structure/hooks/beats/insights/actionItems/risks）。
- Key 从 `tools/hermes-home/config.yaml` 读取（不硬编码、不落日志/响应）。
- 走 openai SDK → `https://token.sensenova.cn/v1`。
- 429 自动重试 1 次。
- 支持 JSON 解析纠错重试（模型偶尔输出 markdown 列表而非 JSON 数组时自动纠正）。

#### 3.2.12 视频流水线（Video Pipeline）

`prism_backend/video-pipeline/` 目录下的视频处理流水线：
- 支持视频剪辑、合成等处理。
- 前端 `video-pipeline` 页面提供模板库和流水线管理。
- 运行记录持久化在 `prism_backend/video-pipeline/runs/` 下。

#### 3.2.13 Easel 内容工作台

前端 `easel-content`、`easel-inbox`、`easel-workbench` 三个页面：
- 内容创作工作台。
- 收件箱（审核/任务通知）。
- 工作管理面板。

#### 3.2.14 Workshop（工坊）

前端 `workshop` 页面：
- AI 技能工坊的 Web 界面。
- 对应后端 `skill_workshop` 模块。

#### 3.2.15 Breakdown（拆解）

前端 `breakdown` 页面：
- 内容拆解的 Web 界面。
- 调用 `/api/v1/fusion/breakdown` API。
- localStorage key 已从 `laoma.breakdown.history` 改为 `lao_ma.breakdown.history`（品牌重命名）。

---

## 4. 基于 Hermes 的相关工作

### 4.1 HermesAgent 集成架构

老马AI工作台 内置 HermesAgent（基于 NousResearch 的 Hermes Agent），作为 AI 助手深度集成到发布流程中。

#### 4.1.1 集成层文件

```
prism_backend/fastapi_app/agent/
├── hermes_agent.py        # CLI 桥接 + Dashboard/WebUI 进程托管
├── hermes_config.py       # llm_config.toml ↔ hermes-home/config.yaml 同步
├── hermes_update.py       # 更新调度器
├── mcp_server.py          # stdio MCP server（暴露 BaseTool 目录）
├── hermes_tools.py        # 核心工具（账号/素材/发布）
├── hermes_tools_extended.py  # 扩展工具（IP池/脚本/Cookie）
├── hermes_tools_social_api.py  # 社媒 API 工具
├── tikhub_tools.py        # TikHub 工具
└── tool_runtime.py        # BaseTool/ToolResult 基类
```

#### 4.1.2 配置同步机制

- **用户编辑入口**：`prism_backend/config/llm_config.toml`（`[llm]` provider/model/api_key/base_url，`[runtime]` max_turns）。
- **同步逻辑**：保存时由 `hermes_config.py::sync_agent_config_to_runtime` 同步到 `tools/hermes-home/config.yaml`。
- **MCP 注册**：同步时自动写入 `mcp_servers.prism`（指向 `python -m fastapi_app.agent.mcp_server`）。

#### 4.1.3 默认预加载技能

每次 Hermes 会话默认预加载 `prism-project-layout` 技能（`--skills prism-project-layout`），
见 `hermes_agent.py` 的 `DEFAULT_PRELOAD_SKILL` 常量。

### 4.2 Hermes MCP 工具清单

Hermes 通过 `tools/hermes-home/config.yaml` 的 `mcp_servers.prism` 注册了一个 stdio MCP server，
把 `fastapi_app/agent/` 下所有 `BaseTool` 子类暴露为可调用工具。

#### 4.2.1 账号/素材/发布工具（hermes_tools.py）

| 工具 | 说明 |
|---|---|
| `list_accounts` | 列出可用账号（platform/status 筛选） |
| `list_files` / `get_file_detail` | 素材视频列表 / 详情 |
| `generate_ai_metadata` | AI 生成标题/标签（支持平台网感文案规则 + 字数/话题红线） |
| `publish_batch_videos` | 批量发布视频 |
| `create_publish_preset` / `list_publish_presets` / `use_preset_to_publish` | 发布预设管理 |
| `get_task_status` / `list_tasks_status` | 任务状态查询 |
| `data_analytics` | 数据分析报告 |
| `external_video_crawler` / `account_video_crawler` | 外部链接抓取 / 项目账号视频抓取 |

#### 4.2.2 扩展工具（hermes_tools_extended.py）

| 工具 | 说明 |
|---|---|
| `ip_pool_manager` | IP 池 list/add/remove/test |
| `run_backend_script` | 执行后端白名单脚本 |
| `cookie_manager` | Cookie list/export/import/refresh |

#### 4.2.3 社媒 API 工具（hermes_tools_social_api.py）

| 工具 | 说明 |
|---|---|
| `douyin_fetch_user_info` / `douyin_fetch_user_videos` / `douyin_fetch_video_detail` | 抖音数据 |
| `tiktok_fetch_user_info` / `tiktok_fetch_user_videos` / `tiktok_fetch_video_detail` | TikTok 数据 |
| `bilibili_fetch_user_info` / `bilibili_fetch_user_videos` / `bilibili_fetch_video_detail` | B 站数据 |

#### 4.2.4 TikHub 工具（tikhub_tools.py）

| 工具 | 说明 |
|---|---|
| `tikhub_kuaishou_user_info` / `tikhub_kuaishou_user_posts` | 快手数据 |
| `tikhub_xiaohongshu_user_info` / `tikhub_xiaohongshu_user_notes` / `tikhub_xiaohongshu_note_id` | 小红书数据 |
| `tikhub_wechat_channels_home` / `tikhub_wechat_channels_video_detail` | 视频号数据 |

### 4.3 Hermes 技能目录

`docs/hermes-skills/` 目录下的技能文件：

| 技能 | 说明 |
|---|---|
| `prism-project-layout` | 项目布局与调用指南（默认预加载） |
| `prism-publish-douyin` | 抖音发布技能 |
| `prism-publish-kuaishou` | 快手发布技能 |
| `prism-publish-xiaohongshu` | 小红书发布技能 |
| `prism-publish-channels` | 视频号发布技能 |
| `prism-publish-bilibili` | B 站发布技能 |
| `prism-publish-tiktok` | TikTok 发布技能 |
| `prism-publish-youtube` | YouTube 发布技能 |
| `prism-publish-baijiahao` | 百家号发布技能 |
| `prism-title-topic` | 标题与话题生成技能 |
| `douyin-publish-computeruse` | 抖音发布 Computer Use 技能 |

**同步机制**：更新时只编辑 `docs/hermes-skills/prism-project-layout/SKILL.md`，
Hermes 会话准备时由 `hermes_config.py::sync_prism_project_skill()` 自动同步到
`tools/hermes-home/skills/software-development/prism-project-layout/` 与
`runtime-data/app/hermes-home/skills/software-development/prism-project-layout/`
（后两者在 `.gitignore` 内，不入库）。

### 4.4 Hermes API 端点

| API | 说明 |
|---|---|
| `POST /api/v1/agent/hermes-run` | 一次性执行 |
| `POST /api/v1/agent/hermes-stream` | SSE 流式执行 |
| `POST /api/v1/agent/hermes-stop` | 停止执行 |
| `POST /api/v1/agent/hermes-confirm` | 确认/审批 |
| `GET /api/v1/agent/config/hermes` | 获取 Hermes 配置 |
| `PUT /api/v1/agent/config/hermes` | 更新 Hermes 配置 |
| `GET /api/v1/agent/config/hermes/runtime` | 运行时状态 |
| `POST /api/v1/agent/config/hermes/dashboard/start` | 启动 Dashboard/WebUI |
| `POST /api/v1/agent/config/hermes/dashboard/stop` | 停止 Dashboard/WebUI |
| `GET /api/v1/agent/config/hermes/update` | 检查更新 |
| `PUT /api/v1/agent/config/hermes/update/settings` | 更新设置 |
| `POST /api/v1/agent/config/hermes/update/check` | 触发更新检查 |
| `POST /api/v1/agent/config/hermes/update/apply` | 应用更新 |

### 4.5 Hermes 前端页面

前端 `chat`、`ai-agent`、`skills`、`workshop` 页面与 Hermes 集成：

- **`chat` 页面**：HermesAgent 对话界面，支持自然语言驱动的内容生成与投放。
- **`ai-agent` 页面**：AI Agent 管理界面。
- **`skills` 页面**：技能管理界面。
- **`workshop` 页面**：技能工坊界面，对应后端 `skill_workshop` 模块。

### 4.6 Hermes 与 老马AI工作台的交互模式

```
用户
  │
  ├── Web UI (/chat, /ai-agent)
  │     │
  │     ▼
  ├── HermesAgent (内置)
  │     │
  │     ├── MCP Server (stdio)
  │     │     │
  │     │     ├── hermes_tools.py (账号/素材/发布)
  │     │     ├── hermes_tools_extended.py (IP池/脚本/Cookie)
  │     │     ├── hermes_tools_social_api.py (社媒API)
  │     │     └── tikhub_tools.py (TikHub)
  │     │
  │     ├── Hermes Skills (预加载 + 按需加载)
  │     │     │
  │     │     ├── prism-project-layout (默认预加载)
  │     │     ├── prism-publish-* (各平台发布技能)
  │     │     └── prism-title-topic (标题生成技能)
  │     │
  │     └── 长记忆 / 多 Agent
  │
  └── CLI (prism)
        │
        └── Domain Service (后端 API)
```

### 4.7 Gemini Computer Use 集成

老马AI工作台支持 Google Gemini Computer Use 作为**受控诊断与修复辅助**：

**定位**：Computer Use 仅在 Patchright 定位失败时收集截图与候选动作，辅助生成可审查的平台适配器代码补丁。它不在正式发布任务中执行点击、填写或提交。正式发布始终使用版本化、可测试的 Patchright 平台适配器。

**禁止行为**：
- 不得在生产账号上自行点击最终"发布"、删除、支付等不可逆操作。
- 不得绕过验证码、风控、人机验证或平台安全机制。
- 不得读取或外传完整 Cookie、密码、私信、个人信息、密钥和未脱敏截图。
- 不得未经审核写入生产选择器配置或代码。
- 不得因模型建议改变 Campaign 内容、发布时间或目标账号。

**本地 MCP 工具**：
```
diagnose_automation_failure(task_id)
open_repair_sandbox(platform, fixture_or_test_account)
request_computer_use_trace(repair_session_id, goal)
create_repair_proposal(repair_session_id)
run_selector_regression(proposal_id)
submit_repair_for_review(proposal_id)
```

---

## 5. 前端页面与功能模块详解

前端代码位于 `prism_frontend/src/app/`，采用 Next.js App Router 结构。

### 5.1 页面清单

| 目录 | 页面 | 功能说明 |
|---|---|---|
| `/` | `page.tsx` | 首页/入口页 |
| `/dashboard-demo` | `page.tsx` | 仪表盘演示页 |
| `/account` | `page.tsx` | 账号管理（多平台账号绑定与状态监控） |
| `/materials` | `page.tsx` | 素材管理（批量上传、AI 标题/标签润色） |
| `/campaigns` | `page.tsx` | 投放计划管理（矩阵计划创建与调度） |
| `/tasks` | `page.tsx` | 任务队列看板（执行状态、日志、重试） |
| `/publish` | `page.tsx` | 发布中心（矩阵发布、批量发布） |
| `/analytics` | `page.tsx` | 数据分析（发布统计、互动、增长、趋势） |
| `/chat` | `page.tsx` | AI 对话（HermesAgent 自然语言交互） |
| `/ai-agent` | `page.tsx` | AI Agent 管理 |
| `/skills` | `page.tsx` | 技能管理 |
| `/workshop` | `page.tsx` | 技能工坊 |
| `/breakdown` | `page.tsx` | 内容拆解（SenseNova 集成） |
| `/fusion` | `page.tsx` | Fusion AI 集成页面 |
| `/video-pipeline` | `page.tsx` | 视频流水线管理 |
| `/calendar` | `page.tsx` | 日历（发布排期可视化） |
| `/trends` | `page.tsx` | 热点趋势 |
| `/ideas` | `page.tsx` | 创意灵感库 |
| `/persona` | `page.tsx` | Persona 身份管理 |
| `/persona-proxy` | `page.tsx` | Persona 代理管理 |
| `/ip-pool` | `page.tsx` | IP 池管理 |
| `/cms` | `page.tsx` | CMS 隐藏后台 |
| `/settings` | `page.tsx` | 系统设置（浏览器管理、运行时配置） |
| `/tools` | `page.tsx` | 开发者工具中心 |
| `/profile` | `page.tsx` | 用户个人设置 |
| `/easel-content` | `page.tsx` | Easel 内容创作 |
| `/easel-inbox` | `page.tsx` | Easel 收件箱 |
| `/easel-workbench` | `page.tsx` | Easel 工作台 |
| `/api/*` | 多个路由 | Next.js API Routes（前端代理后端） |

### 5.2 关键组件

| 文件 | 说明 |
|---|---|
| `layout.tsx` | 根布局（侧边栏 + 内容区），品牌名"老马AI研习社" |
| `globals.css` | 全局样式（暗色主题，CSS 变量体系） |
| `sidebar-new.tsx` | 新版侧边栏（品牌 Logo + 导航） |
| `external-modules.ts` | 外部模块注册（`ai-fusion` 等） |
| `mock-data.ts` | Mock 数据（开发用） |

### 5.3 API Routes

前端 `api/` 目录下的 Next.js API Routes 作为后端代理层：

| 路由 | 说明 |
|---|---|
| `api/tasks/route.ts` | 任务队列代理（聚合后端任务队列 + 发布历史） |
| `api/accounts/route.ts` | 账号管理代理 |
| `api/dashboard/route.ts` | 仪表盘数据代理 |
| `api/publish/route.ts` | 发布管理代理 |
| `api/materials/route.ts` | 素材管理代理 |
| `api/system-feed/route.ts` | 系统通知代理（读取后端日志） |

---

## 6. 后端模块详解

后端代码位于 `prism_backend/`，采用 FastAPI 框架。

### 6.1 核心目录结构

```
prism_backend/
├── fastapi_app/          # FastAPI 主应用
│   ├── main.py           # 应用入口
│   ├── api/v1/           # v1 API 路由
│   │   ├── agent/        # Hermes Agent API
│   │   └── ...           # 其他路由模块
│   ├── agent/            # Hermes 集成层
│   ├── core/             # 核心配置与工具
│   └── services/         # 业务服务
├── ai_service/           # AI 服务（标题生成、元数据生成等）
├── fusion_ai/            # Fusion AI 模块（P0/P1 能力）
├── video-pipeline/       # 视频流水线
├── uploader/             # 各平台上传统一封装
│   ├── douyin/
│   ├── kuaishou/
│   ├── xiaohongshu/
│   ├── tencent/          # 视频号
│   ├── bilibili/
│   ├── baijiahao/
│   ├── tiktok/
│   └── youtube/
├── automation/           # 自动化工作流
├── automation_worker/    # Celery Worker
├── platforms/            # 平台适配器
├── reverse_api/          # 逆向 API
├── biliup/               # B 站上传工具
├── browser_profiles/     # 浏览器档案（本地数据，不提交）
├── cookiesFile/          # Cookie 文件（本地数据，不提交）
├── fingerprints/         # 指纹数据（本地数据，不提交）
├── config/               # 配置
├── db/                   # 数据库（本地数据，不提交）
├── data/                 # 数据文件（本地数据，不提交）
├── storage/              # 存储
├── uploads/              # 上传文件
├── logs/                 # 日志（本地数据，不提交）
└── tools/                # 工具脚本
```

### 6.2 API 路由前缀

| 前缀 | 说明 |
|---|---|
| `/api/v1/ping` | 连通性测试 |
| `/api/v1/accounts` | 账号管理（列表/增删改/状态） |
| `/api/v1/accounts/tools` | 账号工具 |
| `/api/v1/campaigns` `/plans` `/task-packages` | 投放计划 / 计划别名 / 任务包 |
| `/api/v1/auth` `/auth/login/browser` | 登录认证 / 浏览器登录 |
| `/api/v1/files` `/materials` | 文件管理 / 素材管理 |
| `/api/v1/analytics` | 数据分析 |
| `/api/v1/scripts` | 后端脚本执行 |
| `/api/v1/publish` | 发布管理 |
| `/api/v1/tasks` `/tasks/distribution` | 任务队列 / 分发别名 |
| `/api/v1/recovery` | 恢复/补偿 |
| `/api/v1/data` | 数据 |
| `/api/v1/ai` `/ai/threads` `/ai-prompts` | AI 服务 / 线程 / AI 配置 |
| `/api/v1/dashboard` | 仪表盘 |
| `/api/v1/system` `/browser-profiles` | 系统维护 / 浏览器档案 |
| `/api/v1/verification` | 验证码 |
| `/api/v1/agent` `/agent/config` | Hermes Agent API |
| `/api/v1/matrix` | 矩阵发布调度 |
| `/api/v1/manual-tasks` | 人工任务管理 |
| `/api/v1/ip-pool` | IP 池管理 |
| `/api/v1/concurrency` | 并发控制 |
| `/api/v1/cookies` | Cookie 管理 |
| `/api/v1/creator` | 创作者中心 |
| `/api/v1/mediacrawler` | MediaCrawler |
| `/api/v1/crawler` | 混合爬虫 |
| `/api/v1/tikhub` | TikHub 桥接 |
| `/api/v1/persona-proxy` | 代理网关 |
| `/api/v1/persona` | Persona Dashboard 托管 |
| `/api/v1/platforms` | 平台总入口 |
| `/api/v1/platforms/douyin` `/kuaishou` `/xiaohongshu` `/tencent` `/bilibili` `/tasks` | 各平台接口 |
| `/api/v1/tools` | 开发者工具 |
| `/api/v1/ccswitch` | CC Switch 桥接 |
| `/api/fusion/*` | Fusion AI 模块（provider/styles/images/topics/moderation 等） |

### 6.3 平台适配器

支持的平台（每个平台都有独立的 uploader 目录和 Adapter Contract）：

| 平台 | 上传类型 | 登录方式 | 数据回收 |
|---|---|---|---|
| 抖音 | 视频 + 图文 | 扫码 / HTTP | ✅ |
| 快手 | 视频 + 图文 | 扫码 | 预留 |
| 小红书 | 视频 + 图文 | 扫码 | 预留 |
| 视频号 | 视频 | 扫码 | 预留 |
| B 站 | 视频 | biliup 交互登录 | ✅ |
| TikTok | 视频 | 浏览器登录 | ✅ (TikHub) |
| YouTube | 视频 | 浏览器登录 | ✅ (TikHub) |
| 百家号 | 视频 | 扫码 | 预留 |

### 6.4 Adapter Contract（平台适配器契约）

所有平台实现相同的契约：

```python
prepare_session()          # 准备会话环境
validate_account()         # 验证账号
validate_payload()         # 验证载荷
upload_media()             # 上传媒体文件
apply_platform_metadata()  # 设置平台元数据（标题/标签/话题等）
schedule_or_publish()      # 定时或立即发布
verify_receipt()           # 验证发布回执
capture_diagnostics()      # 捕获诊断信息（截图/DOM等）
```

### 6.5 矩阵投放流程（SOP）

1. **绑定账号**（多平台账号矩阵，可绑定浏览器身份 + 固定代理 + per-country 代理地区）。
2. **素材入库**（批量上传 / AI 标题标签润色）。
3. **创建矩阵计划**（平台、账号、素材、话题、封面、定时策略）。
4. **生成矩阵任务并调度执行**（队列化、并发、失败重试、每账号运行时锁）。
5. **看板监控与日志审计**（异常提醒 / 人工介入点）。
6. **数据回收**（抖音、B 站）并复盘迭代。

---

## 7. 架构设计

### 7.1 当前架构

```text
┌─────────────────────────────────────────────────────────┐
│  前端 (Next.js 16)                                        │
│  prism_frontend/ (端口 3000)                              │
│  - Web 控制台 / Electron 桌面端                            │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────────┐
│  后端 (FastAPI)                                           │
│  prism_backend/fastapi_app/ (端口 7000)                   │
│  - 矩阵调度 / 任务队列 / 账号管理 / AI 服务                   │
└───────┬───────────────┬───────────────────┬──────────────┘
        │               │                   │
┌───────▼───────┐  ┌────▼─────┐  ┌─────────▼──────────────┐
│ Celery + Redis │  │ Hermes   │  │ 视频流水线                 │
│ 任务队列 (6379) │  │ Agent    │  │ video-pipeline/          │
│               │  │ (9119/9131)│  │                        │
└───────────────┘  └──────────┘  └────────────────────────┘
        │
┌───────▼───────────────────────────────────────────────────┐
│  浏览器自动化 (Patchright)                                  │
│  - 各平台 Adapter 驱动                                     │
│  - Persona Studio (8787) 身份管理                          │
│  - mihomo 代理网关 (7771-7776)                            │
└───────────────────────────────────────────────────────────┘
```

### 7.2 固定链路

```text
Account
  → persona_profile_id（老马AI工作台 账号表）
  → Persona Profile（指纹 + 持久会话）
  → Sticky Proxy（Proxy Manager 注入 / per-country 代理）
  → Patchright（connect_over_cdp 驱动）
  → Platform Adapter（发布 / 登录 / 数据回收）
```

### 7.3 职责边界

| 层 | 归属 |
|---|---|
| 账号 / 平台 / 任务 / Celery / Redis | 老马AI工作台 |
| 代理网关（per-country 端口 7771–7776） | mihomo（Persona proxies） |
| Proxy Manager（proxies、sticky 绑定、健康检测） | 老马AI工作台 |
| Browser Identity / Fingerprint / Profile | Persona Studio |
| 浏览器执行（平台 Adapter 驱动） | 老马AI工作台 Patchright（`connect_over_cdp`） |
| AI Agent 运行时 | HermesAgent |
| 模型 API 调用 | SenseNova (商汤) / OpenAI 兼容接口 |

### 7.4 目标架构（规划中）

目标架构文档位于 `docs/architecture/target-architecture.md`，核心规划：

**原则**：AI 负责理解和建议；老马AI工作台 Core 负责确定性执行；Patchright 负责真实浏览器操作。

**双工作流**：

| 工作流 | 实现 | 负责 |
|---|---|---|
| AI 工作流 | LangGraph | 理解目标、收集上下文、策略和内容草案、风险检查、等待审核、复盘 |
| 执行业务工作流 | Celery/Redis；后续 Rust 状态机 | 排期、幂等、任务分发、重试、状态、回执、恢复 |
| 浏览器自动化 | Python + Patchright | 登录、上传、页面操作、截图与诊断 |

**分期实施**：
- Phase 0：基础稳定化（当前阶段）
- Phase 1：平台与 CLI 扩展
- Phase 2：Campaign 与审核
- Phase 3：LangGraph Intelligence
- Phase 4：Computer Use Repair Lab
- Phase 5：Rust Core 与 Tauri

---

## 8. 品牌重命名记录（老马AI工作台 → 老马AI研习社）

### 8.1 重命名范围

将前端所有用户可见的"老马AI工作台"品牌名替换为"老马AI研习社"。

### 8.2 已修改文件

| 文件 | 修改内容 |
|---|---|
| `layout.tsx` | 页面 title/description → 老马AI研习社 |
| `sidebar-new.tsx` | Logo 文字 → 老马AI研习社 |
| 各页面 eyebrow | dashboard/account/analytics/campaigns/materials/tasks 等页面的 eyebrow 文本 |
| `chat/page.tsx` | 品牌引用 |
| `fusion/page.tsx` | 品牌引用 |
| `skills/page.tsx` | 品牌引用 |
| `profile/page.tsx` | 品牌引用 |
| `external-modules.ts` | `laoma-fusion` → `ai-fusion` |
| `mock-data.ts` | LaomaAI-Fusion → AI-Fusion |
| `breakdown/page.tsx` | localStorage key `laoma.breakdown.history` → `lao_ma.breakdown.history` |

### 8.3 保留的 老马AI工作台 引用（不可修改）

以下文件中的 `prism_backend` 路径引用**必须保留**，否则会导致后端日志路径解析失败：
- `src/app/api/system-feed/route.ts`（第 17、22 行）
- `src/app/fusion/page.tsx`（第 148、150 行）

---

## 9. 已知问题与修复记录

### 9.1 黑屏问题

**问题**：前端显示黑屏，浏览器侧边栏有内容但主区域空白。

**原因**：
1. CSS `body` 元素缺少 `background-color`。`globals.css` 中 `:root`/`.dark` 定义了 `--background: 0 0% 0%`（纯黑）和 `--foreground: 0 0% 100%`（纯白），但没有规则将背景色应用到 `body`。白色文字在浏览器默认白色背景上不可见。
2. `video-pipeline/page.tsx` 中 `library.clips` 为 undefined 时调用 `.filter()` 导致崩溃。

**修复**：
- `globals.css`：在 `body` 规则中添加 `background-color: hsl(var(--background)); color: hsl(var(--foreground));`。
- `video-pipeline/page.tsx:90`：`(library?.clips ?? []).filter(...)` 防空崩溃。

### 9.2 Dev Server 被取消

**问题**：端口 3000 打不开。

**原因**：之前的 dev server 进程被取消（用户操作），端口释放，无进程监听。

**修复**：重新启动 `npm run dev`。

### 9.3 浏览器截图工具不可用

**问题**：`browser` 工具的 `screenshot` action 返回 `UnknownVizError`。

**原因**：Chrome 149 DevTools 协议 bug，非页面渲染问题。

**绕过方案**：通过 `browser` 工具的 `eval` action 检查 DOM 内容确认页面渲染正常。

### 9.4 MySQL 路径使用 `INSERT OR REPLACE`（SQLite 语法）导致 MySQL 报错

**发现日期**：2026-09-24

**问题**：`prism_core/` 下多个模块在 MySQL 分支（`if mysql_enabled():` 内）错误使用了 `INSERT OR REPLACE`，这是 SQLite 专有语法，MySQL 不兼容。当系统切换到 MySQL 模式时，这些 SQL 语句会直接抛出语法错误。

**根因**：在编写双数据库兼容代码时，MySQL 分支的 INSERT 语句直接复制了 SQLite 分支的 `INSERT OR REPLACE` 语法，未替换为 MySQL 对应的 `INSERT INTO ... ON DUPLICATE KEY UPDATE`。

**影响范围**：扫描全部 14 个 `prism_core` 模块，共发现 10 处 MySQL 分支内的 `INSERT OR REPLACE` bug，分布在 6 个文件中：

| 文件 | MySQL 行号 | 表名 |
|------|-----------|------|
| `content_variant.py` | 97 | `content_variants` |
| `insight.py` | 119 | `publish_insights` |
| `matrix_route.py` | 103 | `matrix_groups` |
| `matrix_route.py` | 260 | `matrix_assignments` |
| `review_queue.py` | 158 | `review_queue` |
| `review_queue.py` | 202 | `review_decisions`（approve_review） |
| `review_queue.py` | 232 | `review_decisions`（reject_review） |
| `webhook.py` | 159 | `webhook_subscriptions` |
| `webhook.py` | 205 | `webhook_deliveries` |
| `dedup.py` | 120 | `dedup_records` |

**已正确无需修复**（4 个文件，MySQL 分支已使用 `INSERT INTO ... ON DUPLICATE KEY UPDATE`）：
- `receipts.py`（第 163-179 行）
- `task_state_machine.py`（第 187-199 行）
- `diagnostics.py`（第 100 行，MySQL 分支使用 `INSERT INTO`）
- `account_health.py`、`platform_fields.py`、`platform_login_checker.py`、`selectors.py`（无写操作或已正确）

**修复方式**：将每个 MySQL 分支中的 `INSERT OR REPLACE INTO table` 替换为：

```sql
INSERT INTO table
(column_list)
VALUES (:param_list)
ON DUPLICATE KEY UPDATE
    col1=VALUES(col1), col2=VALUES(col2), ...
```

更新列覆盖所有非主键列，保留 `created_at` 不被覆盖（主键冲突时保留原始创建时间）。

**验证**：修复后重新扫描全部 `prism_core` 文件，确认所有剩余的 `INSERT OR REPLACE` 均位于 SQLite 分支（`else:` 内），MySQL 分支 0 处残留。6 个修改文件全部通过 `py_compile`。

### 9.5 `content_variant.py` — `record_review()` 重复查询 bug

**问题**：`record_review()` 函数先查询一次 variant，验证后又查询第二次相同 variant，存在冗余 DB 访问。

**修复**：合并为单次查询 + 存在性前置校验，消除冗余。

### 9.6 `monitor/router.py` — `StateTransitionCreate` 模型字段不匹配

**问题**：`StateTransitionCreate` Pydantic 模型包含 `platform` 和 `platform_name` 字段，但 core 的 `StateTransition` 模型不包含这两个字段。创建时会因字段传递而触发验证错误。

**修复**：从 `StateTransitionCreate` 中移除多余的 `platform` 和 `platform_name` 字段，与 core 模型对齐。

### 9.7 `diagnostics/router.py` — 文档字符串路径错误

**问题**：路由模块的文档字符串描述 `POST /diagnostics/{task_id}/redact`，但实际注册的路由是 `POST /diagnostics/redact`（无 path parameter）。

**修复**：修正文档字符串为正确路径。

### 9.8 API 路由覆盖完成（Phase 2.3+）

**背景**：`prism_core` 下的 14 个模块此前仅有部分具备 FastAPI 路由暴露。

**新增 8 个路由包**（均已注册到 `fastapi_app/api/v1/router.py`）：

| 路由包 | 前缀 | 核心模块 |
|--------|------|----------|
| `task_state_machine/` | `/task-state` | 任务状态机（Phase 0.2） |
| `platform_fields/` | `/platform-fields` | 平台字段管理（Phase 1.1-1.5） |
| `platform_login_checker/` | `/login-check` | 登录态检查（Phase 1.6） |
| `content_variant/` | `/content-variants` | 内容版本与审核（Phase 3.1+3.3） |
| `diagnostics/` | `/diagnostics` | 诊断工件采集（Phase 2.2） |
| `monitor/` | `/monitor` | 任务监控与告警（Phase 0.3） |
| `selectors/` | `/selectors` | 选择器版本管理（Phase 2.1） |
| `matrix_route/` | `/matrix-groups` | 矩阵分组路由（Phase 2.3） |

至此 `prism_core` 全部 14 个模块均有对应的 API 路由暴露。

---

## 10. 开发约定与规范

### 10.1 仓库规范（AGENT.md）

- GitHub 只携带源代码、文档、脱敏示例和构建脚本。
- 不得提交或推送真实账号数据、cookies、浏览器档案、指纹、代理/IP 池数据、日志、本地数据库或运行时产物。
- 提交信息、PR 描述、截图中不得包含原始账号标识、cookie 值、代理 IP 或仅本地存在的路径。

### 10.2 界面边框规范

- 界面不得使用 100% 不透明度的纯白色边框（如 `border-white`）。
- 边框 / 分割线颜色必须使用主题 17% 边框令牌 `border-border`（解析为 `hsl(0 0% 17%)`），不得使用完全不透明的白色。
- 同样适用于 hover 状态（`hover:border-border`）和虚线/半透明变体。

### 10.3 本地数据目录（不得提交到 Git）

```
.env
prism_backend/cookiesFile/
config/cookiesFile/
prism_backend/browser_profiles/
config/browser_profiles/
prism_backend/fingerprints/
prism_backend/data/ip_pool*.json
prism_backend/data/account_stats*.json
prism_backend/data/campaigns.json
prism_backend/data/published_works.json
prism_backend/logs/
logs/
tmp-runtime-data/
data/analytics/
data/crawler_output/
data/videos/
*.db
*.sqlite*
dump.rdb
```

### 10.4 提交前检查

- 运行 `git status --short` 检查是否有运行时或敏感文件进入 Git 跟踪。
- 如果发现，用 `git rm --cached <path>` 从索引移除，并添加或修复 ignore 规则。
- 如需提交示例文件，创建脱敏模板（如 `*.example.*`）。

---

## 11. 部署与启动

### 11.1 Windows 本地部署

```powershell
# 方式 A：一键拉起完整本地栈
start.bat

# 方式 B：Supervisor 模式
start.bat supervisor

# 方式 C：手动逐个启动（仅调试用）
scripts\launchers\start_redis.bat
scripts\launchers\start_celery_prismenv.bat
scripts\launchers\start_worker_prismenv.bat
scripts\launchers\start_backend_prismenv.bat
scripts\launchers\start_frontend.bat
```

### 11.2 macOS 部署

```bash
# PM2 模式（推荐）
./start-pm2.sh

# nohup 模式
./start-mac.sh
```

### 11.3 环境配置

**根目录 `.env`**：端口、Redis、浏览器路径、前后端连接地址、`PLAYWRIGHT_HEADLESS`、`LAOMA_BROWSER_BACKEND_DEFAULT`、`LAOMA_DOUYIN_LOGIN_MODE`。

**`prism_backend/config/llm_config.toml`**：HermesAgent 的 provider / model / api_key / base_url。

**浏览器依赖**：`scripts\launchers\setup_browser.bat`。

### 11.4 访问地址

| 服务 | 地址 |
|---|---|
| 前端控制台 | http://localhost:3000 |
| 后端 API 文档 | http://localhost:7000/api/docs |
| Automation Worker | http://localhost:7001 |
| Supervisor API | http://localhost:7002 |
| Persona serve | http://localhost:8787 |
| Hermes Dashboard | http://localhost:9119 |
| Hermes WebUI | http://localhost:9131 |

---

## 12. 开源项目引用

以下项目的代码、架构或实现思路被采用、移植或作为实现参考：

| 项目 | 许可证 | 用途 |
|---|---|---|
| [social-auto-upload](https://github.com/dreammis/social-auto-upload) | MIT | 上游 CLI 自动发布基础 |
| [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | Apache-2.0 | 抖音/TikTok 解析与数据能力 |
| [HermesAgent](https://github.com/nousresearch/hermes-agent) | MIT | 本地 AI Agent 运行时 |
| [Persona Studio](https://github.com/TechQaiser/persona-studio) | MIT | 浏览器身份/指纹/Profile 层 |

第三方归属和许可证说明保留在 `NOTICE.txt`。

**本项目许可**：Apache License 2.0。项目中保留的 MIT 与 Apache-2.0 上游组件继续分别适用其原始许可证。

---

## 13. 附录：关键文件索引

### 13.1 项目根目录

| 文件 | 说明 |
|---|---|
| `README.md` | 项目总览文档 |
| `AGENT.md` | AI Agent 上下文与仓库规范 |
| `pyproject.toml` | Python 项目配置（prism CLI 注册） |
| `prism_cli.py` | prism CLI 入口 |
| `package.json` | Node.js 项目配置 |
| `ecosystem.config.js` | PM2 进程配置（Windows） |
| `ecosystem-mac.config.js` | PM2 进程配置（macOS） |
| `start.bat` | Windows 一键启动脚本 |
| `start-pm2.sh` | macOS PM2 启动脚本 |
| `start-mac.sh` | macOS nohup 启动脚本 |
| `env.example` | 环境变量示例 |
| `NOTICE.txt` | 第三方归属与许可证 |

### 13.2 前端关键文件

| 文件 | 说明 |
|---|---|
| `prism_frontend/src/app/layout.tsx` | 根布局 |
| `prism_frontend/src/app/globals.css` | 全局样式（暗色主题） |
| `prism_frontend/src/app/page.tsx` | 首页 |
| `prism_frontend/src/components/sidebar-new.tsx` | 侧边栏 |
| `prism_frontend/src/lib/external-modules.ts` | 外部模块注册 |
| `prism_frontend/src/lib/mock-data.ts` | Mock 数据 |

### 13.3 后端关键文件

| 文件 | 说明 |
|---|---|
| `prism_backend/fastapi_app/main.py` | 应用入口 |
| `prism_backend/fastapi_app/core/config.py` | 核心配置 |
| `prism_backend/fastapi_app/api/v1/router.py` | API 路由注册 |
| `prism_backend/fastapi_app/agent/hermes_agent.py` | Hermes 桥接 |
| `prism_backend/fastapi_app/agent/hermes_config.py` | Hermes 配置同步 |
| `prism_backend/fastapi_app/agent/mcp_server.py` | MCP Server |
| `prism_backend/fusion_ai/router.py` | Fusion AI 路由 |
| `prism_backend/fusion_ai/breakdown.py` | 内容拆解（SenseNova） |
| `prism_backend/config/llm_config.toml` | LLM 配置 |
| `prism_backend/config/conf.py` | 后端配置 |

### 13.4 文档关键文件

| 文件 | 说明 |
|---|---|
| `docs/architecture/target-architecture.md` | 目标架构设计 |
| `docs/agent-bootstrap.md` | Agent 引导文档 |
| `docs/hermes-skills/prism-project-layout/SKILL.md` | 项目布局技能 |
| `docs/persona-studio-integration.md` | Persona Studio 集成文档 |
| `docs/mcp-server.md` | MCP Server 文档 |
| `docs/repo-layout-and-cleanup.md` | 仓库布局与清理 |
| `docs/tool-catalog-registration.md` | 工具目录注册 |
| `docs/rust-lightweight-architecture-plan.md` | Rust 轻量化架构规划 |

### 13.5 工具与脚本

| 文件 | 说明 |
|---|---|
| `scripts/launchers/` | 各服务启动脚本 |
| `scripts/hermes/setup-local-hermes.ps1` | Hermes 本地安装 |
| `scripts/deploy/` | 部署脚本 |
| `scripts/tests/` | 测试脚本 |
| `tools/hermes-agent/` | Hermes Agent 运行时 |
| `tools/hermes-home/` | Hermes 运行时数据 |
| `tools/hermes-webui/` | Hermes WebUI |
| `tools/persona-studio/` | Persona Studio |
| `tools/persona-studio/proxies/` | mihomo 代理网关 |

---

## 版本信息

- **文档生成日期**：2026-09-23
- **当前状态**：开发中（Phase 0 基础稳定化阶段）
- **品牌名**：老马AI研习社
- **代码许可**：Apache License 2.0
