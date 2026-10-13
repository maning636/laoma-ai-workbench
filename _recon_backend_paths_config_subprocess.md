# Prism-Fusion 后端路径/配置/子进程 侦察报告

> 全部基于 `D:\dim开发\Prism-Fusion\prism_backend`（`fastapi_app/` 主入口）。行号格式 `path:line`。

---

## 1. 路径解析点全扫描

### 1.1 主配置 `fastapi_app/core/config.py`（pydantic Settings 主配置源）
| 变量 | 默认 / 来源 | 行号 |
|---|---|---|
| `BASE_DIR` | `Path(__file__).parent.parent.parent` = `prism_backend/` | `:84` |
| `DATA_DIR` | `_resolve_default_data_dir(BASE_DIR)`：`LAOMA_DATA_DIR` env > dev repo 内 `BASE_DIR` > `%APPDATA%/老马AI工作台/data` > `%LOCALAPPDATA%/…` > `BASE_DIR` | `:21-55, 87` |
| `DATABASE_PATH` / `COOKIE_DB_PATH` / `AI_LOGS_DB_PATH` | `DATA_DIR/db/*.db` | `:89-91` |
| `DATABASE_URL` | 空=SQLite；非空=MySQL | `:95` |
| `REDIS_URL` | `redis://localhost:6379/0` | `:98` |
| `CELERY_BROKER_URL` / `RESULT_BACKEND` | 空时回落 `REDIS_URL`（`resolved_*` 函数 `:182-187`） | `:99-100` |
| `COOKIE_FILES_DIR` / `FINGERPRINTS_DIR` / `BROWSER_PROFILES_DIR` / `VIDEO_FILES_DIR` / `UPLOAD_DIR` | `DATA_DIR/<subdir>` | `:103-107` |
| `PERSONA_API_URL` | `http://127.0.0.1:8787` | `:113` |
| `LOG_FILE` | `DATA_DIR/logs/fastapi_app.log` | `:144` |
| `.env` 加载源 | `Path(__file__).resolve().parent.parent.parent.parent / ".env"` = **仓库根 `.env`** | `:168-173` |

**关键 fallback**：dev 检测靠 `(base_dir.parent / ".git").exists()` 或 `LAOMA_ENV`/`NODE_ENV`（`:11-18`）；`_resolve_default_data_dir` 同时试 `%APPDATA%` 与 `%LOCALAPPDATA%`。

### 1.2 遗留配置 `prism_backend/config/conf.py` / `conf.example.py`
- `APP_ROOT = _resolve_app_root()`：`LAOMA_APP_ROOT` / `LAOMA_RESOURCES_PATH` > `sys.frozen` 探测 > 上溯搜索 `prism_backend|backend|prismenv+browsers`（`:36-50`）。
- `conf.py:57` `load_dotenv(_root_env, override=True)` 会覆盖 os.environ；`conf.example.py:58` 用 `override=False`——**两者行为不一致**。
- `_normalize_env_path` 把 `PLAYWRIGHT_BROWSERS_PATH` / `LOCAL_CHROME_*` / `LOCAL_FIREFOX_PATH` 相对路径改成绝对（`:61-76`）。
- `conf.py` 额外做 `_find_preferred_local_chrome()`（系统 Chrome → bundled → patchright）；`conf.example.py` 缺这段。

### 1.3 Hermes 配置层 `fastapi_app/agent/hermes_config.py`（第二配置中心）
| 变量 | 默认 / 来源 | 行号 |
|---|---|---|
| `LAOMA_RESOURCES_PATH` / `LAOMA_APP_ROOT` | 决定 `get_repo_root()` | `:38-39` |
| `LAOMA_HERMES_PYTHON` | 覆盖 `prismenv` 根 | `:46-57` |
| `PRISM_HERMES_WORKSPACE` | `get_workspace_root()` 覆盖 | `:68-73` |
| `PRISM_HERMES_HOME` | `get_hermes_home_path()`，默认 `<repo>/tools/hermes-home` | `:137-138` |
| `PRISM_HERMES_WEBUI_STATE_DIR` | 默认 `<hermes-home>/webui` | `:149-150` |
| `HERMES_GIT_BASH_PATH` | git-bash 探测覆盖 | `:176-179` |
| Hermes 源 | `<repo>/tools/hermes-agent` | `:76-77` |
| WebUI 源 | `<repo>/tools/hermes-webui` | `:129-130` |
| **web_dist** | `hermes_source_path / hermes_cli / web_dist`（**无环境变量覆盖**） | `:133-134` |

