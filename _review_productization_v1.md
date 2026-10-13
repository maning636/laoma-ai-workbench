# Prism-Fusion 产品化改造 · 专家审阅文档

> 版本：v1（P0 核心已完成，待 review）
> 生成时间：2026-10-11
> 目的：交外部专家审阅当前改造方案、已完成改动、后续路线、待决技术问题
> 仓库路径：`D:\dim开发\Prism-Fusion`（Windows，含中文与连字符）
> 交付目标：**用户开箱即用** —— 一份打包产物双击即可用，不依赖任何本机预装路径

---

## 目录

1. 背景与目标
2. 项目现状（技术栈、目录、启动拓扑）
3. 侦察报告汇总（三大维度）
4. 已完成：P0 阶段（硬编码路径清零）
5. 未做完：P0 剩余项（等确认后再动）
6. 后续路线：P1–P7 详细设计
7. 关键技术决策与理由
8. 风险与回滚
9. 需要专家审阅的待决问题
10. 附录：文件清单与验证方式

---

## 1. 背景与目标

### 1.1 起点

Prism-Fusion（"老马AI工作台"）是一个 Windows 桌面 AI 视频/内容生产套件，由 Python FastAPI 后端 + Next.js 前端 + Electron 打包组成。开发阶段大量使用了本地绝对路径与本机预装依赖，导致：

- **用户拿到打包产物后无法启动**（`E:\FDE\...`、`F:\自媒体\...` 等路径在别的机器上不存在）
- **打包到含中文或空格的目录会崩**（`Path("data/workshop")` 相对路径依赖 cwd）
- **Hermes agent 的 config.yaml 有 3 条并存的解析路径**，互相不一致
- **Easel 组件（外部视频引擎）路径硬编码在 5 处**，用户无法修改

### 1.2 目标（用户确认）

**"未来封装后的会不会有这种问题也得一并解决"** —— 目标是**全量产品化**：

- **8 天工时预算**（用户已确认）
- **Easel 端口以 Easel 侧真相为准**（7860/37289，而非 Prism 侧的 7861/18789）
- **改动不提交，等 review 后再决定切分策略**
- **不动 Hermes 内部代码**，只改 Prism 侧的对接层

---

## 2. 项目现状

### 2.1 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 16 App Router + React 19.2 + shadcn/Radix UI |
| 后端 | FastAPI + Pydantic v2 (pydantic-settings) + SQLAlchemy |
| 数据 | SQLite（本地）+ Redis（Celery broker） |
| 桌面壳 | Electron + NSIS Installer（`desktop-electron/`） |
| 打包 | PyInstaller + build-package.bat + GitHub Actions |
| 第三方 AI | OpenAI SDK（对接 DeepSeek / SenseNova） |
| 浏览器自动化 | patchright（Playwright fork） |

### 2.2 启动拓扑

```
Redis (6379)
    ↑
FastAPI 后端 (7000) ──启动── Hermes Dashboard (9119)
    ↑                     Hermes WebUI (8788)
Celery Worker (7001)
    ↑
Next.js 前端 (3000)
    ↑
Electron 壳（desktop-electron/）
```

### 2.3 目录关键片段

```
Prism-Fusion/
├── prism_backend/fastapi_app/
│   ├── api/v1/          # 所有 API 路由
│   ├── agent/           # Hermes agent 对接层
│   │   ├── hermes_config.py    # 唯一权威的 Hermes 路径解析
│   │   └── hermes_update.py    # Hermes 自动更新（P3 要参考它）
│   ├── core/            # 基础设施（config, logger, db, ...）
│   │   ├── config.py             # Pydantic Settings
│   │   ├── paths.py             # 【本次新增】路径单一入口
│   │   └── logger.py
│   └── utils/
├── prism_backend/fusion_ai/      # 融合 AI 层
│   └── router.py                 # 含一处 config.yaml 硬编码
├── prism_frontend/               # Next.js
├── tools/                        # Hermes、WebUI、Skills 等（.gitignore 排除）
│   ├── hermes-home/              # Hermes 运行时目录（含 config.yaml、.env）
│   ├── hermes-agent/             # Hermes 主程序
│   └── hermes-webui/
├── desktop-electron/             # 打包入口
├── config/                       # 遗留配置（conf.py）
├── .env / .env.example           # 环境变量
└── STARTUP.md                    # 启动文档（部分描述已过期）
```

---

## 3. 侦察报告汇总

三个方向的侦察已完成，报告保存在仓库根：

- 后端：`_recon_backend_paths_config_subprocess.md`
- 前端：小视 agent 报告（内联到本计划）
- 打包：小发 agent 报告（内联到本计划）

### 3.1 后端 🚨 关键发现

#### 3.1.1 硬编码绝对路径（**已修 5 处**，见 §4）

```
orchestrator.py:47                          → E:\FDE\fde-landing-delivery
orchestrator.py:106 + fusion_ai/router.py:107 → D:/工作台/LaomaAI-Fusion/tools/hermes-home/config.yaml
video_pipeline/router.py:47,64-66           → C:/Program Files/nodejs
video_pipeline/router.py:106,113            → F:/自媒体/OpenMontage, F:/自媒体/MoneyPrinterTurbo
video_pipeline/render.py:22,35-36           → C:/Program Files/nodejs
```

**重要发现**：`E:\FDE\fde-landing-delivery` **在当前开发机上也不存在**（幽灵路径）。视频流水线其实一直以"空模板库"运行，`_load_catalog()` 走 except 分支。

#### 3.1.2 Hermes config.yaml 三条解析路径并存（**未修**）

