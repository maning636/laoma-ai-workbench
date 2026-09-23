# Prism-Fusion 新机器启动指南

本指南面向拿到整个文件夹、需要在新电脑上继续开发的人。
读完你应该能在 30 分钟内把前后端跑起来。

> 仓库定位：FastAPI 后端 + Next.js 前端 + Celery/Redis 队列 + Hermes Agent（上游能力）。
> 后端路径仍保留 "Prism" 命名，这是历史包袱，**不要**顺手全局改名。

---

## 0. 前置要求

| 软件 | 版本 | 说明 |
|---|---|---|
| Python | 3.10 – 3.12 | `pyproject.toml` 要求 `>=3.10,<3.13`。3.11 首选 |
| Node.js | 18+ | 前端 Next.js 15 |
| Redis | 任意 6+ | 队列 + 账号级 Browser Runtime 分布式锁 |
| 网络 | 需要 | 首次启动要装依赖（见下） |
| 浏览器 | 可选 | 平台自动化走 `scripts\launchers\setup_browser.bat` |

Windows 环境。`start.bat` 只覆盖 Windows 路径。

---

## 1. 拿到代码

### 方式 A：复制整个文件夹（推荐，最快）

把 `Prism-Fusion` 整个目录拷到新机器，然后：

```bat
cd <你的路径>\Prism-Fusion
start.bat
```

`start.bat` 会自动：
1. 检测 `prismenv` 虚拟环境 → 不存在就用系统 Python 创建；
2. 按 `requirements.txt` 安装后端依赖（约 230 MB，需要网络）；
3. 检测前端 `node_modules` → 不存在就 `npm install`（约 970 MB）；
4. 依次拉起 Redis、Celery、Automation Worker、FastAPI、前端、Persona。

### 方式 B：git clone

```bat
git clone https://github.com/Laihiujin/Prism.git
cd Prism
start.bat
```

**⚠️ 重要：`tools/` 下所有内容都不被主仓库跟踪。**
`.gitignore` L191-196 明确排除它们（注释：「外部项目 clone（构建时拉取，不入库）」）。
复制整个文件夹则全部保留；clone 方式必须自己装。

**核心栈（后端 + 前端 + Celery）不需要下面任何一项。** 缺了只会导致 `/fusion` 等 Hermes 能力接口不可用。

```bat
cd tools

:: 1) Hermes Agent —— 上游开源，pin 到已验证可用的提交
git clone https://github.com/NousResearch/hermes-agent.git
cd hermes-agent
git checkout bb0c230      :: setup-local-hermes.ps1 里硬编码的这个值
cd ..

:: 2) Hermes WebUI —— 独立上游，装成 zip 解包
powershell -ExecutionPolicy Bypass -File ..\scripts\hermes\install-hermes-webui.ps1

:: 3) 装好运行时
powershell -ExecutionPolicy Bypass -File scripts\hermes\setup-local-hermes.ps1
```

注意 `setup-local-hermes.ps1` **只会装 hermes-agent**，它把 `tools/hermes-webui/server.py`
列为「必须已存在」的前置条件。所以第 2 步不能跳过。

**⚠️ 自定义发布技能不会被任何脚本自动安装。**
抖音 / 小红书 / B站 / 视频号 / 快手 / TikTok / YouTube / 百家号的发布技能，
唯一被跟踪的源在 `docs/hermes-skills/`。装好 Hermes 后需要手动复制到它的 home：

```bat
xcopy /E /Y docs\hermes-skills\* tools\hermes-home\skills\software-development\
```


---

## 2. 首次启动

```bat
start.bat
```

等 2–5 分钟（首次要装依赖）。各端口：

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端 | http://localhost:3000 | AI Agent 入口 `/ai-agent` |
| FastAPI 后端 | http://127.0.0.1:7000 | API 根路径 `/api/v1/` |
| Persona API | 见 `tools/persona-studio` | 账号画像 |
| Persona Dashboard | 见 launcher 输出 | 前端仪表盘 |

### Redis 处理

