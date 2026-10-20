# Prism-Fusion 项目总览（老马AI工作台）

> **版本**：v1.1.0 · **日期**：2026-10-19 · **许可**：AGPL-3.0（Community）
>
> 面向项目维护者与新贡献者。所有能力细节可下钻到 [`docs/dev-reports/`](./dev-reports/) 中对应的具体报告。

---

## 1. 项目定位

**Prism-Fusion（老马AI工作台）是"AI 驱动的社媒矩阵投放闭环"桌面工作台** —— 覆盖「投-管-回-编」四大环节：素材投放、账号管理、数据回收、AI 编辑与生成。

- **客户端开源**（AGPL-3.0），**云端内核保留付费**（订阅 + 积分 + Hermes Agent）
- **对标对象**：CreBee / 易媒助手 / 聚媒通 / 澜途AI / FocusGEO —— 竞品头部全部闭源，Prism-Fusion 用 Open Core 抢占空白市场（详见 [open-core-strategy](./dev-reports/2026-10-16-open-core-strategy.md)）
- **技术差异化**：AI 内容生成 + Hermes Agent 编排 + 浏览器自动化 + Persona 指纹，四层叠加形成"发布矩阵 + AI 编排 + 抗风控"的组合能力

---

## 2. 核心能力矩阵

| 环节 | 能力 | 状态 | 说明 |
|------|------|:---:|------|
| **投** | 8 平台批量发布（抖音/B站/小红书/快手/TikTok/YouTube/视频号/百家号） | ✅ 已上线 | 定时 / 重发 / 矩阵账号 |
| **管** | 扫码登录 / Cookie 导入 / Persona 指纹隔离 | ✅ 已上线 | 客户端 patchright + 云端调度 |
| **回** | 抖音 / B站 / TikTok / YouTube 数据回收 | ✅ 已上线 | 通过 TikHub API 代理 |
| **编** | AI 生图（M1）+ AI 智能体风格训练（M2）+ 图片编辑（M5） | ✅ 已上线 | 客户端开源 + 云端 prompt |
| **AI 内核** | Hermes Agent / Hermes WebUI / LLM 代理 | 🔒 Pro | 消费 LLM token 的付费能力 |
| **视频流水线** | Easel 混剪 + 剪辑字幕封面 | ✅ 已上线 | 基础模板开源，高级模板付费 |

---

## 3. 技术栈

| 层 | 技术选型 | 说明 |
|----|---------|------|
| **前端** | Next.js 16（App Router）+ React 19 + TypeScript strict + Tailwind + shadcn/ui | 100+ 页面，282 vitest 用例 |
| **后端 API** | FastAPI + SQLAlchemy async + Celery + patchright | 40+ 子路由 |
| **云服务** | FastAPI + SQLAlchemy + Redis + Pydantic | 注册 / 登录 / 计费 / 支付 / LLM 代理 / feature gate |
| **桌面** | Electron 28.0.0 + electron-builder 24.13.3 + Inno Setup | Supervisor 管理 4 个后端服务 + Redis |
| **数据** | PostgreSQL 生产 / SQLite 本地 · Redis 用于限流与幂等 | 无 ORM 之外的复杂依赖 |
| **AI** | LiteLLM + LangChain + OpenAI SDK + LangGraph | 云端代理，客户端只暴露 API |
| **开源依赖** | ComfyUI（可选，独立进程）· fabric.js · react-image-crop · Unlayer | 客户端侧全部 MIT/Apache |

---

## 4. 五大复刻模块清单

澜途AI 5 大业务模块已在 Prism-Fusion 落地（对标 [lantyou-api-audit](./dev-reports/2026-10-16-lantyou-api-audit.md) + [module-replication-plan](./dev-reports/2026-10-16-module-replication-plan.md)）：

