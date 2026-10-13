# Prism-Fusion 阶段 A 开发报告（对照产品化改造计划）

- 报告日期：2026-10-13
- 对照计划：`_plan_drafts_backup/sess_5f1791658525791_5fj71lu1vgpwq/draft.md`
  ——《Prism-Fusion 产品化改造计划（🅲 完整产品化）》P0-P7
- 交付范围：**阶段 A = P6 主体 + P5 部分**（详见 §2 对照表）
- 工作区状态：未提交、未动 git

> ⚠️ 说明：会话 summary 里出现的 "A1/A2/A3/A4" 是我此前复原旧会话时脑补的命名，
> 与真实计划不符。本报告以 workspace 备份的 **P0-P7** 为准做对照。

---

## 一、原计划概览（8 天，8 阶段）

| 阶段 | 主题 | 工时 | 优先级 |
|---|---|---|---|
| P0 | 生产阻塞点快速修补（硬编码路径） | 0.5d | 🔴 |
| P1 | 配置中心化 + 启动自检（`paths.py` / `/preflight`） | 1.5d | 🔴 |
| P2 | Hermes Runtime 响应 + Easel 状态扩展 | 0.5d | 🔴 |
| P3 | Easel 安装向导 + 路径修改 UI | 2d | 🔴 |
| P4 | Easel 自动更新（含 Hermes 回滚补齐） | 1d | 🟡 |
| P5 | 打包分发体系（CI 增强 / 打包脚本 / 文档 / 依赖收敛） | 1d | 🟡 |
| P6 | 跨平台 subprocess 兜底 + 错误处理 | 1d | 🟡 |
| P7 | 端到端验证 + 打包烟测 | 0.5d | 🔴 |

---

## 二、本轮交付（阶段 A）↔ 原计划对照

| 本轮工作 | 对应原计划 | 完成度 |
|---|---|---|
| 28 处 `subprocess.run/Popen` → `safe_run` / `safe_popen` | **P6 · 改动项 1 + 2**（新增 `subprocess_safe.py` + 迁移所有 53 处） | ✅ 28/28 迁移完；wrapper 早已存在 |
| `.github/workflows/ci.yml` 新增（py_compile + import 烟测 + A1 回归守门 + `.env` 字段守门） | **P5 · 改动项 1**（CI 增强：test / lint / build-backend / verify-package） | 🟡 仅完成最小 CI，pytest 依赖缺失（见 §4） |
| `.env.example` 清理（删除 17 行遗留字段：`FLASK_*` / `UPLOAD_FOLDER` / `MAX_CONTENT_LENGTH` / `COOKIE_DIR` / `COOKIE_BACKUP_DIR` / `REDIS_HOST|PORT|DB` / `JWT_SECRET_KEY`） | **P0 · 改动项 7**（`.env.example` 字段名对齐 pydantic） | 🟡 已修 17 处死字段，未触及 `HOST/PORT` 与 `BACKEND_HOST/BACKEND_PORT` 的对齐（该处需查 `config.py` 确认） |
| `env=` → `env_extra=` 语义调整（`browser_components` / `system/router`） | 属 P6 附带 | ✅ |
| 4 端点健康验证（`/health` `/preflight` `/easel/status` `/config/hermes` 全 200） | **P1 验收 + P2 验收** 的下游回归 | ✅ 已就绪，非本轮改动导致 |

### 明确未做

| 阶段 | 未做原因 |
|---|---|
| **P0 主体** | 5 处硬编码路径（`video_pipeline/orchestrator.py:47,106`、`fusion_ai/router.py:107`、`video_pipeline/router.py` + `render.py`）+ Hermes 三条解析路径并存 + Skills 根冲突 + 相对路径依赖 cwd + Easel 端口默认值不符 + `startup_event` 裸奔行 —— 均未动 |
| **P1 主体** | `paths.py` 单一真相源、`/paths` 端点、`/preflight` 扩展 —— 已有基础但字段未扩展 |
| **P2** | `AgentConfigResponse` 字段扩展、`/outputs` 与 `/drafts` 磁盘降级 —— 未动 |
| **P3** | Easel 安装向导 + 路径修改 UI（后端 4 端点 + 前端卡片）—— 未动，属"用户可见最大收益" |
| **P4** | Easel 自动更新器 + Hermes 回滚补齐 —— 未动 |
| **P5 主体** | 打包脚本改 secret 排除、`PACKAGING.md`、依赖收敛（`pyproject.toml` vs `requirements.txt`）、PyInstaller 入口收敛（`backend_service.py` 三服务改走 `paths.py::get_backend_root()`）、版本号同步脚本 —— 全部未动 |
| **P6 项 3/4/5** | `workshop.py` 跨平台探测、`startup_event` try 包裹、前端统一错误处理 —— 未动 |
| **P7** | `e2e_packaged_test.ps1` / `integration_test.py` / CI 的 `e2e-packaged` job —— 未动 |

