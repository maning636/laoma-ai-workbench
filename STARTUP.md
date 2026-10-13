# LaomaAI-Fusion 新机器启动指南

你拿到整个 `LaomaAI-Fusion` 文件夹后，按下面**第 1 节**做完就能跑起来。
预计时间：第一次 15–30 分钟（装工具 + 装依赖），之后每次 1 分钟。

> 仓库定位：FastAPI 后端 + Next.js 前端 + Celery/Redis 队列 + Hermes Agent（可选加件）。
> 后端路径仍保留 "老马AI工作台" 命名，这是历史包袱，**不要**顺手全局改名。

---

## 1. 五步跑起来（首次）

### 第 1 步：确认环境

需要已经装好（如果没有就装，都装最新版）：

- **Python 3.11** —— 从 https://www.python.org/downloads/ 下载。安装时**必须勾选**「Add python.exe to PATH」
- **Node.js 18 或更新** —— 从 https://nodejs.org/ 下载 LTS 版
- **Git** —— 从 https://git-scm.com/ 下载。用于 submodule 和推送代码
- **网络** —— 首次要装依赖（~700 MB），断网装不上
- **Redis** —— 有两种装法，见「第 1 步补充」

验证：

```bat
python --version   :: 应显示 3.11.x
node --version     :: 应显示 v18+
git --version      :: 应显示 2.x
```

**第 1 步补充：装 Redis（二选一）**

```bat
:: 方案 A：项目自带，不用配 PATH（推荐）
:: 从 https://github.com/tporadowski/redis/releases 下载最新 MSVC Release zip
:: 解压到 LaomaAI-Fusion\prism_backend\Redis\
:: start.bat 会优先找这个路径

:: 方案 B：系统级安装
:: 下载并安装 Redis，加入 PATH，start.bat 会用 PATH 里的 redis-server
```

### 第 2 步：把文件夹放到合适位置

**建议放在 `D:\LaomaAI-Fusion`**（或任意纯英文短路径）。不要放中文路径、不要放很长的嵌套路径，Windows 上很多工具对路径长度敏感。

文件夹拷过去后确认一下：

```bat
cd D:\LaomaAI-Fusion
dir start.bat       :: 应该存在
dir prism_backend   :: 应该有 fastapi_app 子目录
dir prism_frontend  :: 应该有 package.json
```

### 第 3 步：装 Python 依赖（start.bat 自动做）

✅ **`start.bat` 会自动建 `prismenv` 并装依赖**，一般不需要手动跑。它内部会：

- 找不到 `prismenv\Scripts\python.exe` 就用 `py -3.11` / `py -3` / `python` 建一个 venv
- 用 `prismenv\.requirements-ready` 时间戳对比 `requirements.txt`，只要 requirements 比时间戳新就重装一次
- 装依赖时先升级 pip，再 `pip install -r requirements.txt`

（如果 `start.bat` 里 Python 检测失败，或你想用 conda 手动建，就自己跑：）

```bat
cd D:\LaomaAI-Fusion
python -m venv prismenv
prismenv\Scripts\activate
pip install -r requirements.txt
```

大概 2–5 分钟，看网速。装完看到 `Successfully installed ...` 就成功了。

