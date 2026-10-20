# Prism-Fusion GitHub 开源发布准备报告

- 报告日期：**2026-10-19**（文件名沿用原计划日期 `2026-10-16-github-release-prep.md`，内容按今日实际生成）
- 目标：为 Prism-Fusion（老马AI工作台）AGPL-3.0 开源发布补齐 CONTRIBUTING + Issue/PR 模板 + GitHub Actions CI，最终让仓库达到 GitHub 开源社区基线标准。
- 范围：本仓库根目录 + `.github/` + `docs/dev-reports/`，**不改动任何业务代码或测试**。

---

## 1. 创建的文件清单

| 路径 | 类型 | 说明 |
|---|---|---|
| `CONTRIBUTING.md` | 新建 | 中文贡献指南（10 章 + 附录 A/B） |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | 新建 | Bug 报告表单（YAML，12 字段） |
| `.github/ISSUE_TEMPLATE/feature_request.yml` | 新建 | 功能请求表单（YAML，10 字段） |
| `.github/ISSUE_TEMPLATE/config.yml` | 新建 | Issue 配置（禁用空白 Issue，5 个 contact_links） |
| `.github/PULL_REQUEST_TEMPLATE.md` | 新建 | PR 模板（Markdown，含测试粘贴区 + Checklist） |
| `.github/workflows/ci.yml` | **修改** | 新增 `frontend-lint-test`、`backend-selftest` 两个硬门 job |
| `.github/workflows/release.yml` | 未改动 | 现有实现已完备（tag v* 触发 Win/Mac 双平台打包 + Release） |
| `README.md` | **修改** | 目录新增「贡献与开源」条目、正文补 CONTRIBUTING 链接 |
| `docs/dev-reports/2026-10-16-github-release-prep.md` | 新建 | 本报告 |

共 **7 个新文件 + 2 个修改文件**，未触碰业务代码。

---

## 2. CONTRIBUTING.md 摘要

10 章 + 附录：

1. **快速开始**：fork → clone → 建 `prismenv` → `start.bat`
2. **开发环境搭建**：
   - 基础依赖矩阵（Node 20 / Python 3.11 / Redis 7 / Electron）
   - `prismenv` 虚拟环境（Windows `Scripts/`、macOS `bin/`）
   - 前端 `npm ci`
   - 浏览器运行时 `scripts\launchers\setup_browser.bat`
3. **代码规范**：
   - 前端 TypeScript strict（`npm run lint:all` + `tsc --noEmit`）
   - 后端 Python PEP8（ruff，禁止裸 `subprocess.run/Popen`）
   - Conventional Commits（`feat(m1): xxx` / `fix(backend): xxx`，scope 覆盖 M1-M5）
4. **测试要求**：明确 4 项必跑：`tsc --noEmit` / `vitest run` / `python tests/test_m1_ai_design.py` 等 M1-M2-M3 自运行脚本 / ruff + eslint
5. **分支策略**：`main` / `feature/*` / `fix/*` / `chore/*` / `docs/*`
6. **PR 流程**：基于 `.github/PULL_REQUEST_TEMPLATE.md`，1 位维护者 review + CI 全绿 → squash merge
7. **开发者工具中心**：`/tools` 页面与后端 API 列表
8. **Open Core 边界**：Community 可贡献清单 vs Pro 云端（prompt / key / 数据）不可贡献
9. **行为准则**：简短版 Code of Conduct，指向 LINUX DO 社区
10. **联系方式**：LINUX DO / Buymeacoffee / 微信交流群

附录：常见命令速查 + 目录约定。

---

## 3. Issue / PR 模板设计

### 3.1 Issue 模板

**`.github/ISSUE_TEMPLATE/bug_report.yml`** — Bug 报告

- 提交流程：预检 checkbox（查重 / 最新版本） → 概述 → 复现步骤 → 期望 / 实际 → 日志 → 版本（Community / Pro / Desktop）→ 操作系统 → 模块 → 敏感凭据脱敏声明
- 关键字段：`edition`（Community/Pro/Desktop）、`module`（M1-M5 + 平台适配器 + Persona + 前端/后端/桌面/部署）
- 强制脱敏勾选，防 API Key 泄露

**`.github/ISSUE_TEMPLATE/feature_request.yml`** — 功能请求

- 场景 / 问题 → 期望方案 → 替代方案 → 涉及模块 → **建议归属（Community / Pro / 混合 / 不确定）** → 参与意愿 checkbox（愿意提交 PR / 提供设计稿 / 仅提供需求）
- 建议归属字段直接服务 Open Core 判断，减少维护者来回追问

