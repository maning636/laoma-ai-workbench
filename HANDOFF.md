# Prism-Fusion（老马AI工作台）开发交接文档

> 面向接手 agent 的一站式指南。读完本文应该可以在 30 分钟内理解项目定位、启动方式、代码结构和主要约定。
>
> **项目一句话**：AI 驱动的多平台内容矩阵发布与分发中台，覆盖"投-管-回"闭环。技术栈：FastAPI + Next.js + Celery/Redis + Playwright + Electron。
>
> 🆕 **首次接手请先读 [`docs/handover/PROJECT-HANDOVER.md`](docs/handover/PROJECT-HANDOVER.md)** —— 那是 2026-10-24 的交棒入口，补上了本文件与 dev-reports 都缺的「2026-10-17 ~ 10-24 收官段」：项目全过程、交付清单、未来计划、以及一份踩坑清单（§8）。本文继续作为**技术细节**参考（目录结构、API 路由、启动方式、风格约定）。

---

## 0. TL;DR（先做这 5 件事）

1. **必读文件**（按顺序）：
   - `AGENT.md`（AI agent 上下文与仓库卫生规则）
   - `README.md`（项目定位、SOP、API 示例）
   - `STARTUP.md`（本地起服务、常见坑）
   - `DEVELOPMENT-RECORD.md`（最近的开发记录，很长，按需查）
   - `docs/hermes-skills/prism-project-layout/SKILL.md`（后端完整路由清单，权威源）

2. **代码地图**：
   - 后端：`prism_backend/fastapi_app/api/v1/<module>/router.py` — 所有 REST 路由
   - 前端：`prism_frontend/src/app/<route>/page.tsx` — 所有页面
   - 桌面：`desktop-electron/` + `desktop-electron/resources/supervisor/`
   - 运维脚本：`scripts/launchers/`（启动）、`scripts/packaging/`（打包）

3. **首次启动**（Windows 开发模式）：
   ```powershell
   cd D:\dim开发\Prism-Fusion
   python -m venv prismenv
   prismenv\Scripts\activate
   pip install -r requirements.txt
   cd prism_frontend && npm install && cd ..
   start.bat
   ```
   前端 :3000，后端 :7000，Automation Worker :7001。

4. **不要做的事**（会踩坑）：
   - 不要改"老马AI工作台"这个历史命名（全局替换会崩）
   - 不要往 `tools/` 塞本项目代码（外部子模块）
   - 不要提交 `.env`、`cookies*`、`browser_profiles/`、`fingerprints/`、`*.db`
   - 不要用 PowerShell 内联 `python -c "..."`（中文路径 + GBK 编码会炸），一律写 `.py` 文件再运行
   - 不要 `git add -A` / `git stash` / `git reset --hard`

5. **前端接口边界**：所有边框颜色用 `border-border`（17% 主题色），**禁止** `border-white`。

---

## 1. 项目定位与业务闭环

### 1.1 一句话
把「账号、素材、计划、排期、执行、监控、回收」统一到可编排的矩阵任务系统。

### 1.2 闭环
```
账号 → Persona 浏览器身份 → 固定代理 → Patchright 执行
     → 平台 Adapter → 发布 / 登录 / 数据回收
```

### 1.3 支持平台
| 平台 | 登录方式 | 发布 | 数据回收 |
|---|---|---|---|
| 抖音 | 扫码 / HTTP 逆向（实验） | ✅ | ✅ 本地 API |
| 快手 | 扫码 | ✅ | 付费 API |
| 小红书 | 扫码 | ✅ | 付费 API |
| 视频号 | 扫码 | ✅ | 付费 API |
| B 站 | 扫码 | ✅ | ✅ 本地 API |
| TikTok | Patchright 本机浏览器 | ✅ | ✅ TikHub API |
| YouTube | Patchright 本机浏览器 | ✅ | ✅ TikHub API |
| 百家号 | 扫码 | ✅ | — |

### 1.4 依赖上游（Apache-2.0 / MIT，见 `NOTICE.txt`）
- `social-auto-upload`（CLI 发布基础）
- `Douyin_TikTok_Download_API`（抖音/TikTok 数据）
- `HermesAgent`（本地 AI agent 运行时）
- `Persona Studio`（浏览器身份/指纹）