### 1.4 Easel 配置层 `fastapi_app/services/easel_workbench.py`
- `EASEL_DIR = Path(os.getenv("LAOMA_EASEL_DIR") or (REPO_ROOT.parent / "Easel"))`（`:27`）——fallback 是仓库根父目录/Easel，非 monorepo 部署必错。
- `EASEL_PORT = int(os.getenv("LAOMA_EASEL_PORT") or 7861)`（`:28`）
- `LAOMA_EASEL_GATEWAY_PORT or 18789`（`:31`）

`easel_outputs.py`:
- `OUTPUTS_DIR = _env("LAOMA_OUTPUTS_DIR", EASEL_DIR / "outputs")`（`:42`）
- `_env` 会把 `replace_me`/`your-api-key`/`xxx`/`<...>` 占位符视为未配置（`:24-39`）——设计良好。

### 1.5 🚨 硬编码路径
| 文件 | 硬编码 | 行号 |
|---|---|---|
| `video_pipeline/orchestrator.py` | `E:\FDE\fde-landing-delivery` | `:47` |
| 同上 | `D:/工作台/LaomaAI-Fusion/tools/hermes-home/config.yaml` | `:106` |
| `fusion_ai/router.py` | 同上 `D:/工作台/LaomaAI-Fusion/tools/hermes-home/config.yaml` | `:107` |
| `video_pipeline/router.py` | `F:/自媒体/OpenMontage`, `F:/自媒体/MoneyPrinterTurbo`, `C:/Program Files/nodejs` | `:47, 64-66, 106, 113` |
| `video_pipeline/render.py` | `C:/Program Files/nodejs` 强插 PATH | `:22, 35-36` |
| `services/workshop.py` | `WORKSHOP_DIR = Path("data/workshop")`（**相对路径**，依赖 cwd） | `:24` |
| `api/v1/accounts/router.py` | biliup exe 靠 `parents[4]` 上溯 | `:395` |
| `utils/process_manager.py` | `REPO_ROOT` 靠 `parents[2]`；`HERMES_HOME = REPO_ROOT/"tools"/"hermes-home"`（**未读 `PRISM_HERMES_HOME` 环境变量**） | `:28, 32` |

### 1.6 Skills / Shared scripts
- `skill_registry.py:21-22`：`SKILLS_DIR = EASEL_DIR/"skills"/"openclaw"`；`SHARED_SCRIPTS_DIR = EASEL_DIR/"skills"/"shared"/"scripts"`
- `workshop.py:22-23`：`PYTHON_EXE = EASEL_DIR/".venv"/"Scripts"/"python.exe"`（**仅 Windows**）；`SCRIPTS_DIR = EASEL_DIR/"skills"/"shared"/"scripts"`
- `video_pipeline/orchestrator.py:431-433`：`EASEL_DIR/".venv"/"Scripts"/"python.exe"` 与 `EASEL_DIR/"skills"/"shared"/"scripts"/"asr.py"`

### 1.7 Sessions / ai-sessions
- `agent/router.py:39`：`_SESSIONS_DIR = Path(os.getenv("LAOMA_SESSIONS_DIR") or (Path("data")/"ai-sessions"/"hermes"))`——**又是相对路径**
- `chat_history.py:44`：SQLite `chat_sessions` 表（会话消息存储）
- Hermes 侧 sessions 通过 `PRISM_HERMES_HOME/sessions/` 由 Hermes 自己管