| 位置 | 解析方式 | 状态 |
|---|---|---|
| `agent/hermes_config.py` | env `PRISM_HERMES_HOME` → 默认 `tools/hermes-home` | ✅ 唯一权威 |
| `agent/tool_registry.py:33` | 硬编码 `runtime-data/app/hermes-home` | ❌ 需修 |
| `fusion_ai/router.py:107` | 硬编码 `D:/工作台/...` | ✅ 已修为走 hermes_config |
| `orchestrator.py:106` | 硬编码同上 | ✅ 已修 |
| `utils/process_manager.py:32` | 定义 `HERMES_HOME = REPO_ROOT / "tools" / "hermes-home"`（另在 :236/237/289 引用），绕过 `PRISM_HERMES_HOME` 权威入口 | ❌ 需改走 `hermes_config.get_hermes_home_path()` |

> **注**：经核实（2026-10-11 三 agent 探索），`utils/process_manager.py:32` **确实存在** `HERMES_HOME = REPO_ROOT / "tools" / "hermes-home"`，另在 :236/237/289 引用，侦察报告行号**准确**。此前"全仓 grep `HERMES_HOME` 命中 0 处"的判断是**错误的**——grep 路径未覆盖 `utils/`。真正问题是该处与 `agent/hermes_config.py:138` 独立维护同一路径，绕过了 `get_hermes_home_path()` 唯一权威入口。

#### 3.1.3 Skills 根路径冲突（**未修**）

- `skill_registry.py` 用 `EASEL_DIR/skills/openclaw`
- `tool_registry.py:33` 用 `runtime-data/app/hermes-home/skills`
- 两处指向不同目录，导致 skill 加载可能命中不到

#### 3.1.4 相对路径依赖 cwd（**未修**，2026-10-11 扩展核实）

后端**无任何一处**用 `Path(__file__).parents[N]` 或 `get_source_repo_root()` 锚定，全部裸奔在 cwd 上。已知裸奔点（7 处 `data/*` + skills 双路径 + automation logs）：

| 文件:行 | 代码 |
|---|---|
| `fastapi_app/services/workshop.py:24` | `WORKSHOP_DIR = Path("data/workshop")`（使用处 :121）|
| `fastapi_app/api/v1/agent/router.py:39` | `_SESSIONS_DIR = Path(os.getenv("LAOMA_SESSIONS_DIR") or (Path("data")/"ai-sessions"/"hermes"))`（使用处 :47）|
| `fastapi_app/services/matrix_scheduler.py:33` | `self.tasks_file = Path("data/matrix_tasks.json")` |
| `fastapi_app/services/ip_pool_service.py:40` | `self.ip_pool_file = Path("data/ip_pool.json")` |
| `fastapi_app/services/campaign_service.py:12` | `CAMPAIGNS_FILE = Path("data/campaigns.json")` |
| `fastapi_app/agent/hermes_config.py:434/435` | skills 双路径：`Path("tools")/"hermes-home"/"skills"` + `Path("runtime-data")/"app"/"hermes-home"/"skills"` |
| `automation_worker/worker.py:598/625` | `screenshot_path = Path("logs")/...`（自动化 worker 截图）|

打包后 cwd 变化即崩或写错位置。**P1 工作量因此从"2 处"上修至"7+ 处"**。另有 `fastapi_app/api/v1/files/services.py:41` 的 `Path("covers")/...` 是相对 URL 返回（未必落盘，风险次之）。

> **注**：侦察报告原写的 `workshop.py:24` / `agent/router.py:39` 行号准确，但文件路径把**路由**与**服务**搞混了——实际在 `fastapi_app/services/workshop.py:24` 和 `fastapi_app/api/v1/agent/router.py:39`（非 `api/v1/workshop.py`、非 `agent/router.py`）。

#### 3.1.5 其他

- **Easel 端口默认值不对**：Prism 默认 `7861/18789`，Easel 实际是 `7860 + 37289（profile 哈希计算）`
- **health-check 覆盖不足**（`system/router.py:510-569`）：只查 DB / 7001 / AI config / 磁盘；不查 Easel / Hermes / Redis / Celery / Persona / Playwright
- **judgment bug**：`system/router.py:558-561` 把 `"unknown"` 当 degraded 但语义上 unknown ≠ degraded
- **subprocess 编码/窗口**：53 处调用点中仅 6 处设 `CREATE_NO_WINDOW`；27 处 `shell=True`
- **跨平台坑**：`workshop.py:22` 硬指 `.venv/Scripts/python.exe`（Windows only）
- **startup_event 唯一裸奔行**：`main.py:143` `os.environ.setdefault` 无 try/except
- **`config/conf.py:57` vs `conf.example.py:58`** `load_dotenv override` 不一致（True vs False）
- **`.env.example` 与 pydantic 不一致**：`PORT=5409`（`.env.example`） vs `PORT=7000`（`config.py:73`）
- **Python 版本冲突**：`pyproject.toml` 声明 `>=3.10,<3.13`，实际 `prismenv` 是 3.13
- **依赖双源**：`pyproject.toml`（未锁版本） vs `requirements.txt`（锁版本），版本可能不一致

### 3.2 前端 🚨 关键发现

- **技术栈**：Next.js 16 + React 19.2 + shadcn/Radix
- **`/settings` 页面**（1154 行，`src/app/settings/page.tsx`）无 Easel 专属卡片，只有 4 张"敬请期待"占位
- **零 `webkitdirectory` / `showOpenDialog` / `openFolder`** —— **用户当前无法在 UI 里改任何路径**
- **`EnvironmentInstallCard` 的三行"安装(待接入)"按钮是纯 toast 占位**（`environment-install-card.tsx:272-285`），无进度、无日志
- **Hermes Runtime 端点已存在**：`/api/v1/agent/config/hermes/runtime` 返回完整 runtime map，但**不含 Easel 字段**
- **API 客户端无统一封装**：设置页全内联 fetch，其余混用 `fetcher` / `apiGet` / `useQuery + fetcher`
- **无 401/500 全局兜底，无 React Error Boundary，无 Skeleton**

### 3.3 打包 🚨 关键发现

