# 工程手册 · ENGINEERING PLAYBOOK

> 来源：Prism-Fusion 项目（`D:\dim开发\Prism-Fusion`）11 个月工程实践中沉淀的可复制工程体系。
> 目标读者：接手本仓库的工程师与 AI Agent；要把这套体系迁移到**新项目**的团队。
> 阅读方式：先扫 §1 三支柱建立心智，再按章查机制与检查单；新项目直接跳到 §9 与 `NEW-PROJECT-KIT/`。

---

## §1 工程三支柱（一句话总纲）

这套工程体系只有三根柱子。所有具体机制（gitignore 纪律、硬门、roundtrip、AGPL 义务履行……）都挂在其中一根上面。

### 1.1 干净的施工环境

**定义**：仓库只装该装的东西，运行时数据绝不入库；依赖、缓存、目录落盘位置有明确规范；一台新机器按最短路径能从 clone 走到「能跑测试」。

**本项目机制清单**：
- `.gitignore` 覆盖 17 类运行时目录（`.env` / `*.db` / `*.sqlite*` / `logs/` / `_caches/` / `_appdata_electron/` / `prism_backend/cookiesFile/` / `prism_backend/browser_profiles/` / `prism_backend/fingerprints/` / `data/analytics/` / `data/crawler_output/` / `data/videos/` / `runtime-data/` / `dump.rdb` 等）。
- `AGENT.md` 的 Repo Hygiene / Push Rules / Local-Only Data 三段是**唯一权威**：`git add -A` / `git add .` / `git stash` / `git reset --hard` / `git checkout ./` / `git clean` / `git push --force` / `git commit --no-verify` 全部禁用。
- `scripts/tests/check_requirements_cover_imports.py` 是依赖声明闸门：扫描 `prism_backend/` 下的模块级第三方 import，与 `requirements*.txt` 声明对齐，并带 `--self-test` 反向自测。
- 缓存落盘规范：全部落 `D:\cache\` 与项目内 `_caches/`，严禁写 C 盘；npm / pip / TEMP / PyInstaller / Electron 的缓存目录都通过环境变量重定向。
- `bootstrap` 最短路径写在 `STARTUP.md` 与 `scripts/`：`D:\dev\python\python.exe` → `pip install -r requirements.txt` → `pip install -r requirements-dev.txt` → `cd prism_frontend && npm ci` → `pytest prism_backend/fastapi_app/tests/`。

**复制检查单**：
- [ ] 有 `.gitignore`，覆盖所有已知运行时目录
- [ ] 有 `AGENT.md`，至少含 Repo Hygiene + Push Rules + Local-Only Data 三段
- [ ] 有依赖声明闸门，且带反向自测
- [ ] 缓存目录明确写在规范里，不落在 C 盘
- [ ] 有 bootstrap 文档，「clone → 跑通测试」≤ 10 步

### 1.2 可追溯可更新的知识体系

**定义**：每个决策能找到出处，每个事实能追到证据；文档与代码不漂移；AGENTS.md 作为 AI 与人共用的上下文契约。

**本项目机制清单**：
- 文档分层五类：口径唯一权威（`README.md` / `CONTRIBUTING.md` / `LICENSE` / `NOTICE.txt`）、交接（`docs/handover/PROJECT-HANDOVER.md` / `HANDOFF.md`）、坑清单（`docs/handover/PROJECT-HANDOVER.md` §8，60+ 条编号坑）、开发报告（`docs/dev-reports/` 按日期）、决策台账（`docs/handover/PROJECT-HANDOVER.md` §4，11 条 P#/D# 编号决策）。
- 防漂移工具化：`scripts/docs/` 的 **build/read/roundtrip** 三件套。`build_sprint_acceptance.py` 生成 `docs/handover/SPRINT-ACCEPTANCE-R1R2.md`，`read_sprint_acceptance.py` 回读并拒识坏行，`test_sprint_acceptance_roundtrip.py` 断言全字段往返一致 + 反向自测。
- 证据分级三档：`【已验证】`（有日期与命令实测）/ `【已确认】`（口径拍板）/ `【推测】`（方案判断）。同一章节里混用是允许的，但**必须显式标注**，不允许把「推测」写成「事实」。
- `AGENT.md` 作为 AI 上下文契约，Hermes 每次会话通过 `DEFAULT_PRELOAD_SKILL`（`prism_backend/fastapi_app/agent/hermes_agent.py`）预加载 `docs/hermes-skills/prism-project-layout/SKILL.md`。

**复制检查单**：
- [ ] 有 README / CONTRIBUTING / LICENSE / NOTICE / SECURITY 五件套
- [ ] 有 HANDOVER / 坑清单 / dev-reports / ADR 四栏文档
- [ ] 关键表结构（验收表、决策表）有 build+read+roundtrip 三件套
- [ ] 决策按 P#/D# 编号入台账，每条含「为什么 + 否掉了什么 + 代价」
- [ ] 有 AGENTS.md，明确 AI 与人共用

### 1.3 可验证可自动化的测试拦截

**定义**：任何改动都被自动化测试拦在 merge 之前；有硬门、有软门、有失败教训。

**本项目机制清单**：
- 8 硬门（`.github/workflows/ci.yml`）：`python-smoke` / `lint` / `lint-frontend` / `frontend-lint-test` / `backend-selftest` / `cloud-service-tests` / `deps-gate` / `test`。
- 1 软门（默认 skip）：`e2e-packaged`，`continue-on-error: true`，只在 `workflow_dispatch` 手动触发时执行。
- TDD 红→绿证据：测试先写、断言先红、修复后转绿，保留 commit 对偶。
- 评审闭环：实现 → 评审 → 修复 → 复审，四段证据链落 `.superpowers/sdd/` 或 `docs/dev-reports/`。

**复制检查单**：
- [ ] 至少 4 个硬门（lint / test / deps-gate / security）
- [ ] 每个 gate 有反向自测（证明不是「永远 OK」的假闸门）
- [ ] TDD 有红绿证据留存
- [ ] 评审走「实现→评审→修复→复审」四步闭环

---

## §2 环境即代码

### 2.1 Gitignore 纪律

**原则**：GitHub 只装源码、文档、脱敏示例、构建脚本。运行时数据一律不进。

**本项目的运行时目录清单**（`AGENT.md` 的 Local-Only Data 段是唯一权威，共 17 类）：
- 凭据与配置：`.env` / `*.env.local`
- 数据库：`*.db` / `*.sqlite*` / `dump.rdb`
- 爬虫/账号资产：`prism_backend/cookiesFile/` / `config/cookiesFile/` / `prism_backend/browser_profiles/` / `config/browser_profiles/` / `prism_backend/fingerprints/`
- 运营数据：`prism_backend/data/ip_pool*.json` / `prism_backend/data/account_stats*.json` / `prism_backend/data/campaigns.json` / `prism_backend/data/published_works.json` / `data/analytics/` / `data/crawler_output/` / `data/videos/`
- 日志与临时：`logs/` / `prism_backend/logs/` / `tmp-runtime-data/`
- 缓存/本地 AppData：`_caches/` / `_appdata_electron/` / `_appdata_laoma_bid/` / `_electron_userdata/` / `_electron_userdata_packaged/`
- Pro 独占资源（Pro 打包注入，不进开源树）：`cloud_service/llm_proxy/_pro_assets/`（由 `.gitignore:318` 排除，注入方式见 `scripts/cloud/inject_pro_assets.py`）

**修法**：
- 需要给文档用的示例文件，一律 `.example.*` 后缀（如 `.env.example`）。
- 已误入 Git 的运行时文件：`git rm --cached <path>` + 补 `.gitignore` 规则；**绝不用** `git reset --hard` / `git clean`。
- 每次提交前 `git status --short`，看到运行时文件即停。

### 2.2 依赖声明闸门（deps-gate）

**原理**：`scripts/tests/check_requirements_cover_imports.py` 做两件事：
1. **正向**：扫描 `prism_backend/**/*.py` 的模块级 `import X` / `from X import Y`，剔除标准库、自身子包、已知本地扩展后，与 `requirements.txt` / `requirements-dev.txt` 里的声明对齐，未声明即报错。
2. **反向自测（`--self-test`）**：逐个删掉候选包的声明，要求它们必须被重新报出来。如果删了还报 OK，说明闸门**失灵**（被本地目录影子污染），job 直接红。

**为什么必须反向自测**：坑 C4 —— 打包产物里整份拷贝的第三方包目录会形成本地目录影子，闸门「永远返回 OK」。反向自测是唯一能证明它不是假闸门的办法。

### 2.3 缓存落盘规范

**规范**：npm / pip / TEMP / PyInstaller / Electron 的缓存全部落 D 盘（`_caches/` 或 `D:\cache\`），**严禁写 C 盘**。CI 缓存按依赖类型分流（`npm` → `prism_frontend/package-lock.json`，`pip` → `requirements.txt` + `requirements-dev.txt`）。

**为什么**：C 盘是系统盘，容量小、IO 慢、易污染；打包产物动辄数 GB，写 C 盘会让打包在低空闲时直接 OOM（坑 W12：Next.js 生产构建报 `Zone Allocation failed`，本机总 15.25 GB，空闲 <2 GB 时必现）。

### 2.4 Bootstrap 最短路径

**目标**：clone 完 → 能跑通测试，不超过 10 步。

**本项目路径**：
1. `git clone` + `git submodule update --init --recursive`
2. 装 Python 3.11+（`D:\dev\python\python.exe`，独立解释器不污染系统）
3. `python -m pip install --upgrade pip`
4. `python -m pip install -r requirements.txt`
5. `python -m pip install -r requirements-dev.txt`
6. `cd prism_frontend && npm ci`（Node 22 硬性下限）
7. `cd desktop-electron && npm ci`
8. `pytest prism_backend/fastapi_app/tests/`（第一步「跑通」信号）
9. `pytest cloud_service`（自运行脚本包装）
10. `python scripts/tests/check_requirements_cover_imports.py --self-test`

**规范**：bootstrap 文档必须写「前置条件 → 依赖安装 → 环境自检 → 第一个测试运行」四段，每段可复跑命令。

---

## §3 版本与发布管理

### 3.1 单 main + tag 发版模型

**原则**：只有一个长期分支 `main`；`git push origin main`；`git push origin v<version>` 触发发版。CI 对分支全放开，`tags-ignore: ['v*']` 让发版 tag 走 `release.yml` 而不是主 CI。发版并发控制：`concurrency: prism-release-${{ github.ref }}`，`cancel-in-progress: false`。

### 3.2 版本号单一真源

**原则**：版本号只有一处真值。本项目真值是 `desktop-electron/package.json` 的 `version` 字段，tag 与资产名一致，云端地址也是单一真值 `laomaCloudUrl`（`release.yml` 与 `scripts/packaging/resolve_cloud_url.ps1` 读同一个字段）。

**流程**：
- tag 触发 `v<version>` → workflow 自动把 `desktop-electron/package.json` 的 `version` 同步为该值。
- 手动触发（`workflow_dispatch`）填 version 则同步，留空则用当前版本。
- 资产名纯 ASCII（`LaomaAI-${version}-setup.${ext}`）—— 中文触发 `isSafeGithubName` 正则不过（坑 P2）。

### 3.3 CHANGELOG 纪律

**原则**：每条必须可溯源到日期 + commit 或 PR。禁止编造「未实施的功能」。

**格式**（`CHANGELOG.md`）：`## [版本] - YYYY-MM-DD` + 分类条目（Added / Changed / Fixed / Removed / Docs），每条引用 commit 或 PR 号。