### 1.8 Tools
- `tool_registry.py:28-33`：`TOOLS_DIR = REPO_ROOT/"tools"`；`SKILLS_ROOT = REPO_ROOT/"runtime-data"/"app"/"hermes-home"/"skills"`——**注意与 hermes_config 默认 `tools/hermes-home` 不同！**
- `tool_catalog.py` 无硬编码路径

---

## 2. Easel 依赖点

### 2.1 三大核心服务
**`easel_workbench.py`（Web 进程托管）**
- 依赖：`asyncio`, `subprocess`, `httpx`, `psutil`（`:70-76`）, `loguru`
- env：`LAOMA_EASEL_DIR`, `LAOMA_EASEL_PORT`, `LAOMA_EASEL_GATEWAY_PORT`
- 动作：`asyncio.create_subprocess_exec(easel.exe, "web", "--port", ...)`（`:164-174`），`CREATE_NO_WINDOW`（`:162`）
- 幂等保护：`get_easel_status` + `_probe_web_api`（`:92-99, :145-147`）
- Easel 缺失：`start_easel` 抛 `RuntimeError("Easel 未安装或安装不完整: ... 请先运行 Easel 仓库的 setup.ps1")`（`:150-153`）→ **硬失败**

**`easel_drafts.py`（HTTP 桥）**
- 依赖：`httpx` + `easel_workbench.{EASEL_DIR, EASEL_HOST, EASEL_PORT, _easel_url}`（`:22`）
- 落盘：`IMPORTS_FILE = BACKEND_ROOT/"db"/"easel_imports.json"`（`:25`），当前 17 字节
- 上限：`MAX_IMPORT_FILE_MB = 160`（`:34`）
- Easel Web API 不可达：`list_drafts`/`get_draft_detail` 抛 `RuntimeError("Easel Web API 不可达")`（`:69, :106`）→ **硬失败（502）**
- `_load_imports` 文件缺失走空 dict，写失败走 warning（`:48-60`）

**`easel_outputs.py`（磁盘真相源，不经 HTTP）**
- 依赖：`easel_workbench.EASEL_DIR`（`:19`）
- `OUTPUTS_DIR` 可被 `LAOMA_OUTPUTS_DIR` 覆盖（`:42`）
- `list_outputs`/`get_outputs_cached`：**目录不存在返回空列表**（`:120-133, :136-142`）→ **优雅降级**
- HTML 预览带 base64 内联本地图（32MB 上限）（`:249-300`）

### 2.2 `EASEL_DIR` 引用扇出
```
skill_registry.py:19         → SKILLS_DIR, SHARED_SCRIPTS_DIR
workshop.py:20               → PYTHON_EXE, SCRIPTS_DIR
easel_outputs.py:19          → OUTPUTS_DIR 默认
easel_drafts.py:22           → _easel_url()（间接 EASEL_PORT/HOST）
video_pipeline/orchestrator.py:431 → asr.py transcribe（level-3 fallback）
easel_bridge/router.py:90    → _easel_base_url()（间接）
```

### 2.3 API 层表现（`easel_bridge/router.py`）
| 端点 | 行 | Easel 缺失时 |
|---|---|---|
| `/easel/status` | `:29` | 优雅（`installed:false`） |
| `/easel/start` | `:39` | **硬崩 500** |
| `/easel/stop` | `:50` | 优雅（stopped_pid=None） |
| `/easel/drafts` | `:61` | **硬崩 502**（应改用 `list_outputs` 降级） |
| `/easel/drafts/{p}` | `:72` | 硬崩 502 |
| `/easel/outputs` | `:85` | **硬崩 502**（应改用磁盘降级） |
| `/easel/media/{p}` | `:102` | 硬崩 502 |
| `/easel/drafts/{p}/import` | `:116` | 硬崩 502 |
| `/api/v1/skills` | — | 优雅（`total:0`） |
| `/api/v1/skills/refresh` | — | 优雅（空列表） |
| `/api/v1/skills/shared-scripts` | — | 优雅（空列表） |
| `/api/v1/workshop/run` | — | **硬崩**（`RuntimeError: Easel 运行环境缺失`） |
| 视频流水线 level-3 本地 ASR | `orchestrator.py:474` | 优雅（warning + failed） |