- **打包体系已有基础**：`build-package.bat` + `build_services.ps1` + `desktop-electron/`（NSIS/Inno）+ `.github/workflows/release.yml`
- **CI 不含测试**：只有 build + publish
- **Hermes 更新机制可借鉴**（`agent/hermes_update.py`，313 行）：双文件分离 + 15 分钟调度 + `stop → reset → apply` + 原子写 JSON；但**无回滚**
- **Easel 无对应更新机制**：只有手动 `setup.sh`/`setup.ps1`，无版本 pin、无 self-update
- **Secret 打包风险**：`prism_frontend/.env.local`、`tools/hermes-home/.env` 会被 `extraResources` 打进 NSIS 包
- **PyInstaller 入口脆弱**：`backend_service.py:9-56` 用 3 层探测找 repo 根
- **文档 vs 代码不一致**：`STARTUP.md:58` 说 `start.bat` 不自动装依赖，实际会自动
- **Hermes pin 在 `setup-local-hermes.ps1:10`**：`$AgentCommit = "bb0c230"`
- **发布目标**：`desktop-electron/package.json:228-234`，`ncipollo/release-action@v1`
- **PyInstaller + 中文路径 + 无签名** = 高风险组合

---

## 4. 已完成：P0 阶段

### 4.1 目标

清掉所有"打包后一定炸"的硬编码绝对路径，让后端在任何机器上都能启动。

### 4.2 改动清单

#### 4.2.1 新增文件：`prism_backend/fastapi_app/core/paths.py`

**作用**：路径解析单一入口。各函数 fallback 优先级**不统一**（见下"设计原则"第 4 条的逐函数核对，2026-10-11 实证）。

**核心 API**：

```python
# 主入口
def get_repo_root() -> Path
def get_data_dir() -> Path
def get_hermes_runtime_config_path() -> Path  # 委托给 agent.hermes_config

# 视频流水线
def get_template_lib_dir() -> Path
def get_nodejs_dir() -> Path
def get_openmontage_dir() -> Path
def get_moneyprinter_dir() -> Path
```

**新增可选环境变量**（用于生产打包）：

| 变量 | 用途 | 默认降级 |
|---|---|---|
| `LAOMA_TEMPLATE_LIB_DIR` | 视频模板素材库 | `tools/templates/` |
| `LAOMA_NODEJS_DIR` | Node.js 安装目录 | 自动探测 `which("node")` → `ProgramFiles\nodejs` |
| `LAOMA_OPENMONTAGE_DIR` | OpenMontage 目录 | `DATA_DIR/third-party/OpenMontage/` |
| `LAOMA_MONEYPRINTER_DIR` | MoneyPrinterTurbo 目录 | `DATA_DIR/third-party/MoneyPrinterTurbo/` |
| `LAOMA_THIRD_PARTY_ROOT` | 第三方工具根目录（可选，同时设置 OpenMontage 和 MoneyPrinter 父目录） | — |
| `LAOMA_DATA_DIR` | 应用数据目录（与 settings.DATA_DIR 保持语义一致） | `%APPDATA%/老马AI工作台/data` |
| `PRISM_HERMES_HOME` | Hermes home 目录（唯一权威，在 hermes_config 里） | `tools/hermes-home/` |

**设计原则**：

1. **尽量不抛异常**：自身无 `raise`，但 `get_hermes_runtime_config_path()` 委托 `agent.hermes_config`（其行为不受本文件控制），且 `Path.resolve()` 在极端 env 输入下可抛。**此前"永不抛异常"措辞过强，已修正。**
2. **无循环依赖**：反向只 import stdlib + `agent.hermes_config`（后者只 import stdlib）。**2026-10-11 实证**：`core/` 下无任何模块 import `paths`，仅 video_pipeline 三处 import；§7.1 担心的 `paths → config → logger` 循环当前**不存在**。
3. **`get_data_dir()` 独立于 `settings.DATA_DIR`**：避免 `core.paths → core.config → core.logger → ...` 的循环风险。**副作用**：与 `settings.DATA_DIR` 是两套逻辑，**"实测一致"不成立**——见 §9.1-1 的 5 处分叉点实证，P1 必须统一（含调用关系 + env 名）。
4. **fallback 顺序各函数不一致**（2026-10-11 实证，P1 引入 paths.json 前需先统一模板）：
   - `get_template_lib_dir`：env `LAOMA_TEMPLATE_LIB_DIR` → repo_root/tools/templates（**无候选层**）
   - `get_nodejs_dir`：`which("node")` → env `LAOMA_NODEJS_DIR` → ProgramFiles/nodejs（**探测优先于 env**，与"env > 候选 > 默认"相反）
   - `get_openmontage_dir` / `get_moneyprinter_dir`：env → `LAOMA_THIRD_PARTY_ROOT` → `get_data_dir()/third-party/*`
   - `get_data_dir`：env `LAOMA_DATA_DIR` → APPDATA → LOCALAPPDATA → repo_root
   - `get_repo_root`：硬编码 `Path(__file__).resolve().parents[3]`（无 env、无候选、无 fallback）

#### 4.2.2 修改文件 1：`prism_backend/fastapi_app/api/v1/video_pipeline/orchestrator.py`

**3 处改动**：

```python
# 顶部 imports
+ from fastapi_app.core import paths as core_paths

# :47
- _TEMPLATE_LIB_DIR = Path(r"E:\FDE\fde-landing-delivery")
+ _TEMPLATE_LIB_DIR = core_paths.get_template_lib_dir()

# :106
- cfg_path = Path("D:/工作台/LaomaAI-Fusion/tools/hermes-home/config.yaml")
+ cfg_path = core_paths.get_hermes_runtime_config_path()
```

#### 4.2.3 修改文件 2：`prism_backend/fastapi_app/api/v1/video_pipeline/router.py`

**4 处改动**：