### 3.4 发版守卫

**体积下限守卫**（`.github/workflows/release.yml` `build-windows`）：安装包 ≥ 400 MB（419430400 B），防 CI 静默打出空壳包。一旦 `build_services.ps1` 抛错未 fail 或被跳过，装包会掉到 200 MB 左右，此步直接 fail。

**产物校验**（`desktop-electron/scripts/verify-release-assets.mjs`）：验证版本号、资产齐全（`.exe` / `.blockmap` / `latest.yml`）、哈希匹配。

**已发布防覆盖**（`check` job）：
```bash
if gh release view "$TAG" >/dev/null 2>&; then
  echo "Release $TAG already exists - skip rebuild."
  echo "should_build=false" >> "$GITHUB_OUTPUT"
fi
```
tag 已被手工发布过（资产已验收）时不再重复打包，避免 CI 用未验收产物覆盖已验收资产。

### 3.5 回退路径

**原则**：不发新包替换，做「镜像并存 + superseded 标记」。

**做法**：
- GitHub Release 保留历史版本，不删。
- 自建下载通道保留旧版 `latest.yml` 备份。
- 官网下载页指向最新 tag，旧版可手动访问。
- 版本被 supersede 时在 CHANGELOG 里显式标注，不做物理删除。

**教训**：坑 P3（`latest.yml` 里名字对不上，1.1.4 时代老 bug）—— 版本号匹配不精确，旧包残留导致静默发错包。修法：打包脚本按版本号精确匹配。