### 2.4 Easel 依赖扇出图
```
                                LAOMA_EASEL_DIR (env)
                                            │
                                            ▼
                                easel_workbench.EASEL_DIR
                              (fallback: REPO_ROOT.parent/"Easel")
                                            │
        ┌──────────────┬─────────────┬──────┴──────┬────────────────┬───────────────┐
        ▼              ▼             ▼             ▼                ▼               ▼
 easel_workbench  easel_drafts  easel_outputs  skill_registry   workshop      video_pipeline
 (进程托管)        (HTTP桥)      (磁盘读取)     (skills索引)     (Easel venv)  orchestrator
```

---

## 3. 启动流程 `main.py:136-320`

| 步 | 内容 | try/except | 失败时 | 行 |
|---|---|---|---|---|
| 1 | `os.environ.setdefault("LAOMA_DATA_DIR", str(settings.DATA_DIR))` | ❌ 裸奔 | 崩 | `:143` |
| 2 | `_migrate_dir` cookiesFile / fingerprints / browser_profiles（含 LOCALAPPDATA 回迁） | ✅ 三合一 | warn 后 continue | `:191-196` |
| 3 | `VIDEO_FILES_DIR.mkdir` | ✅ | warn | `:199-202` |
| 4 | 4 目录批量 mkdir | ✅ 逐个 | warn | `:204-214` |
| 5 | SQLite `ensure_main_db_schema` | ✅ | warn（**但 DB schema 缺失会让后续所有 DB 操作崩**） | `:218-226` |
| 6 | MySQL `metadata.create_all` | ✅ | warn | `:229-237` |
| 7 | TaskQueueManager（`db/task_queue.db`） | ✅ | warn → `app.state.task_manager=None` → 任务 API 全崩 | `:240-252` |
| 8 | manual_tasks 表（`importlib.util.spec_from_file_location` 兜底导入 `db/create_manual_tasks_table.py`） | ✅ | warn | `:255-270` |
| 9 | `get_batch_publish_service` | ✅ | warn（**注释说"Celery/Redis 已加载"但此处未建 Celery 实例**） | `:273-279` |
| 10 | `get_openclaw_agent` | ✅ | warn | `:286-292` |
| 11 | Hermes dashboard autostart（除 `LAOMA_SUPERVISOR_MANAGES_HERMES_UI=1`） | ✅ | warn | `:295-305` |
| 12 | Account cleanup scheduler（每 6h） | ✅ | warn | `:307-313` |
| 13 | Hermes update scheduler | ✅ | warn | `:315-320` |

**未启动**：Celery worker、Redis broker 都不在 startup 内（靠 `utils/process_manager.py` 或 pm2 外部拉起）。

### 3.1 `/api/v1/system/health-check`（`system/router.py:510-569`）
检查项：
- `database`：`main_db_pool.get_connection().execute("SELECT 1")`
- `browser`：HTTP `http://127.0.0.1:7001/health`（Automation Worker）
- `ai_service`：`get_ai_config("chat")` 是否非空
- `disk_space`：`shutil.disk_usage(settings.BASE_DIR)`

**overall_status 判定 bug**（`:558-561`）：
```python
"healthy" if all(
    v in ["healthy", "not_available"] or "GB" in str(v)
    for v in health_status.values()
) else "degraded"
```
- `disk_space = "5GB free"` 命中 `"GB"` → 算 healthy
- `"unknown"` 不在白名单，磁盘检查失败会拉低整体状态
- **缺检**：Easel / Hermes / Redis / Celery / Persona / Playwright 浏览器 / task_queue.db / manual_tasks 表 / skills 目录全部未检查
- `main.py:381` `/health` 只回 version，无诊断

---