项目内 `prism_backend\Redis\` 目录是**空的**（二进制未随仓库分发）。`start_stack_prismenv.bat` 的查找顺序是：

1. `prism_backend\Redis\redis-server.exe`
2. 系统 PATH 里的 `redis-server`

**新机器上你需要自己装 Redis**，二选一：

- 从 https://github.com/tporadowski/redis/releases 下载 Windows 版，解压到 `prism_backend\Redis\`（这样项目自带，不用配 PATH）；
- 或全局安装并加入 PATH。

不装 Redis，Celery 队列和账号级浏览器锁都不会工作。

---

## 3. 目录结构速览

```
Prism-Fusion/
├── prism_backend/          # FastAPI 后端（543 个跟踪文件）
│   ├── fastapi_app/api/v1/ # 所有 REST 路由
│   ├── config/             # 配置模板（conf.py 无密钥，可入库）
│   └── Redis/              # ← 空目录，Redis 二进制放这里
├── prism_frontend/         # Next.js 前端（258 个跟踪文件）
├── scripts/launchers/      # 所有 .bat 启动脚本
├── tools/hermes-agent/     # ⚠️ 独立 git 仓库，不被主仓库跟踪
├── tools/hermes-webui/     # ⚠️ 同上，需 install-hermes-webui.ps1
├── tools/persona-studio/   # ⚠️ 同上，start.bat 会尝试拉起但容忍缺失
├── tools/hermes-home/      # ⚠️ Hermes 运行时 home，含本地 auth.json
├── docs/hermes-skills/     # ✅ 唯一被跟踪的发布技能源（11 个）
├── docs/                   # 文档
├── start.bat               # 总入口，带自举逻辑
├── STARTUP.md              # 本文件
└── pyproject.toml / uv.lock / requirements.txt
```

### 本轮新增的成品模块（刚提交入库）

后端 `fastapi_app/api/v1/` 下新增 6 个路由，已注册进 `router.py`：

- `easel_bridge` → `/easel` 工作台托管（内嵌 iframe + 稿件桥）
- `skills` → `/skills` 技能库注册中心
- `workshop` → `/workshop` 创作工坊（脚本表单直调）
- `video_pipeline` → `/video-pipeline` 视频流水线（HyperFrames 引擎）
- `content_library` → `/content-library` 原生内容库
- `profile` → `/content-library/profile` 账号画像

外加 `fusion_ai/` → `/fusion`，聚合 AI 多 Provider / 平台风格 / 生图 / 热点 / 审核 / 模型广场 / 技能 / 认知 / NL→SQL / 配置中心。

前端对应页面在 `prism_frontend/src/app/`：`easel-workbench`、`easel-inbox`、`easel-content`、`skills`、`workshop`、`video-pipeline`、`breakdown`、`calendar`、`chat`、`fusion`、`ideas`、`profile`、`trends`、`publish`、`analytics`。

---

## 4. 日常开发

```bat
# 只重启某个服务
scripts\launchers\restart_backend.bat
scripts\launchers\restart_celery.bat

# 停全部
scripts\launchers\stop_stack.bat

# 释放端口（后端 7000 / 前端 7001）
scripts\launchers\kill_port_7000.bat
scripts\launchers\kill_port_7001.bat

# supervisor 模式（Redis + Supervisor + 前端）
start.bat supervisor