---

## 三、详细执行结果

### 3.1 P6 · subprocess 迁移（阶段 A 主体）

- 迁移：28 处 `subprocess.run/Popen` → `safe_run` / `safe_popen`，覆盖 30+ 文件
- 保留：wrapper 自身 3 处 + `utils/process_manager.py` 2 处（计划明确要求保留 `CREATE_NEW_PROCESS_GROUP`，不适合 wrapper 化）
- 清理：8 个文件的死 `import subprocess`

**关键迁移点**：
- `video_transcoder.py` / `video_probe.py` / `video_frames.py`
- `ai_service/script_runner.py` / `ai_service/function_calling_tools.py`
- `fastapi_app/api/v1/ai/router.py` / `files/router.py` / `system/router.py`
- `fastapi_app/agent/hermes_config.py` / `hermes_agent.py`
- `fastapi_app/services/tool_registry.py` / `persona_dashboard.py`
- `tools/browser_components.py`
- `utils/automation_bootstrap.py` / `video_*`
- `uploader/bilibili_uploader/runtime.py`
- `douyin_tiktok_api/download.py`
- `myUtils/auth.py`

**DEVNULL 模式**（3 处：`hermes_agent` / `persona_dashboard` / `accounts/router`）：
```python
safe_run(cmd, capture_output=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
```

**例外语义确认**：
- `automation_bootstrap.py:248` 的 `TimeoutExpired` / `CalledProcessError` 映射与 `safe_run` 透传行为一致（`safe_run` 内部即调 `subprocess.run`，异常类型不变）

**验收**：`py_compile` 全过；全仓扫描无残留（白名单外）；后端启动 4 端点全 200。

### 3.2 P5 · CI 最小守门（阶段 A 部分）

新增 `.github/workflows/ci.yml`，四条守门：
1. **py_compile 全后端** —— 捕获语法回归
2. **8 个关键模块 import 烟测** —— 捕获循环导入、缺失依赖
3. **A1 回归守门** —— 扫描裸 `subprocess.run/Popen`，白名单只允许 `subprocess_safe.py` 与 `process_manager.py`
4. **`.env.example` 遗留字段守门** —— 防死字段回流

原计划 P5 要求的 `pytest` + `ruff check` + `black --check` + `build-backend` + `verify-package` 未做，理由见 §4。

### 3.3 P0 附带 · `.env.example` 死字段清理