---

## 2. 顶层目录结构

```
D:\dim开发\Prism-Fusion\
├── README.md                    # 项目定位、SOP、API 示例
├── STARTUP.md                   # 首次启动指南
├── AGENT.md                     # AI agent 上下文与仓库卫生
├── DEVELOPMENT-RECORD.md        # 近期开发记录（47KB）
├── PLAN_next_steps.md           # 待办规划
├── PLAN_verification_measures.md# 验证方案
├── pyproject.toml / requirements.txt / uv.lock
├── package.json                 # 根级（pm2、启动脚本）
├── start.bat / start-mac.sh / start-pm2.sh / stop.bat
├── ecosystem.config.js / ecosystem-mac.config.js   # PM2 配置
├── prism_cli.py                 # CLI 入口（`prism` 命令）
├── prismenv/                    # Python 虚拟环境（不入库）
├── prism_backend/               # FastAPI 后端
├── prism_frontend/              # Next.js 前端
├── desktop-electron/            # Electron 客户端 + 打包
├── scripts/                     # 启动 / 打包 / 部署 / 调试脚本
│   ├── launchers/               # Windows .bat 启动脚本
│   ├── packaging/               # PyInstaller 打包脚本
│   ├── deploy/                  # nginx / setup 脚本
│   ├── hermes/                  # Hermes Agent 安装脚本
│   ├── dev/ / fixes/ / tests/ / maintenance/ / release/ / utilities/ / legacy/
├── tools/                       # ⚠️ 外部子模块（不入库）
│   ├── hermes-agent/            # Hermes Agent（上游 clone）
│   ├── hermes-webui/            # Hermes WebUI
│   ├── hermes-home/             # Hermes 运行时 home
│   └── persona-studio/          # Persona Studio（当前缺失）
├── docs/                        # 功能文档
│   ├── architecture/            # 架构设计
│   ├── hermes-skills/           # 每个平台发布技能的 SKILL.md
│   ├── demos/                   # 演示 GIF
│   ├── agent-bootstrap.md       # Agent 启动模板
│   ├── repo-layout-and-cleanup.md
│   ├── persona-studio-integration.md
│   └── douyin-publish-*.md      # 抖音发布专题
├── data/                        # 运行时数据（不入库）
├── logs/ / tmp/ / browsers/     # 运行产物（不入库）
└── runtime-data/                # PM2 数据目录
```

---

## 3. 后端架构（`prism_backend/`）

### 3.1 启动入口
- **开发**：`prism_backend/fastapi_app/run.py` → uvicorn，默认监听 `127.0.0.1:7000`
- **生产**：PyInstaller 打包成 `desktop-electron/resources/services/backend/backend.exe`，由 supervisor 拉起
- **入口**：`fastapi_app/main.py`

### 3.2 环境变量
模板在 `prism_backend/.env.example` 和 `fastapi_app/.env.example`。关键项：
- `BACKEND_PORT` / `LAOMA_BACKEND_PORT`：后端端口（supervisor 默认 9200，开发默认 7000）
- `PLAYWRIGHT_HEADLESS`：无头模式开关
- `LAOMA_BROWSER_BACKEND_DEFAULT`：`patchright` / `persona`
- `LAOMA_DOUYIN_LOGIN_MODE`：`browser`（默认）/ `http`（实验）
- `PERSONA_API_URL`：Persona 服务地址（默认 `http://127.0.0.1:8787`）
- Redis、DB、各类 API key、TikHub key 等

### 3.3 API 路由（`fastapi_app/api/v1/<module>/`）
按子目录列出，每个目录都有 `router.py`：

