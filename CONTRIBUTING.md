# 贡献指南（CONTRIBUTING）

感谢你对 **Prism-Fusion（老马AI工作台）** 的兴趣。本项目是自媒体矩阵发布 + AI 内容生成的 Open Core 平台，代码基于 **AGPL-3.0** 开源，功能分为 **Community（开源免费）** 与 **Pro（云端付费服务）** 两层。

> 阅读顺序：[快速开始](#1-快速开始) → [开发环境](#2-开发环境搭建) → [代码规范](#3-代码规范) → [测试](#4-测试要求) → [分支与提交](#5-分支与提交) → [PR 流程](#6-pr-流程) → [Open Core 边界](#8-open-core-边界) → [行为准则](#9-行为准则-code-of-conduct)

---

## 1. 快速开始

```powershell
# 1) Fork 到个人账号 → clone
git clone https://github.com/<your-name>/Prism.git
cd Prism

# 2) 开发环境（详见 §2）
python -m venv prismenv
prismenv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cd prism_frontend; npm ci; cd ..

# 3) 启动（Windows 一键）
start.bat
# 或 macOS：./start-pm2.sh

# 4) 开发模式
cd prism_frontend; npm run dev          # 前端 :3000
cd prism_backend;  uvicorn fastapi_app.main:app --reload --port 7000  # 后端 :7000
```

更多部署细节见 [README.md · 部署开始](README.md#部署开始)。

---

## 2. 开发环境搭建

### 2.1 基础依赖

| 组件 | 版本 | 说明 |
|---|---|---|
| Node.js | **20.x**（LTS） | Next.js 16 要求 |
| npm | 10.x | 随 Node 附带 |
| Python | **3.11** | 与 `prismenv` 打包一致 |
| Git | 2.40+ | 支持 sparse checkout |
| Redis | 7.x | 矩阵任务队列 |
| Electron | 随 `desktop-electron/package.json` | 桌面打包 |

> Windows 用户请确保已安装 Visual C++ Build Tools、Git for Windows。

### 2.2 虚拟环境（`prismenv`）

推荐使用仓库根目录下的 `prismenv`（Windows）/ `prismenv`（macOS/Linux，`bin/` 布局），保证与 CI 打包产物一致：

```powershell
# Windows
python -m venv prismenv
prismenv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
```

```bash
# macOS / Linux
python3 -m venv prismenv
source prismenv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt` 为生产依赖，`requirements-dev.txt` 仅包含 pytest / ruff / black / flake8 / alembic 等开发工具。

### 2.3 前端依赖

```powershell
cd prism_frontend
npm ci            # 使用 lockfile，CI 与本地一致
npm run dev       # 本地开发
```

`desktop-electron/` 与 `cloud_service/` 各自独立，仅在需要时安装。

### 2.4 浏览器运行时

矩阵发布依赖 Patchright（Playwright 兼容发行版）：

```powershell
scripts\launchers\setup_browser.bat
```

或在 Web 控制台的 **系统设置 → 浏览器管理** 一键安装 Chromium / Firefox。

---

## 3. 代码规范

### 3.1 前端（TypeScript strict）

- `prism_frontend/tsconfig.json` 已开启 `"strict": true`；PR 前必须 `tsc --noEmit` 全绿。
- 使用函数组件 + Hooks，避免 class 组件；组件放 `src/components/`，页面放 `src/app/`（Next.js App Router）。
- ESLint 全量：`npm run lint:all`；增量（改动文件）：`npm run lint`。
- 样式使用 Tailwind CSS，禁止内联样式；自定义颜色走 `tailwind.config.ts`。
- 严禁提交 `node_modules/`、`.next/`、`.env.local`（已在 `.gitignore`）。

### 3.2 后端（Python PEP 8）

- 遵循 PEP 8；行宽 120（项目内默认）；函数命名 `snake_case`，类 `PascalCase`。
- 类型注解：公共 API / 服务函数必须写类型；内部工具函数尽力而为。
- 日志使用 `loguru`；异常处理必须记录上下文，禁止裸 `except:`。
- **禁止裸 `subprocess.run/Popen`**：CI 会检查（仅允许 `fastapi_app/utils/subprocess_safe.py` 与 `utils/process_manager.py`），请通过 `subprocess_safe` 包装。
- **禁止在代码中硬编码 API key / token / 密码**；使用 `.env` 或 `fastapi_app/config/llm_config.toml`。

### 3.3 Commit Message（Conventional Commits）

```
<type>(<scope>): <subject>

[body]

[footer]
```

**type 取值**：`feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `ci` / `build` / `perf`。

示例：

```
feat(m1): add Flux model routing
fix(backend): handle cloud unreachable fallback
docs(readme): update community vs pro table
test(m2): cover jwt expiry edge case
```

- **scope** 使用模块名：`m1`（文生图）/ `m2`（智能体）/ `m3`（积分）/ `m4`（工作流）/ `m5`（图片编辑器）/ `frontend` / `backend` / `desktop` / `cloud`。
- subject 使用祈使句、英文小写首字母，长度 ≤ 72 字符。
- 破坏性变更在 body 首行加 `BREAKING CHANGE: <说明>`。

---

## 4. 测试要求

**提交前请本地跑通下面 4 项**（与 CI 一致）：

```powershell
# 前端类型检查
cd prism_frontend; npx tsc --noEmit; cd ..

# 前端单元测试
cd prism_frontend; npx vitest run; cd ..

# 后端 M1 / M2 / M3 自运行测试（不启动服务，全 mock）
cd prism_backend
python tests/test_m1_ai_design.py
python tests/test_m2_agents.py
python tests/test_c17_subscription_tier.py   # M3 积分与订阅分层
cd ..

# Lint（前端 ESLint 全量 + 后端 ruff）
cd prism_frontend; npx eslint; cd ..
python -m ruff check prism_backend/ --select E9,F63,F7,F82
```

### 4.1 项目测试模式

- **后端测试为自运行脚本模式**：每个 `prism_backend/tests/test_*.py` 都提供 `if __name__ == "__main__": sys.exit(main())`，直接 `python tests/test_xxx.py` 运行，末尾打印 `ALL TESTS PASSED`。
- 用例之间严格隔离：每次调用 `reset_*` 恢复 mock，不污染真实 `.env` / DB / Redis。
- 不启动 FastAPI 服务、不连真实 Redis、不调真实 LLM API；全部通过 mock。
- `cloud_service/` 下脚本同样为自运行模式，`cloud_service/conftest.py` 用 `pytest_collect_file` 钩子将其包装为 pytest 用例。

### 4.2 新增测试的最小要求

- 新增/修改业务代码必须补齐对应测试；
- 单测必须能独立运行（自运行 + mock）；
- 集成测试（需外部服务）请放入 `scripts/tests/`，不要放进 `prism_backend/tests/`。

---

## 5. 分支与提交

### 5.1 分支策略

```
main            ← 生产分支，仅通过 PR 合并；tag v*.*.* 触发 release.yml
feature/<name>  ← 新功能（基于 main 切出）
fix/<name>      ← 缺陷修复
chore/<name>    ← 依赖升级 / 构建 / 脚本
docs/<name>     ← 文档
```

**命名**：小写 + 短横线，例 `feature/m1-flux-model`、`fix/douyin-abogus-timeout`。

### 5.2 提交前自查

```powershell
# 1. 格式化（可选，但推荐）
cd prism_frontend; npx prettier --write "src/**/*.{ts,tsx}"; cd ..

# 2. 单元测试
cd prism_frontend; npm test; cd ..

# 3. 类型检查
cd prism_frontend; npx tsc --noEmit; cd ..

# 4. 后端自运行测试
cd prism_backend; python tests/test_m1_ai_design.py; python tests/test_m2_agents.py; cd ..
```

### 5.3 Husky / lint-staged

仓库已配置 `husky` + `lint-staged`，提交前会自动对 `*.{js,jsx,ts,tsx}` 运行 `eslint --fix`。首次 clone 后请执行：

```powershell
npm install         # 根目录，会触发 husky prepare
```

---

## 6. PR 流程

1. 从最新 `main` 切分支：`git checkout main && git pull && git checkout -b feature/xxx`
2. 完成开发与本地测试（§4）
3. Push 分支并打开 PR，使用仓库的 `.github/PULL_REQUEST_TEMPLATE.md`
4. 至少 1 位维护者 review，CI 全绿后 squash merge

### PR Checklist

- [ ] 本地 `tsc --noEmit` / `vitest run` / M1-M2-M3 自运行测试全绿
- [ ] Commit 遵循 Conventional Commits
- [ ] UI 改动附截图 / GIF
- [ ] 关联 Issue：`Closes #<id>`
- [ ] 涉及配置变更时更新 `.env.example` 与 README
- [ ] 文档同步（README / docs/dev-reports）

---

## 7. 开发者工具中心（`/tools` 页面）

Web 控制台 `http://localhost:3000/tools` 是一键安装 / 启动 / 管理开发工具的入口，收录：

- `deepseek-harness`、`ccswitch`、`computer-use-linux`、`hermes-agent`、`persona-studio` 等 skill / MCP / 插件 / 组件；
- Hermes 技能的软启用 / 停用（在 `active/` 与 `_disabled/` 间移动，不物理删除）；
- Persona Studio dashboard 一键构建。

后端 API：`GET /api/v1/tools`、`POST /api/v1/tools/{id}/install|uninstall|launch|build|toggle`。

新增工具请同步：
1. `prism_backend/fastapi_app/.../tools_registry.py`（注册项）
2. `tools/<tool-name>/` 或 `vendor/` 下的实现
3. 本节的收录列表

---

## 8. Open Core 边界

| 层 | 归属 | 可贡献范围 |
|---|---|---|
| **Community** | 本仓库，AGPL-3.0 | ✅ 欢迎 PR：客户端、后端、Electron、Persona 集成、平台适配器、CLI、测试、文档 |
| **Pro 云端** | 官方私有仓库 / 服务 | ❌ 不公开：云端 prompt 模板、LLM API key、TikHub 数据 key、Hermes Agent 官方运行时、付费用户体系 |

**贡献指引**：

- ✅ **可贡献**：M1 文生图（provider 路由 / capabilities）、M2 智能体（配额 / LLM 抽取）、M3 积分（本地版）、M4 工作流、M5 图片编辑器、平台适配器（douyin / xhs / bilibili / kuaishou / youtube / tiktok）、Persona 集成、开发者工具中心。
- ❌ **不可贡献**：需要访问官方云端的 prompt / key / 数据回收实现。你可以提交**接口契约**或**mock 层**的 PR，但不能要求公开云端密钥。
- 🔀 **建议**：新功能默认走 Community，只有涉及云端资源、订阅门槛、数据服务时才作为 Pro 需求单提出。

**代码归属**：所有向本仓库提交的代码默认视为贡献者授权 AGPL-3.0 分发。请在 PR 中勾选 "Code of Conduct" 相关项。

---

## 9. 行为准则（Code of Conduct）

保持友善、尊重、包容。具体：

- 使用**建设性**的技术讨论；
- 尊重贡献者的名字、贡献记录与选择；
- 不使用侮辱性、歧视性、性别化、地域化语言；
- 不私聊骚扰、跟踪或威胁他人；
- 报告不当行为：邮件联系维护者或在 Issue 中 @maning636。

完整版本参见 [LINUX DO](https://linux.do/) 社区规则。

---

## 10. 联系方式

- 讨论与求助：[LINUX DO](https://linux.do/)（社区交流主阵地）
- Bug / 需求：使用仓库 Issue 模板
- 赞助：[Buymeacoffee](https://buymeacoffee.com/laihiujin3)
- 微信交流群：见 README 二维码

---

## 附录 A · 常见开发命令速查

```powershell
# 启动本地开发栈（Windows）
start.bat

# 仅后端
cd prism_backend; uvicorn fastapi_app.main:app --reload --port 7000

# 前端开发
cd prism_frontend; npm run dev

# 前端 lint / test
cd prism_frontend; npm run lint:all; npx vitest run; npx tsc --noEmit

# 后端 lint
python -m ruff check prism_backend/ --select E9,F63,F7,F82

# 后端测试（M1/M2/M3）
cd prism_backend
python tests/test_m1_ai_design.py
python tests/test_m2_agents.py
python tests/test_c17_subscription_tier.py

# Cloud Service 测试
python -m pytest cloud_service -q

# Desktop 打包
cd desktop-electron; npm ci; npx electron-builder --win --publish never
```

## 附录 B · 目录约定速查

```
prism_frontend/       Next.js 控制台（/tools、/cms、账号、任务、素材、AI 生成）
prism_backend/        FastAPI 后端 + Celery + Automation Worker
prism_backend/tests/  后端自运行测试（test_*.py）
desktop-electron/     Electron 桌面端与打包
cloud_service/        Open Core 云端参考实现（自部署 Community 用）
tools/                自托管组件（hermes-agent / persona-studio / proxies 等）
scripts/              启动 / 部署 / 集成验证脚本
docs/dev-reports/     开发过程报告（含本指南所属的开源准备报告）
```

---

**Thanks for helping make Prism-Fusion better. 🙌**
