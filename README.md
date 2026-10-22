# 老马AI工作台（Prism-Fusion）
> 自媒体矩阵发布 + AI 内容生成 · **Open Core 平台**

**下载即用 · 注册升级** —— 从 GitHub 拉下来就能跑，用 3 账号 3 平台免费体验；想解锁无限账号、多平台发布、云端 AI、数据回收增强、指纹防护、代理 IP 池，注册后升级 Pro（¥99/月）。

---

## 快速开始

```
① 下载 GitHub 仓库    →  ② 安装依赖     →  ③ start.bat 启动
④ 打开 http://localhost:3000  →  ⑤ 注册账号（免费额度）
⑥ 用 3 账号 / 3 平台免费体验   →  ⑦ 点"升级 Pro" → 云端 AI + 无限账号
```

**Community Edition** 是 GitHub 开源的免费版本，AGPL-3.0 协议；**Pro Edition** 是订阅制云端服务。**本仓库开源了服务端实现 `cloud_service/`（同为 AGPL-3.0），但 Pro 依赖的云端资源（模型 Key、用户数据、指纹画像、代理 IP 池）不随代码分发**，需由官方托管或自建。详见下文 [Community vs Pro](#community-vs-pro)。

完整部署指南见 [部署开始](#部署开始)；矩阵投放 SOP 见 [矩阵投放流程](#矩阵投放流程sop)；参与开发请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## Community vs Pro

| 功能 | Community（免费，开源） | Pro（¥99/月） |
|---|---|---|
| 矩阵发布账号数 | 3 个 | **无限** |
| 可用平台数 | 3 个（抖音 / 小红书 / B 站） | **多平台**（快手 / 视频号 / TikTok / YouTube / X 等已接入平台，数量随版本扩充） |
| 账号登录 | 扫码 / Cookie 导入 | 扫码 / Cookie 导入 + **持久会话** |
| AI 内容生成 | **自配 key**（离线模式） | **云端 prompt**（不用自配 key，防逆向） |
| 文生图（M1） | 自配 key / 本地 | 云端 API（gpt-image / 通义 / ComfyUI） |
| Hermes Agent | 本地自部署 | 云端代理 + **2 个配额** |
| 数据回收 | ✅ 抖音 / B 站 / TikTok / YouTube | ✅ 同左 + 增强（自动刷新 / 批量） |
| Persona 指纹增强 | ❌（仅 patchright 直连） | ✅ 相干指纹 + Profile 持久化 + 反检测 |
| 代理管理 / IP 池 | ❌ | ✅ 标准 endpoint + sticky 绑定 + 地区映射 |
| 高级定时 / 批量发布 | 基础定时 | **高级定时** + 失败重试策略 |
| 素材管理 | 上传 / 手动标题标签 | 上传 + AI 标题标签润色 |
| 工作流（M4） | ✅ 全开源 | ✅ 全开源 |
| 图片编辑器（M5） | ✅ 全开源 | ✅ 全开源 |
| 开发者工具中心 | ✅ 全开源 | ✅ 全开源 |
| 排期 / 任务管理 | ✅ 全开源 | ✅ 全开源 |
| 注册 / 订阅 UI | ✅ 内置（引导付费） | — |
| 团队 / 协作 | 单人 | 单人（Team 档后续扩展） |

> **一句话区分**：Community = "能用但不够爽"的开源壳；Pro = "很爽但不可抄"的付费核（云端 prompt / Hermes / 数据 / 指纹 / 代理）。
> fork 竞品拿到什么？—— 拿到客户端代码，但拿不到云端 prompt / key / 数据服务 → AI 不够聪明 → 用户还是会回来付费。

> ⚠️ **Open Core 边界现状（2026-10-22 已拍板）**：上表"云端 prompt（防逆向）"一行与当前代码状态存在偏差 —— prompt 模板（`cloud_service/llm_proxy/prompts.py`）目前仍随 AGPL-3.0 代码入库。**马哥已拍板（D6）：该文件移出开源树，只在 Pro 包提供**；开源树保留接口 stub，执行批次 B2（详见 `docs/feature-inventory-and-oss-boundary.md` §7.4）。未开源的是服务端实例上的 prompt 数据、模型 Key、用户数据、指纹画像与代理池。

### 定价

| 档位 | 月费 | 年费 | 包含 |
|---|---|---|---|
| **Community** | ¥0 | ¥0 | 3 账号 / 3 平台 / 自配 key / 基础 prompt / 开源可自部署 |
| **Pro** | ¥99 | ¥999 | 无限账号 / 多平台 / 云端 AI / Hermes Agent / 数据回收增强 / 指纹 / 代理 |
| **Team**（后续） | ¥299 | ¥2999 | Pro + 多人协作 + 权限 + 审核流 |

---

## 目录
- [项目定位](#项目定位)
- [核心能力（矩阵投放闭环）](#核心能力矩阵投放闭环)
- [新功能集成](#新功能集成)
- [功能](#功能)
- [支持平台](#支持平台)
- [架构概览](#架构概览)
- [部署开始](#部署开始)
  - [Windows 本地部署](#windows-本地部署)
  - [macOS（PM2）部署](#macospm2部署)
- [命令行](#命令行)
- [矩阵投放流程（SOP）](#矩阵投放流程sop)
- [API 示例](#api-示例)
- [目录结构](#目录结构)
- [合规提示](#合规提示)
- [项目支持与采用](#项目支持与采用)
- [贡献与开源](#贡献与开源)
- [许可](#许可)

---

## 项目定位

老马AI工作台是一个“矩阵投放 / 分发中台”，把「账号、素材、计划、排期、执行、监控、回收」统一到可编排的任务系统中：
- 适合多平台、多账号的规模化分发与运营底座；
- 不强行覆盖剪辑/混剪/内容工厂，可作为外部生产链路的对接层；
- 设计参考行业常见“编-投-管-回”闭环，但项目更聚焦于“投 + 管 + 回”；
- **同时是 AI 内容生产平台**：选题、趋势、拆解、账号画像、内容库、创作工作台，加上 AI 生图、视频流水线与图片编辑器，让素材从「产出」直接进入「发布」；
- **对话式生成**：内置 Hermes Agent，可用自然语言把上面的能力串起来（HermesChat / AI 对话）。

---

## 我们基于什么（借鉴与致谢）

| 上游项目 | 许可证 | 我们拿走什么 | 我们自己加了什么 |
|---|---|---|---|
| [social-auto-upload](https://github.com/dreammis/social-auto-upload) | MIT | 多平台发布适配器与 CLI 发布基础 | Web 工作台、账号体系、任务队列、审核与调度 |
| [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | Apache-2.0 | 抖音 / TikTok 解析与数据采集 | 统一的数据回收工作台与复盘看板 |
| [HermesAgent](https://github.com/nousresearch/hermes-agent)（Nous Research） | MIT | 本地 AI Agent 运行时 | 对话式生成（HermesChat）、Agent 控制台与提示词体系 |
| [Persona Studio](https://github.com/TechQaiser/persona-studio) | MIT | 浏览器身份 / 指纹 / Profile 层 | 代理网关、账号→身份→代理的固定绑定编排 |
| [Easel](https://github.com/ZJU-REAL/Easel)（浙大 ZJU-REAL Lab） | Apache-2.0 | 内容创作工作台的 API 契约（**仅参考，未 vendor 源码**） | 内容库 / 收件箱 / 创作工作台 / 创作工坊 + 审核队列 |

> 谱系：`social-auto-upload (MIT)` → 本项目早期形态 `SynapseAutomation (Apache-2.0)` → **老马AI工作台 (AGPL-3.0)**。
> 逐项归属见 [NOTICE.txt](NOTICE.txt) 与 [vendor/VENDOR.md](vendor/VENDOR.md)。

---

## 我们在其上做了什么（新增能力与开放级别）

> **Community** = 开源版直接可用；**Pro** = 需官方云端账号 / 授权（云端推理、模型市场、Agent 配额、数据回收增强等）。
> 具体额度口径见 [cloud_service/billing/feature_gate.py](cloud_service/billing/feature_gate.py)。

| 能力组 | 新增能力 | 相对原项目 | Community | Pro |
|---|---|---|---|---|
| 概览 | 仪表盘、快速开始向导 | 全新 | 全部 | — |
| 资源 | 账号管理、素材库 | 沿用并重做 | 全部 | 账号数 3 → 无限 |
| 资源 | 代理管理、代理网关、Persona 指纹 | 全新 | — | 全部 |
| 内容 | 选题库、趋势热榜、内容拆解、账号画像、CMS | 全新 | 全部 | — |
| 内容 | 内容库、收件箱、创作工作台、创作工坊 | 全新 | 全部 | — |
| 生成 | AI 生图、视频流水线、图片编辑器 | 全新 | 本地自配 Key | 官方云端生图 / 渲染 |
| 产物 | 产物中心（统一产物 ID / 阶段流转 / 血缘） | 全新 | 全部 | — |
| 分发 | 矩阵发布、发布中心、发布任务、分发记录、排期日历、任务管理 | 沿用并重做 | 全部 | 平台数提升（不写死数量） |
| 分发 | 审核队列（队列 / 版本审批 / 敏感词库） | 全新 | 全部 | — |
| 分发 | 营销活动 + 任务包编排 | 全新 | — | 全部 |
| 数据 | 数据中心、趋势分析、各平台视频数据 | 数据回收扩到全部已接入平台 | 全部 | 数据回收增强 |
| 智能 | AI 对话、技能库 | 全新 | 全部 | — |
| 智能 | HermesChat 对话式生成 | 全新 | — | 流式对话 |
| 智能 | Agent 控制台、提示词配置、运行设置 | 全新 | — | Agent 配额 0 → 2 |
| AI-Fusion | 融合中心、风格库、内容审查、融合分析、融合配置 | 全新 | 全部 | — |
| AI-Fusion | 模型市场、供应商配置 | 全新 | — | 官方云端模型 |
| 开发者工具 | 工具中心（MCP / 技能）、演示控制台、系统设置 | 全新 | 全部 | 授权 / 订阅管理 |

---

## 核心能力（矩阵投放闭环）

### 投：矩阵发布与调度
- 多平台、多账号、多素材组合发布；
- 批量生成任务、统一入队、并发调度；
- 定时发布、结果回传、失败重试；

### 管：账号与任务运营
- 账号绑定、状态监控、异常提醒；
- 任务队列看板、执行日志可视化；
- 每账号固定身份绑定（账号 → 浏览器身份 → 固定代理 → 浏览器执行）；

### 回：数据回收（复盘输入）
- 当前支持：抖音、B 站、TikTok、YouTube；
- 预留可扩展：快手、小红书、视频号等（按平台适配器扩展）；

### 编：AI 编排加速（投前准备）
- 内置 HermesAgent AiAgent 助手(装备Computeruse、各类mcp、skill、长记忆、多Agent）
- 自然语言生成/润色标题、标签、话题等投放配置；
- 支持“一句话投放”（示例见下）；

### 可扩展 / 可自托管
- FastAPI + Next.js + Celery/Redis + Patchright + Persona Studio；
- 平台适配器模块化扩展；
- Web 控制台 + Electron 桌面端，可本地或私有化部署；
- 浏览器身份层、代理层均可在「直连 / 内置后台 / 自托管」间按需开关；

---

## 新功能集成

> 最近一轮优化的核心是把“账号的**固定身份环境**”落成可编排、可切换、可一键维护的组件：
> **账号 → Persona 浏览器身份 → 固定代理 → Patchright 执行**，并补齐运行时管理、开发者工具中心与后台配置。

### 1) Persona Studio —— 浏览器身份 / 指纹 / Profile 层

集成 [Persona Studio](https://github.com/TechQaiser/persona-studio)（MIT，开源自托管反检测浏览器与 Profile 管理器）作为 老马AI工作台的 **Browser Identity / Fingerprint / Profile 层**：

- **相干指纹生成**：OS / UA / GPU / 屏幕 / 时区 / 语言彼此一致，避免“macOS UA 配 NVIDIA GPU”这类一眼假组合；
- **Profile 持久化**：Cookie / LocalStorage / IndexedDB 随 Profile 留存，登录一次、下次启动仍在；
- **持久会话**：账号登录态跨任务复用，无需重复扫码；
- **引擎可选**：`cloak`(CloakBrowser) / `camoufox` / `patchright` / `playwright`（默认与 老马AI工作台运行时一致的 `patchright`）；
- **代理注入 + 出口 IP / 泄漏检测**。

老马AI工作台 **不自研**指纹、Profile 存储、指纹伪造，全部交给 Persona Studio；不安装时自动回退 **Patchright 直连模式**（每账号独立 `data/browser_profiles/<account>/` persistent context），功能不中断，仅少相干指纹/持久会话增强。

- 账号表 `cookie_accounts` 增加 `persona_profile_id`（默认 = account_id）、`browser_backend`（patchright / persona）、`proxy_id`；
- 一个 老马AI工作台 账号 ↔ 一个 Persona Profile；
- Persona serve：`http://127.0.0.1:8787`（`PERSONA_API_URL`）。

### 2) per-country 代理网关 + 每账号代理绑定

独立的官方 **mihomo** 网关（`tools/persona-studio/proxies/`）提供 **将订阅遍历映射为 HTTP/SOCKS mixed 端口，各路由到一个地区节点：
如：
| 地区 | 端口 | locale / 时区对齐 |
|---|---|---|
| 直连 | — | 本机网络 + 本机 locale/时区 |
| 🇸🇬 新加坡 (sg) | 7771 | en-SG / Asia/Singapore |
| 🇯🇵 日本 (jp) | 7772 | ja-JP / Asia/Tokyo |
| 🇺🇸 美国 (us) | 7773 | en-US / America/New_York |
| 🇩🇪 德国 (de) | 7774 | de-DE / Europe/Berlin |
| 🇹🇼 台湾 (tw) | 7775 | zh-TW / Asia/Taipei |
| 🇭🇰 香港 (hk) | 7776 | zh-HK / Asia/Hong_Kong |

- 账号通过 `GET/PUT /api/v1/accounts/{id}/persona-proxy` 绑定地区；
- 进程启动浏览器时，按绑定注入对应代理，并按 country 对齐 **locale / 时区 / 国家**，让指纹更真实；
- 未绑定地区（direct）或未勾选时，回退到 **IP 池代理**（Proxy Manager 的 sticky 绑定）。

### 3) 代理管理（Proxy Manager / IP 池）

老马AI工作台 自研的代理管理：
- 登记标准 HTTP/SOCKS5 endpoint，自动健康检测（延迟 / 可用性）；
- **sticky 固定绑定**：`proxy_id` 权威落账号表，同一账号始终走同一代理；
- 批量导入 / 导出、自动绑定（从空闲池按 region 匹配）、`max_bindings` 上限；
- 每账号环境视图（`GET /api/v1/accounts/{id}/environment`）：展示 Browser + Proxy + Runtime 状态。

> 3Proxy / gluetun / sing-box 等只产出标准 HTTP/SOCKS5 endpoint 登记进 Proxy Manager，不进入 老马AI工作台 核心业务。

### 4) 浏览器运行时管理（系统 Chrome / 无头 / 运行时切换）

设置页「浏览器管理」提供：
- **运行时检测**：Patchright 是否安装、当前采用哪种运行时；
- **浏览器资源**：Chromium / Firefox 的安装、卸载与版本识别，可一键 `patchright install`；
- **系统 Chrome 优先**：倾向于使用本机 Chrome，而非下载的 Chromium；
- **无头/有人头运行**：写入 `.env` 的 `PLAYWRIGHT_HEADLESS`，web 设置页可切换；
- **进程管理**：重启、停止与退出 Supervisord / PM2 管理的进程；
- **数据清理**：素材、账号与 Cookies、浏览器数据、缓存；
- **应急工具**：系统自检、日志导出、强制停止。

### 5) 开发者工具中心（一键安装 / 技能管理）

`/tools` 页面统一管理可一键安装的开发工具，按 **skill / MCP / 插件 / 组件** 分类：
- 已收录：`deepseek-harness`、`ccswitch`、`computer-use-linux`、`hermes-agent`、`persona-studio`；
- **一键安装 / 卸载**：克隆 + 构建（如 persona dashboard 构建）；
- **启动 / 调用**：已装桌面应用（如 CC Switch）可从 老马AI工作台 直接打开；
- **Hermes 技能软启用 / 停用**：技能（`SKILL.md`）在 `active` 与 `_disabled` 目录间移动，**不物理删除**；
- 后端：`GET /api/v1/tools`、`/{id}/install`、`/{id}/uninstall`、`/{id}/launch`、`/{id}/build`、`/{id}/toggle`。

### 6) CMS 隐藏后台

`/cms` 隐藏管理后台，集中控制运行开关（修改后需重启后端生效）：
- **抖音登录模式**：`browser`（正式 / 当前模拟）↔ `http`（逆向 HTTP 测试）；
- **浏览器后端**：`patchright` / `persona`；
- **无头模式**：`PLAYWRIGHT_HEADLESS`；
- 相关 `.env`：`LAOMA_DOUYIN_LOGIN_MODE`、`LAOMA_BROWSER_BACKEND_DEFAULT`。

### 7) 账号登录体验改进

- **二维码登录**：支持取消（停止连接/轮询）与重试；支持从本机 Chrome 导入已登录账号；
- **从本机 Chrome 导入**：复制本机 Chrome 的 Cookies/Local State 到 老马AI工作台 专用 profile（非无痕），无需关闭 Chrome，若平台已登录则直接读取登录态入库；
- **TikTok / YouTube**：恢复上游 SAU 交互式登录，修复 `--no-sandbox` 崩溃、cookie 抓取与账号入库（user_id 兜底 + account_id）；
- **Toast 自动关闭**：修复 Radix 暂停态导致通知不自动关闭的问题。

### 8) 每账号运行时锁

Redis 每账号 Browser Runtime 分布式锁（`runtime_lock_service`）：保证同一账号的浏览器任务串行执行，避免并发互踩；心跳续期，异常自动释放。

### 9) TikTok / YouTube 数据采集 + TikHub 账号信息自动回填

- **TikTok 视频数据采集**：通过 TikHub Web API 自动把账号数字 uid 解析为完整 secUid，拉取作品列表（视频 ID / 标题 / 封面 / 播放 / 点赞 / 评论 / 分享 / 收藏 / 发布时间），无需浏览器；
- **YouTube 视频数据采集**：通过 TikHub 频道 API 拉取频道视频列表（视频 ID / 标题 / 封面 / 播放 / 点赞 / 评论 / 时长）；
- **账号信息自动回填**：TikTok / YouTube 浏览器登录成功后，自动用 TikHub 反查账号真实资料（账号名 uniqueId、昵称、头像）并写回账号库，账号列表页直接显示真实名字和头像，无需手动补录；已有账号也可在账号列表点击「补全」手动触发反查（`POST /accounts/{id}/enrich-tikhub`）；
- **YouTube 频道注册解析**：添加 YouTube 账号时支持直接填频道名 / @handle / 频道链接，一键解析出 channel_id、频道名、头像并预填（`POST /accounts/resolve/youtube-channel`）；
- 依赖 TikHub API Key（`ai_model_configs` 表配置），充值后即可使用全部接口。

---

## 功能

> 标注说明：**🟢 Community** = 开源免费使用；**🔵 Pro** = 付费云端服务（¥99/月）；**🟢🔵 混合** = 基础版开源 + 高级能力付费。

### 1) 账号管理——登录账号
🟢 Community / 🔵 Pro
支持平台「抖音、快手、小红书、视频号、B 站」扫码登录；
「TikTok、YouTube」则是 patchright 调用本机浏览器登录后，账号自动入库并回源账号信息；
Community 限 3 账号 / 3 平台，Pro 无限。

### 2) 素材管理——AI 标题/标签润色 + 批量上传
🟢🔵 混合
批量拖拽上传（🟢）；AI 自动补全标题/标签（🔵，Community 用自配 key 走基础 prompt）。

### 3) 多平台多账号同步发布
🟢🔵 混合
支持「抖音、快手、小红书、视频号、B 站」同步发布；AI 一句话发布：
"帮我把素材库刚上传的视频，生成标题、标签并定时发布 23:55，发布到所有平台；"
Community 限 3 平台（抖音 / 小红书 / B 站），Pro 解锁多平台发布（数量随版本扩充）+ 高级定时。

### 4) 访问不同平台/账号的创作者后台
🟢🔵 混合
每个账号有独立浏览器身份（🟢 patchright 直连）+ 固定代理；
🔵 Pro 提供 Persona 指纹增强（相干指纹 + Profile 持久化 + 反检测）与 IP 池 / sticky 绑定 / 地区映射。

### 5) 视频数据回收与复盘
🔵 Pro
支持抖音、B 站、TikTok、YouTube 数据回收（依赖云端 TikHub API）；Community 版基础可用，Pro 版增强（自动刷新 / 批量）。

### 🎬 产品演示视频（纯黑白）

**真实交互 Walkthrough**（登录弹窗 · 素材 · 矩阵发布 · 任务 · Agent 对话，纯黑白包装）：

![walkthrough](docs/demos/prism_wrap.gif)

**14 页功能巡览**（仪表盘 / 账号管理 / 矩阵发布 / 数据 / Agent …，HyperFrames 合成）：

![tour](docs/demos/prism_hyperframes_demo.gif)

---

## 支持平台

内置平台适配器（可扩展）：
- 抖音
- 快手
- 小红书
- 视频号
- B 站
- TikTok（本机浏览器登录）
- YouTube（本机浏览器登录）

### 登录运行时状态

- 支持抖音、快手、小红书、视频号、B 站、Tiktok、Youtube 账号掉线检测；

---

## 架构概览

技术栈：FastAPI、Next.js、Celery/Redis、Patchright、Persona Studio、Electron、mihomo（代理网关）；

```text
prism_frontend/    # Next.js 控制台（计划/任务/看板/工具/CMS）
prism_backend/     # FastAPI 后端（矩阵调度 + AI 服务 + 账号/代理/运行时）
scripts/           # 启动与运维脚本
desktop-electron/  # Electron 客户端与打包
tools/             # 自托管组件（hermes-agent / hermes-webui / persona-studio）
```

职责边界：

| 层 | 归属 |
|---|---|
| 账号 / 平台 / 任务 / Celery / Redis | 老马AI工作台 |
| 代理网关（per-country 端口 7771–7776） | mihomo（Persona proxies） |
| Proxy Manager（proxies、sticky 绑定、健康检测） | 老马AI工作台 |
| Browser Identity / Fingerprint / Profile | Persona Studio |
| 浏览器执行（平台 Adapter 驱动） | 老马AI工作台 Patchright（`connect_over_cdp`） |

固定链路：

```text
Account
  → persona_profile_id（老马AI工作台 账号表）
  → Persona Profile（指纹 + 持久会话）
  → Sticky Proxy（Proxy Manager 注入 / per-country 代理）
  → Patchright（connect_over_cdp 驱动）
  → Platform Adapter（发布 / 登录 / 数据回收）
```

---

## 部署开始

### Windows 本地部署

采用本地部署：适合开发、调试，可单独查看 Redis / Celery / Automation Worker / FastAPI / HermesAgent 的运行状态。

#### 1) 安装依赖

方式 A：`prismenv`（默认推荐）

```powershell
python -m venv prismenv
prismenv\Scripts\activate
pip install -r requirements.txt

cd prism_frontend
npm install
cd ..
```

也可以直接运行 `start.bat`。它会优先检测 `prismenv`，不存在时自动创建并安装根 `requirements.txt`。

方式 B：`conda`

```powershell
conda create -n prism python=3.11.4
conda activate prism

pip install -r requirements.txt
cd prism_frontend
npm install
cd ..
```

#### 2) 配置环境

必须检查两类配置：

- 根目录 `.env`：端口、Redis、浏览器路径、前后端连接地址、`PLAYWRIGHT_HEADLESS`、`LAOMA_BROWSER_BACKEND_DEFAULT`、`LAOMA_DOUYIN_LOGIN_MODE`。
- `prism_backend\config\llm_config.toml`：HermesAgent 的 provider / model / api_key / base_url。

浏览器依赖：

```powershell
scripts\launchers\setup_browser.bat
```

桌面版支持在“系统设置”页管理 `Chromium` / `Firefox`；所有平台自动化统一由 `Patchright` 执行。

#### 3) 启动方式

方式 A：一键拉起完整本地栈

```powershell
start.bat
```

等价于默认 `prismenv` 模式，会按顺序启动：

1. Redis
2. Celery Worker
3. Automation Worker
4. FastAPI Backend
5. Frontend

重要说明：

- 本地后端进程缺一不可。少起任意一个进程，前端页面可能能打开，但任务调度、浏览器执行、异步回调、HermesAgent 调用链都会不完整。
- HermesAgent Dashboard / WebUI 由 FastAPI 在非 Supervisor 模式下自动托管；前提是 `prism_backend\config\llm_config.toml` 已正确配置，且本地 Hermes 运行时已通过 `scripts\hermes\setup-local-hermes.ps1` 安装完成。

方式 B：Supervisor 模式

```powershell
start.bat supervisor
```

该模式会启动：

- Redis
- Supervisor
- Frontend

再由 Supervisor 托管：

- FastAPI Backend
- Celery Worker
- Automation Worker
- HermesAgent 相关界面与网关

方式 C：手动逐个进程启动（仅调试时使用）

```powershell
scripts\launchers\start_redis.bat
scripts\launchers\start_celery_prismenv.bat
scripts\launchers\start_worker_prismenv.bat
scripts\launchers\start_backend_prismenv.bat
scripts\launchers\start_frontend.bat
```

#### 4) Windows 访问地址

- 控制台：http://localhost:3000
- 后端 API：http://localhost:7000/api/docs
- Automation Worker：http://localhost:7001
- Supervisor API：http://localhost:7002（仅 `start.bat supervisor`）
- Persona serve：http://localhost:8787
- per-country 代理网关：http://localhost:7771-7776
- HermesAgent Dashboard：http://localhost:9119
- HermesAgent WebUI：http://localhost:9131

---

### macOS（PM2）部署

macOS 推荐用 **PM2** 统一管理全套进程，避免 nohup 多进程难维护的问题：

```bash
./start-pm2.sh
```

`ecosystem-mac.config.js` 会拉起：

| 进程 | 说明 | 地址 |
|---|---|---|
| `prism-backend` | FastAPI 后端（run.py，使用 `.venv` python） | http://127.0.0.1:7000 |
| `prism-worker` | Automation Worker | http://127.0.0.1:7001 |
| `prism-celery` | Celery Worker（threads pool） | Redis |
| `prism-frontend` | Next.js 控制台 | http://localhost:3000 |
| `persona-api` | Persona serve（`persona --data-dir ... serve`） | http://127.0.0.1:8787 |
| `persona-proxy` | 独立官方 mihomo 网关 | http://127.0.0.1:7771-7776 |

> `start-pm2.sh` 会先清理残留进程避免端口占用，再启动并打印 `pm2 list`。
> `ecosystem-mac.config.js` 显式设置 `LAOMA_BROWSER_BACKEND_DEFAULT=persona`，即 macOS 默认走 Persona 身份层。

常用命令：

```bash
PM2_HOME=./runtime-data/pm2 ./prism_frontend/node_modules/.bin/pm2 logs
PM2_HOME=./runtime-data/pm2 ./prism_frontend/node_modules/.bin/pm2 restart all
PM2_HOME=./runtime-data/pm2 ./prism_frontend/node_modules/.bin/pm2 stop all
```

也可以使用 `start-mac.sh`（nohup 拉起 Redis + Backend + Worker + Celery + Frontend，等价 Windows 的 `start.bat`）：

```bash
./start-mac.sh
```

macOS 访问地址与 Windows 相同（见上）。

---

## 命令行

安装项目后可以直接使用 `prism` 命令。CLI 与 Web、桌面端共用同一套平台适配器、账号文件和 Patchright 运行时：

```bash
pip install -e .

prism douyin login --account creator
prism douyin check --account creator
prism douyin upload-video \
  --account creator \
  --file ./video.mp4 \
  --title "示例标题" \
  --description "示例简介" \
  --tags "老马AI工作台,自动发布"
```

定时发布使用本地时间，格式为 `YYYY-MM-DD HH:MM`：

```bash
prism xiaohongshu upload-video \
  --account creator \
  --file ./video.mp4 \
  --title "示例标题" \
  --schedule "2026-08-18 20:30"
```

国际平台首次使用需在运行 老马AI工作台的本机浏览器中完成账号登录；登录态会以 storage state 保存并供任务队列复用：

```bash
prism tiktok login --account creator
prism youtube login --account creator
prism youtube upload-video --account creator --file ./video.mp4 --title "Example" \
  --description "Video description" --tags "老马AI工作台,automation" --visibility unlisted
```

### Gemini Computer Use 受控恢复（可选）

Gemini Computer Use 仅用于在 Patchright 定位失败时收集截图与候选动作，辅助生成可审查的平台适配器代码补丁；
它不在正式发布任务中执行点击、填写或提交。正式发布始终使用版本化、可测试的 Patchright 平台适配器。

---

## 矩阵投放流程（SOP）

1. 绑定账号（多平台账号矩阵，可绑定浏览器身份 + 固定代理 + per-country 代理地区）；
2. 素材入库（批量上传 / AI 标题标签润色）；
3. 创建矩阵计划（平台、账号、素材、话题、封面、定时策略）；
4. 生成矩阵任务并调度执行（队列化、并发、失败重试、每账号运行时锁）；
5. 看板监控与日志审计（异常提醒 / 人工介入点）；
6. 数据回收（抖音、B 站）并复盘迭代；

---

## API 示例

生成矩阵任务：

```http
POST /api/v1/matrix/generate_tasks
Content-Type: application/json
```

```json
{
  "platforms": ["xiaohongshu", "douyin"],
  "accounts": {
    "xiaohongshu": ["account_id_1", "account_id_2"],
    "douyin": ["account_id_3"]
  },
  "materials": ["material_id_1", "material_id_2"],
  "title": "xxxxx",
  "topics": ["#xxx", "#xxx"]
}
```

账号固定身份绑定（Persona 代理地区）：

```http
GET  /api/v1/accounts/{account_id}/persona-proxy   # 读取绑定地区 + 可用地区列表
PUT  /api/v1/accounts/{account_id}/persona-proxy   # 设置地区（direct/sg/jp/us/de/tw/hk）
```

账号环境视图：

```http
GET /api/v1/accounts/{account_id}/environment
```

开发者工具：

```http
GET  /api/v1/tools                      # 工具目录（skill/mcp/plugin/component）
POST /api/v1/tools/{tool_id}/install    # 一键安装
POST /api/v1/tools/{tool_id}/uninstall  # 卸载
POST /api/v1/tools/{tool_id}/launch     # 打开本地应用
POST /api/v1/tools/{tool_id}/build      # 构建（如 Persona dashboard）
POST /api/v1/tools/{tool_id}/toggle     # 软启用/停用技能
```

---

## 目录结构

- `prism_backend/fastapi_app`：API、矩阵调度、任务队列与服务逻辑；
- `prism_frontend/`：矩阵投放控制台（Next.js，含 `/tools`、`/cms`）；
- `desktop-electron/`：桌面客户端与打包脚本；
- `scripts/`：启动、调试、维护脚本；
- `tools/`：自托管组件（`hermes-agent` / `hermes-webui` / `persona-studio` 及 `proxies` 代理网关）；
- `runtime-data/`：运行时数据（PM2 的 `pm2` 目录、Hermes 技能等）；
- `scripts/tests/`：手动与集成验证脚本（原 `Test/` 目录已收纳至此）；
---

## 合规提示

本项目用于自动化流程与效率提升，请在合法合规、遵守平台规则的前提下使用；
涉及账号体系与内容发布的规模化运营，建议建立团队内部内容审核与风险控制流程；

---

## 项目支持与采用

老马AI工作台的能力建设受益于开源生态；下列项目的代码、架构或实现思路被采用、移植或作为实现参考：

- [social-auto-upload](https://github.com/dreammis/social-auto-upload)：上游 CLI 自动发布基础；MIT License。
- [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API)：抖音 / TikTok 解析与数据能力参考；Apache License 2.0。
- [HermesAgent](https://github.com/nousresearch/hermes-agent)：本地 AI Agent 运行时与集成参考；MIT License。
- [Persona Studio](https://github.com/TechQaiser/persona-studio)：浏览器身份 / 指纹 / Profile 层；MIT License。
- [Easel](https://github.com/ZJU-REAL/Easel)（浙大 ZJU-REAL Lab）：内容创作工作台 API 契约参考源，副本存放于 [tools/easel-ref/](tools/easel-ref/)；Apache License 2.0。本项目未直接 vendor 完整 Easel，仅参考 API 契约；归属、抽取版本与本地改动详见 [vendor/VENDOR.md](vendor/VENDOR.md)。

对应第三方归属和许可证说明保留在 [NOTICE.txt](NOTICE.txt)，逐项细节见 [vendor/VENDOR.md](vendor/VENDOR.md)。

---

## 许可
老马AI工作台 自身代码基于 **GNU Affero GPL v3.0 (AGPL-3.0)** 开源。选择 AGPL-3.0 的理由：

1. **强制 fork 后也开源**：即使有人 fork 后部署为 SaaS / 私有云服务，只要对外提供网络服务就必须开源其代码 —— 防止闭源竞品直接复用我们的架构与客户端代码。
2. **符合 Open Core 商业模式**：核心客户端开源吸引开发者生态，价值集中在**云端服务**（prompt 模板 / LLM key / 数据回收增强 / Hermes Agent / 指纹增强），这些不随代码分发；fork 竞品拿不到云端 prompt + key + 数据 → 用户体验大幅缩水 → 用户还是会回来付费。
3. **兼容现有 Apache-2.0 依赖**：见下条。

项目中保留的 MIT 与 Apache-2.0 上游组件继续分别适用其原始许可证；这些组件以**独立文件 / 独立目录**形式存在，与本项目的 AGPL-3.0 代码**弱耦合**（通过 HTTP / 命令行 / 环境变量交互），避免 AGPL 传染到它们的分发物。上游版权、许可证和 NOTICE 归属详见 [NOTICE.txt](NOTICE.txt) 与 [vendor/VENDOR.md](vendor/VENDOR.md)。

### 云端服务

本仓库的 `cloud_service/` 目录开源，但**实际生产环境的云端服务**（`prompt` 模板库 / LLM API key / TikHub 数据 key / Hermes Agent 内核）**不包含在代码里**，由官方运营；用户可通过自部署 `cloud_service/` 搭建本地版（Community 模式），但拿不到官方云端的 prompt 与数据资源。

## Community

本项目在 [LINUX DO](https://linux.do/) 社区进行交流与开源推广。

感谢 LINUX DO 社区为开发者提供交流与分享的平台。

## 贡献与开源

欢迎通过 Issue / PR 参与本项目开发。参与前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，涵盖：

- **开发环境搭建**（Node.js 20 / Python 3.11 / `prismenv` 虚拟环境 / Electron）
- **代码规范**（TypeScript strict / Python PEP 8 / Conventional Commits）
- **测试要求**（`tsc --noEmit` / `vitest` / 后端 M1-M2-M3 自运行测试 / ruff / eslint）
- **分支策略**（`main` / `feature/*` / `fix/*` / `chore/*` / `docs/*`）
- **PR 模板**（`.github/PULL_REQUEST_TEMPLATE.md`）
- **Issue 模板**（`.github/ISSUE_TEMPLATE/`：Bug 报告 / 功能请求）
- **行为准则**（简短版 Code of Conduct）
- **Open Core 边界**（Community 可贡献 vs Pro 云端不公开）

CI 流程见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)（push/PR 自动运行 8 个 job：6 个硬门 + 2 个软门 `test`（backend pytest）与 `e2e-packaged`（打包 E2E，仅 workflow_dispatch）），发布走 [`.github/workflows/release.yml`](.github/workflows/release.yml)（tag `v*` 触发 Windows/macOS 打包 + GitHub Release）。

## [BuymeaCoffee](https://buymeacoffee.com/laihiujin3)

| | | |
|-|-|-|
| ![1d1114b7-9c71-4c18-91df-0a462bed5405](https://github.com/user-attachments/assets/f0c38071-f69a-4262-a339-182c090d4c41) | ![dac9dc35-e027-42e8-b6aa-81f3211906da](https://github.com/user-attachments/assets/761ae5f1-8350-49d6-bba6-de2f01f1b73e) | ![老马AI工作台 交流群二维码](docs/prism-qq-group-qr.jpg) |