| 子目录 | 职责 |
|---|---|
| `accounts/` | 账号管理（绑定、登录、身份、代理、TikHub 回填） |
| `agent/` | Hermes Agent 配置、runtime、更新、MCP 服务器、插件、gateway |
| `ai/` + `ai_prompts/` | LLM 对话、提示词、线程 |
| `analytics/` | 数据回收（含 douyin sec_uid resolver） |
| `auth/` | 登录（browser_login、services、services_v2、version_switch） |
| `campaigns/` | 计划 / 排期（含 plans_alias、task_packages） |
| `ccswitch/` | CC Switch 集成 |
| `concurrency/` | 并发控制 |
| `content_library/` + `content_variant/` | 素材库 / 素材变体 |
| `cookies/` | Cookie 管理 |
| `crawler/` | 爬虫任务 |
| `creator/` | 创作者数据 |
| `dashboard/` | 仪表盘聚合 |
| `data/` | 数据查询 |
| `dedup/` | 去重 |
| `diagnostics/` | 系统诊断 |
| `easel_bridge/` | Easel 工作台桥接 |
| `files/` + `materials_alias/` | 素材文件 |
| `matrix/` | 矩阵任务生成（核心 API：`POST /matrix/generate_tasks`） |
| `mcp/` | MCP 服务 |
| `persona_proxy/` | per-country 代理网关绑定（7771-7776） |
| `proxies/` | Proxy Manager（IP 池） |
| `skills/` | 技能库注册中心 |
| `tasks/` | 任务队列 |
| `tools/` | 开发者工具中心（install/uninstall/launch/build/toggle） |
| `video_pipeline/` | 视频流水线 |
| `workshop/` | 创作工坊 |
| `fusion_ai/` | 聚合 AI 能力（`/fusion`） |
| `profile/` | 账号画像 |

**路由注册**：所有 `api/v1/*` 的路由聚合到 `api/v1/router.py`，由 `main.py` 挂到 `/api/v1`。

### 3.4 业务模块（`fastapi_app/` 之外）
`prism_backend/` 下还有：
- `automation_worker/` — 浏览器自动化执行 worker（独立进程，:7001）
- `fusion_ai/` — 聚合多 Provider LLM
- `ai_service/` — AI 服务封装
- `platforms/` — 平台适配器（老版）
- `app_new/platforms/` — 新版平台适配器（含 `douyin_http.py`）
- `douyin_tiktok_api/` — 抖音/TikTok 数据 API 集成
- `biliup/` — B 站发布（submodule，需 `git submodule update --init`）
- `video-pipeline/` — 视频处理流水线
- `uploader/` — 上传组件
- `prism_core/` — 核心逻辑
- `reverse_api/` — 逆向 API 研究（**仅研究，禁止用于生产**）
- `mcp_server.py` — MCP 服务端

### 3.5 数据存储
- **数据库**：见 `db/`、`models/`（SQL 或 JSON 存储，具体看代码）
- **Redis**：任务队列 + 分布式锁（`runtime_lock_service` 每账号锁）
- **文件目录**（不入库）：
  - `cookies/`、`cookiesFile/`：平台 Cookie
  - `browser_profiles/`：Patchright persistent context
  - `fingerprints/`：浏览器指纹
  - `uploads/`、`videoFile/`、`storage/`：素材
  - `data/`：`ip_pool*.json`、`campaigns.json`、`published_works.json` 等

### 3.6 关键依赖（15 个）
```
fastapi / uvicorn         # Web 框架
pydantic / pydantic-settings
sqlalchemy / redis
celery                    # 异步队列
patchright / playwright   # 浏览器自动化（patchright 是 playwright 反检测 fork）
aiohttp / httpx
Pillow                    # 图片
moviepy / ffmpeg-python   # 视频处理
loguru                    # 日志
```

---

## 4. 前端架构（`prism_frontend/`）

### 4.1 技术栈
- Next.js（App Router） + React + TypeScript
- Tailwind CSS + shadcn/ui（`components/ui/`）
- Zustand 或 React Query（看 `src/store/` 或组件内）
- 构建输出：`.next/standalone` 供 Electron 打包使用

### 4.2 后端地址配置
`next.config.ts` 中：
```ts
const publicBackendUrl = process.env.NEXT_PUBLIC_BACKEND_URL
                     || process.env.NEXT_PUBLIC_API_BASE
                     || "http://127.0.0.1:7000"
```
前端用 `NEXT_PUBLIC_BACKEND_URL` 覆盖默认 `http://127.0.0.1:7000`。模板见 `.env.local.example`。