```python
# 顶部 imports
+ from fastapi_app.core import paths as core_paths

# _build_env 内 :47
- node_dir = str(Path("C:/Program Files/nodejs"))
+ node_dir = str(core_paths.get_nodejs_dir())

# _resolve_npx 内 :64-66
- for cand in (Path("C:/Program Files/nodejs/npx.cmd"),
-              Path("C:/Program Files/nodejs/npx.exe"),
-              Path(str(Path.home() / "AppData/Roaming/nvm"))):
+ for cand in (Path(core_paths.get_nodejs_dir()) / "npx.cmd",
+              Path(core_paths.get_nodejs_dir()) / "npx.exe",
+              Path(str(Path.home() / "AppData/Roaming/nvm"))):

# /engines 端点 :106,113
- "path": "F:/自媒体/OpenMontage",
- "installed": Path("F:/自媒体/OpenMontage").exists(),
+ "path": str(core_paths.get_openmontage_dir()),
+ "installed": core_paths.get_openmontage_dir().exists(),

- "path": "F:/自媒体/MoneyPrinterTurbo",
- "installed": Path("F:/自媒体/MoneyPrinterTurbo").exists(),
+ "path": str(core_paths.get_moneyprinter_dir()),
+ "installed": core_paths.get_moneyprinter_dir().exists(),
```

#### 4.2.4 修改文件 3：`prism_backend/fastapi_app/api/v1/video_pipeline/render.py`

**3 处改动**：

```python
# 顶部 imports
+ from fastapi_app.core import paths as core_paths

# _build_env 内 :22
- node_dir = str(Path("C:/Program Files/nodejs"))
+ node_dir = str(core_paths.get_nodejs_dir())

# _resolve_npx 内 :35-36
- for cand in (Path("C:/Program Files/nodejs/npx.cmd"),
-              Path("C:/Program Files/nodejs/npx.exe"),
-              Path(str(Path.home() / "AppData/Roaming/nvm"))):
+ for cand in (Path(core_paths.get_nodejs_dir()) / "npx.cmd",
+              Path(core_paths.get_nodejs_dir()) / "npx.exe",
+              Path(str(Path.home() / "AppData/Roaming/nvm"))):
```

#### 4.2.5 修改文件 4：`prism_backend/fusion_ai/router.py`

**3 处改动**：

```python
# 顶部 imports
+ from fastapi_app.core import paths as core_paths

# :98 清理无用导入
- from pathlib import Path as _Path

# :107
- cfg_path = _Path("D:/工作台/LaomaAI-Fusion/tools/hermes-home/config.yaml")
+ cfg_path = core_paths.get_hermes_runtime_config_path()
```

### 4.3 冒烟验证结果

在开发机上执行以下验证，全部通过：

```powershell
# 1) 后端 /health
> Invoke-WebRequest http://127.0.0.1:7000/health
200 OK: {"status":"healthy","version":"2.0.0","timestamp":"2026-10-11T21:51:22.299025"}

# 2) Hermes 配置端点
> Invoke-WebRequest http://127.0.0.1:7000/api/v1/agent/config/hermes
200 OK: 返回 provider/model/base_url/api_key/max_turns/is_configured/runtime

# 3) Hermes runtime 端点
> Invoke-WebRequest http://127.0.0.1:7000/api/v1/agent/config/hermes/runtime
200 OK

# 4) Python 直接 import 4 个改动文件
> python -c "from fastapi_app.api.v1.video_pipeline import orchestrator; from fastapi_app.api.v1.video_pipeline import render; from fastapi_app.api.v1.video_pipeline import router as vp_router; import prism_backend.fusion_ai.router"
orchestrator OK, TEMPLATE_LIB= D:\dim开发\Prism-Fusion\tools\templates
render OK
vp_router OK
fusion_ai OK
```

### 4.4 关键副作用（需在 review 时确认）

1. **`E:\FDE\fde-landing-delivery` 在开发机上也不存在**，视频流水线的模板库功能原本就以"空目录"运行。改后行为不变，但**若用户实际配了模板库**，需在 `.env` 加 `LAOMA_TEMPLATE_LIB_DIR=<path>`。

2. **`F:\自媒体\*` 在开发机上不存在**，`/video-pipeline/engines` 会显示 OpenMontage/MoneyPrinterTurbo `installed: false`。若用户实际在用，需配 `LAOMA_OPENMONTAGE_DIR` / `LAOMA_MONEYPRINTER_DIR` / `LAOMA_THIRD_PARTY_ROOT`。

3. **`get_data_dir()` 与 `settings.DATA_DIR` 是两套独立逻辑**：当前实测一致（都指向 `%APPDATA%/老马AI工作台/data`），但如果用户设置了 `LAOMA_DATA_DIR` 只影响 `get_data_dir`，不影响 `settings.DATA_DIR`。**P1 阶段会统一**（见 §6.1）。

4. **`.env.example` 的 `PORT=5409` 与 `config.py:73` 的 `PORT=7000` 不一致**（本次未修）：属于文档准确性问题，非打包阻塞。P1/P5 阶段修。

---

## 5. P0 剩余项（等 review 后再动）

### 5.1 三处位置已重新定位（2026-10-11 三 agent 探索完成）

| 报告位置 | 实际情况 | 状态 |
|---|---|---|
| `utils/process_manager.py:32` | **行号准确，存在** `HERMES_HOME = REPO_ROOT / "tools" / "hermes-home"`；另在 :236/237/289 引用。问题：绕过 `hermes_config.get_hermes_home_path()` 权威入口 | ❌ 需改走权威入口（非"丢失"） |
| `workshop.py:24` `WORKSHOP_DIR` | **行号准确，文件路径错**：实际在 `fastapi_app/services/workshop.py:24`（侦察误记为 `api/v1/workshop.py`，该文件不存在）；使用处 :121 | ⚠️ 路径相对 `data/workshop`，待改绝对 |
| `agent/router.py:39` `_SESSIONS_DIR` | **行号准确，文件路径错**：实际在 `fastapi_app/api/v1/agent/router.py:39`（侦察误记为 `agent/router.py`）；使用处 :47；`os.getenv("LAOMA_SESSIONS_DIR")` 兜底是相对 `data/ai-sessions/hermes` | ⚠️ 相对路径，待改绝对 |