**`.github/ISSUE_TEMPLATE/config.yml`** — Issue 配置

- `blank_issues_enabled: false`
- 5 个 contact_links：Discussions / LINUX DO / 部署文档 / 贡献指南 / 开发报告

### 3.2 PR 模板

**`.github/PULL_REQUEST_TEMPLATE.md`** — Markdown 格式

- **改动描述**（1-3 句话）
- **改动类型**（feat / fix / docs / refactor / test / chore / ci / perf / breaking）
- **涉及模块**（M1-M5 + 平台适配器 + Persona + 代理 + /tools + 前端 + 后端 + Electron + Cloud Service + 部署）
- **测试结果**：代码块直接粘贴命令输出（**不是**勾选框，强制粘贴真实结果）
- **截图 / 录屏**
- **关联 Issue**：`Closes #<id>`
- **Checklist**：11 项（本地测试、代码规范、Conventional Commits、文档更新、截图、测试覆盖、无硬编码 secret、未泄露凭据、未触及 Pro 云端）
- **Reviewer 提示**：M1/M2/M3 后端测试、UI 深色/浅色主题、配置同步 `.env.example`

---

## 4. CI 流程设计

### 4.1 结构总览（`.github/workflows/ci.yml`）

触发：`push`（tags-ignore `v*`）/ `pull_request` / `workflow_dispatch`（可选 e2e-packaged）。
并发：`prism-ci-${{ github.ref }}`，`cancel-in-progress: true`。

| Job | 门类型 | 作用 | 依赖 / 关键步骤 |
|---|---|---|---|
| `python-smoke` | 硬门 | `py_compile` 全后端 + 关键模块 import 烟测 + 禁止裸 `subprocess.run/Popen` + `.env.example` 无遗留字段 | Python 3.11，最小依赖；`working-directory: prism_backend` |
| `lint` | 硬门 | ruff 最小规则集 `E9,F63,F7,F82`（`prism_backend/`） | `--extend-exclude` 排除 `dist-build/node_modules/prismenv` 等 |
| `lint-frontend` | 硬门 | ESLint 全量（`npm run lint:all`） | Node 20 + npm ci，`working-directory: prism_frontend` |
| **`frontend-lint-test`** | **硬门（新增）** | `npx tsc --noEmit` + `npx vitest run` | Node 20 + npm ci 缓存；`working-directory: prism_frontend` |
| **`backend-selftest`** | **硬门（新增）** | M1 / M2 / M3 自运行脚本测试 | Python 3.11，`requirements.txt` + `requirements-dev.txt`；`working-directory: prism_backend`；逐个跑 `python tests/test_m1_ai_design.py` / `test_m2_agents.py` / `test_c17_subscription_tier.py` |
| `test` | 软门（保留） | `pytest fastapi_app/tests/`，`continue-on-error: true` | 等待测试隔离补齐后转硬门 |
| `cloud-service-tests` | 硬门（原有） | `pytest cloud_service`（5 自运行脚本 → 177 check） | 轻量 pip 依赖，无 selenium/patchright |
| `e2e-packaged` | 软门（手动触发） | Windows self-hosted runner 上跑打包产物烟测 | `workflow_dispatch` + `run_e2e_packaged: true` |

### 4.2 关键设计选择

- **自运行脚本 vs pytest**：项目测试模式是 `python tests/test_xxx.py` 直接运行 + `if __name__ == "__main__": sys.exit(main())` 断言返回 0。新增 `backend-selftest` job 尊重这一模式，`continue-on-error: false`（硬门），失败即阻塞。
- **依赖缓存**：
  - 前端：`cache: npm` + `cache-dependency-path: prism_frontend/package-lock.json`
  - 后端：`cache: pip` + 双依赖文件 `requirements.txt` / `requirements-dev.txt`
- **`working-directory`**：所有前端步骤显式 `prism_frontend`，所有后端自运行测试显式 `prism_backend`。
- **Node 20 / Python 3.11**：与本地 `prismenv` 打包版本、`desktop-electron` CI 一致。
- **不动 release.yml**：现有 `release.yml` 已覆盖 Windows NSIS + macOS dmg/zip 打包、版本号自动同步、GitHub Release 发布，无遗漏。

### 4.3 变更差异