### 4.3 页面清单（`src/app/`）
| 路由 | 用途 |
|---|---|
| `/` | 首页 |
| `/account` | 账号管理（登录、扫码、Persona 代理绑定） |
| `/publish/matrix` | **矩阵发布**（核心，含多平台 Config） |
| `/publish/distribution` | 分发任务抽屉 |
| `/materials` | 素材库 |
| `/campaigns` | 计划/排期 |
| `/calendar` | 发布日历 |
| `/tasks` | 任务队列看板 |
| `/breakdown` | 数据拆解 |
| `/analytics/*` | 数据回收（按平台 `/analytics/videos/[platform]`） |
| `/profile` | 账号画像 |
| `/trends` | 热点 |
| `/ideas` | 灵感库 |
| `/chat` | AI 对话 |
| `/workshop` | 创作工坊 |
| `/video-pipeline` | 视频流水线 |
| `/fusion` | 聚合 AI（多 Provider） |
| `/easel-workbench` / `/easel-content` / `/easel-inbox` | Easel 工作台 |
| `/ai-agent` / `/ai-agent/settings` | Hermes Agent 面板 + 设置 |
| `/skills` | 技能库 |
| `/persona` / `/persona-proxy` | Persona 身份层 / per-country 代理 |
| `/ip-pool` | IP 池管理 |
| `/tools` | 开发者工具中心 |
| `/settings` | 系统设置（浏览器管理、无头、进程） |
| `/cms` | 隐藏后台（运行时开关） |
| `/dashboard-demo` | 演示仪表盘 |
| `/api/*` | Next.js API routes（代理/桥接） |

### 4.4 关键组件
- `src/app/publish/components/PlatformConfigs.tsx` — **多平台 Config 组件**（DouyinConfig、KuaishouConfig、XhsConfig、BilibiliConfig、VideoChannelConfig）。改多平台 UI 先动这里
- `src/app/publish/components/PlatformSelector.tsx` — 平台选择器
- `src/components/hermes/*` — Hermes 相关组件（embedded host、config panels、provider card）
- `src/components/ui/*` — shadcn/ui 基础组件
- `src/app/settings/hooks/useSettingsActions.ts` — 系统设置 hook（浏览器 runtime 状态等）

### 4.5 已知前端坑
1. **`<Select.Item value="">` 会崩**（Radix UI 硬约束）
   - `""` 是保留值，用于清空选中显示 placeholder
   - Next.js 14+ dev 模式会抛 `Runtime Error`
   - **改法**：用 `"none"` 之类占位，`onValueChange` 里转回 `null`/`undefined`
   - 已修过：`PlatformConfigs.tsx:383` DouyinConfig 的"不加入合集"选项
2. **中文路径 + PowerShell 编码**
   - `python -c "..."` 会因 GBK 编码报错
   - 写 `.py` 文件再跑
3. **Next.js Agent Rules**（`prism_frontend/AGENTS.md`）
   - 该版本 Next.js 是特化版本，API 和约定可能不同于训练数据
   - 写代码前先看 `node_modules/next/dist/docs/`

---

## 5. 桌面端与打包（`desktop-electron/`）

### 5.1 技术栈
- Electron 28.0.0
- electron-builder 24.13.3
- PyInstaller（把 Python 服务打成 exe）
- Inno Setup（生成 NSIS 安装包）

### 5.2 关键文件
- `desktop-electron/package.json`：name `laoma-ai-workbench`，version `1.1.0`
- `desktop-electron/installer.iss`：Inno Setup 脚本（安装路径、快捷方式）
- `desktop-electron/resources/supervisor/supervisor.py`：**进程编排器（1589 行）**
- `desktop-electron/resources/supervisor/api_server.py`：supervisor 对外 HTTP API
- `desktop-electron/resources/services/backend/backend.exe`：PyInstaller 打的后端

### 5.3 Supervisor 管理的子服务
`supervisor.py` 里定义的 `service_ports`：
| 服务 | 端口 | 启动方式 |
|---|---|---|
| `backend` | 9200（supervisor 期望） | PyInstaller exe 或 python |
| `automation-worker` | 7001 | 同上 |
| `celery-worker` | — | python -m celery |
| `hermes-gateway` | — | hermes CLI |
| `hermes-dashboard` | 9119 | hermes CLI |
| `hermes-webui` | 9131 | server.py |
| `api_server` | 7000（Electron ↔ supervisor 通信） | 内嵌 |