> **此前"全仓 grep `HERMES_HOME` 命中 0 处"的判断错误**：经核实 grep 路径未覆盖 `utils/`。`process_manager.py:32` 精确存在，侦察报告准确。

> **附**：相对路径风险面实际远超本表三处，见 §3.1.4 修订（已扩展至 7 处 `data/*` + skills 双路径 + automation logs）。

### 5.2 建议 P1 阶段一并处理

- `.env.example` `PORT=5409` → `PORT=7000`
- `config/conf.py:57` vs `conf.example.py:58` `load_dotenv override` 统一为 `False`
- `pyproject.toml` `requires-python` 与 `requirements.txt` 依赖二选一
- 相对路径（workshop / sessions）改为绝对

---

## 6. 后续路线：P1–P7

### 6.1 P1 · 配置中心化 + 启动自检（1.5 天）

**目标**：把路径解析收敛到 `paths.json` 单一真相源，同时提供 `/preflight` 接口让前端能读到所有依赖状态。

**改动**：

#### 6.1.1 扩展 `core/paths.py`

```python
# 新增 API
def get_skills_dir() -> Path: ...  # 收敛到统一 skills 根
def load_paths_config() -> dict: ...  # 从 paths.json 读
def save_paths_config(d: dict) -> None: ...  # 原子写

# paths.json 位置
def get_paths_config_path() -> Path:
    return get_data_dir() / "paths.json"

# 优先级：env > paths.json > 默认 monorepo 路径
def get_easel_dir() -> Path:
    env = os.getenv("LAOMA_EASEL_DIR")
    if env: return Path(env).expanduser().resolve()
    cfg = load_paths_config()
    if cfg.get("easel_dir"): return Path(cfg["easel_dir"]).resolve()
    return get_source_repo_root() / "easel"  # 同级目录

def get_hermes_home() -> Path:
    # 委托给 agent.hermes_config，保持一致
    from fastapi_app.agent.hermes_config import get_hermes_home_path
    return get_hermes_home_path()
```

**统一收敛点**：把 `tool_registry.py:33` 的 `runtime-data/app/hermes-home/skills` 改为读 `get_skills_dir()`。

#### 6.1.2 新增 `/api/v1/system/preflight` 端点

返回结构：

```json
{
  "python": {"path": "...", "version": "3.13.x", "prismenv_ready": true},
  "redis": {"url": "redis://localhost:6379/0", "reachable": true},
  "celery": {"broker": "...", "result_backend": "...", "reachable": true},
  "easel": {"dir": "...", "installed": false, "ready": false, "reason": "未找到 Easel 目录"},
  "hermes": {"home": "...", "installed": true, "ready": true, "dashboard_port": 9119},
  "persona_api": {"url": "http://127.0.0.1:8787", "reachable": false},
  "playwright": {"patchright_chromium_installed": true},
  "disk_space": {"total_gb": 480, "free_gb": 120, "warning": false},
  "skills_dir_exists": true,
  "third_party_tools": {"openmontage": {...}, "moneyprinter": {...}},
  "template_lib": {"dir": "...", "exists": false, "reason": "未配置 LAOMA_TEMPLATE_LIB_DIR"}
}
```

#### 6.1.3 扩展 `/api/v1/system/health-check`

- 调用 `/preflight` 聚合结果
- 修正 `:558-561` 的 `unknown` 判定 bug

#### 6.1.4 启动末段跑一次 preflight

```python
# main.py startup_event 末尾
asyncio.create_task(_run_startup_preflight())

async def _run_startup_preflight():
    result = await run_preflight_check()
    missing = [k for k, v in result.items() if not v.get("ready")]
    if missing:
        logger.warning(f"[Startup] 缺失组件: {missing}")
    else:
        logger.info("[Startup] 全部依赖就绪")
```

### 6.2 P2 · Hermes Runtime 响应扩展 + 设置页 Easel 卡片（1.5 天）

**目标**：设置面板能看到 Easel 状态。

**后端改动**：

`api/v1/agent/config_routes.py::AgentConfigResponse` 增加字段：

```python
class AgentConfigResponse(BaseModel):
    # ...现有字段
    easel_dir: Optional[str] = None
    easel_ready: bool = False
    easel_status: str = "not_configured"  # not_configured | not_installed | ready | error
    skills_dir: Optional[str] = None
```

`_build_response()` 从 `easel_bridge` 拉真实状态。

**前端改动**：

新增 `prism_frontend/src/components/settings/easel-provider-card.tsx`：

```tsx
- 安装状态徽章（未装 / 已装 / 就绪 / 异常）
- 路径输入框 + "浏览"按钮（Electron dialog）
- "一键安装" 按钮 → 调 /easel/install → SSE 流式显示日志
- "重新检测" 按钮 → 调 /easel/detect
- "复制路径" / "打开 Easel 官网" 快捷操作
```

挂载到 `src/app/settings/page.tsx` 的 `renderEnvironment` 分区。

### 6.3 P3 · Easel 自动更新接入（1 天）

**目标**：Easel 侧接入类 Hermes 更新器，且**补上 Hermes 缺失的回滚**。

**改动**：

1. 新增 `prism_backend/fastapi_app/agent/easel_update.py`（约 300 行）：

```python
# 结构镜像 hermes_update.py
# - 双文件：DATA_DIR/easel-update-settings.json + DATA_DIR/easel-update-state.json
# - 15 分钟轮询调度
# - stop → git clone/fetch → setup.ps1 → reset 顺序
# - 补回滚：git clone 前先 git rev-parse HEAD 记录 old_sha
# - apply 失败时 git reset --hard old_sha + 重跑 pip install

async def check_update(): ...
async def apply_update(): ...  # 内含回滚逻辑
def start_update_scheduler(): ...  # 15 分钟一次
```

2. 同步修 `hermes_update.py:160-238`：加 `old_sha` 快照 + 失败回滚

3. 注册到 `startup_event`

4. 前端 `HermesUpdateSettings` 旁加 `EaselUpdateSettings`