| 模块 | 功能 | 技术选型 | 测试 | 关键文件 |
|------|------|---------|------|----------|
| **M1 · AI 生图** | 5 provider（NanoBanana/DALL-E/Flux/Flux2/通义）+ ComfyUI 预留 + 积分预扣/实扣 | FastAPI + `image_generators.py`（复用现有）+ `ai_design.py`（新） | 后端 **74/74 PASS** + 前端 **255/255 PASS**（新增 61 用例） | [m1-implementation](./dev-reports/2026-10-16-m1-implementation.md) / [m1-frontend](./dev-reports/2026-10-16-m1-frontend.md) |
| **M2 · 智能体风格训练** | 上传样稿→LLM 抽取 style_prompt→生图注入；配额 limit=2；JWT 强制鉴权 | FastAPI + `ai_agents.py` + LLM 代理 + JSON 存储 | 后端 **102/102 PASS** · 前端 **193/193 PASS** | [m2-implementation](./dev-reports/2026-10-16-m2-implementation.md) |
| **M3 · 积分账本** | available/frozen/consumed 三段状态 + 5 档预设（≥1000 送 50%）+ 精确落账 | 自建 3 表（`credit_balance`/`credit_ledger`/`credit_pricing`），零第三方计费依赖 | **87/87 PASS**（51 原有 + 36 硬化） | [m3-implementation](./dev-reports/2026-10-16-m3-implementation.md) / [m3-hardening](./dev-reports/2026-10-16-m3-hardening.md) |
| **M4 · 场景向导** | 4 卡首页引导 + Wizard 状态机 + URL 同步 + Agent 选择步骤 | 纯前端（shadcn）+ `wizard-core.ts` 纯函数 | 前端 **193/193 PASS**（含 M4 46 用例） | [m4-implementation](./dev-reports/2026-10-16-m4-implementation.md) |
| **M5 · 图片编辑器** | 上传→裁剪（6 比例）→fabric 编辑（文字/形状/滤镜/撤销）→导出 | 纯前端 · fabric.js v7 + react-image-crop v11 | 前端 **122/122 PASS**（含 M5 13 用例） | [m5-implementation](./dev-reports/2026-10-16-m5-implementation.md) |

**技术决策要点**：
- ComfyUI 走**独立进程 + HTTP**接入以规避 GPL 传染（不合并源码，法务通说不触发传染）
- 全部 mock 测试，不真调商业 API；M3 未引入 Flexprice/Lago/OpenMeter 避免 AGPL 传染
- 前端严格遵循"UI 薄 + 逻辑厚"约定：所有派生/校验抽到 `lib/*.ts` 纯函数层，vitest 直接覆盖

---

## 5. Open Core 策略

**核心公式**（[open-core-strategy](./dev-reports/2026-10-16-open-core-strategy.md)）：

> 开源"能用但不够爽"的壳（发布/账号/素材/基础 AI）；付费"很爽但不可抄"的核（云端 prompt / Hermes / 数据 / 指纹）。fork 竞品拿不到云端 prompt + key + 数据。

### Community vs Pro 分层

| 能力 | Community（AGPL-3.0） | Pro（订阅 ¥99/月） |
|------|:---:|:---:|
| 账号上限 | 3 个 | 无限 |
| 平台覆盖 | 3 个（含抖音/B站/小红书） | 60+ |
| 积分额度 | 2000 免费 | 无限 + 充值 |
| AI 生图（基础） | ✅（自配 key） | ✅（云端代理） |
| AI 智能体配额 | 0 | 2（可扩） |
| Hermes Agent | ❌ | ✅ |
| Persona 指纹 | ❌ | ✅ |
| 数据回收 | 基础 | 全平台 |
| 团队管理 | 单人 | 多人 + 权限 |
| 视频流水线模板 | 基础 | 高级 |

### 实现要点

- **许可**：`LICENSE` = AGPL-3.0（Network Clause 是 Open Core 唯一护城河）
- **Feature Gate**：`cloud_service/billing/feature_gate.py` 提供 10 个 flag（`max_accounts` / `max_platforms` / `ai_mode` / `image_gen` / `agent_quota` / `data_recovery` / `persona` / `proxy_management` / `stream_chat` / `team_members`），端点 `/billing/flags` `/billing/feature/{name}` `/billing/quota/{feature}`
- **前端消费**：`plan-badge.tsx` + `plan-flags.ts` 消费 `/cloud/billing/feature-flags`，未登录/401/5xx 全降级为 Community 默认（详见 [frontend-badge-m4-agent](./dev-reports/2026-10-16-frontend-badge-m4-agent.md)）
- **打包隔离**：Community 独立 `package.community.json` + `installer-community.iss` + `build-community.ps1`，AppId 不同可与 Pro 共存（详见 [community-packaging](./dev-reports/2026-10-16-community-packaging.md) + [community-build-verify](./dev-reports/2026-10-16-community-build-verify.md)）