## 4. 配置文件清单

### 4.1 顶层 & backend
| 文件 | 作用 | 被谁读 |
|---|---|---|
| `.env`（不存在，只有 `env.example`） | 全局配置 | `config.py:171`, `config/conf.py:57` |
| `env.example` | 模板（PLAYWRIGHT/CORS/AI/SOCIAL_COPILOT） | 复制粘贴 |
| `prism_backend/.env.example` | 后端模板（3981B） | — |
| `prism_backend/fastapi_app/.env.example` | 后端模板（549B） | — |
| `prism_backend/fastapi_app/core/config.py` | pydantic Settings 主源 | 全后端 |
| `prism_backend/config/conf.py` | 遗留路径归一化 + Chrome 探测 + `load_dotenv override=True` | automation, uploader |
| `prism_backend/config/conf.example.py` | 同上 example 版（`override=False`） | — |
| `prism_backend/config/hermes_agent.example.toml` | Hermes agent 模板 | Hermes |

### 4.2 平台特性 JSON/YAML
- `config/platform_features_{douyin,xiaohongshu,kuaishou,channels}.json`
- `config/fingerprint_policy.json`（1089B）
- `config/guide_config.json`（1658B）
- `config/ai_prompts.yaml` / `ai_prompts_unified.yaml`
- `config/selectors/{channels,douyin}_upload.json`

### 4.3 Hermes 运行时（`tools/hermes-home/`）
- `.env`（10B，基本空）
- `config.yaml`：LLM `model.{api_key,base_url,default}`；被 `fusion_ai/router.py:107` 与 `video_pipeline/orchestrator.py:106` **硬编码绝对路径**读取
- `auth.json`, `.skills_prompt_snapshot.json`, `spawn-ledger.json`, `update-settings.json`, `update-state.json`
- `webui/settings.json`
- `cache/*.json`, `sessions/*.json`
- `models_dev_cache.json`, `ollama_cloud_models_cache.json`, `provider_models_cache.json`

### 4.4 其它
- `douyin_tiktok_api/config.yaml` + `crawlers/{douyin,tiktok}/web/config.yaml` + `docker-compose.yml`
- `myUtils/tikhub_endpoints.json` + `myUtils/cookies.json`
- `db/easel_imports.json`（17B，运行时）
- `data/ai-sessions/hermes/sess-*/meta.json`
- `video-pipeline/runs/*.json`
- `profiles/*/profile.json`
- `_profile_build/smoke_test.json`
- `prism_frontend/.env.local` + `.env.local.example`
- `tools/hermes-agent/.env.example`（27KB）+ `.envrc`
- 顶层 `pyproject.toml` / `uv.lock` / `package.json` / `pnpm-lock.yaml` / `package-lock.json`
- 顶层 `ecosystem.config.js` / `ecosystem-mac.config.js`（pm2）

### 4.5 观察
- **两份 env.example 与 config 不一致**：`fastapi_app/.env.example` 里 `PORT=5409`，但 `config.py:73` 默认 `PORT=7000`；`config.py` 用 `HOST`/`PORT`，`.env.example` 顶层写 `BACKEND_HOST`/`BACKEND_PORT`（pydantic `case_sensitive=True` → `BACKEND_HOST` 完全无效）。
- `config/conf.py` vs `conf.example.py` 的 `load_dotenv override` 不一致（True vs False）。
- Hermes 运行时同时被三处指向：`tools/hermes-home`（hermes_config 默认）、`runtime-data/app/hermes-home`（tool_registry SKILLS_ROOT）、`D:/工作台/LaomaAI-Fusion/tools/hermes-home`（fusion_ai & video_pipeline 硬编码）。

---

## 5. subprocess 调用点