⚠️ **已知不一致**：`backend.exe` 实际监听 **7000**，但 supervisor 期望 **9200**（`BACKEND_PORT` 环境变量未生效或未读取）。**待修**：定位根因。

### 5.4 打包流程
```powershell
cd desktop-electron
npm install
npm run pack         # 或 npm run dist
# 或走 scripts/packaging/build_services.ps1 先打 PyInstaller，再 electron-builder
```
产物：`desktop-electron/dist-build/老马AI工作台-X.Y.Z-setup.exe`。

### 5.5 已知打包坑
1. **Redis 未打包进 installer**
   - 打包日志警告 `file source doesn't exist from=...resources\redis`
   - 结果：`D:\Program Files\LaomaAI\resources\Redis\` 不存在
   - 影响：Redis 相关功能可能挂
2. **`supervisor.log` 和 `backend.log` 都是 0 字节**
   - supervisor.py 里 `RotatingFileHandler("logs/supervisor.log")` 是相对路径
   - PyInstaller 打包后 cwd 不对，日志写不进预期目录
   - 影响：出问题没日志可查
3. **supervisor 传的 `BACKEND_PORT` 未生效**
   - supervisor 期望 :9200，backend.exe 实际 :7000
   - 影响：supervisor 健康检查一直失败（虽然 API 实际是通的）

---

## 6. 端口与进程全景

### 6.1 开发模式（`start.bat`）
| 进程 | 端口 |
|---|---|
| Next.js 前端 | 3000 |
| FastAPI 后端 | 7000 |
| Automation Worker | 7001 |
| Redis | 6379 |
| Persona serve | 8787 |
| Hermes Dashboard | 9119 |
| Hermes WebUI | 9131 |
| per-country 代理网关 | 7771-7776 |
| Supervisor API（仅 supervisor 模式） | 7002 |

### 6.2 生产模式（Electron 安装后）
安装目录：`C:\Program Files\LaomaAI\` 或 `D:\Program Files\LaomaAI\`

进程链：
```
LaomaAI.exe (main)
  └─ Supervisor (python)
       ├─ backend.exe (PyInstaller) → :7000（实际）/:9200（期望）
       ├─ automation-worker.exe → :7001
       ├─ celery-worker (python)
       ├─ hermes-dashboard → :9119
       └─ hermes-webui → :9131
  └─ Next.js standalone → :3000