---

## §4 知识管理体系

### 4.1 文档分层

| 层 | 职责 | 本项目实例 |
|---|---|---|
| 口径唯一权威 | 产品定位、边界、协议 | `README.md` / `CONTRIBUTING.md` / `LICENSE` / `NOTICE.txt` / `SECURITY.md` |
| 交接 | 从一个人到另一个人的完整交接 | `docs/handover/PROJECT-HANDOVER.md` / `HANDOFF.md` / `docs/handover/DELIVERY-CHECKLIST.md` |
| 坑清单 | 实际踩过的坑，编号 + 现象 + 根因 + 修法 | `docs/handover/PROJECT-HANDOVER.md` §8（60+ 条） |
| 开发报告 | 按日期记录 | `docs/dev-reports/` |
| 决策台账 | 每条架构决策 | `docs/handover/PROJECT-HANDOVER.md` §4（P1–P7、B2、D4、单一客户端、支付删除） |
| 验收表 | 冲刺验收 | `docs/handover/SPRINT-ACCEPTANCE-R1R2.md` |

### 4.2 防漂移机制：roundtrip 工具化

**本项目样板**：`scripts/docs/` 下的 build / read / roundtrip 三件套：
- `build_sprint_acceptance.py` 生成 `docs/handover/SPRINT-ACCEPTANCE-R1R2.md`。
- `read_sprint_acceptance.py` 回读该 md，`strict` 校验列数、枚举值、编号重复、组计数；坏行直接抛 `ValueError`。
- `test_sprint_acceptance_roundtrip.py` 断言：build→read 全字段往返一致；注入验收结果（pending→passed）后统计正确升级；**反向自测**：篡改数据列后 read 必须报出差异；坏表拒识。