- 新增 2 个 job：`frontend-lint-test`（硬门）、`backend-selftest`（硬门）
- 保留 6 个原有 job，仅微调 `test` job 名字为 `Pytest (backend tests, soft)` 以明示软门身份
- 顶部注释块重写为分层说明（硬门 / 软门 / 缓存策略）
- 无破坏性变更：原有软门 `test`、`e2e-packaged` 保持不变，`continue-on-error` 行为不变

### 4.4 校验

已用 `prismenv\Scripts\python.exe -c "import yaml; yaml.safe_load(...)"` 对所有 YAML 做语法校验：

```
ci.yml OK
release.yml OK
bug_report.yml OK
feature_request.yml OK
config.yml OK
```

---

## 5. README 检查结果

| 项 | 状态 | 位置 / 备注 |
|---|---|---|
| 快速开始步骤清晰 | ✅ | L8-L18，5 步流程 + Community/Pro 一句话区分 |
| Community vs Pro 对比表 | ✅ | L22-L45，16 行对比 + 一句话总结 |
| 定价表 | ✅ | L47-L54，Community / Pro / Team 三档 |
| 部署步骤（Windows / macOS / PM2 / 一键 start.bat） | ✅ | L306-L456，覆盖本地、Supervisor、PM2、CLI 四种方式 |
| 命令行 / API 示例 | ✅ | L458-L556 |
| 合规提示 | ✅ | L571-L575 |
| License（AGPL-3.0）声明 | ✅ | L592-L603（含 AGPL 选择理由 + 与 Apache 兼容说明 + 云端服务边界） |
| NOTICE.txt / VENDOR.md 引用 | ✅ | L588 |
| LINUX DO 社区 | ✅ | L605-L609 |
| **CONTRIBUTING 链接** | ✅ **本次新增** | 目录 + 快速开始段落 + 新增「贡献与开源」章节，指向 CONTRIBUTING / `.github/PULL_REQUEST_TEMPLATE.md` / `.github/ISSUE_TEMPLATE/` / `.github/workflows/ci.yml` / `.github/workflows/release.yml` |

**本次 README 变更**：
1. 目录新增 `[贡献与开源](#贡献与开源)` 条目
2. 快速开始段落末尾追加 `；参与开发请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)`
3. 「感谢 LINUX DO」下方新增「贡献与开源」章节，覆盖开发环境 / 代码规范 / 测试 / 分支 / 模板 / CoC / Open Core 边界 + CI / Release 工作流位置

其他内容**未修改**，避免无关重构。

---

## 6. 开源发布 checklist（还差什么）

### ✅ 已就绪

- [x] `LICENSE`（AGPL-3.0，之前 Open Core 拆分时创建）
- [x] `NOTICE.txt` + `vendor/VENDOR.md`（上游 MIT / Apache-2.0 归属）
- [x] `README.md`（快速开始 + Community/Pro + 部署 + 命令行 + API + 架构 + 合规 + 贡献）
- [x] `CONTRIBUTING.md`（本次新增）
- [x] `.github/ISSUE_TEMPLATE/`（bug / feature / config）
- [x] `.github/PULL_REQUEST_TEMPLATE.md`
- [x] `.github/workflows/ci.yml`（8 个 job，6 硬门 + 2 软门）
- [x] `.github/workflows/release.yml`（Win + macOS 打包 + GitHub Release）
- [x] `docs/dev-reports/`（26 份历史开发报告）
- [x] `docs/demos/prism_wrap.gif` / `prism_hyperframes_demo.gif`（README 引用）
- [x] `prism-qq-group-qr.jpg`（微信群二维码）
- [x] 后端 M1 / M2 / M3 自运行测试（后端硬门 CI）
- [x] 前端 tsc + vitest + ESLint（前端硬门 CI）
- [x] Cloud Service 5 脚本 pytest 包装（177 check）

### ⚠️ 建议后续补齐（非阻塞）

- [ ] **`CODEOWNERS`**：未创建。建议指定 `@laihiujin` 为根目录 owner，`@team-frontend`（未来）为 `prism_frontend/`，`@team-backend` 为 `prism_backend/`。
- [ ] **`SECURITY.md`**：未创建。当前 `.env.example` 已无 `FLASK_*` 遗留字段（CI 硬门守），但缺失安全披露渠道；建议添加 `private` 邮件 / 漏洞响应 SLA。
- [ ] **`.github/CODE_OF_CONDUCT.md`**：本次在 CONTRIBUTING 中做了简短版，未单独提 `.github/CODE_OF_CONDUCT.md`（GitHub UI 会显示 CoC badge）。如需 GitHub UI 高亮，建议单独成文。
- [ ] **`.github/dependabot.yml`**：未创建。建议对 `npm` / `pip` / `github-actions` 三种生态开 weekly 依赖更新 PR。
- [ ] **徽章（badges）**：README 顶部无 CI / coverage / license badge，可在开源发布前加上：
  ```markdown
  [![CI](https://github.com/Laihiujin/Prism/actions/workflows/ci.yml/badge.svg)](https://github.com/Laihiujin/Prism/actions/workflows/ci.yml)
  [![Release](https://github.com/Laihiujin/Prism/actions/workflows/release.yml/badge.svg)](https://github.com/Laihiujin/Prism/releases)
  [![AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
  ```