**关键设计**：回滚触发点必须是"任何一步失败"，包括 git fetch、pip install、setup.ps1、setup.sh。**old_sha 快照必须在 git 操作之前**，不是之后。

### 6.4 P4 · 打包分发体系（1 天）

**目标**：修 CI + 修文档 + 修 secret 打包 + 修 PyInstaller 路径探测。

**改动**：

1. **CI 增强**（`.github/workflows/release.yml`）：
   - `test` job：`pytest`
   - `lint` job：`ruff check` + `black --check`
   - `build-backend` job：PyInstaller 打包 supervisor + backend + worker
   - `verify-package` job：解压 NSIS 包 → 从含中文路径启动 → 跑 `/preflight` → 校验全绿

2. **修 `build-package.bat`**：
   - 排除 `.env*` 和 `tools/hermes-home/auth.json`
   - 加"从解压目录跑一次 preflight"步骤

3. **修文档**：
   - `STARTUP.md` 修正与实际不符的章节
   - 新增 `PACKAGING.md`：打包流程、CI 触发方式、本地复现步骤

4. **依赖收敛**：
   - `pyproject.toml` 与 `requirements.txt` 二选一（建议留 `requirements.txt` 锁版本）
   - `requires-python` 改为 `>=3.11`

5. **PyInstaller 入口统一**：`backend_service.py` / `celery_worker_service.py` / `automation_worker_service.py` 三处 3 层探测改为直接走 `core.paths.get_backend_root()`

6. **版本管理**：新增 `scripts/version.sh` / `version.ps1`，同步 3 处版本号

### 6.5 P5 · subprocess 兜底 + 跨平台（1 天）

**目标**：跨平台不炸，Windows GUI 不闪窗，用户看到的错误都是可读的。

**改动**：

1. 新增 `prism_backend/fastapi_app/utils/subprocess_safe.py`：

```python
def safe_run(cmd, *, timeout, cwd, env_extra=None, encoding='utf-8', shell=False):
    """
    自动注入：
    - PYTHONUTF8=1, PYTHONIOENCODING=utf-8, PYTHONUNBUFFERED=1
    - Windows: CREATE_NO_WINDOW (除非 shell=True 或 GUI 命令)
    - cwd 不存在则抛 ConfigError 而非 OSError
    - encoding 失败用 errors='replace'，不 silent
    - 统一日志
    """

def safe_popen(cmd, *, cwd, env_extra=None):
    ...
```

2. 迁移 53 处 subprocess 调用点，**分 3 批 PR**：
   - 批 1：6 处已设 `no_window` 的
   - 批 2：27 处 `shell=True` 的
   - 批 3：20 处常规调用

3. `workshop.py:22` `PYTHON_EXE` 加跨平台探测：
   ```python
   if sys.platform == "win32": venv/Scripts/python.exe
   elif sys.platform.startswith("darwin"): venv/bin/python
   else: venv/bin/python3
   ```

4. `startup_event`：`os.environ.setdefault` 包 try，`app.state.task_manager` 下游 API 加判空

5. **前端统一错误处理**：
   - 新增 `QueryClient` 全局 error handler
   - `ApiError` 增加 `kind`：`network` / `auth` / `config` / `not_installed` / `rate_limit`
   - 各卡片按 `kind` 展示对应文案与"修复指引"按钮

### 6.6 P6 · 端到端验证 + 打包烟测（0.5 天）

**改动**：