### 5.1 编码/环境完整（好）
| 位置 | 命令 | 备注 |
|---|---|---|
| `easel_workbench.py:164` | `easel.exe web --port` | `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `PYTHONUNBUFFERED=1`, `EASEL_PORT`, `CREATE_NO_WINDOW`, `cwd=EASEL_DIR` |
| `workshop.py:146` | `easel .venv python <script>` | `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `CREATE_NO_WINDOW`, `utf-8 errors=ignore`, `timeout=900s` |
| `video_pipeline/router.py:139,157` / `render.py:69,88` | `npx hyperframes {check,render}` | `_build_env()` 含 proxy + `PYTHONUTF8/IOENCODING=1` + `NODE_NO_WARNINGS=1` + 强插 `C:/Program Files/nodejs`, `CREATE_NO_WINDOW`, `utf-8 errors=ignore`, timeout 60/600s |
| `video_pipeline/orchestrator.py:444` | `easel .venv python asr.py` | UTF-8 环境，`CREATE_NO_WINDOW`, timeout 900s |
| `hermes_update.py:90` | `git -C <src> <args>` | `utf-8 errors=replace`, `cwd=src`, `timeout=120s` |
| `hermes_update.py:150,182,204,207,210,216,220` | `python -c` / `powershell setup-local-hermes.ps1` / `pip install/uninstall/upgrade` | `utf-8 errors=replace`, `cwd` 各异, `timeout=300-1800s` |
| `hermes_config.py:219` | `python -c gateway config` | `PYTHONPATH` + `utf-8 errors=replace` |
| `hermes_agent.py:340,381,655,680` | `hermes python -c runpy hermes_cli` | `_build_process_env` 含 `HERMES_HOME/PYTHONUTF8/PYTHONIOENCODING=1/PYTHONPATH/HERMES_CONFIG_PATH/HERMES_YOLO_MODE=1/HERMES_WEB_DIST/HERMES_WEBUI_*`, `utf-8 errors=ignore`, `cwd` 参数化 |
| `persona_dashboard.py:126,156` | `npm install` / `node vite.js --no-open` | `utf-8 errors=ignore`, `VITE_API_URL` env |
| `persona_dashboard.py:192` | `taskkill /F /T /PID` | `timeout=5s` |

### 5.2 编码/环境不严谨（有风险）
| 位置 | 问题 |
|---|---|
| `tool_registry.py:112` | `shell=True` 无 env/creationflags/cwd |
| `tool_registry.py:233` | `open_url Popen(cmd, shell=True)` **无 creationflags** → Windows 弹窗，URL 含中文可能崩 |
| `tool_registry.py:376` | `git clone` 无 `encoding=`，`text=True` 默认 GBK on Win |
| `tool_registry.py:413,480,447` | `shell=True` + 无 creationflags + 无显式 env |
| `automation_bootstrap.py:248` | 无 encoding，无 creationflags |
| `utils/video_transcoder.py:27,112,185` | ffmpeg |
| `utils/video_probe.py:84` | ffprobe |
| `utils/video_frames.py:81` | ffmpeg，`text=True` 无 encoding |
| `ai_service/script_runner.py:76` | 未细查 |
| `api/v1/ai/router.py:583` | 未细查 |
| `api/v1/files/router.py:1146,1186` | 未细查 |
| `api/v1/system/router.py:128,148,715` | `:715` 是 `Popen` |
| `myUtils/auth.py:627` | 未细查 |
| `tools/browser_components.py:161,203` | 未细查 |
| `uploader/*/main*.py`（6+ 处） | 老 uploader 内部 |
| `automation_worker/worker.py`（5+ 处） | 未细查 |
| `reverse_api/signing/douyin_abogus_signer.py:30` | 未细查 |

### 5.3 Win32 `CREATE_NO_WINDOW` 覆盖度
仅下列设了 `CREATE_NO_WINDOW`：
- `easel_workbench.py:162`
- `workshop.py:152`
- `persona_dashboard.py:192`
- `video_pipeline/router.py:80,145`（3 处）
- `video_pipeline/render.py:50,75,94`（3 处）
- `video_pipeline/orchestrator.py:445`

**其余 27+ 个 subprocess 调用点均未设**，Windows GUI 场景下 cmd 弹窗（尤其 `tool_registry.py:233 open_url`）。