- [ ] **仓库元信息**（在 GitHub 设置页配置，非文件）：
  - Topics：`ai` / `social-media` / `matrix-publish` / `fastapi` / `nextjs` / `electron` / `persona` / `agpl-3.0`
  - About：一句话简介 + 主语言 + 首页链接
  - Releases 页面首次 tag（如 `v0.4.0`）触发 `release.yml`
- [ ] **`test` job 转硬门**：`fastapi_app/tests/` 目前软门，待 conftest 与运行时解耦后移除 `continue-on-error`。
- [ ] **社区入口**：LINUX DO 板块建立 + Discussions 启用（当前 README 已引用，但 Discussions tab 需在仓库设置中显式开启）。

### 🔒 需要注意的开源红线

- **Pro 云端实现**：`cloud_service/` 是官方自部署 Community 参考，**生产环境的 prompt 模板 / LLM key / TikHub 数据 key / Hermes Agent 官方运行时** 必须保持不公开（CONTRIBUTING §8 已声明）。发布前建议对 `cloud_service/` 做一次 secret 扫描（`gitleaks` / `truffleHog`）。
- **测试数据**：`prism_backend/tests/` 全部 mock，不携带真实 API Key；`prism_backend/config/llm_config.toml.example` 中占位符必须为 `changeme` / `sk-example` 类，不能是真实 key。
- **依赖清单**：`requirements.txt` / `package-lock.json` / `pnpm-lock.yaml` 均为上游官方发布版本，无内部私有源。

---

## 7. 剩余不确定性

1. **`frontend-lint-test` 首次运行的通过性**：CI 中 `npm ci` + `npx tsc --noEmit` + `npx vitest run` 组合未在 GitHub Actions 上跑过。历史上 `tsc.out2` 存在于仓库根，暗示此前有过类型问题；如果首次 CI 红，需要先本地 `npx tsc --noEmit` 排查是否 `.next/types` 未生成导致的误报。
2. **`backend-selftest` 依赖 `requirements.txt` 安装耗时**：`requirements.txt` 覆盖生产全依赖（含 `celery` / `patchright` / `sqlalchemy` 等），pip install 可能需要 5-10 分钟；如后续需要提速，可以拆一份 `requirements-test.txt` 只包含测试依赖。
3. **`test` job 软门转硬门时机**：需 SaaS 化改造补齐 conftest 隔离后转硬门；本次不做，避免 CI 全线红。
4. **仓库 remote**：任务描述提到 `Laihiujin/Prism.git` 与 `prism-server` 分叉。本次报告未处理 git 侧；开源发布前需要：
   - 在 GitHub 建仓 / fork，确认目标仓库
   - 清理 `.git/config` 中的 token
   - 首次 push 前跑一次 `git log --all --grep=` 确认无内部 commit message 泄露
5. **CI 运行时间估算**：目前 6 个硬门 job 并行，估算 8-12 分钟；后续如引入端到端打包测试（`e2e-packaged`）需 self-hosted Windows runner，成本较高，建议保持 `workflow_dispatch` 手动触发。

---

## 附录 · 变更文件哈希清单（便于回滚）

```
CONTRIBUTING.md                                          (新增, ~11KB)
.github/ISSUE_TEMPLATE/bug_report.yml                    (新增)
.github/ISSUE_TEMPLATE/feature_request.yml               (新增)
.github/ISSUE_TEMPLATE/config.yml                        (新增)
.github/PULL_REQUEST_TEMPLATE.md                         (新增)
.github/workflows/ci.yml                                 (修改：新增 frontend-lint-test + backend-selftest)
README.md                                                (修改：目录 + 快速开始 + 贡献与开源章节)
docs/dev-reports/2026-10-16-github-release-prep.md      (新增，本报告)
```

**未改动**：所有业务代码、测试代码、`release.yml`、`.env.example`、`requirements*.txt`、`package-lock.json`、`.husky/`、`vendor/`。