---

## 6. 商业闭环

**用户旅程**（一次完整交易）：

```
GitHub 下载 → 3 账号试玩 → 想更多 → 注册 → 2000 免费积分
                                                    ↓
    升级 Pro（¥99/月） ← 云端代理激活 ← AI 变聪明 + 数据回流 + 指纹防护
                                                    ↓
                                     AI 生图（1.5 积分/张）
                                                    ↓
                                     风格训练（M2 Agent，limit=2）
                                                    ↓
                                     矩阵发布 + 数据回收
                                                    ↓
                                     积分消耗 → 复充（¥10/¥50/¥100/¥300/¥500）
                                                    ↓
                                     赠送规则：≥1000 送 50%
```

**定价对标**：澜途AI 1 积分 = ¥0.10，AI 生图 1.5 积分 = ¥0.15/张（详见 [lantyou-api-audit](./dev-reports/2026-10-16-lantyou-api-audit.md)）。

**支付通道**：微信支付 + 支付宝（`cloud_service/payment/` 完整实现，含 webhook 回调 / 退款 / 对账）。

**授权制取舍**：Prism-Fusion 目前坚持**纯注册制 + SaaS**（`cloud_service.auth` JWT + `Subscription`），**无硬件绑定 / 无离线凭据**。如未来需要"私有化桌面"（企业版），可插拔引入 bidmaster 的 Ed25519 + 硬件指纹模块（工作量 5-8 人日，见 [authorization-vs-registration](./dev-reports/2026-10-16-authorization-vs-registration.md)）。

---

## 7. 健壮性保障

### 测试基线（2026-10-19 全绿）

| 层 | 用例数 | 状态 |
|----|:---:|:---:|
| M1 后端（AI 生图） | 74/74 断言 | ✅ |
| M1 前端（AI Studio） | 61 新 + 集成 | ✅ |
| M2 后端（Agents） | 102/102 断言 | ✅ |
| M3 后端（积分） | 87/87 断言（51 原 + 36 硬化） | ✅ |
| M4 前端（Wizard） | 46 用例 | ✅ |
| M5 前端（Editor） | 13 用例 | ✅ |
| 中危硬化专项 | 27/27 断言 | ✅ |
| Open Core 前端 flags | 27 新 + 集成 | ✅ |
| **前端 vitest 汇总** | **282/282 PASS** | ✅ |
| `tsc --noEmit` | 0 errors | ✅ |

**总计 600+ 断言全绿**，无破坏性回归。

### 已完成的中危/高危修复

| # | 问题 | 严重度 | 修复 |
|---|------|:---:|------|
| 1 | Redis `idempotency.acquire` get+set 非原子 | 中 | 改为 `SET NX EX` 一次原子写（10 并发下 provider 只调用 1 次） |
| 2 | SQLite `with_for_update()` no-op | 记录 | 生产切 MariaDB 自动生效；本地依赖 Redis 幂等键 + 单进程 |
| 3 | `user_id` 信任 body / Bearer 裸串 | 中 | 引入 `_decode_jwt_sub`，Bearer 存在则强制校验，env `M1_REQUIRE_JWT=true` 关闭回退 |
| 4 | prompt 未长度上限 | 中 | `_MAX_PROMPT_LEN=10000`，超限 400 |
| 5 | `allow_origins=["*"]` | 中 | 改为 `CORS_ORIGINS` env 白名单，禁止 `*` |
| 6 | 高频端点无限流 | 中 | 新增 `RateLimitMiddleware`（Redis INCR+EXPIRE）：freeze/consume=20/min，generate=10/min |
| 7 | M2 agent 端点信任 `?user_id=` | 高 | 强制 Bearer JWT，6 种 401 覆盖（garbage / expired / refresh-type / no-sub / query / body） |
| 8 | M1 SQL 参数错位（真实 bug） | 高 | `insert_record` 参数元组与 SQL 列顺序错位一列，已修正 |
| 9 | M3 预设档语义模糊 | 严重 | 扁平 float 数组 → 显式 dict `{points, bonus_points}`；`Order.plan='credit'` 通过 schema；`Order.credit_points` 精确落账 |

**详细清单**：见 [global-hardening-audit](./dev-reports/2026-10-16-global-hardening-audit.md) · [medium-hardening](./dev-reports/2026-10-16-medium-hardening.md) · [m2m4-hardening](./dev-reports/2026-10-16-m2m4-hardening.md) · [m3-hardening](./dev-reports/2026-10-16-m3-hardening.md)。