### 5.4 中文路径 / GBK 高风险
- 项目根路径本身是中文（`D:\dim开发\...`）。任何未加编码保护的 subprocess 都有风险。
- 特别危险：`tool_registry.py:233` `open_url` shell=True；`tool_registry.py:113` `_check_installed` shell=True + text=True；`automation_bootstrap.py:248` 无编码。

---

## 🚨 高优先级风险清单

1. **硬编码绝对路径**（3 处严重）：
   - `orchestrator.py:47` `E:\FDE\fde-landing-delivery`
   - `orchestrator.py:106` & `fusion_ai/router.py:107` `D:/工作台/LaomaAI-Fusion/tools/hermes-home/config.yaml`
   - `video_pipeline/router.py:106,113` `F:/自媒体/OpenMontage`, `F:/自媒体/MoneyPrinterTurbo`
   - `video_pipeline/render.py:22` / `router.py:47,64-66` `C:/Program Files/nodejs`

2. **Hermes config.yaml 三条不同解析路径并存**：
   - `hermes_config.py`（env-driven）
   - `tool_registry.py:33` `runtime-data/app/hermes-home`
   - `fusion_ai`+`orchestrator` 硬编码 `D:/工作台/LaomaAI-Fusion/...`
   - `utils/process_manager.py:32` 的 `HERMES_HOME` 也绕过 `PRISM_HERMES_HOME` 覆盖

3. **相对路径依赖 cwd**：`WORKSHOP_DIR = Path("data/workshop")`（workshop.py:24）、`_SESSIONS_DIR = Path("data")/"ai-sessions"/"hermes"`（agent/router.py:39）。

4. **两条 skills 根路径并存**：`skill_registry.py` `EASEL_DIR/skills/openclaw` vs `tool_registry.py` `runtime-data/app/hermes-home/skills`。

5. **health-check 覆盖面严重不足**：不检查 Easel/Hermes/Redis/Celery/Persona/Playwright/task_queue.db/skills；`:558-561` 判定逻辑把 `"unknown"` 当降级。

6. **Windows subprocess 大多未设 `CREATE_NO_WINDOW`**（27+/53）；`tool_registry.py:233 open_url` shell=True 会闪窗。

7. **`config/conf.py` vs `conf.example.py` 的 `load_dotenv override` 不一致**（True vs False）；`conf.py` 覆盖 os.environ 可能踩 `LAOMA_*` 优先级坑。

8. **`workshop.py:22` `PYTHON_EXE` 只识别 Windows `.venv/Scripts/python.exe`**，macOS/Linux 部署必崩。

9. **startup_event 唯一裸奔行**（`main.py:143`）+ `task_manager` 初始化失败后所有依赖 `app.state.task_manager` 的路由会 AttributeError。

10. **`.env.example` 与 pydantic 字段名不一致**：`BACKEND_HOST/BACKEND_PORT` 完全无效（`config.py` 用 `HOST/PORT`）。

---

## 📋 paths 建议清单（应集中到单一配置源）

**A. 数据/存储根**
- `LAOMA_DATA_DIR` → 影响 DATA_DIR / DATABASE_PATH / COOKIE_DB_PATH / AI_LOGS_DB_PATH / LOG_FILE / COOKIE_FILES_DIR / FINGERPRINTS_DIR / BROWSER_PROFILES_DIR / VIDEO_FILES_DIR / UPLOAD_DIR / task_queue.db / ai-sessions / video-pipeline/runs / workshop / manual_tasks
- `LAOMA_SESSIONS_DIR`
- `LAOMA_OUTPUTS_DIR`（覆盖 Easel outputs）
- `DATABASE_URL`（SQLite → MySQL 切换）

**B. 应用根**
- `LAOMA_APP_ROOT` / `LAOMA_RESOURCES_PATH`
- `LAOMA_ENV`（dev 判定）

