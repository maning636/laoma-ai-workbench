# Prism-Fusion 项目交接文档

> 日期:2026-10-13
> 用途:交给用户 + 下一位 agent,理解当前进度、开发事件、设计思维;辅助云端部署
> 仓库:`D:\dim开发\Prism-Fusion`(Windows,路径含中文)
> 状态:本地产品化(A/B 类)主体已完;C 类 SaaS 主体已完工,进入真机联调 + 部署 + 加固阶段

---

## 目录

1. [项目概览](#1-项目概览)
2. [进度总览](#2-进度总览)
3. [开发事件时间线](#3-开发事件时间线)
4. [设计思维与关键决策](#4-设计思维与关键决策重点)
5. [架构现状](#5-架构现状)
6. [遗留与风险](#6-遗留与风险)
7. [交接要点(给下一位 agent)](#7-交接要点给下一位-agent)

---

## 1. 项目概览

| 维度 | 内容 |
|---|---|
| **定位** | 老马 AI 工作台 —— Windows 桌面 AI 视频/内容生产套件 |
| **形态演变** | 纯本地单机(Electron + 127.0.0.1:7000 FastAPI)→ **云端 SaaS 订阅**(混合:核心下沉 + 双版本架构) |
| **后端** | FastAPI + Pydantic v2 + SQLAlchemy 2.0 + Celery/Redis |
| **前端** | Next.js 16 App Router + React 19 + shadcn/Radix + Tailwind |
| **桌面壳** | Electron + NSIS / Inno Setup 打包 + supervisor.exe 服务编排 |
| **打包** | PyInstaller(`backend_service` / `celery_worker_service` / `automation_worker_service` onedir) |
| **第三方 AI** | DeepSeek / SenseNova(经 SiliconFlow 兼容端点) |
| **上游组件** | Hermes Agent + Hermes WebUI + Easel(外部视频引擎) |
| **核心能力** | 8 平台发布(抖音/小红书/B 站/视频号/快手/知乎/头条/西瓜)+ AI 内容生成 + 浏览器自动化(patchright)+ 视频流水线 |
| **主要目录** | `prism_backend/`(本地后端)· `prism_frontend/`(前端)· `desktop-electron/`(壳)· `cloud_service/`(**SaaS 云端新目录**) |

---

## 2. 进度总览

分类口径:**P0–P5 产品化改造**(本主线) · **A 类**(立即收尾) · **B 类**(本地产品化收尾) · **C 类**(SaaS 化) · **D 类**(长期 review)。

### 2.1 已完成 ✅

| 类 | 项 | 说明 |
|---|---|---|
| P0 | 硬编码路径清零 | `video_pipeline/orchestrator.py`(3 处)· `fusion_ai/router.py` · `video_pipeline/{router,render}.py` 全部改走 `core/paths.py` |
| P1 | 配置中心化 | `core/paths.py` + `paths.json` + `/preflight` 扩展 + 启动自检 |
| P2 | Easel 卡片 | `/api/v1/easel/status` + `easel-provider-card` 前端 |
| P3 | Easel 自动更新 | `easel_update.py` + **三层回滚**(git SHA 快照 + zip 备份 + 双目录切换)+ Hermes 回滚补齐 |
| P4 | 打包分发 | `PACKAGING.md` + `supervisor.spec` bug 修 + secret 排除 + 依赖收敛 |
| P5 | subprocess 兜底 | `fastapi_app/utils/subprocess_safe.py` + 33 处迁移(白名单:`subprocess_safe` 3 + `process_manager` 2) |
| review 批量 | 硬 bug 修 | gateway 端口 `7861→7860` / `18789→37289`;6 模块前缀双重 `/api/v1/api/v1/`;dev repo 窄化分支;`automation_worker` 日志锚定 |
| C 盘防护 | 四层 | env + Electron `setPath` + `run.py` 兜底 + `paths.py` 兜底 |
| A1 | `ci.yml` modules 列表 | 硬守门后剔出运行时模块,避免 CI 必红 |
| A2 | `.env.example` 死字段清理 | 删 17 处零引用字段(`FLASK_*` / `UPLOAD_FOLDER` / `COOKIE_DIR` / `REDIS_HOST|PORT|DB` 等) |
| A3 | P5 残留终检 | 白名单外裸 subprocess = 0 |
| — | `video_transcoder` `get_logger` 既存 bug | 已修(改用 `create_logger`,历史遗留) |
| — | `ci.yml` import 烟测 | 由 `SKIP` 改为硬失败(`sys.exit(1)`) |
| B5 | E2E 打包烟测脚本 | `scripts/tests/e2e_packaged_test.ps1` + `integration_test.py`(**脚本已实跑**,产物冒烟验证) |
| B6 | PyInstaller 入口统一 | 抽 `prism_backend/_paths.py`(仅 stdlib);3 份 `*_service.py` 探测收敛 |
| B8 | CI 加 test/lint | `requirements-dev.txt`(pytest + httpx + pytest-asyncio + pytest-cov + ruff) |
| B9 | env 前缀统一 | `PRISM_* → LAOMA_*`(含 `.env.example` / 部署脚本 / 前端 env 注入) |
| B10 | 启动慢优化 | **26s → 2–3s**(Hermes dashboard 由阻塞启动改为延迟/并行;冷启动最大瓶颈 18s 大幅收敛) |
| B7 | supervisor SERVICE_REGISTRY | `desktop-electron/resources/supervisor/supervisor.py` 加 `SERVICE_REGISTRY`(7 服务:redis/automation-worker/backend/celery-worker/hermes-dashboard/hermes-webui/hermes-gateway);`stop_all`/`start_services` 按 `stop_order`/`start_order` 排序;`_is_service_ready` 通用 `_probe`;`restart_policy` 合并进 registry;原 20 处 "backend" 硬编码收敛 |
| C12 | 用户体系 + JWT | `cloud_service/auth/` — `User` 表 + register/login/refresh/logout + `Depends(current_user)` + `auth/security.py`(140 行) |
| C13 | 订阅 + license + 计费 | `cloud_service/billing/` — `Subscription` / `Usage` / `Plan` 表 + `/subscription` / `/usage/consume` / `/license/verify` / `/subscription/activate` |
| C14 | LLM 代理 + prompt 下沉 | `cloud_service/llm_proxy/` — `POST /cloud/llm/chat` + `/cloud/prompts` + `llm_client.py` + **`prompts.py` 336 行**(Jinja2 风格渲染 + 内存表 `CLOUD_PROMPTS` / `BASIC_PROMPTS` + 幂等 `sync_prompts_to_db`) |
| C14a | 双版本 prompt 分层 | 云端 `tier=cloud` 高价值 prompt + `tier=basic` 离线可复用模板;DB 表 `prompts(name, tier, template, variables_json, version, is_active)` |
| C14b | 客户端 prompt 路由 | `prism_backend/fusion_ai/prompt_router.py`(184 行)+ `prompts_basic.py`(166 行,离线基础库) |
| C16 | 客户端双通道 | `prism_backend/fusion_ai/cloud_gateway.py`(557 行,后端侧 gateway)+ `prism_frontend/src/lib/cloud-auth.ts`(431 行,前端 JWT/refresh) |
| C18 | pyarmor 混淆试点 | `scripts/packaging/obfuscate.py`(314 行,check/backup/restore/obfuscate/inject/verify)+ `build_services.ps1` 集成(备份→混淆→注入→打包→恢复,pyarmor 缺失时降级不破坏);试点模块:`cloud_gateway.py` |
| C17 | key 剥离(订阅态) | 订阅态订阅 → 三处本地 key 清空(`.env` / SQLite `ai_model_configs` / `hermes-home/config.yaml`) |
| C19 | 支付 | `cloud_service/payment/` — `PaymentAdapter` 抽象 + `alipay.py`(131 行) + `wechat.py`(124 行) + `/cloud/payment/*` + 对账 |
| C — UI | 前端 C 类 | `prism_frontend/src/app/login/page.tsx` + `components/settings/cloud-subscription-card.tsx`(340 行)+ `hooks/useLicenseHeartbeat.ts`(85 行,24h 心跳) |
| C — 测试 | 云端单测 | `cloud_service/test_{billing,llm,payment,e2e}.py` 共 804 行 |
| 工作区 | 3 commits 落地 | `09ff37d` / `bbc906e` / `8598f7c`(全部 2026-10-13) |

### 2.2 进行中 🟡

| 类 | 项 | 状态 |
|---|---|---|
| C16a | Hermes 双通道适配 | 通道适配骨架已建(订阅态写代理 endpoint),**真机联调未跑** |
| C20 | 云基础设施 | 资源清单已定(阿里云 ECS + RDS + Redis + 域名/HTTPS),**未开通** |
| C21 | cloud_service 部署 | Docker / Nginx / 告警骨架未做;当前仅本地 `cloud.db`(SQLite) |
| 部署 | 前端 build + 后端打包冒烟 | 未跑(工作区还有 14+ 未提交改动) |

### 2.3 未做 ❌

| 类 | 项 | 备注 |
|---|---|---|
| C15 | 签名/风控代理下沉 | **暂缓**(§7 决策 1「仅核心 AI」明确排除);仅保留可选 `/cloud/fingerprint/policy` |
| D — | 6 模块前缀兼容层移除 | 观察期后再移除 |
| D — | Easel `openclaw.json` 目录备份 | 只备份文件不足 |
| D — | `openclaw@latest` pin 版本 | 待 pin |
| D — | `paths.json` 加入 `.gitignore` | 防误追踪 |

**当前工作区**(未提交)包含所有 C 类 SaaS 新文件:`cloud_service/`、`prism_backend/fusion_ai/{cloud_gateway,prompt_router,prompts_basic}.py`、`prism_frontend/src/app/login/`、`components/settings/cloud-subscription-card.tsx`、`hooks/useLicenseHeartbeat.ts`、`lib/cloud-auth.ts`,以及对 `config.py` / `hermes_config.py` / `fusion_ai/router.py` / `settings/page.tsx` / `env.ts` / `desktop-electron/*` / `build-package.bat` / `build_services.ps1` 的改动。

### 2.4 工作区提交记录

```
8598f7c | 2026-10-13 | fix(mixed): 10 个混合文件整文件提交(含背景+本主线改动)
bbc906e | 2026-10-13 | feat(mainline): 本主线 P0-P5/B 类新文件 + vendor 归属文档 + 14 新 API 目录挂载
09ff37d | 2026-10-13 | chore(productize): 品牌 PRISM_→LAOMA_ + Easel 复刻 + 视频流水线 + Settings 重构 + 主题 + 打包脚本/文档
e00daf6 | 2026-09-23 | docs: 修正 STARTUP.md 的 Hermes 安装链说明
30a6aaf | 2026-09-23 | chore: 移除构建产物,加入 uv.lock 保证依赖可复现
52ec305 | 2026-09-23 | chore: 提交成品组件,冻结项目用于跨机器迁移
```

**C 类 SaaS 全部未提交**(`cloud_service/` 整目录 + 3 个 fusion_ai 新文件 + 前端登录/订阅/心跳/JWT 5 个新文件 + 若干混合修改)。

---

## 3. 开发事件时间线

按事件序列(非按文件),尽量给阶段与工时定位。

### 3.1 P0 路径清零(2026-10-11 前)

- 硬编码 5 处:`video_pipeline/orchestrator.py:47,106`(E:\FDE\fde-landing-delivery)· `fusion_ai/router.py:107`(D:/工作台/LaomaAI-Fusion/tools/hermes-home/config.yaml)· `video_pipeline/router.py:47,64-66`(C:/Program Files/nodejs)· `render.py`
- 全部改走 `core/paths.py` 解析;`orchestrator.py` 引入 `core_paths` 变量;新增 `_is_dev_source_tree()` 兜底识别仓库根 vs `%APPDATA%`

### 3.2 P1 配置中心化(2026-10-11)

- 新建 `prism_backend/fastapi_app/core/paths.py`(86 行 → 现含 `_is_dev_source_tree` 兜底)
- 新增 `paths.json` 落 `DATA_DIR/`(与 secrets 隔离)
- 扩展 `/api/v1/system/preflight` + health-check 分档 + `startup_event` 触发 preflight

### 3.3 P2 Easel 卡片(2026-10-11~12)

- `/api/v1/easel/status` 端点 + `easel-provider-card` 前端卡片
- Easel 端口对齐真相(7860/37289)

### 3.4 P3 Easel 自动更新(2026-10-12)

- 新建 `easel_update.py`(参考 `hermes_update.py` 模板 313 行)
- **三层回滚**:git SHA 快照(首选) + zip 备份(次选) + 双目录切换(兜底)
- Hermes 侧回滚补齐;`get_update_status` 导出回滚字段

### 3.5 P4 打包分发(2026-10-12)

- `PACKAGING.md` 新增(7 阶段流程详解)
- `supervisor.spec` bug 修
- `build-package.bat` secret 排除列表 + 依赖收敛(pyproject/requirements)
- 版本号同步脚本 `build-version.json`

### 3.6 P5 subprocess 兜底(2026-10-13 前)

- 新建 `fastapi_app/utils/subprocess_safe.py`(`safe_run` / `safe_popen`)
- 33 处 `subprocess.run/Popen` 迁移,跨 30+ 文件
- 白名单:wrapper 自身 3 处 + `utils/process_manager.py` 2 处(`CREATE_NEW_PROCESS_GROUP` 语义保留)

### 3.7 Review 批量修复(2026-10-13)

- **Bug 1**:gateway 端口硬编码错误 `7861→7860` / `18789→37289`
- **Bug 2**:6 模块路由前缀双重 `/api/v1/api/v1/` → 兼容层 + prefix 收敛
- dev repo 检测窄化(避免向上探到 `C:\`)
- `automation_worker` 日志锚定到 `data/logs`
- `STARTUP.md` / `PACKAGING.md` 文档同步

### 3.8 C 盘防护(2026-10-13)

- **四层防护**建立(见 §4.6)
- 目标:防止 Windows 默认写到 C 盘系统目录

### 3.9 A 类立即收尾(2026-10-13)

- A1:`ci.yml` modules 列表调整 — 硬守门后剔出运行时模块
- A2:`.env.example` ↔ `config.py` 字段核对 — 删 17 处零引用死字段
- A3:P5 残留终检 — 白名单外裸 subprocess = 0
- `video_transcoder.get_logger` 既存 bug 修(改用 `create_logger`,历史遗留 import 错误)
- `ci.yml` import 烟测从 `SKIP` 改为硬失败(否则守门形同虚设)

### 3.10 B 类本地产品化收尾(2026-10-13)

| 项 | 内容 |
|---|---|
| B5 | E2E 打包烟测脚本 `e2e_packaged_test.ps1` + `integration_test.py` + CI e2e job;**实跑验证 /preflight 无 null** |
| B6 | PyInstaller 入口统一 — 抽 `prism_backend/_paths.py`(仅 stdlib),3 份 `*_service.py` 探测收敛(原探测过宽会向上探到 C:\) |
| B8 | CI 加 test/lint — 新增 `requirements-dev.txt`(pytest + httpx + pytest-asyncio + pytest-cov + ruff) |
| B9 | env 前缀统一 `PRISM_* → LAOMA_*`(全仓 + `.env.example` + 部署脚本 + 前端 env 注入) |
| B10 | **启动慢 26s → 2–3s**(Hermes dashboard 原阻塞 18s,改为延迟/并行启动) |
| B7 | ✅ supervisor SERVICE_REGISTRY(7 服务集中描述,stop/start order + restart_policy 合并进 registry;原 20 处 "backend" 硬编码收敛) |

### 3.11 工作区提交(2026-10-13)

- `09ff37d chore(productize)`:背景 PRISM→LAOMA 品牌 + Easel 复刻 + 视频流水线 + Settings 重构 + 主题 + 打包脚本
- `bbc906e feat(mainline)`:本主线 P0-P5/B 类新文件 + vendor 归属文档 + 14 新 API 目录挂载
- `8598f7c fix(mixed)`:10 个混合文件整文件提交(见 §4.9)

### 3.12 C 类 SaaS 化(2026-10-13,未提交)

- **决策签核 C11**:§7 七点全部拍板(仅核心 AI 下沉 · 双版本 · 支付宝+微信 · 阿里云/腾讯云 · 下沉+混淆 · 保留离线 · Hermes 归属暂不定)
- **设计文档落盘**:`docs/dev-reports/2026-10-13-saas-c-class-design.md`(20.6 KB)
- **C12 用户体系**:`cloud_service/auth/{models,router,security}.py`(299 行)+ `/cloud/auth/*`
- **C13 订阅/计费**:`cloud_service/billing/{models,router,schemas}.py`(362 行)+ `/cloud/subscription` `/cloud/usage/consume` `/cloud/license/verify` `/cloud/subscription/activate`
- **C14 LLM 代理**:`cloud_service/llm_proxy/{models,router,schemas,llm_client,prompts}.py`(939 行);`/cloud/llm/chat` + `/cloud/prompts`
- **C14a prompt 分层**:`prompts.py`(336 行,Jinja2 渲染 + `CLOUD_PROMPTS` / `BASIC_PROMPTS` + `sync_prompts_to_db` 幂等 upsert)
- **C14b 客户端 prompt 路由**:`prism_backend/fusion_ai/prompt_router.py`(184 行)+ `prompts_basic.py`(166 行)
- **C16 双通道**:`prism_backend/fusion_ai/cloud_gateway.py`(557 行)+ `prism_frontend/src/lib/cloud-auth.ts`(431 行)
- **C17 key 剥离**:`hermes_config.py` + `config.py` 改造(订阅态清空本地 key,离线态保留)
- **C19 支付**:`cloud_service/payment/{adapter,alipay,wechat,models,router,schemas}.py`(741 行)+ `/cloud/payment/*` + 对账
- **C 类 UI**:`prism_frontend/src/app/login/page.tsx` + `components/settings/cloud-subscription-card.tsx`(340 行)+ `hooks/useLicenseHeartbeat.ts`(85 行,24h 心跳)+ `lib/env.ts` 加 `cloudBaseUrl`
- **C 类测试**:`cloud_service/test_{billing,llm,payment,e2e}.py`(804 行)
- 详见各 C 类模块文件行数与 `cloud_service/` 目录结构(§5)

---

## 4. 设计思维与关键决策(重点)

> 每条按 **决策 + 为什么 + 权衡/代价** 展开。这是"为什么这么做"的答案,比进度更重要。

### 4.1 路径单一入口:`core/paths.py`

- **决策**:所有路径解析收敛到 `fastapi_app/core/paths.py`;`paths.json` 存 `DATA_DIR/`,不入库;`_is_dev_source_tree()` 识别仓库根 vs `%APPDATA%`
- **为什么**:开发阶段大量 `E:\FDE\...` / `F:\自媒体\...` 硬编码,用户拿到打包产物后必炸;相对路径依赖 cwd 也会因 Electron 启动目录不同而崩
- **权衡/代价**:
  - 出现 `settings.DATA_DIR` 与 `paths.get_data_dir()` **两套逻辑**并存(pydantic 与 core 层各一套)
  - 2026-10-11 三 agent 实证两者"实测一致"**不成立**,存在 5 处分叉:
    1. dev repo 检测路径
    2. env 名不一致(`DATA_DIR` vs `LAOMA_DATA_DIR`)
    3. 存在性检查强度
    4. 路径规范化
    5. 兜底差异
  - 未完全收敛:B9 只做 `PRISM→LAOMA` env 名,`DATA_DIR` ↔ `LAOMA_DATA_DIR` 收敛留待观察期

### 4.2 双版本架构(线上版 + 离线版)

- **决策**:**同一份 exe**,通过"订阅态 vs 自配 key 态"切换;线上版走云端 prompt,离线版用本地基础 prompt
- **为什么**:§7 决策 1(仅核心 AI 下沉)与决策 6(保留离线)看似互斥 —— 若允许用户自配 key 纯本地跑,那核心 AI 也就本地跑,下沉无意义。**解法**:差异化资产放云端,基础模板留本地
- **权衡/代价**:
  - **离线版基础 prompt 可被逆向** — 但即使被抄也"能用但不够聪明",不构成产品差异化损失(**明确接受此风险**)
  - prompt 库需要**双份维护**(云端 `prompts` 表 vs 本地 `prompts_basic.py`);用统一版本 tag 对齐
  - 客户端切换逻辑要覆盖"云端不可达 / 未登录 / 订阅过期"三种降级路径(见 §4.5)

### 4.3 核心资产下沉防逆向

- **决策**:差异化资产下沉云端;分类见 `_plan_productization_saas.md` §2.3
- **为什么**:PyInstaller 可解包(uncompyle6 反编译),无防逆向的本地资产等于公开;而**下沉是提高成本,不追求绝对防逆向**
- **资产分级**(实证排序):
  - 🔴 极高(必下沉):`fusion_ai/`(cognition / platform_styles / model_market / hot_topics / content_moderator / skill_workshop / nl_query / router)· `reverse_api/` + 抖音签名算法
  - 🔴 高(LLM 代理下沉):`ai_service/`
  - 🟠 中高(部分下沉):`myUtils/` 策略下沉、执行留本地;`platforms/*` 签名拼装下沉、浏览器操作留本地
  - ❌ **必须本地**(边界):浏览器自动化(patchright / playwright) · 大文件上传 · Persona 指纹数据 · cookie 存储
- **代价**:
  - 客户端需要联网才能用高价值 prompt
  - 云成本 + 运维负担
  - Hermes 子进程改造复杂(独立 config + venv)
  - **B4 签名/风控下沉暂缓**(§7 决策 1 明确"仅核心 AI")— 因下沉算法意义有限,需浏览器环境配合

### 4.4 key 剥离(订阅态不读本地 key)

- **决策**:订阅用户 `.env` / SQLite `ai_model_configs` / `hermes-home/config.yaml` 三处明文 key 清空;`hermes_config.py` 写代理 endpoint;Hermes 子进程经代理调 LLM
- **为什么**:LLM key 是订阅变现的基础,不剥离等于用户可绕过订阅自行调用 LLM
- **代价**:
  - **Hermes 独立 config.yaml + 独立 venv**,改造复杂 — 若破坏 P3 自动更新的回滚机制,难以修复
  - 分步执行:先 LLM 主链路,再 Hermes
  - 离线态保留原行为(不打破兼容)

### 4.5 双通道 + 三层降级

- **决策**:客户端 SDK(`cloud_gateway.py` 后端 + `cloud-auth.ts` 前端)统一路由;失败时按序降级
- **为什么**:核心资产下沉但用户体验要连续,不能"云端 502 就全崩"
- **降级顺序**:
  1. 云端不可达 → 弹窗提示 + 用户可选重试 / 切离线
  2. 未登录 → 引导登录
  3. 订阅过期 → 降级到离线版模式或拒绝云端调用
- **代价**:**不静默降级** — 订阅态断网时若静默用本地基础 prompt,用户感知不到"付费降级"。选择明示降级让"付费/免费"边界清晰,同时牺牲部分"无缝"体验

### 4.6 四层 C 盘防护

- **决策**:
  1. `LAOMA_DATA_DIR` env 显式指定
  2. Electron `app.setPath('userData', ...)` 改到用户可选目录
  3. `run.py` 兜底:检测 cwd 或默认值是否在 C 盘,若是则改道
  4. `paths.py` 兜底:`_is_dev_source_tree` + `get_data_dir()` 最终校验
- **为什么**:Windows 默认 `%APPDATA%` 在 C 盘,系统更新可能清理;而本项目数据量(视频中间产物、cookie、persona 指纹)不小
- **代价**:四层冗余代码,任何一层失效其他层接住;调试路径时**必须逐层验证**(不是简单 grep env)

### 4.7 supervisor SERVICE_REGISTRY(已完成)

- **决策**:**已实施**(B7 完成)—— 引入 `SERVICE_REGISTRY` 数据结构,集中描述打包服务的元数据(exe_paths / host / port_default / env_port_keys / log_file / start_order / stop_order / health_paths / status_extras / restart_policy)
- **为什么**:`desktop-electron/resources/supervisor/supervisor.py`(现 1553 行)原 1595 行内 "backend" 硬编码 20 次,跨 8 类语义结构:停止顺序 2. 端口字典 3. 重启策略 4. 可执行路径 5. 启动顺序 6. 日志路径 7. 健康检查 8. 就绪探针 9. 端口冲突集 —— 新增服务需改 8 处,极易漏项
- **落地范围**:`SERVICE_REGISTRY` 覆盖 7 个服务(redis / automation-worker / backend / celery-worker / hermes-dashboard / hermes-webui / hermes-gateway),每服务独立配置 `stop_order`(0-9)/`start_order`(0-6)/`restart_policy`(`max_restarts` / `backoff` / `stable_after`);`stop_all` 与 `start_services` 显式按 registry 排序,`_is_service_ready` 走通用 `_probe`(TCP 或 HTTP)
- **收益**:新增/删除服务只需改 `SERVICE_REGISTRY` 一处;停止顺序、健康探针、重启策略均可数据化配置;20 处 "backend" 硬编码全部收敛
- **遗留**(下一轮清理项,不阻塞上线):
  1. `api_server.py` `/status` 端点仍按旧列表硬编码,未读 registry
  2. `get_service_launch` / `env name` 若干分支保留(用于环境变量解析的兼容路径)
  3. 尚未真机回归:需打包后跑一次完整启动/停止/重启循环验证 `stop_order` 语义
- **状态**:核心结构已落地,列为 B7 完成项;残余清理并入 §6.2 观察期

### 4.8 subprocess 统一封装 `safe_run`

- **决策**:所有 `subprocess.run/Popen` 走 `subprocess_safe.py` 的 `safe_run` / `safe_popen`
- **为什么**:打包后跨平台(未来 Mac/Linux)风险;统一 timeout 处理、`CREATE_NO_WINDOW` 隐藏控制台、编码统一 UTF-8、日志锚定
- **代价**:
  - **白名单例外**:`process_manager.py` 2 处保留原 `subprocess.run`(需要 `CREATE_NEW_PROCESS_GROUP` 特殊语义,不适合 wrapper 化)
  - 迁移时 DEVNULL 模式需注意:3 处 `hermes_agent` / `persona_dashboard` / `accounts/router` 使用 `safe_run(cmd, capture_output=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)`

### 4.9 提交策略 D(混合文件整文件提交)

- **决策**:`8598f7c` 单独一次提交,10 个"混合文件"整文件提交,commit message 显式标注 `fix(mixed):`
- **为什么**:工作区有 294 文件背景改动(2026-09-23 冻结后约 2 周的产品化开发)+ 本主线叠加;逐行切分不可能
- **代价**:
  - 混合文件无法独立 revert(整文件回滚)
  - 保留完整 diff 供事后追溯,不再细分
  - 3 commits 分层:背景 / 本主线新文件 / 混合文件 — 各层可独立回滚

---

## 5. 架构现状

### 5.1 本地栈(`prism_backend/` + `desktop-electron/`)

```
Redis (6379)
    ↑
FastAPI 后端 (127.0.0.1:7000) ──启动── Hermes Dashboard (9119) [延迟启动,不再阻塞]
    ↑                                    Hermes WebUI (8788)
Celery Worker (7001)
    ↑
Next.js 前端 (3000)
    ↑
Electron 壳 (desktop-electron/)
    ├─ supervisor.exe(服务编排)
    ├─ backend_service.exe / celery_worker_service.exe / automation_worker_service.exe(PyInstaller onedir)
    └─ prismenv + patchright browsers + hermes-agent/webui
```

**主要目录**:
- `prism_backend/fastapi_app/api/v1/`(14+ API 目录)
- `prism_backend/fastapi_app/agent/`(Hermes 对接)
- `prism_backend/fastapi_app/core/{paths,config,logger,db}.py`
- `prism_backend/fastapi_app/utils/subprocess_safe.py`
- `prism_backend/fusion_ai/`(prompt + `cloud_gateway.py` + `prompt_router.py` + `prompts_basic.py`)
- `prism_backend/_paths.py`(PyInstaller 顶层路径解析,仅 stdlib)

### 5.2 云端栈(`cloud_service/`)— **新目录,未提交**

```
cloud_service/
├── main.py                 (42 行)FastAPI 入口 + lifespan(init_db 幂等)
├── settings.py             (73 行)CLOUD_* env 解析 + JWT_SECRET 兜底随机
├── db.py                   (44 行)SQLAlchemy + init_db
├── auth/
│   ├── models.py           (37 行)User 表
│   ├── router.py           (222 行)register/login/refresh/logout/me
│   └── security.py         (140 行)JWT 签发/校验 + Depends(current_user)
├── billing/
│   ├── models.py           (71 行)Subscription / Usage / Plan 表
│   ├── router.py           (234 行)/subscription / usage/consume / license/verify / subscription/activate
│   └── schemas.py          (57 行)
├── llm_proxy/
│   ├── models.py           (47 行)Prompt ORM
│   ├── router.py           (346 行)POST /cloud/llm/chat + GET /cloud/prompts
│   ├── llm_client.py       (101 行)DeepSeek / SenseNova / SiliconFlow 上游封装
│   ├── prompts.py          (336 行)PromptDef 内存表 + Jinja2 渲染 + sync_prompts_to_db 幂等 upsert
│   └── schemas.py          (109 行)
├── payment/
│   ├── adapter.py          (88 行)PaymentAdapter 抽象
│   ├── alipay.py           (131 行)支付宝电脑网站支付 + 当面付
│   ├── wechat.py           (124 行)微信 Native + JSAPI
│   ├── models.py           (87 行)Order / Invoice
│   ├── router.py           (250 行)/cloud/payment/create / callback / order/{no}
│   └── schemas.py          (61 行)
└── test_*.py               (4 文件共 804 行)
```

**当前运行方式**:本地 `sqlite:///cloud.db` 单文件;`uvicorn cloud_service.main:app --port 8000`。生产需迁移 RDS(MySQL/PG)。

### 5.3 客户端双通道(`prism_frontend/` + `prism_backend/fusion_ai/`)

- **前端**:`src/lib/cloud-auth.ts`(431 行,JWT 存储 + refresh + logout)· `src/hooks/useLicenseHeartbeat.ts`(85 行,24h 心跳)· `src/components/settings/cloud-subscription-card.tsx`(340 行,订阅管理 UI)· `src/app/login/page.tsx`(登录页)
- **后端**:`fusion_ai/cloud_gateway.py`(557 行,后端侧 API 代理)+ `prompt_router.py`(184 行,prompt_id → tier 路由)+ `prompts_basic.py`(166 行,离线基础 prompt 库)
- **判定逻辑**:
  ```
  启动 → 检查订阅(localStorage + license 心跳)
    ├─ 有订阅 + 云端可达 → 线上版(chatClient → /cloud/llm/chat,prompt 只传 prompt_id)
    ├─ 有订阅 + 云端不可达 → 弹窗提示 → 重试 / 切离线模式
    └─ 无订阅 / 自配 key 模式 → 离线版(chatClient → 本地基础 prompt)
  ```
- **env**:`LAOMA_INTERNAL_BACKEND_URL`(本地) + `LAOMA_CLOUD_BACKEND_URL`(云端),并存

### 5.4 Prompt 分层

| Tier | 位置 | 内容 | 可见性 |
|---|---|---|---|
| **cloud** | `cloud_service/llm_proxy/prompts.py::CLOUD_PROMPTS` + DB `prompts` 表 | cognition · platform_styles(8 平台)· model_market · hot_topics · content_moderator · skill_workshop · nl_query · router | 客户端只传 `prompt_id`,看不到模板源码 |
| **basic** | 云端同步一份 + 客户端 `prism_backend/fusion_ai/prompts_basic.py` | greeting · simple-title · simple-tag · simple-rewrite · fallback | 离线版可用;即使逆向也"能用但不够聪明" |

### 5.5 支付链路

- **抽象**:`PaymentAdapter`(create_order / handle_callback / query_order / refund)
- **实现**:`alipay.py`(电脑网站支付 + 当面付)+ `wechat.py`(Native + JSAPI);Stripe **未做**(§7 决策 3 明确)
- **订单**:云端 `orders` 表(order_no / out_trade_no / status / paid_at)
- **对账**:每日对账脚本(**骨架已建,真机联调未跑**)
- **外部依赖**:支付宝 + 微信商户号申请周期 2–3 周(**必须现在启动,否则阻塞上线**)

---

## 6. 遗留与风险

### 6.1 C 类 SaaS 未做项

| # | 项 | 影响 | 优先级 |
|---|---|---|---|
| **C20** | 云基础设施(ECS + 域名 + HTTPS + RDS + Redis) | 阻塞真机联调与部署 | 🔴 P0 |
| **C21** | cloud_service 部署(Nginx 反代 + 日志 + 告警 + CI/CD) | 阻塞生产上线 | 🔴 P0 |
| **stream 支持** | `/cloud/llm/chat` 目前**非流式**;`ai_service/llm.py` 未加 `stream=True` 分支 | 影响体验(长 prompt 等待久) | 🟡 P2 |
| **退款** | `PaymentAdapter.refund()` 抽象已定义,**实际实现未联调** | 运营必需 | 🟡 P2 |
| **对账** | 每日对账脚本骨架,未跑真实支付流水 | 财务对账必需 | 🟡 P2 |
| **订单超时** | `orders` 表已建,**未实现超时取消 + 回滚订阅** 逻辑 | 支付安全 | 🟡 P2 |
| **pyarmor 加固 C18** | 混淆试点已完成(`cloud_gateway.py` + `obfuscate.py` + `build_services.ps1` 集成,pyarmor 缺失降级不破坏);**范围仅 1 模块**,license/订阅校验/token 双版本判定等加固项未上 | 防逆向辅助 | 🟢 P3 |
| **真机联调** | 云端 + 客户端全链路未跑;仅 `test_e2e.py` 走本地 `TestClient` | 阻塞发布 | 🔴 P0 |
| **PyArmor license 未启动** | 设计提到"双版本判定 + token 校验 + 订阅心跳"要加固;实际 pyarmor 未装 | 防逆向 | 🟢 P3 |

### 6.2 本地产品化未做项

| # | 项 | 影响 | 优先级 |
|---|---|---|---|
| **B7 残余** | SERVICE_REGISTRY 主结构已落地;遗留:`api_server.py` `/status` 列表未改、`get_service_launch`/env name 分支保留、需真机回归 stop_order 语义 | 打包可靠性(次要) | 🟡 P2 |
| **启动慢遗留** | B10 已从 26s 优化到 2–3s;**仍有 ~2s Hermes 冷启动残余**;可继续深挖但不阻塞上线 | 体验 | 🟢 P3 |
| **Hermes 归属** | §7 决策 7 "暂不定",C16a 只做通道适配;后续若纳入订阅需重做 | 长期决策 | 🟢 P3 |

### 6.3 代码/测试风险

- **C 类新代码全未提交**:14+ 未追踪/未提交文件;若工作区损坏无回退点
- **`cloud_service` 无 CI**:目前仅本地 `TestClient` 跑通 4 个 `test_*.py`;GitHub Actions 未加 cloud_service job
- **`ci.yml` 尚未覆盖 C 类**:仅守门 P5 subprocess 与 `.env` 死字段
- **prompt 库双份维护成本**:云端 `prompts.py` + 本地 `prompts_basic.py`;需统一版本 tag 对齐(未自动化)
- **PyInstaller + Python 3.13 兼容性**:评审文档列出但未验证(见 `_review_productization_v1.md` §9.2)
- **Electron + NSIS + 中文路径 + 无签名**:SmartScreen 提示未解决

### 6.4 外部依赖(阻塞上线)

| 项 | 周期 | 阻塞点 |
|---|---|---|
| 支付宝商户号申请 | 2–3 周 | C19 支付上线 |
| 微信商户号 + API 证书申请 | 2–3 周 | C19 支付上线 |
| 域名备案(若新域名) | 2–3 周 | C20 部署 |
| 云厂商账户合规审核 | 1 周 | C20 部署 |

**建议**:立刻并行启动商户号 + 备案申请(不占开发工时,但阻塞上线)。

### 6.5 长期 review(D 类,穿插)

- 6 模块前缀兼容层观察期后移除
- Easel `openclaw.json` 目录备份(不只文件)
- `openclaw@latest` pin 版本
- `paths.json` 加入 `.gitignore`
- health-check fast/full 分档完善
- 跨会话计划编号口径统一(避免 P0-P7 定义混乱)

---

## 7. 交接要点(给下一位 agent)

### 7.1 先读什么(按顺序)

1. **本文档** — `docs/dev-reports/2026-10-13-project-handover.md` — 30 分钟全局理解
2. **计划主文档** — `_plan_productization_saas.md` — §7 决策已拍板,§11 是任务清单
3. **C 类详细设计** — `docs/dev-reports/2026-10-13-saas-c-class-design.md` — 双版本架构 / 服务端模块 / 客户端改造
4. **整体评估** — `docs/dev-reports/2026-10-13-overall-assessment.md` — 上线可行性判断
5. **代码入口**:
   - 云端:`cloud_service/main.py`(挂 4 个 router 的入口)
   - Prompt:`cloud_service/llm_proxy/prompts.py`(`PromptDef` + `CLOUD_PROMPTS` / `BASIC_PROMPTS` + `sync_prompts_to_db`)
   - 双通道后端:`prism_backend/fusion_ai/cloud_gateway.py`
   - 双通道前端:`prism_frontend/src/lib/cloud-auth.ts`
   - 本地路径:`prism_backend/fastapi_app/core/paths.py`
6. **文档**:
   - `STARTUP.md`(启动,15–20 分钟)
   - `PACKAGING.md`(打包,7 阶段流程)

### 7.2 当前状态一句话

> 本地产品化(A/B 类)主体已完,P0-P5 主体 + review 批量 + C 盘防护 + B7 supervisor SERVICE_REGISTRY + B10 启动优化(26s→2-3s)已落地;3 个 commit 已入库。C 类 SaaS(用户体系 + 订阅 + LLM 代理 + 支付 + 双通道 + UI)主体已在本地跑通(**未提交**);C18 pyarmor 试点已上线(`cloud_gateway.py` + `obfuscate.py`,pyarmor 缺失时降级)。下一步是**云基础设施 + 真机联调 + 支付商户号 + pyarmor 加固扩展**。

### 7.3 下一步(推荐顺序)

**🔴 P0(阻塞上线)**
1. **提交 C 类工作区** — `cloud_service/` + 3 个 `fusion_ai/` 新文件 + 前端 5 个新文件 + 若干混合修改;否则无回退点
2. **C20 云基础设施** — 阿里云/腾讯云开通 ECS + RDS + Redis + 域名/HTTPS;1–1.5d
3. **C21 cloud_service 部署** — Nginx 反代 + Docker + 日志聚合 + 告警;1–1.5d
4. **真机联调** — 客户端 → 云端 → LLM → 支付全链路
5. **并行启动商户号申请**(支付宝 + 微信,2–3 周周期)
6. **并行启动域名备案**(若新域名)

**🟠 P1**
7. **B7 残余收尾** — `api_server.py` `/status` 列表切 registry + `get_service_launch`/env name 分支清理 + 真机回归 stop_order 语义;0.5–1d
8. **C 类 stream 支持** — `/cloud/llm/chat` 加 `stream=True` 分支
9. **CI 加 cloud_service job** — pytest + 部署前守门

**🟡 P2**
10. **支付退款 + 订单超时 + 每日对账** — 运营必需
11. **prompt 库双份同步自动化** — 版本 tag 对齐

**🟢 P3(上线稳定后)**
12. **C18 pyarmor 加固扩展** — 试点已完成(`cloud_gateway.py` 已上;`obfuscate.py` + `build_services.ps1` 集成完毕,pyarmor 缺失时降级跳过不阻塞);后续:范围扩到 token 校验 / 订阅心跳 / 双版本判定 / license 校验;需 pyarmor license(商业版),先跑 1–2 周观察再扩展
13. **启动残余优化** — 剩余 ~2s Hermes 冷启动
14. **Hermes 归属决策**(§7 决策 7 暂不定,待产品成熟)

### 7.4 特别提醒下一位 agent

- **仓库路径含中文**:`D:\dim开发\Prism-Fusion` — 命令要用 PowerShell 语法(`Set-Location` + 单引号,不是 `cd /d` + `&&`)
- **虚拟环境**:`prismenv/Scripts/python.exe`(3.11);不要 pip install 到系统 Python
- **C 类全未提交** — 提交前先 `git status --short` 看范围;建议按 §4.9 三层策略(背景/主线/混合)分层
- **测试入口**:`& prismenv\Scripts\python.exe -m pytest cloud_service -q`(需要 `-o 'testpaths=cloud_service'` 或 cd 到 cloud_service 目录,当前 pytest 自动发现会跳过)
- **启动后端**:见 `STARTUP.md`;当前启动 ~2–3s(已优化)
- **启动云端**:`cd cloud_service && uvicorn main:app --reload --port 8000`(本地 sqlite,生产切 RDS)
- **不要动 Hermes 内部代码**,只改 `prism_backend/fastapi_app/agent/hermes_*.py` 对接层
- **不要全局改名 "老马AI工作台" → "Prism-Fusion"**(历史包袱,`STARTUP.md` 明示)
- **`ci.yml` 硬守门** — subprocess 白名单外必红;`.env.example` 死字段必红;import 烟测已硬失败
- **提交时明确路径** — 避免 `git add -A` / `git add .`,按文件显式添加

### 7.5 关键文件速查

| 用途 | 路径 |
|---|---|
| 路径单一入口 | `prism_backend/fastapi_app/core/paths.py` |
| PyInstaller 顶层路径 | `prism_backend/_paths.py` |
| subprocess 封装 | `prism_backend/fastapi_app/utils/subprocess_safe.py` |
| Hermes config | `prism_backend/fastapi_app/agent/hermes_config.py` |
| Hermes 更新模板 | `prism_backend/fastapi_app/agent/hermes_update.py` |
| 云端入口 | `cloud_service/main.py` |
| 云端配置 | `cloud_service/settings.py` |
| LLM 代理 + Prompt | `cloud_service/llm_proxy/{router,prompts,llm_client}.py` |
| 支付 | `cloud_service/payment/{adapter,alipay,wechat}.py` |
| 双通道后端 | `prism_backend/fusion_ai/cloud_gateway.py` |
| 客户端 prompt 路由 | `prism_backend/fusion_ai/{prompt_router,prompts_basic}.py` |
| 前端 JWT/订阅 | `prism_frontend/src/lib/cloud-auth.ts` |
| 订阅心跳 | `prism_frontend/src/hooks/useLicenseHeartbeat.ts` |
| 订阅 UI | `prism_frontend/src/components/settings/cloud-subscription-card.tsx` |
| 登录页 | `prism_frontend/src/app/login/page.tsx` |
| supervisor 服务编排 | `desktop-electron/resources/supervisor/supervisor.py`(B7 已完成:SERVICE_REGISTRY 覆盖 7 服务,1553 行) |
| 打包脚本 | `scripts/packaging/build-package.bat` + `build_services.ps1` |

---

## 附:主要开发报告索引

| 文档 | 内容 |
|---|---|
| `docs/dev-reports/2026-10-13-project-handover.md` | **本文档** — 交接总纲 |
| `docs/dev-reports/2026-10-13-phase-A-progress.md` | 阶段 A(progress):P0-P5 + review 完成度 |
| `docs/dev-reports/2026-10-13-phase-A-verification.md` | 阶段 A 独立验证 + 修正 |
| `docs/dev-reports/2026-10-13-overall-assessment.md` | 整体评估 + 上线可行性 |
| `docs/dev-reports/2026-10-13-saas-decision-guide.md` | SaaS 7 决策选择题(给非技术方) |
| `docs/dev-reports/2026-10-13-saas-c-class-design.md` | C 类 SaaS 详细设计(双版本架构等) |
| `_plan_productization_saas.md` | 主计划 · §7 决策 · §11 任务清单 |
| `_review_productization_v1.md` | 产品化审阅(P0-P7 路线) |
| `STARTUP.md` | 新机器启动指南 |
| `PACKAGING.md` | 打包分发流程 |

---

*本文档基于 2026-10-13 工作区实际状态编写;下一位 agent 交接前先 `git status --short` 与本报告 §2.2/§2.3 对照,确认未提交项是否已收敛。*