### 数据库迁移要点

- **M3 三张新表**：`credit_balance` / `credit_ledger` / `credit_pricing`，`UNIQUE(pricing_key, pricing_version)` 支持热更新价目
- **`orders` 表变更**：`days` 改为 `Optional[int]`（NULL 允许），新增 `credit_points: Optional[float]`
- **老库部署前必跑**：
  ```sql
  -- PostgreSQL
  ALTER TABLE orders ALTER COLUMN days DROP NOT NULL;
  -- MySQL
  ALTER TABLE orders MODIFY COLUMN days INT NULL;
  ```

---

## 8. 部署状态

| 项 | 状态 | 备注 |
|----|:---:|------|
| 服务器 | ✅ **active running** | OpenCloudOS 9.6，IP 101.43.65.216，`cloud_service` :8091 |
| 数据库迁移 | ✅ 完成 | 3 张 credit 表 + orders 表结构变更已应用 |
| Community 打包（dir） | ✅ 通过 | `dist-community/` = 1.61 GB，20 项关键资源齐全，用时 30.7 s |
| Community 打包（NSIS） | ⏸️ 未验证 | 551 MB 耗时过长，未跑端到端（脚本语法已通过，Inno 未编译） |
| 前端 standalone | ✅ 45.49 MB | 29 routes 已 prerendered |
| Pro 版打包 | ⏸️ 未受影响 | `package.json` / `installer.iss` 未改动 |
| GitHub CI | ✅ 就绪 | 6 硬门 job 并行，预计 8-12 分钟 |
| Open Core 前端 flags | ✅ 消费完成 | 10 flag + Badge + Agent 下拉，282/282 PASS |

**关键路径产物**：`desktop-electron/package.community.json`（本次已从 package.json 风格**重构为扁平 build 配置**，元信息迁入 `extraMetadata`）· `desktop-electron/build-community.ps1`（8 参数齐全）· `desktop-electron/installer-community.iss`（AppId 独立）。

---

## 9. 文档索引（25 份 dev-reports）

用 `glob docs/dev-reports/2026-10-16-*.md` 校验，实际共 **25 份**（任务描述"17 份"的清单遗漏了 8 份；`feature-flag-client.md` 未单独成文）。按主题聚类：

### 战略与调研（3）
| 报告 | 一句话说明 |
|------|-----------|
| [open-core-strategy](./dev-reports/2026-10-16-open-core-strategy.md) | Open Core 商业化分层（8 竞品对标 + Community/Pro 定价 + Phase 1-3 路线） |
| [github-reference-audit](./dev-reports/2026-10-16-github-reference-audit.md) | 5 模块开源方案调研（ComfyUI / promptfoo / Flexprice / Trigger.dev / Unlayer） |
| [lantyou-api-audit](./dev-reports/2026-10-16-lantyou-api-audit.md) | 澜途AI API 逆向（积分制 / 计费契约 / 5 模块复刻参考） |

### 方案与实现（7）
| 报告 | 一句话说明 |
|------|-----------|
| [module-replication-plan](./dev-reports/2026-10-16-module-replication-plan.md) | 5 模块复刻总方案（22-24 人日估算 + 技术选型 + 目录约定） |
| [m1-implementation](./dev-reports/2026-10-16-m1-implementation.md) | M1 AI 生图后端（5 provider + 积分预扣/实扣，74/74 PASS） |
| [m1-frontend](./dev-reports/2026-10-16-m1-frontend.md) | M1 前端 AI Studio（`/fusion/image-studio`，61 新用例） |
| [m2-implementation](./dev-reports/2026-10-16-m2-implementation.md) | M2 智能体风格训练（LLM 抽取 + 配额 + JWT，102/102 PASS） |
| [m3-implementation](./dev-reports/2026-10-16-m3-implementation.md) | M3 积分账本（3 张表 + 5 档预设，51/51 PASS） |
| [m4-implementation](./dev-reports/2026-10-16-m4-implementation.md) | M4 场景向导（4 卡 Wizard + URL 同步，46 用例） |
| [m5-implementation](./dev-reports/2026-10-16-m5-implementation.md) | M5 图片编辑器（fabric + react-image-crop，13 用例） |