1. 新增 `scripts/tests/e2e_packaged_test.ps1`：
   - 清空 `LAOMA_*` 环境变量
   - 从 zip 解压到 `D:\测试\path with spaces\`
   - 双击 exe → 打开 settings → 走"未装 Easel → 浏览 → 保存 → 一键安装"
   - 校验 `/preflight` 全部非 null

2. 新增 `scripts/tests/integration_test.py`：覆盖 `/preflight`、`/easel/install`、`/easel/update` 端点

3. 加入 CI 的 `e2e-packaged` job

### 6.7 阶段顺序建议

```
Wave 1 (Day 1-3):  P0 → P1 → P2 → P3(前端部分)
Wave 2 (Day 4-5):  P3(更新机制) + P5 并行
Wave 3 (Day 6-7):  P4（打包）
Wave 4 (Day 8):    P6（E2E 验证）
```

---

## 7. 关键技术决策与理由

### 7.1 为什么 `get_data_dir()` 不复用 `settings.DATA_DIR`？

`core.paths` 位于 `fastapi_app/core/paths.py`，`core.config` 在同目录。**如果 `paths.py` 直接 import `core.config`**，会出现：

```
core.paths → core.config → core.logger → (?)
```

`core.config` 内部使用 `pydantic_settings`，且 `Settings` 类实例化时读取 `.env`。**如果 `paths.py` 被 logger 或其他基础设施间接引用**，会形成循环。因此 `paths.py` 独立实现 env 解析。

**副作用**：`LAOMA_DATA_DIR` 只影响 `paths.get_data_dir()`，不影响 `settings.DATA_DIR`。**P1 阶段会把两者统一到同一个入口**（`get_data_dir` 反向调用 `settings.DATA_DIR`，或让 `settings.DATA_DIR` 调用 `get_data_dir`）。

### 7.2 为什么 `get_hermes_runtime_config_path()` 委托给 `agent.hermes_config`？

`agent/hermes_config.py` 是 Hermes 路径解析的**唯一权威**：

- `get_hermes_home_path()` 优先级 env `PRISM_HERMES_HOME` → 默认 `tools/hermes-home/`
- 多处代码依赖它：`hermes_agent.py`、`hermes_update.py`、`config_routes.py`、`ccswitch_bridge.py`
- 已实现完整的目录/文件探测与 fallback

如果在 `core.paths` 里再实现一份，会导致配置分裂（正是本次要解决的问题）。所以 `core.paths.get_hermes_runtime_config_path()` 只做转发。

**风险**：如果未来 `agent/hermes_config.py` 反向 import `core.paths`，会循环依赖。**当前无此依赖**。

### 7.3 为什么模板库降级到 `tools/templates/` 而不是保留硬编码？

三个原因：

1. **原路径 `E:\FDE\fde-landing-delivery` 在开发机上都不存在**（幽灵路径）。
2. 保留硬编码会让打包产物**默认指向不存在的路径**，用户报错信息毫无意义。
3. 降级到 `tools/templates/` 让 `_load_catalog()` 走 except 分支（返回空 catalog），**行为与当前完全一致**（因为原本就是空）。

**决策代价**：如果用户实际在用视频模板库，需要在 `.env` 显式配置。**这是正确的行为** —— 打包后应该显式配置，不应默认存在。

### 7.4 为什么 OpenMontage / MoneyPrinterTurbo 降级到 `DATA_DIR/third-party/*`？

同上理由，加一个考虑：**用户可能自己装第三方工具，不来自仓库**。放到 `DATA_DIR`（`%APPDATA%/老马AI工作台/data`）里：

- 不会污染仓库
- 用户可通过 P3 的前端 UI 修改路径
- 打包后不会被 NSIS 拷走（避免 secret/二进制膨胀）

### 7.5 为什么不直接改 `workshop.py` / `agent/router.py` 的相对路径？

两个原因：

1. **侦察报告的行号不准**：`api/v1/workshop.py` 不存在，`WORKSHOP_DIR` 定义位置需重新定位。
2. **相对路径修复是 P1 阶段的一部分**：等 P1 把 `get_data_dir` 和 `settings.DATA_DIR` 统一后，改相对路径会更安全（避免两套 `DATA_DIR` 不一致）。

### 7.6 为什么不修 `.env.example` 的 PORT 与 `config.py` 不一致？

**属于文档准确性问题**，非打包阻塞。修改 `.env.example` 会让用户困惑（原来用 5409 的用户改了会找不到），需与前端 `NEXT_PUBLIC_BACKEND_PORT` 联动。放在 P5（打包体系）阶段一并处理。

---

## 8. 风险与回滚

### 8.1 P0 阶段风险

| 风险 | 影响 | 回滚方案 |
|---|---|---|
| `core.paths` 被 logger 反向引用导致循环 | 后端启动失败 | `git revert` 单 PR，或临时把 `paths.py` 里的 `from .logger import` 删除（当前无此 import） |
| 用户实际在用的 `F:\自媒体\OpenMontage` 变为 `installed: false` | 视频流水线部分引擎不可用 | 用户在 `.env` 加 `LAOMA_OPENMONTAGE_DIR=F:\自媒体\OpenMontage` 即可恢复 |
| `hermes_config` 的 `PRISM_HERMES_HOME` 与 `paths.py` 不一致 | config.yaml 找不到 | 目前 P0 未修改 `hermes_config.py`，无风险 |

### 8.2 单 PR 回滚

所有 P0 改动集中在一个 PR（5 个文件），`git revert <commit>` 即可完全回滚。

### 8.3 P1-P6 阶段的通用风险

- 每个阶段独立成 PR，可单独回滚
- P1 `paths.json` 是新增文件，回滚只需删除
- P3 `easel_update.py` 是新增文件，回滚只需删除 + 恢复 `hermes_update.py` 的改动
- P5 subprocess 迁移分 3 批 PR，可按批次回滚

---

## 9. 需要专家审阅的待决问题

### 9.1 决策类（影响后续架构）

1. **`LAOMA_DATA_DIR` 与 `settings.DATA_DIR` 的关系**
   - 选项 A：`paths.get_data_dir()` 是权威，`settings.DATA_DIR` 反向调用它
   - 选项 B：`settings.DATA_DIR` 是权威，`paths.get_data_dir()` 反向调用它
   - 选项 C：保持现状（两套逻辑），P5 阶段文档明确说明
   
   推荐 **A**（`core` 层的路径解析应该自洽，Pydantic Settings 应该消费而非定义）。

   > **2026-10-11 三 agent 实证**：两者"实测一致"**不成立**，已定位 5 处分叉点：
   > 1. **dev repo 检测**：`settings` 有（`.git` 存在或 `LAOMA_ENV=dev` → 指仓库根），`paths` 无（指 `%APPDATA%`）——**开发机上就分叉**。
   > 2. **env 名不一致**：`settings` 经 pydantic 读 `DATA_DIR`（字段名），`paths` 只读 `LAOMA_DATA_DIR`；`.env` 写 `DATA_DIR=` 时 `paths` 忽略。
   > 3. **存在性检查**：`paths` 信任 env 存在即返回，`settings` 要求 `_has_data_payload` 或 `exists()`。
   > 4. **路径规范化**：`paths` 全部 `.expanduser().resolve()`，`settings` 原样返回。
   > 5. **兜底**：`paths` 兜底 `get_repo_root()`，`settings` 兜底 `BASE_DIR`（fastapi_app 目录），两者不同。
   >
   > 结论：选 A 的同时**必须统一 env 名**（`DATA_DIR` ↔ `LAOMA_DATA_DIR` 二选一），否则即使 `settings` 反调 `paths.get_data_dir()`，pydantic 仍会用 `DATA_DIR` env 覆盖默认值，绕过 `paths`。建议保留 `LAOMA_DATA_DIR` 为唯一 env 名，`settings.DATA_DIR` 改为 `@field_validator` 调 `paths.get_data_dir()`。

2. **Skills 目录如何统一**
   - 选项 A：`tool_registry.py:33` 的 `runtime-data/app/hermes-home/skills` 收敛到 `get_skills_dir()`
   - 选项 B：只统一 `skill_registry.py` 一侧，Hermes 内部保持不动
   - 选项 C：新增独立 skills 根，两处都读同一份
   
   推荐 **B**（最小改动），避免动 Hermes 内部。

3. **Easel 端口真相**
   - 选项 A：改 Prism 所有 `7861` 为 `7860`（对齐 Easel 侧）
   - 选项 B：保持 `7861` 默认，强制用户 env 指定
   - 选项 C：从 Easel 侧读取端口，Prism 不硬编码
   
   用户已确认 **A**。但 gateway 端口是 profile 哈希计算，无法静态指定，需要选项 **C** 的思路。

4. **回滚策略**
   - 选项 A：git clone 前 `git rev-parse HEAD` 快照 + 失败回滚（当前设计）
   - 选项 B：下载 zip + checksum 离线更新
   - 选项 C：双目录切换（当前目录 vs 备用目录）
   
   推荐 **A**（与 Hermes 更新机制一致，实现简单）。

5. **paths.json 的位置**
   - 选项 A：`DATA_DIR / "paths.json"`（当前设计，与 secrets 隔离）
   - 选项 B：`~/.laoma-ai/paths.json`（更标准的用户配置目录）
   - 选项 C：仓库根 `paths.json`（打包时排除）
   
   推荐 **A**（与 secrets 分离，用户可备份）。

### 9.2 技术类（可能需要专家经验）

6. **PyInstaller + Python 3.13 + 中文路径**的兼容性
   - 有无已知的 hook 问题？
   - `--add-data` / `--add-binary` 处理 `tools/hermes-home/` 时是否有 encoding 问题？
   - 是否有必要 pin 到 3.11 而非 3.13？

7. **Electron + NSIS + 中文路径 + 无签名**
   - SmartScreen 提示如何解决？（自签名证书？代码签名服务？）
   - NSIS 打包时如何处理 `.env` 排除列表？

8. **subprocess 53 处迁移的成本**
   - 分批 PR 策略是否可行？
   - 是否有其他更优雅的方案（如 monkeypatch subprocess 模块）？

9. **CI e2e-packaged 测试**
   - GitHub Actions `windows-latest` 是否够？
   - 是否需要自托管 Windows VM 以避免网络依赖？
   - Easel setup.ps1 是否可在 CI 环境跑通？

### 9.3 范围类

10. **P5 是否必要**（subprocess 兜底 + 跨平台）
    - 当前所有 subprocess 已在生产使用，未出过事
    - 但打包后风险显著升高
    - 是否可延后到下一 sprint？

11. **Hermes pin 的版本策略**
    - 当前 `setup-local-hermes.ps1:10` 硬 pin `bb0c230`
    - P3 引入 `easel_update.py` 后，Hermes 是否也应改为动态拉取？
    - 还是继续保持 pin，用户手动升级？

---

## 10. 附录

### 10.1 本次改动文件清单

```
prism_backend/fastapi_app/core/paths.py                          [新增，86 行]
prism_backend/fastapi_app/api/v1/video_pipeline/orchestrator.py  [修改，3 处]
prism_backend/fastapi_app/api/v1/video_pipeline/router.py        [修改，4 处]
prism_backend/fastapi_app/api/v1/video_pipeline/render.py        [修改，3 处]
prism_backend/fusion_ai/router.py                                [修改，3 处]
```

### 10.2 验证方式（专家可复现）

```powershell
# 环境准备
cd D:\dim开发\Prism-Fusion
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$py = 'D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe'

# 1) 验证 core.paths 模块可用
& $py -c "import sys; sys.path.insert(0, 'prism_backend'); from fastapi_app.core import paths; print(paths.get_template_lib_dir()); print(paths.get_hermes_runtime_config_path())"

# 2) 验证 4 个改动模块可 import
& $py -c "import sys; sys.path.insert(0, 'prism_backend'); from fastapi_app.api.v1.video_pipeline import orchestrator, render, router as vp_router; import prism_backend.fusion_ai.router; print('OK')"

# 3) 启动后端
cd prism_backend
& $py -m uvicorn fastapi_app.main:app --host 127.0.0.1 --port 7000

# 4) 另一个终端验证 API
Invoke-WebRequest http://127.0.0.1:7000/health
Invoke-WebRequest http://127.0.0.1:7000/api/v1/agent/config/hermes
Invoke-WebRequest http://127.0.0.1:7000/api/v1/agent/config/hermes/runtime
```

### 10.3 相关文档

- 完整产品化计划：~~`_plan_productize_master.md`（11 章节，含行号锚点）~~ **[2026-10-11 核实：该文件在仓库根不存在，全仓递归搜索 `*plan_productize*` 0 命中。可能散落在 `PLAN_next_steps.md`(15.5KB) / `PLAN_verification_measures.md`(28.5KB) / `HANDOFF.md`(24.3KB) 等本文档未提及的文件中，或从未落盘。待定位]**
- 后端侦察报告：`_recon_backend_paths_config_subprocess.md`
- 前端侦察：内联在本文档 §3.2
- 打包侦察：内联在本文档 §3.3
- 启动文档：`STARTUP.md`（**部分描述已过期**，见 §3.3）

### 10.4 参考代码

- Hermes 更新模板：`prism_backend/fastapi_app/agent/hermes_update.py`（313 行，P3 直接参考）
- Hermes 路径解析权威：`prism_backend/fastapi_app/agent/hermes_config.py`
- Pydantic Settings：`prism_backend/fastapi_app/core/config.py`
- 遗留配置（有冲突）：`config/conf.py`（不在 fastapi_app 内）

---

## 结语

这份文档的核心是：**P0 已经清掉了所有"打包后一定炸"的绝对路径**（5 处硬编码 → 走统一路径解析）。剩下的 P1–P6 是**产品化能力增量**，每项都可以独立交付、独立回滚。

**最需要专家审阅的三处**：

1. **`core/paths.py` 的设计**（§7.1、§7.2）：会不会埋循环依赖？与 `settings.DATA_DIR` 的关系？
2. **P1 的 paths.json 设计**（§6.1）：JSON 位置、格式、优先级是否合理？
3. **P3 的回滚策略**（§9.1-4）：git clone 前 old_sha 快照方案在生产环境的可靠性。

其他部分基本是按现有模式扩展，风险可控。

---

**下一步**：等专家 review 反馈后，确认或调整 §9 的待决问题，然后开始 P1。