# conda 模式（不用 prismenv 时）
start.bat conda
```

依赖变更：改 `requirements.txt` 后重新 `start.bat` 即可，`ensure_prismenv` 会比较 `requirements.txt` 与 `.requirements-ready` 时间戳，变了就重装。

---

## 5. 已刻意清理的内容

为了让文件夹可移植，以下均已删除。**新机器上会按需自动重建**，不要困惑：

| 已删 | 体积 | 重建方式 |
|---|---|---|
| `prism_frontend/node_modules` | 970 MB | `start.bat` 自动 `npm install` |
| `prism_frontend/.next` | 219 MB | Next.js 构建缓存，自动重建 |
| `.venv` | 577 MB | **无人引用**，永久删除 |
| `prismenv` | 231 MB | `start.bat` 自动创建 + 装依赖 |
| `tools/hermes-agent/node_modules` | 287 MB | 在该目录 `npm install` |
| `build/supervisor/` | 12 MB | PyInstaller 产物，已加入 `.gitignore` |
| `tmp/`、`logs/`、`prism_publisher.egg-info`、各 `__pycache__` | 50 MB | 运行产物 |

保留理由：这些全是机器生成的派生物，占原体积 1.7 GB / 2.58 GB。保留源码 + 锁定文件，新机器几分钟内可完全复现。

---

## 6. 配置与密钥

仓库里**没有**任何密钥，也没有 `.env`。只有一套模板：

```bat
:: 后端主配置
prism_backend/config/conf.py          # 纯模板，无密钥，可直接入库
:: 各模块 .env.example（共 5 份）
```

首次运行前按需复制并填写：

```bat
copy prism_backend\.env.example prism_backend\.env
```

需要填的通常是：LLM API Key、各平台 cookie/token、`hermes_agent.toml`（Hermes 桥接）。
**密钥不要提交进 git。**

### 本机状态文件（不在仓库里，新机器上没有）

这几类东西被 `.gitignore` 排除，因为它们是**你本机的身份和凭据**，不是代码：

| 位置 | 内容 | 新机器怎么办 |
|---|---|---|
| `prism_backend/.env` | LLM key、平台 token | 自己填 |
| `prism_backend/config/hermes_agent.toml` | Hermes 桥接配置 | 从模板改 |
| `prism_backend/config/llm_config.toml` | LLM 多 Provider 配置 | 从模板改 |
| `tools/hermes-home/.env`、`auth.json` | Hermes 登录凭据 | 首次运行 Hermes 后自动生成 |
| `prism_backend/Redis/` | Redis 二进制 | 见第 2 节 |

`tools/hermes-home/` 里含 Hermes 的登录状态（`auth.json`、`.env`）。
它被 `.gitignore` 排除所以**不会进 git**，但如果你用「复制整个文件夹」的方式迁移，
这些文件会被一起拷过去 —— 那意味着新程序员会继承你的 Hermes 登录态。

两种处理：

- **想让新程序员用你自己的账号跑**：什么都不用做，凭据已经跟文件夹走了。
- **想让新程序员用自己的账号**：删掉 `tools/hermes-home\auth.json`、
  `tools/hermes-home\.env`、`tools/hermes-home\auth.lock`，首次运行 Hermes 会自动重建。

---

## 7. 已知边界

- **`.git` 是浅克隆**（`git rev-list --count HEAD` = 1），只有最近 1 个提交的快照。要完整历史：
  ```bat
  git fetch --unshallow
  ```
  remote 是 `https://github.com/Laihiujin/Prism.git`，需要有写权限才能推送。
- **`prism_backend/biliup` 是空的 submodule**（`git submodule status` 显示未初始化）。用到 B 站发布时才需要：
  ```bat
  git submodule update --init prism_backend/biliup
  ```
- **`start.bat` 硬编码 `prismenv`**，完全不用 `.venv`。所以仓库里不再保留任何虚拟环境。
- **`ecosystem.config.js` 用相对路径**（`cwd: './prism_frontend'`），可移植。
- 路径全部相对，无绝对路径硬编码（已扫描确认）。

---

## 8. 出问题时先查

1. 后端起不来 → `restart_backend.bat`，看 7000 端口是否被占（`kill_port_7000.bat`）
2. 前端白屏 → `node_modules` 是否已装；`npm run dev` 日志
3. 队列任务不执行 → Redis 是否在跑（`redis-server` 进程）
4. `/fusion` 相关接口 404 → `tools/hermes-agent` 是否已 clone
5. 依赖装不上 → Python 版本是否在 3.10–3.12；网络是否通

有问题先跑 `scripts\launchers\stop_stack.bat` 再重试，别叠进程。