> `uv.lock` 也提交了，如果装了 [uv](https://docs.astral.sh/uv/)，可以更快：
> `uv sync`（会自动用 lock 文件里的精确版本）

### 第 4 步：装前端依赖（只做一次）

```bat
cd D:\LaomaAI-Fusion\prism_frontend
npm install
```

大概 1–3 分钟。`package-lock.json` 已提交，版本可复现。

> 也可以跳过这步，`start.bat` 会检测到 `node_modules` 缺失然后自己 `npm install`。

### 第 5 步：启动

回到项目根目录：

```bat
cd D:\LaomaAI-Fusion
start.bat
```

等 1–2 分钟（服务逐个拉起），全部启动后：

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端 | http://localhost:3000 | AI Agent 入口 `/ai-agent` |
| FastAPI 后端 | http://127.0.0.1:7000 | API 根路径 `/api/v1/` |
| Celery worker | 后台进程 | 队列任务 |
| Redis | localhost:6379 | 队列 + 分布式锁 |

浏览器打开 http://localhost:3000 看到页面就成功了。

**如果启动时报错**，最常见的是 3 个：

1. `Virtual environment "prismenv" not found` → 第 3 步没做
2. `Redis startup failed` → 第 1 步的 Redis 没装，装一下再来
3. `npm: command not found` → Node.js 没装，回去装

---

## 2. 之后每次启动

```bat
cd D:\LaomaAI-Fusion
start.bat
```

1 分钟内启动完成。停止服务用 `scripts\launchers\stop_stack.bat`，别叠进程。

---

## 3. 配置密钥

仓库里**没有任何密钥**，只有一套模板。首次跑通基本功能后，按需复制填写：

```bat
copy prism_backend\.env.example prism_backend\.env
```

需要填的通常是：

- LLM API Key（调 AI 用）
- 各平台 cookie/token（抖音 / 小红书 / B站 / 视频号 / 快手 / TikTok / YouTube / 百家号）
- `prism_backend/config/hermes_agent.toml`（Hermes 桥接，可选）
- `prism_backend/config/llm_config.toml`（多 Provider LLM 配置，可选）

**密钥不要提交进 git。** `.gitignore` 已经排除 `.env` 和 `hermes_agent.toml`。

---

## 4. Hermes Agent（可选，按需装）

**核心栈（后端 + 前端 + Celery）不依赖 Hermes**。不装也行，只是以下功能不可用：

- AI 多 Provider（`/fusion/ai`）
- Persona Studio（`/persona`）
- 技能工坊（`/workshop`）
- 创作工坊、视频流水线的 AI 能力
- 平台风格、热点、审核、认知、模型广场

如果要装，先确认工具齐全（git、python、node 都要有），然后：

```bat
cd D:\LaomaAI-Fusion

:: 1) 装 Hermes Agent —— 上游开源
cd tools
git clone https://github.com/NousResearch/hermes-agent.git
cd hermes-agent
git checkout bb0c230       :: setup-local-hermes.ps1 里硬编码的已知可用版本
cd ..\..

:: 2) 装 Hermes WebUI —— 独立上游，装成 zip 解包
powershell -ExecutionPolicy Bypass -File scripts\hermes\install-hermes-webui.ps1

:: 3) 装好运行时
powershell -ExecutionPolicy Bypass -File scripts\hermes\setup-local-hermes.ps1

:: 4) 安装自定义发布技能（不会被脚本自动装）
xcopy /E /Y docs\hermes-skills\* tools\hermes-home\skills\software-development\
```

**注意：** `setup-local-hermes.ps1` 只装 hermes-agent，它把 `tools/hermes-webui/server.py` 列为「必须已存在」的前置条件。所以第 2 步不能跳过。

`Persona Studio` 是独立的第三个组件，如果要用 `/persona` 相关功能，还需要单独 clone `tools/persona-studio`（目前仓库里没有）。

---

## 5. 目录结构速览

```
LaomaAI-Fusion/
├── prism_backend/          # FastAPI 后端
│   ├── fastapi_app/api/v1/ # 所有 REST 路由
│   ├── config/             # 配置模板（conf.py 无密钥，可入库）
│   └── Redis/              # Redis 二进制放这里（可选，见第 1 步）
├── prism_frontend/         # Next.js 前端
├── scripts/launchers/      # 所有 .bat 启动脚本
├── docs/hermes-skills/     # 唯一被跟踪的 11 个发布技能源
├── docs/                   # 其他文档
├── start.bat               # 总入口
├── STARTUP.md              # 本文件
├── pyproject.toml          # Python 依赖声明
├── uv.lock                 # 依赖锁（uv 用户）
├── requirements.txt        # 依赖锁（pip 用户）
└── tools/                  # ⚠️ 全部不被 git 跟踪（见下节）
    ├── hermes-agent/       #   Hermes Agent（上游 clone）
    ├── hermes-webui/       #   Hermes WebUI（脚本安装）
    ├── hermes-home/        #   Hermes 运行时 home（含 auth.json）
    └── persona-studio/     #   Persona Studio（目前不在本仓库）
```

### 本轮新加的成品模块

后端 `fastapi_app/api/v1/` 下新注册的路由：

- `easel_bridge` → `/easel` 工作台托管
- `skills` → `/skills` 技能库注册中心
- `workshop` → `/workshop` 创作工坊
- `video_pipeline` → `/video-pipeline` 视频流水线
- `content_library` → `/content-library` 原生内容库
- `profile` → `/content-library/profile` 账号画像
- `fusion_ai/` → `/fusion` 聚合 AI 能力

前端对应页面在 `prism_frontend/src/app/`：`easel-workbench`、`skills`、`workshop`、`video-pipeline`、`breakdown`、`calendar`、`chat`、`fusion`、`ideas`、`profile`、`trends`、`publish`、`analytics`。

---

## 6. 日常开发命令

```bat
:: 重启某个服务
scripts\launchers\restart_backend.bat
scripts\launchers\restart_celery.bat

:: 停全部
scripts\launchers\stop_stack.bat

:: 释放端口（后端 7000 / 前端 7001）
scripts\launchers\kill_port_7000.bat
scripts\launchers\kill_port_7001.bat

:: supervisor 模式
start.bat supervisor

:: conda 模式（不用 prismenv 时）
start.bat conda
```

依赖变更：改 `requirements.txt` 后，直接再跑一次 `start.bat` 就行——它会用 `prismenv\.requirements-ready` 时间戳对比 `requirements.txt`，只要 requirements 比时间戳新就会自动重装一次（见第 3 步）。想手动装也可以：

```bat
prismenv\Scripts\activate
pip install -r requirements.txt
```

**注意**：自动重装只在 `start.bat`（或 `start.bat prismenv` / `start.bat supervisor`）启动时触发，直接跑子脚本 / 手动启后端不会触发；时间戳文件损坏时删掉 `prismenv\.requirements-ready` 强制重装。

---

## 7. 已刻意清理的内容

为了让文件夹能直接复制，下面这些**都删掉了**。新机器上按需重建，不用困惑：

| 已删 | 原来多大 | 怎么办 |
|---|---|---|
| `prism_frontend/node_modules` | 970 MB | `start_frontend.bat` 自动 `npm install`（或手动跑） |
| `prism_frontend/.next` | 219 MB | 前端构建缓存，`npm run dev` 自动重建 |
| `.venv` | 577 MB | **无人引用**，永久删除，不要重建 |
| `prismenv/` | 231 MB | 第 3 步手动 `python -m venv prismenv` |
| `tools/hermes-agent/node_modules` | 287 MB | 在该目录 `npm install` |
| `build/supervisor/` | 12 MB | PyInstaller 产物，已加 `.gitignore` |
| `tmp/`、`logs/`、`__pycache__` | 50 MB | 运行产物，运行会自动生成 |

**总计省 2.1 GB**。文件夹从 2580 MB 缩到 446 MB。全部是可再生的派生物，源码 + 锁文件齐全，新机器几分钟内可完全复现。

---

## 8. 本机状态文件（凭据）

仓库里没有任何凭据。这些文件被 `.gitignore` 排除，**不跟 git 走**，但**会跟文件夹走**：

| 位置 | 内容 | 说明 |
|---|---|---|
| `prism_backend/.env` | LLM key、平台 token | 自己填 |
| `prism_backend/config/hermes_agent.toml` | Hermes 桥接配置 | 从模板改 |
| `prism_backend/config/llm_config.toml` | LLM 多 Provider 配置 | 从模板改 |
| `tools/hermes-home/.env`、`auth.json` | Hermes 登录凭据 | ⚠️ 见下 |

**关于 `tools/hermes-home/`**：里面存着 Hermes 的登录状态。如果你把整个文件夹拷给同事，这些文件也会一起过去 —— **同事会继承你的 Hermes 账号**。

- **想让他用你的账号**：不用动，直接跑
- **想让他用自己的账号**：删掉这 3 个文件，首次运行 Hermes 会重建：

  ```bat
  del tools\hermes-home\auth.json
  del tools\hermes-home\.env
  del tools\hermes-home\auth.lock
  ```

---

## 9. 已知边界

- **`.git` 是浅克隆**，只有最近 1 个提交的快照。要完整历史：
  ```bat
  git fetch --unshallow
  ```
  remote 是 `https://github.com/Laihiujin/laoma-ai-workbench.git`，需要有写权限才能推送。
- **`prism_backend/biliup` 是空的 submodule**，用到 B 站发布时才需要：
  ```bat
  git submodule update --init prism_backend/biliup
  ```
- **`start.bat` 硬编码 `prismenv`**，完全不用 `.venv`。所以仓库里不再保留任何虚拟环境。
- **`tools/` 全部不被 git 跟踪**（`.gitignore` L191-196，注释「外部项目 clone，构建时拉取，不入库」）。
  - **整包拷贝**：全部保留
  - **`git clone`**：`tools/` 是空的，Hermes 那套得自己装（见第 4 节）
- **`ecosystem.config.js` 用相对路径**（`cwd: './prism_frontend'`），可移植
- **路径全部相对**，无绝对路径硬编码（已扫描确认）

---

## 10. 出问题时先查

| 现象 | 排查 |
|---|---|
| `prismenv not found` | 第 3 步没做，`python -m venv prismenv && pip install -r requirements.txt` |
| `Redis startup failed` | 第 1 步的 Redis 没装好，装一下再来 |
| 前端白屏 / `npm not found` | Node.js 没装，或 `npm install` 没跑完 |
| 后端 7000 端口被占 | `scripts\launchers\kill_port_7000.bat` |
| 前端 3000 端口被占 | `scripts\launchers\kill_port_7001.bat`（脚本里写的 7001 是历史名，实际是 3000） |
| 队列任务不执行 | `redis-cli ping`，返回 PONG 才行 |
| `/fusion` 相关接口 404 | Hermes 没装，见第 4 节 |
| Persona 端口 8787/5175 不通 | Persona Studio 没装（目前不在本仓库），可忽略 |
| 依赖装不上 | 确认 Python 版本是 3.10–3.12；确认网络能访问 PyPI |
| 一堆 `address already in use` | 没干净退出，先 `scripts\launchers\stop_stack.bat` 再重试 |

有问题先 `stop_stack.bat` 再试，别叠进程。

---

## 11. 项目约定（给新接手的程序员）

- **别改名**：后端路径还是 "老马AI工作台"，不是 "LaomaAI-Fusion"。全局替换会踩坑
- **密钥不进 git**：`.env`、`hermes_agent.toml`、`auth.json` 一律本地
- **依赖走锁文件**：改 `requirements.txt` 就重装 `prismenv`；改 `package.json` 就 `npm install`
- **构建产物不进 git**：`.next/`、`__pycache__/`、`node_modules/`、`build/supervisor/` 都排除在 `.gitignore`
- **`tools/` 是外部项目**：不要往里面塞本项目代码；改它等于改上游

有问题先读 [DEVELOPMENT-RECORD.md](DEVELOPMENT-RECORD.md) 看最近做了什么，`docs/` 下有具体功能文档。

## 12. 打包与发布

要打包安装程序（本地或 CI）走 [PACKAGING.md](PACKAGING.md)，那里有一键脚本、CI 流程、Secret 排除策略和常见故障排查。