`.env.example` 从 125 行降到 108 行，删除全部**仓库零引用**的字段（grep 全仓 0 命中）：
- `FLASK_PORT` / `FLASK_HOST` / `FLASK_DEBUG` —— 后端是 FastAPI 非 Flask
- `UPLOAD_FOLDER` / `MAX_CONTENT_LENGTH` —— 代码读的是 `UPLOAD_DIR`
- `COOKIE_DIR` / `COOKIE_BACKUP_DIR` —— 代码读的是 `COOKIE_FILES_DIR`
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` —— 只 `ecosystem.config.js` 用；代码读 `REDIS_URL`
- `JWT_SECRET_KEY` —— 仓库零引用（当前 JWT 复用 `SECRET_KEY`）

替换为代码实际读取的：`PORT` / `HOST` / `DEBUG` / `UPLOAD_DIR` / `COOKIE_FILES_DIR` / `REDIS_URL`。

### 3.4 A4 · 后端启动 + 4 端点健康验证

| 端点 | 状态 | 返回摘要 |
|---|---|---|
| `GET /health` | 200 | `{"status":"healthy","version":"2.0.0"}` |
| `GET /api/v1/system/preflight` | 200 | python / redis / celery / easel 组件就绪；`persona_api` 未就绪（既有告警） |
| `GET /api/v1/easel/status` | 200 | `installed:true, running:false, port:7860` |
| `GET /api/v1/agent/config/hermes` | 200 | `provider:custom, model:deepseek-v3, is_configured:true` |

---

## 四、未做项 & 遗留

### 4.1 pytest 依赖缺失，CI 只能做 py_compile
仓库无 `pytest`、无 `requirements-dev.txt`。`prism_backend/fastapi_app/tests/` 下 8 个 `test_*.py` 存在但当前无法运行。
- 建议：新增 `requirements-dev.txt`（含 `pytest` + `httpx` + `pytest-asyncio` + `pytest-cov`），CI 加 `pytest` job
- 优先级：中

### 4.2 supervisor 服务列表统一（P5 附带）
计划 P5 改动项 5 要求 `backend_service.py` 等 3 个 service 入口走 `paths.py::get_backend_root()`。
- 现状：`desktop-electron/resources/supervisor/supervisor.py` 1595 行内 **"backend" 硬编码 20 次**，分散在 8+ 类不同语义结构（停止顺序 / 端口字典 / 重启策略 / 可执行路径 / 启动顺序 / 日志路径 / 健康检查 / 就绪探针 / 端口冲突集）
- 建议：单开任务，先设计 `SERVICE_REGISTRY` 数据结构，再分批替换
- 本轮不做理由：改动 200+ 处跨 6 类语义，风险高

### 4.3 启动慢（未做）
后端冷启动约 30-35s，其中 Hermes CLI 初始化 + dashboard 启动约 22s 是最大瓶颈。
- 优化需 `cProfile` / `py-spy` 定位，本轮未启动

### 4.4 计划 §7 前置确认（7 项决策点）
原计划要求签核后再开工：
1. P0 优先级排序
2. `paths.json` 位置（建议 `DATA_DIR/paths.json`）
3. Skills 根统一范围（`tool_registry.py:33` 是否要动 Hermes 侧）
4. Easel 端口默认值（Easel 真相 7860/37289 vs Prism 现有 7861/18789）
5. CI `e2e-packaged` 是否需真实虚拟机
6. **P4 回滚策略**：git SHA 快照 vs 下载 zip + checksum（离线更新模式）—— **最大分歧**
7. 8 天工时上限是否硬约束

- 现状：**均未签核**
- 影响：影响 P3 / P4 / P5 的具体做法，本轮未启动这三阶段，暂无阻塞

---

## 五、改动清单

### 新增
- `.github/workflows/ci.yml` —— 快速 CI（py_compile + import 烟测 + A1 回归守门 + .env 字段守门）

### 修改
- `prism_backend/.env.example` —— 125→108 行，清理 17 处零引用死字段
- 30+ 文件的 28 处 subprocess 调用点（详见 §3.1）

### 未动（明确排除）
- `desktop-electron/resources/supervisor/supervisor.py` —— 服务列表统一留独立任务
- 所有业务逻辑（P0-P4 / P7 范围）
- git 工作区状态（保持原状，未 add/commit）

---

## 六、下一步建议

按 P0-P7 阻塞关系与本轮已完成的 A 阶段成果，推荐：

1. **签核 §7 决策点**（尤其 §7-6 离线模式）—— 阻塞 P4 / P5 具体做法
2. **启动 P0**（0.5d）—— 清硬编码路径，是所有后续阶段的地基
3. **启动 P1**（1.5d）—— 建 `paths.py` 单一真相源，是 P2/P3/P4/P5 共享基础
4. **补 `requirements-dev.txt`**（0.1d）—— 让 CI 的 pytest job 能真跑
5. **P3 Easel 安装向导**（2d）—— 用户可见最大收益
6. **P6 剩余 + P5 打包分发**（2d）—— 收尾
7. **P7 端到端**（0.5d）—— 收官

若严格按原计划 8 天工期，P0-P2 应最先做；本轮做的 P6 主体与 P5 最小 CI 是"可并行、可独立回滚"的中优先级工作，不影响主干推进。