### 健壮性（4）
| 报告 | 一句话说明 |
|------|-----------|
| [global-hardening-audit](./dev-reports/2026-10-16-global-hardening-audit.md) | 全局健壮性审查（10 维度矩阵 + M1 6 条 FAIL 修复，140/140 PASS） |
| [m3-hardening](./dev-reports/2026-10-16-m3-hardening.md) | M3 硬化（预设档 schema + Order.credit_points 精确落账，87/87 PASS） |
| [m2m4-hardening](./dev-reports/2026-10-16-m2m4-hardening.md) | M2 JWT 强制 + M4 Suspense + Agent 选择步骤接入 |
| [medium-hardening](./dev-reports/2026-10-16-medium-hardening.md) | 6 项中危修复（幂等原子化 / prompt 上限 / CORS 白名单 / 限流） |

### Open Core 落地（3）
| 报告 | 一句话说明 |
|------|-----------|
| [open-core-implementation](./dev-reports/2026-10-16-open-core-implementation.md) | AGPL-3.0 + feature_gate（10 flag）+ 3 只读端点实现 |
| [community-packaging](./dev-reports/2026-10-16-community-packaging.md) | Community 独立打包配置（AppId 隔离 / Hermes 剔除 / 8 步脚本） |
| [community-build-verify](./dev-reports/2026-10-16-community-build-verify.md) | 打包端到端验证（standalone 45.49 MB / dir 1.61 GB / 30.7 s） |

### 前端体验（1）
| 报告 | 一句话说明 |
|------|-----------|
| [frontend-badge-m4-agent](./dev-reports/2026-10-16-frontend-badge-m4-agent.md) | PlanBadge + AgentPickerStep 打通（282/282 PASS + 27 新用例） |

### 治理与开源发布（3）
| 报告 | 一句话说明 |
|------|-----------|
| [github-release-prep](./dev-reports/2026-10-16-github-release-prep.md) | GitHub 开源准备（CONTRIBUTING + 5 模板 + CI 硬门） |
| [authorization-vs-registration](./dev-reports/2026-10-16-authorization-vs-registration.md) | 授权制 vs 注册制取舍（bidmaster Ed25519 vs Prism-Fusion 纯 SaaS） |
| [rea-capability-assessment](./dev-reports/2026-10-16-rea-capability-assessment.md) | REA 6.5.0 能力评估（确认 Web/JS 工具链可用，非原生二进制工具不配置） |

### 部署与早期探查（4）
| 报告 | 一句话说明 |
|------|-----------|
| [server-access-and-deploy-prep](./dev-reports/2026-10-16-server-access-and-deploy-prep.md) | 服务器访问与部署准备 |
| [startup-residual-optimization](./dev-reports/2026-10-16-startup-residual-optimization.md) | 启动残余优化 |
| [celery-consumption-probe](./dev-reports/2026-10-16-celery-consumption-probe.md) | Celery 消费路径早期探查 |
| [plan-numbering-glossary](./dev-reports/2026-10-16-plan-numbering-glossary.md) | 计划编号口径说明（P0-P7 / A-D 类 / C1-C21 编号关系） |

> **注**：任务清单中提到的 `feature-flag-client.md` 未单独成文——前端消费 10 flag 的能力已并入 [open-core-implementation](./dev-reports/2026-10-16-open-core-implementation.md) 与 [frontend-badge-m4-agent](./dev-reports/2026-10-16-frontend-badge-m4-agent.md)。`celery-consumption-probe.md` 与 `server-access-and-deploy-prep.md` 为早期探查，未列入原任务清单但实际存在。

---

## 10. 遗留问题（按优先级 & 是否需要 K）

> "需要 K" = 需要 K 端介入（KMS / 服务器 / 法务 / 商务 / 支付通道），非代码工作；
> "不需要 K" = 纯工程任务，可继续开发推进。

### 高优先级