**转义约定**：单元格里的 `\` → `\\`，`|` → `\|`；read 侧按同一规则还原，roundtrip 测试据此断言逐字段一致。

**核心原则**：
- 数据源单一化：改验收项改脚本，不要手改生成的 md。
- 状态列是唯一允许人工编辑的列。
- Reader 是收工闸门，宁可报错也不能「永远输出 OK」。

### 4.3 证据分级三档

同一章节里三档可混用，但**必须显式标注**：

| 档位 | 语义 | 使用场景 |
|---|---|---|
| 【已验证】 | 有命令实测 + 日期 + 输出 | 「2026-10-24 实测：本地 HEAD = c24a11d」 |
| 【已确认】 | 有口径拍板（决策台账条目） | 「P7=B 拍板：不给密钥 → 显式关掉依赖平台密钥的能力」 |
| 【推测】 | 方案判断、未实测 | 「预计切换到 GitHub provider 后国内用户下载耗时增加 X 分钟」 |

**禁止**：把推测写成事实；把已确认写成已验证。

### 4.4 AGENTS.md 作为 AI 上下文契约

**内容**：
- 项目布局唯一权威源（`docs/hermes-skills/prism-project-layout/SKILL.md`）
- Repo Hygiene / Push Rules / Interface Border Rule
- Local-Only Data 目录清单

**机制**：`prism_backend/fastapi_app/agent/hermes_agent.py` 的 `DEFAULT_PRELOAD_SKILL` 让 Hermes 每次会话默认预加载该技能；`hermes_config.py::sync_prism_project_skill()` 由 Hermes 会话准备时自动同步到 `tools/hermes-home/` 与 `runtime-data/app/hermes-home/`（后两者在 `.gitignore` 内）。

**纪律**：只编辑源文件，派生位置由脚本同步、不入版本库。

---

## §5 质量门禁体系

### 5.1 8 硬门总表

以下所有硬门定义来自 `.github/workflows/ci.yml` 头注，逐条含「拦什么 / 修法 / 失败教训」：

| # | 门名 | 拦什么 | 失败教训 / 修法 |
|---|---|---|---|
| 1 | `python-smoke` | 语法错 + 模块级 import 失败 + subprocess 白名单越界 + `.env.example` 遗留字段 | 最小依赖下 import 关键模块（`fastapi_app.core.config` / `paths` / `utils.subprocess_safe`），失败即视为 CI 失败；`.env.example` 快速校验 `FLASK_PORT` / `UPLOAD_FOLDER` / `MAX_CONTENT_LENGTH` 等遗留字段 |
| 2 | `lint` | 后端语法/致命错误 + 常见 NameError | ruff 最小规则集 E9/F63/F7/F82；`--extend-exclude 'dist-build,node_modules,prismenv,build,dist,.venv,__pycache__,hermes-agent'` |
| 3 | `lint-frontend` | 前端 ESLint 全量 | `npm run lint:all`；CI 跑全仓、pre-commit 只看变更文件 |
| 4 | `frontend-lint-test` | 前端 tsc + vitest | Node 22 硬性下限 —— jsdom 30.1.3 内嵌 undici 8.12.3，`engines` 要求 node ≥ 22.19.0；Node 20 下 6 个 DOM 测试文件全挂（坑 C2） |
| 5 | `backend-selftest` | 后端 M1/M2/M3 自运行脚本 | `python tests/test_m1_ai_design.py` / `test_m2_agents.py` / `test_c17_subscription_tier.py`，末尾打印 `ALL TESTS PASSED` |
| 6 | `cloud-service-tests` | `cloud_service/` 下 5 个自运行脚本 | `cloud_service/conftest.py` 用 `pytest_collect_file` 钩子把每个脚本包装成 pytest 用例；必须传**目录**不能传单文件，否则 `0 items` exit 5（坑 C3） |
| 7 | `deps-gate` | 依赖声明与 import 不一致 | 见 §2.2；**必须带 `--self-test` 反向自测**，否则是假闸门（坑 C4） |
| 8 | `test` | 后端 pytest 接口测试 + license 护栏 | 2026-10-23 从软门转硬门。转硬门前必须补齐六个坑：`cryptography` 声明 / `test_core` 陈旧断言 / `test_data` 陈旧接口 / `test_hermes_config` monkeypatch 目标 / `conftest` Windows 文件锁 / license 护栏覆盖。**不再加 `-x`**，一次把全部失败打出来 |

### 5.2 软门

`e2e-packaged`：默认 skip；`continue-on-error: true`；`workflow_dispatch` 且 `run_e2e_packaged=true` 时才跑；需要 self-hosted Windows runner + 真实打包产物（`dist-out\v*\win-unpacked`）。

### 5.3 TDD 红→绿证据

**规范**：
- 测试先写、断言先红、修复后转绿。
- 保留 commit 对偶（红 commit 与绿 commit 的 diff）。
- 测试文件命名 `test_{phase}_{module}.py`（如 `test_c17_subscription_tier.py`）。

**防假通过原则**：
- 验证改写/覆盖的那条路径时，用**只有它能产生的值**（专用变量名、专用 id、专用色值）。
- 断言要能区分「这条路径生效」与「别的路径顺便生效」（坑 V1）。
- 断言写成上下文敏感形态：`/控制在\s*\d{3,}/` 而不是「正文里不能出现『控制在』」（坑 V2）。

### 5.4 评审流：实现 → 评审 → 修复 → 复审

**闭环四段证据链**：
- **实现**：commit 里附自运行测试 / pytest 通过截图或命令输出。
- **评审**：评审意见落到 `.superpowers/sdd/valkyrie-gamora-big-barda/*.review.md` 或 `docs/dev-reports/`。
- **修复**：commit 里 `Fixes: <review-id>` 或引用评审条目编号。
- **复审**：修复后的评审结论，同样落文档。

**AI 评审纪律**：AI 评审意见按「技术成立 / 不成立」判定，不按「礼貌性」判定。技术性质疑要求 reviewer 给出证据链，不接受「感觉」类反馈。

---

## §6 安全与合规

### 6.1 仓库卫生十禁

以下一律**不提交、不推送**（`AGENT.md` Repo Hygiene）：
1. 真实账号数据（Cookie / 浏览器 profile / 指纹）
2. 代理 IP 池数据
3. 生产日志
4. 本地数据库（`*.db` / `*.sqlite*` / `dump.rdb`）
5. 运行时产物（`dist/` / `dist-out/` / `_appdata_*/`）
6. 原始账号标识（用户名 / ID / 手机 / 邮箱）
7. 凭据值（API key / secret / token / password）
8. 本机绝对路径（如 `D:\Users\...`）
9. 截图 / 复制的调试输出中含上述任一项
10. 任何被 Git 误跟踪后的 `git add -A` / `git stash` / `git reset --hard` / `git push --force` / `git commit --no-verify`

**commit message 纪律**：扫一遍 diff 里的路径与账号标识，禁止把本机绝对路径、账号名、Cookie 值写进 message / PR 描述 / 截图。

### 6.2 凭据管理

**原则**：凭据只在**位置**上存在，不进库。

**做法**：
- 仓库里只放 `.env.example` / `env.example`，字段脱敏。
- `.env` 本身进 `.gitignore`。
- 服务器凭据（`/opt/prism-fusion/` 下）由 systemd `EnvironmentFile=` 加载。
- GitHub Secrets 存 Apple 证书 / npm token / PyArmor license。

### 6.3 Secret 与依赖扫描

- **Secret 扫描**：见 `.github/workflows/security.yml`（gitleaks + 依赖审计），由另一子智能体在建。落地后作为第 9 硬门。
- **依赖安全扫描**：`safety check -r requirements.txt`（Python）/ `npm audit --omit=dev`（Node）；CI 里高危即 fail。
- **本地扫描命令**：`grep -rE '(sk-|ghp_|api_key|password).*=[^*]' .`（PLAN_verification_measures.md G8）。

### 6.4 代码签名路线图

- **Windows**：`electron-builder` 的 `win.winCodeSign` 由 GitHub Secrets 提供（证书 `.pfx` 的 base64 + 密码）。
- **macOS**：默认 unsigned（Gatekeeper 会拦截，需右键打开）。正式分发时配 `CSC_LINK` / `CSC_KEY_PASSWORD` / `APPLE_ID` / `APPLE_APP_SPECIFIC_PASSWORD` / `APPLE_TEAM_ID`。
- **回退策略**：签名未配置时打包仍成功，只是 Gatekeeper 会拦截。用户可通过右键打开绕过。

---

## §7 知识产权与软著

### 7.1 AGPL 义务履行

AGPL-3.0 的核心义务：任何**部署运行**的服务必须提供对应源码给**用户**。

**本项目履行路径**（`README.md` §「协议」/ `docs/handover/PROJECT-HANDOVER.md` §4 P4）：
1. 开源仓本身即「对应源码包」：GitHub 公开仓 → 任何用户可以 clone / 看历史 / 提 issue。
2. 官网保留 GitHub + 自建镜像**双通道**（决策 P1=A）：0 成本、可获取。
3. 历史版本在 Git tag 里保留，Release 里可下载。

### 7.2 署名与 NOTICE 纪律

- `LICENSE`：AGPL-3.0 完整文本。
- `NOTICE.txt`：第三方组件归属与许可证声明，包括 MIT（`social-auto-upload`）与 Apache-2.0（`SynapseAutomation`）上游。
- `vendor/VENDOR.md`：逐项第三方依赖归属与许可证。
- **纪律**：修改上游代码必须保留其版权声明（NOTICE 第 3 行署名 `maning636`）。

### 7.3 软著材料 SOP

**SOP 摘要**（完整流程见 `docs/engineering/SOFT-COPYRIGHT-SOP.md` —— E-3 子任务在建，此处仅占位引用）：
- 提交内容：源代码（前 30 页 + 后 30 页）、软件说明书、软件名称、版本号、著作权人信息、完成日期。
- 版本号与 GitHub tag 对齐；提交前扫描 U+FFFD = 0（坑 A5）。
- 提交后归档材料到 `docs/handover/`，保留提交回执。

---

## §8 人员与 AI 协作

### 8.1 CODEOWNERS 与权限分层

**建议结构**（新项目模板见 `NEW-PROJECT-KIT/templates/AGENT-TEMPLATE.md`）：
```
*                @owner
prism_backend/   @backend-team
prism_frontend/  @frontend-team
desktop-electron/ @desktop-team
.github/workflows/ @release-team
docs/            @docs-team
```

**权限分层**：
- Owner：全库 merge 权限
- Code Owner：所在目录 merge 权限 + 必须评审
- Contributor：只能开 PR
- Viewer：只读

### 8.2 AI 参与记录规范

**Git trailer**：AI 参与的 commit 必须带 `AI-Model: <model-name>` trailer，如 `AI-Model: GPT-4o` / `AI-Model: Claude-Sonnet-4`。

**格式**：
```
feat(backend): 新增 subscription tier 判定