```

---

## 7. 关键运维脚本（`scripts/`）

### 7.1 启动（`scripts/launchers/`）
```
start_stack_prismenv.bat       # 一键启动全部（prismenv 模式）
start_stack_supervisor.bat     # supervisor 模式
start_stack_conda.bat          # conda 模式
start_redis.bat / start_backend.bat / start_celery.bat / start_worker.bat / start_frontend.bat
restart_backend.bat / restart_celery.bat
stop_celery.bat / force_kill_backend.bat
kill_port_7000.bat / kill_port_7001.bat
setup_browser.bat              # 装浏览器依赖
```

### 7.2 打包（`scripts/packaging/`）
```
build_services.ps1             # 打包 Python 服务为 exe
build-supervisor.bat / build-package.bat
build-version.json             # 版本号配置
install_hibbiki_chromium.ps1   # 装 hibbiki chromium
```

### 7.3 部署（`scripts/deploy/`）
```
nginx.conf / setup-nginx.sh    # 生产 nginx 部署
```

### 7.4 其他
- `scripts/hermes/`：Hermes 安装/同步
- `scripts/dev/`：开发辅助
- `scripts/tests/`：验证脚本
- `scripts/fixes/`：一次性修复脚本（用完可留档）
- `scripts/maintenance/`：日常维护
- `scripts/release/`：发版流程
- `scripts/ip_pool/`：IP 池管理
- `scripts/utilities/`：通用工具
- `scripts/legacy/`：历史遗留

---

## 8. 数据库与状态存储约定

### 8.1 敏感文件（**绝不入库**）
见 `.gitignore` 和 `AGENT.md`：
```
.env / *.env.local
prism_backend/cookiesFile/ / config/cookiesFile/
prism_backend/browser_profiles/ / config/browser_profiles/
prism_backend/fingerprints/
prism_backend/data/ip_pool*.json
prism_backend/data/account_stats*.json
prism_backend/data/campaigns.json
prism_backend/data/published_works.json
prism_backend/logs/ / logs/
data/analytics/ / data/crawler_output/ / data/videos/
*.db / *.sqlite* / dump.rdb
tools/hermes-home/auth.json / .env
```

### 8.2 关键运行时状态
- `prism_backend/config/hermes_agent.toml`：Hermes 桥接配置
- `prism_backend/config/llm_config.toml`：LLM Provider 配置（含 key）
- `tools/hermes-home/auth.json`：Hermes 登录状态（拷给同事会共享账号）
- `runtime-data/pm2/`：PM2 运行时
- `runtime-data/app/hermes-home/`：Hermes 技能同步目标

---

## 9. 代码风格与约定

### 9.1 命名
- 后端仍是"老马AI工作台"，**不要**改成 `LaomaAI-Fusion` 之类
- 前端 Next.js App Router 结构：`app/<route>/page.tsx` + `layout.tsx`
- Python 后端：`fastapi_app/api/v1/<module>/{router,services,schemas}.py` 三件套

### 9.2 前端 UI 约定（重要）
- **边框**：只用 `border-border`（17% 主题色），**禁止** `border-white` 100% 不透明
- Hover 状态也用 `hover:border-border`
- Dashed / translucent 变体也保持 17% 主题色

### 9.3 Agent Skills
- 每个平台发布有独立 SKILL.md：`docs/hermes-skills/prism-publish-*/SKILL.md`
- Hermes agent 启动时默认预加载 `prism-project-layout` 技能（`DEFAULT_PRELOAD_SKILL`）
- 同步机制：`hermes_config.py::sync_prism_project_skill()`

### 9.4 Git 约定
- 提交前 `git status --short`，确认无敏感文件
- 用显式路径 `git add <path>`，不用 `git add -A`
- 提交消息不含账号 ID、cookie 值、代理 IP、绝对路径

### 9.5 Python 环境约定
- 优先用 `prismenv/`（start.bat 硬编码）
- 装依赖用 `pip install -r requirements.txt`（或 `uv sync`）
- **不要**往 `tools/` 塞本项目代码（外部子模块）
- **不要**全局替换"老马AI工作台"字符串

---

## 10. 抖音相关特别约定（`prism_backend/AGENTS.md`）

**⚠️ 核心约束**：`DouyinHttpAdapter`（HTTP 逆向登录）**仅实验用途，严禁接入正式发布路径**。

- 位置：`app_new/platforms/douyin_http.py`
- 原因：抖音登录涉及 `verifycenter` 会话、`s_v_web_id` 反爬，HTTP 客户端无法真实触发浏览器 JS 环境，返回 `error_code=2156 "系统繁忙"`
- 详见：`prism_backend/reverse_api/DOUYIN_HTTP_2156_FINDINGS.md`

**正式发布永远走**：`DouyinAdapter`（`app_new/platforms/douyin.py`）+ `PlaywrightLoginManager`（`fastapi_app/api/v1/auth/services.py`）

**允许 HTTP 模式仅在**：
1. `LAOMA_DOUYIN_LOGIN_MODE=http` 明确设置
2. 仅 worker/API 层默认用 HTTP adapter
3. 账号系统、发布链路、扫码入口禁用 HTTP

**改动前必读**：`DOUYIN_HTTP_2156_FINDINGS.md` + `prism_backend/AGENTS.md`。

---

## 11. 常见问题（快速排查）

| 现象 | 排查 |
|---|---|
| `prismenv not found` | `python -m venv prismenv && pip install -r requirements.txt` |
| Redis 启动失败 | 装 Redis：`prism_backend/Redis/` 或系统 PATH |
| 前端白屏 | Node 没装 / `npm install` 没跑完 |
| 端口 7000 被占 | `scripts\launchers\kill_port_7000.bat` |
| 队列不执行 | `redis-cli ping` |
| `/fusion` 404 | Hermes 没装，见 `STARTUP.md §4` |
| Persona 端口不通 | Persona Studio 没装（当前不在仓库） |
| 依赖装不上 | Python 3.10-3.12，网络可达 PyPI |
| `address already in use` | `stop_stack.bat` 干净退出 |
| 抖音发布失败 | 先确认登录模式：`LAOMA_DOUYIN_LOGIN_MODE` 应为 `browser` |
| 前端 Select 报错 `value=""` | Radix UI 硬约束，改用非空字符串占位 |
| PowerShell 中文路径报错 | 写 `.py` 文件，不 inline |
| Electron 打包后日志 0 字节 | supervisor.py 相对路径问题，见 §5.5 |
| 后端 :9200 无响应 | backend.exe 实际监听 :7000，supervisor 期望 :9200 不匹配 |

---

## 12. 接手检查清单

新 agent 拿到的第一件事：

- [ ] 读 `AGENT.md` + `STARTUP.md`
- [ ] `cd D:\dim开发\Prism-Fusion && git status --short`（看是否有脏工作区）
- [ ] 尝试 `python prismenv\Scripts\python.exe --version`（验证 venv 存在）
- [ ] 尝试 `cd prism_frontend && node --version`
- [ ] 读 `docs/hermes-skills/prism-project-layout/SKILL.md`（后端路由权威）
- [ ] 读 `DEVELOPMENT-RECORD.md` 最近 200 行（近期在做什么）
- [ ] 明确本次任务范围（不要顺手改别的地方）

---

## 13. 已知未完成 / 待办

从最近对话和历史线索看，以下事项未闭合：

1. **Supervisor 端口不一致**：`BACKEND_PORT` 环境变量传给 backend.exe 未生效（supervisor 期望 :9200，实际 :7000）
2. **Supervisor 日志为空**：`supervisor.log`、`backend.log` 都是 0 字节，PyInstaller stdout 未重定向
3. **Redis 未打包**：installer 里缺 `resources/Redis/`，运行时 Redis 相关功能可能挂
4. **抖音 Select.Item 空 value** 已修（`PlatformConfigs.tsx:383`），但可能还有其他组件存在同类问题，需扫一遍
5. **矩阵发布点抖音其他操作**：需要用户提供具体错误进一步定位
6. **`"语音接入配置读取失败"` 粉色条**：早期用户反馈，源码中未定位到（推测是运行时 toast）
7. **抖音/tiktok 品牌色渐变**：已改，待用户视觉确认

---

## 14. 联系方式与上游

- 项目 GitHub：`https://github.com/maning636/laoma-ai-workbench`
- 社区：LINUX DO
- 许可证：AGPL-3.0（本项目代码）+ MIT/Apache-2.0（上游组件）
- 归属详见：`NOTICE.txt`