| # | 问题 | 类型 | 说明 |
|---|------|------|------|
| 1 | **真实联调** | 需要 K | M1-M5 目前全部 mock 测试；需要 K 提供：真实 LLM key / 真实 ComfyUI GPU / TikHub key / 支付沙盒商户号 |
| 2 | **GitHub 开源发布** | 需要 K | 建仓 / fork、清理 `.git/config` token、`gitleaks` / `truffleHog` secret 扫描、法务确认 AGPL 边界、发布前 commit 审计 |
| 3 | **ComfyUI GPL 传染** | 需要 K（法务） | 当前方案：独立进程 + HTTP，通说不传染；商业化前建议咨询 IP 律师。严格合规场景可切 Replicate / RunPod |
| 4 | **JWT 密钥共享** | 需要 K（运维） | 生产 `cloud_service/.env` 与 `fastapi_app/.env` 必须共享同一 `JWT_SECRET`（或 `CLOUDJWT_SECRET` / `CLOUD_SECRET_KEY` / `SECRET_KEY`），当前仅本地开发一致 |
| 5 | **Redis 高可用** | 需要 K（运维） | 限流依赖 Redis；无 Redis 时 `fallback_allow=True`（放行 + warning）。生产需监控 `[RateLimit] Redis unavailable` 告警 |

### 中优先级

| # | 问题 | 类型 | 说明 |
|---|------|------|------|
| 6 | `M1_REQUIRE_JWT` 默认 false | 不需要 K | 保留 body.user_id 兼容路径以不破坏 140 条 M1 测试；前端全面接入 JWT 后应翻到 true |
| 7 | M3 老订单回填 | 不需要 K | 已支付老积分订单 `credit_points=NULL`；可跑 `UPDATE orders SET credit_points = amount * points_per_yuan WHERE plan='credit'` |
| 8 | M1 provider 扩展 | 不需要 K | IMAGE_EDIT / PRODUCT_ANALYSIS 未实现；gpt-image-1 edit 需扩展 `image_generators.py` |
| 9 | ComfyUI provider 未接入 | 不需要 K | 复刻方案 M1 提到 `comfyui_client.py`，GPU 未就绪；接入需 1-2 人日 |
| 10 | M4 场景 Wizard 步骤占位 | 不需要 K | AI 写稿/生图/视频流水线的 4 步目前只做 UI 骨架；真实业务接入需接 M1/M3/M2 后端 |
| 11 | M5 图片上传到素材库 | 不需要 K | 当前仅本地裁剪+导出；`/api/v1/files/upload` 可复用 |
| 12 | M2 LLM 抽取质量 | 不需要 K | `_STYLE_EXTRACT_SYSTEM` 是通用模板，未 few-shot；生产拉 3-5 组澜途真实样例提升抽取质量 |
| 13 | M1/M2 状态污染（老问题） | 不需要 K | `test_ai_design_generate_all` / `test_ai_design_pagination` / `test_ai_design_idempotency` 依赖进程内共享 store；加 fixture 或 `@IsolatedTest` decorator |
| 14 | `test_payment_leftover.py` flaky | 不需要 K | Redis 不可达降级 lock-free 后偶发 1 次；与本轮无关联，可加 `xfail` 或改造时序断言 |
| 15 | M1 前端 `pricing` 端点硬编码 | 不需要 K | 前端 `1.5 积分/张` 硬编码；`PointsClient.get_pricing` 失败也回落此常量。若需动态展示需加 `GET /cloud/points/pricing` |
| 16 | `PlanBadge` 只查 4 个 flag | 不需要 K | 当前低频无感；如做"实时"需改为 `load()` 定时刷新 |
| 17 | `agentLocked` 只信 PlanBadge 派生 | 不需要 K | 应统一从 feature_gate 单一权威取数；当前 M2 `/quota` 与 PlanBadge 双源存在漂移风险 |

### 低优先级 / 待观察

| # | 问题 | 类型 | 说明 |
|---|------|------|------|
| 18 | CI `frontend-lint-test` 首次运行 | 不需要 K | 未在 GitHub Actions 上跑过；首次红先本地 `npx tsc --noEmit` 排查 `.next/types` 未生成的误报 |
| 19 | CI `backend-selftest` 依赖安装耗时 | 不需要 K | `requirements.txt` 覆盖全依赖，pip 需 5-10 分钟；可拆 `requirements-test.txt` |
| 20 | `test` job 软门转硬门 | 不需要 K | SaaS 化改造补 conftest 隔离后再转 |
| 21 | Community NSIS 端到端打包 | 不需要 K | 551 MB 耗时过长，本次未跑；首次真正发布前建议在干净环境跑一次 |
| 22 | electron-updater 双版本共存 | 不需要 K | Pro/Community 若共用 GitHub Release，`latest.yml` 会互相覆盖；建议分仓库或分 channel |
| 23 | Code 签名未接入 | 不需要 K | `-SignInstaller` 参数已预留但未实现；生产发布前配置证书 |
| 24 | M5 前端 jsdom canvas | 不需要 K | 项目默认 `environment: "node"`，未装 `node-canvas`；DOM 相关分支需浏览器端手工或 e2e 覆盖 |
| 25 | 未做视觉回归 | 不需要 K | 全部只跑 tsc + vitest；建议发布前 `next dev` 服务器端人工确认 Badge 展开/折叠、Community/Pro 状态、AgentPickerStep 3 分支 |