Fixes: #123

AI-Model: Claude-Sonnet-4
```

**目的**：追溯每个 AI 生成的代码，便于审查、便于将来做 AI 使用统计与合规审计。

### 8.3 人机分工原则

**AI 执行 + 人拍板决策点**：
- AI 负责：实现、测试、文档、review、重构。
- 人负责：架构决策、协议选择、成本预算、发布时间、是否上线、对外沟通。

**决策台账里的 AI 边界**：
- AI 不能决定：协议（AGPL / MIT / Apache）、订阅定价、云端部署策略、是否开源、是否公开个人信息。
- AI 可以建议，但必须留给人拍板。
- 决策台账里显式记录「决策者」「日期」「证据」。

---

## §9 新项目检查单（从零到第一个可发版本）

从 `NEW-PROJECT-KIT/` 复制后，逐项勾选。**全部勾选后打第一个 tag** `v0.1.0`。

| # | 项 | 参考 |
|---|---|---|
| 1 | 仓库初始化，LICENSE（AGPL-3.0）入库 | 本手册 §7.1 |
| 2 | `README.md` / `CONTRIBUTING.md` / `SECURITY.md` / `NOTICE.txt` 五件套齐 | §4.1 |
| 3 | `AGENT.md` 就位，含 Repo Hygiene / Push Rules / Local-Only Data | §2.1 |
| 4 | `.gitignore` 覆盖所有运行时目录，本地实测 `git status --short` 干净 | §2.1 |
| 5 | 依赖声明文件：`requirements.txt` + `requirements-dev.txt` + `package.json` | §2.2 |
| 6 | 依赖声明闸门 + 反向自测跑通 | §2.2 |
| 7 | 最小测试：1 个后端单测 + 1 个前端单测 | §5.3 |
| 8 | `lint` 硬门（后端 ruff + 前端 ESLint）| §5.1 |
| 9 | `test` 硬门（pytest + vitest） | §5.1 |
| 10 | `deps-gate` 硬门 | §5.1 |
| 11 | `security.yml` 硬门（gitleaks + 依赖审计） | §6.3 |
| 12 | 版本号单一真源，tag 与资产名一致 | §3.2 |
| 13 | `CHANGELOG.md` 建首条 `0.1.0 - <date>` | §3.3 |
| 14 | `release.yml` 就位，含体积下限守卫 + 已发布防覆盖 | §3.4 |
| 15 | `deploy/` 或 `Dockerfile` 就位 | 视技术栈 |
| 16 | 决策台账 `docs/architecture/decisions/0001-*.md` 首条 ADR | §4.1 |
| 17 | 坑清单 `docs/handover/PROJECT-HANDOVER.md` §8 建骨架 | §4.1 |
| 18 | `docs/dev-reports/` 建首份 | §4.1 |
| 19 | 验收表 build/read/roundtrip 三件套（`scripts/docs/`） | §4.2 |
| 20 | CI 全绿，无硬门失败 | §5 |
| 21 | 本地 bootstrap 文档写就，从 clone 到跑通测试 ≤ 10 步 | §2.4 |
| 22 | 打 tag `v0.1.0` | §3.4 |
| 23 | 发版流水线跑通，产出可下载资产 | §3.4 |
| 24 | GitHub Release 已发布，历史版本可下载 | §3.5 |
| 25 | 官网 / README 指向最新 tag | §3.5 |

**下一步**：把上述检查单里每一条对应的模板从 `docs/engineering/NEW-PROJECT-KIT/` 复制到新项目根目录，逐个替换 `{{项目名}}` 占位符，按 §1 三大支柱逐一落实。

---

*本手册版本 v1.0，与 Prism-Fusion 仓库 HEAD `c24a11d`（截至 2026-10-24）对齐。*
*下次更新：新增机制落地时，先改对应文件，再改本手册对应章节，保证单一真源。*