---

## 15. 文档索引

| 文件 | 用途 |
|---|---|
| `README.md` | 项目定位、SOP、API 示例 |
| `docs/handover/PROJECT-HANDOVER.md` | **交棒入口（2026-10-24）**：项目全过程 + 交付清单 + 未来计划 + 踩坑清单 |
| `docs/handover/DELIVERY-CHECKLIST.md` | 交付确认单：接手工作组逐项核对回执 |
| `STARTUP.md` | 首次启动、常见坑 |
| `AGENT.md` | AI agent 上下文、仓库卫生 |
| `DEVELOPMENT-RECORD.md` | 近期开发记录 |
| `PLAN_next_steps.md` | 待办规划 |
| `PLAN_verification_measures.md` | 验证方案 |
| `prism_backend/AGENTS.md` | 后端特别规则（抖音 HTTP 模式禁令） |
| `prism_frontend/AGENTS.md` | Next.js 版本特殊性说明 |
| `docs/hermes-skills/prism-project-layout/SKILL.md` | 后端完整路由清单 |
| `docs/hermes-skills/prism-publish-*/SKILL.md` | 每平台发布技能 |
| `docs/architecture/` | 架构设计文档 |
| `docs/douyin-publish-*.md` | 抖音发布专题 |
| `docs/persona-studio-integration.md` | Persona Studio 集成 |
| `docs/mcp-server.md` | MCP 服务端 |
| `desktop-electron/README_INSTALL.txt` | 桌面端安装说明 |
| **本文件** `HANDOFF.md` | 交接文档（你在这里） |

---

**最后一句话**：这是一个成熟但仍在迭代的商业级项目。改任何地方前先想清楚影响面，改完跑一遍相关测试，绝不 commit 敏感数据。有疑问优先读上游文档，不猜测。