### 需要决策但非阻塞

- **M2 style_profile 存储**：当前 JSON，未来是否迁移到数据库表（`style_profiles`）？
- **积分有效期**：澜途目前无过期，Prism-Fusion 也未实现；若加入期策略需 `CreditLedger.expire_at` 字段
- **Team Plan**：Open Core 预留 `team_members` flag，未来如加 Team 单位需扩 plan 枚举（当前 normalizeFlags 遇 team 会兜底为 community）

---

## 11. 下一步

### Phase 1（近期，工程可独立推进）

1. **前端全面接入 JWT** → 翻 `M1_REQUIRE_JWT=true`，M1 移除 body.user_id 回退
2. **M2 style_profile 迁移到数据库**（如需要跨用户 / 团队共享）
3. **补齐 M5 DOM 交互测试**（引入 `@testing-library/react`，与 M4 一致的取舍可延后）
4. **补 M1 provider 的 IMAGE_EDIT / PRODUCT_ANALYSIS**（gpt-image-1 edit 已有 SDK 支持）
5. **M4 Wizard 步骤接入真实业务**（AI 写稿→M1 生成，视频流水线→Easel 后端）

### Phase 2（需要 K 介入）

1. **真实联调**：K 提供 LLM key / ComfyUI GPU / TikHub key / 支付沙盒商户号，跑端到端
2. **生产 Redis 部署** + 密钥分发（`JWT_SECRET` 共享）
3. **`gitleaks` / `truffleHog` 全仓扫描**，清理任何潜在 secret
4. **法务确认**：AGPL 边界（独立进程是否传染）+ 与 MIT/Apache 上游依赖兼容
5. **GitHub 建仓**：确认目标仓库、清理 `.git/config`、发布前 commit 审计
6. **GitHub Actions CI 首次跑**：修 `frontend-lint-test` / `backend-selftest` 首次运行问题

### Phase 3（后续功能扩展）

1. **ComfyUI 后端接入**（`comfyui_client.py`，1-2 人日）
2. **21 种图片类型扩展**（当前只做 4 种常用：封面/配图/海报/白底）
3. **M3 积分有效期策略**（`CreditLedger.expire_at`）
4. **Team Plan + 多租户**（扩 plan 枚举 + `team_members` flag 真正启用）
5. **私有化授权制**（可选，5-8 人日，参考 [authorization-vs-registration](./dev-reports/2026-10-16-authorization-vs-registration.md)）
6. **Discussions 社区 + Docs GitHub Pages**（Open Core Phase 3 运营）

---

## 附录：关键路径速查

```bash
# 前端
cd prism_frontend && npm ci && npx tsc --noEmit && npx vitest run

# 后端
cd prism_backend && python tests/test_m1_ai_design.py
cd prism_backend && python tests/test_m2_agents.py
cd cloud_service && python test_points.py

# Community 打包（dir 模式）
cd desktop-electron && npx electron-builder --config package.community.json --win --x64 --dir
```

**相关文档**：
- [docs/architecture/target-architecture.md](./architecture/target-architecture.md) · 目标架构
- [`docs/dev-reports/`](./dev-reports/) · 全部 17 份 dev-reports
- [`docs/dev-reports/2026-10-13-deployment-guide.md`](./dev-reports/2026-10-13-deployment-guide.md) · 早期部署指南

> **注**：`docs/strategy/open-core.md`（open-core-implementation 报告提到）实际未落库，策略基线以 [open-core-strategy](./dev-reports/2026-10-16-open-core-strategy.md) 报告为准。

---

*本文档整合自 17 份 2026-10-16/17/18/19 的 dev-reports，作为项目维护者的入口索引。任何细节以对应 dev-report 原文为准。*