**C. Easel**
- `LAOMA_EASEL_DIR` / `LAOMA_EASEL_PORT` / `LAOMA_EASEL_GATEWAY_PORT`
- 派生：`EASEL_DIR/.venv/Scripts/{python,easel}.exe`, `EASEL_DIR/skills/openclaw`, `EASEL_DIR/skills/shared/scripts`, `EASEL_DIR/outputs`

**D. Hermes**
- `LAOMA_HERMES_PYTHON`
- `PRISM_HERMES_HOME` / `PRISM_HERMES_WEBUI_STATE_DIR` / `PRISM_HERMES_WORKSPACE`
- `HERMES_GIT_BASH_PATH`
- 派生：`tools/hermes-agent`, `tools/hermes-webui`, `hermes-home/config.yaml`, `hermes-home/.env`, `hermes-home/webui`, `hermes-home/sessions`, `hermes-home/cache`, `hermes-home/gateway_state.json`

**E. Skills**（**冲突项**）
- `EASEL_DIR/skills/openclaw`（skill_registry）
- `runtime-data/app/hermes-home/skills`（tool_registry）
- `tools/hermes-home/skills`（Hermes 自身）

**F. 浏览器 / Playwright**
- `PLAYWRIGHT_HEADLESS`
- `PLAYWRIGHT_BROWSERS_PATH`
- `LOCAL_CHROME_PATH`（+ `_WIN`/`_MAC`/`_LINUX` 变体）
- `LOCAL_CHROME_HEADLESS_SHELL_PATH`
- `LOCAL_FIREFOX_PATH`

**G. Redis / Celery**
- `REDIS_URL`
- `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`

**H. Persona / 代理**
- `PERSONA_API_URL`（`PERSONA_API_BASE` property 别名）
- `PERSONA_INJECT_PROXY` / `PERSONA_DEFAULT_ENGINE` / `PERSONA_LAUNCH_TIMEOUT`
- `LAOMA_PERSONA_DASHBOARD_HOST`

**I. AI 服务**
- `SILICONFLOW_API_KEY` / `SILICONFLOW_BASE_URL` / `SILICONFLOW_PROMPT_MODEL` / `SILICONFLOW_IMAGE_MODEL` / `DEEPSEEK_OCR_MODEL`
- Legacy: `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL`
- `LAOMA_SILICONFLOW_ASR_MODEL` / `LAOMA_SILICONFLOW_BASE_URL` / `LAOMA_ASR_MODEL`
- `HERMES_HOME/config.yaml` 内 `model.{api_key,base_url,default}`（当前被两处硬编码读取）

**J. 第三方工具**（当前硬编码）
- 模板库：`E:\FDE\fde-landing-delivery`
- `F:/自媒体/OpenMontage`
- `F:/自媒体/MoneyPrinterTurbo`
- `C:/Program Files/nodejs`（npx 兜底）

**K. 端口/主机**
- `HOST` / `PORT`（7000）
- Automation Worker：`127.0.0.1:7001`（health-check 硬编码）
- Persona API：`127.0.0.1:8787`
- Persona Dashboard：`127.0.0.1:5173`
- Easel Web：`127.0.0.1:7861`
- Easel Gateway：`127.0.0.1:18789`
- Hermes Dashboard / WebUI：`9119` / `8788`（`utils/process_manager.py:50-51`）
- `_PROXY_HTTP_URL` / `_PROXY_HTTPS_URL`（video_pipeline 内 env）

**L. 其它**
- `LAOMA_SUPERVISOR_MANAGES_HERMES_UI`（决定是否自动启动 Hermes UI）
- `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` / `PYTHONUNBUFFERED=1`（子进程 env 统一）
- `NODE_NO_WARNINGS=1`（hyperframes）
- `HERMES_YOLO_MODE=1`（hermes_agent）
- `HERMES_CONFIG_PATH` / `HERMES_WEB_DIST` / `HERMES_WEBUI_HOST/PORT/API_BASE`
- `VITE_API_URL`（persona_dashboard）

---

*报告完*
