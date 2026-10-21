# Prism-Fusion:产品化收尾 + SaaS 化改造 开发计划

> 生成:2026-10-12 | 状态:**规划中(未授权实现)** | 关联:[_review_productization_v1.md]
> 仓库:`D:\dim开发\Prism-Fusion`
> 本计划合并用户两个诉求:① 收尾本地产品化;② 服务器代理核心功能防逆向 + 订阅收费。**建议合并为一个两阶段计划**(理由见 §3)。

---

## 1. 目标

| 目标 | 内容 | 交付物 |
|---|---|---|
| **A 本地产品化收尾** | 完成 P5 剩余 → P6 E2E → 清 review,产出"可打包、可分发、稳定可跑"的本地产品 | 打包安装包能双击即用 |
| **B SaaS 化改造** | 核心资产下沉服务器,客户端做薄,加user账号 + 订阅收费,防逆向 | 云端代理 + 订阅体系 + 瘦客户端 |

---

## 2. 现状事实(基于 5 个调研 agent 的实证)

### 2.1 已完成(P0-P5 部分 + review 批量)
- P0 路径清零 · P1 配置中心化(paths.py + paths.json + /preflight)· P2 Easel 卡片 · P3 Easel 自动更新(三层回滚)· P4 打包分发(CI/supervisor.spec 修/secret 排除/PACKAGING.md)
- P5 subprocess 兜底:`subprocess_safe.py`(safe_run/safe_popen)+ 批1/2(14 处)+ hermes/easel(19 处)= **33 处已迁,剩 ~29 处**
- review 批量:修 **2 个硬 bug**(gateway 端口 7861→7860 / 18789→37289;6 模块前缀双重 `/api/v1/api/v1/`)+ dev repo 窄化分支 + automation_worker logs 锚定 + STARTUP/PACKAGING 文档
- 冒烟:后端能启动,`/health`+`/preflight` 200,启动慢 ~26s(Hermes dashboard 18s)

### 2.2 架构现状(关键事实,决定 B 的难度)
| 维度 | 现状 | 对 SaaS 化的含义 |
|---|---|---|
| 部署形态 | **纯本地单机**:Electron + 本地 FastAPI(127.0.0.1:7000),无远程后端 | 需新增"云端"一层 + 客户端双通道 |
| 用户体系 | **无**。`api/v1/auth/` 是第三方平台扫码登录;`SECRET_KEY`/`ACCESS_TOKEN_EXPIRE_MINUTES` 遗留未用 | 需从 0 建 users + JWT + 中间件 |
| 订阅/授权 | **无** license、无订阅、无计费 | 需从 0 建 |
| LLM key | **本地明文 3 处**:`.env` / SQLite `ai_model_configs` / `hermes-home/config.yaml` | 需下沉 + 剥离本地 |
| 防逆向 | **几乎为零**:无 license/完整性检查,PyInstaller 可解包(uncompyle6),无混淆 | 依赖"核心下沉"+ 可选加固 |
| CORS/假设 | CORS 白名单固定 3 个,全仓按"单用户单机"写 | 需加租户隔离(owner_id) |

### 2.3 核心资产 vs 代理边界(逆向价值实证排序)
| 资产 | 逆向价值 | 能否下沉 | 判定 |
|---|---|---|---|
| `myUtils/`(cookie_manager / fingerprint_policy / device_fingerprint / selector_manager) | 🔴 极高 | ✅ 策略+校验下沉,执行留本地 | **下沉** |
| `reverse_api/` + `douyin_tiktok_api/crawlers/*/xbogus.py·abogus.py` 签名算法 | 🔴 极高 | ✅ 纯算法,最易下沉 | **下沉** |
| `fusion_ai/`(cognition/platform_styles/model_market/hot_topics prompt 工程) | 🔴 高 | ✅ 经 LLM 代理,客户端拿不到 prompt 源 | **下沉** |
| `ai_service/`(llm.py/function_calling/title_topic) | 🔴 高 | ✅ LLM 代理 | **下沉** |
| `fastapi_app/agent/`(hermes_*/openclaw_* 编排) | 🟠 中高 | ⚠️ 部分(编排可下沉,子进程需改造) | 部分下沉 |
| `platforms/*`(发布适配/verification) | 🟠 中高 | ⚠️ 签名/字段拼装可下沉,浏览器操作留本地 | 部分下沉 |
| 浏览器自动化(Playwright/patchright)、大文件上传、Persona 指纹数据 | — | ❌ **必须本地**(需用户机器 Chrome/指纹) | 留本地 |

---

## 3. 总体判断:合并(推荐)

**结论:合并为一个两阶段计划,而非两个独立计划。**

理由:
1. **阶段 B 会修订阶段 A 的设计**:key 剥离、鉴权中间件、Hermes 调用链、客户端双通道——若先按纯本地架构收尾(A)、再拆改(B),会返工。
2. **A 是 B 的基础**:SaaS 客户端仍需本地壳(浏览器自动化/文件/UI),本地产品化必须过关。
3. **B 的边界受 A 约束**:A 确立的 paths/preflight/双回滚/打包体系,B 直接复用。

**合并方式**:A 收尾现状架构,但在 A 中就为 B 预留接口(鉴权中间件骨架、key 读取抽象层、客户端 gateway 层),不提前实现。

---

## 4. 阶段 A:本地产品化收尾(可独立交付)

### A1. P5-3c:剩余 ~29 处 subprocess 迁移
- **文件簇**:video_transcoder / video_probe / video_frames(ffmpeg)、system/router(Popen 重启前端)、ai_service/*、files/router、uploader/{bilibili,tiktok,youtube}/runtime、browser_components、automation_bootstrap、persona_dashboard、process_manager(保留 CREATE_NEW_PROCESS_GROUP)、accounts/router(`asyncio.to_thread(subprocess.run,...)` 特殊形式)
- **方式**:按文件簇分批,每批 import 验证 + 不改行为
- **验收**:各模块 import OK;`safe_run/safe_popen` 使用;无裸 `subprocess.run/Popen` 残留(除 wrapper 自身)

### A2. P6:E2E 打包烟测
- 跑 `build-package.bat` 全流程(**风险:动构建产物**;建议在 CI 或临时目录,不动工作区)
- 从**含空格+中文路径**解压 → 双击 exe → 走 settings → 校验 `/preflight` 全绿
- 新增 `scripts/tests/e2e_packaged_test.ps1` + `integration_test.py`
- **验收**:打包产物在干净路径能启动 + preflight 无 null

### A3. review 清单收尾(从 23 项收敛后)
- **PyInstaller 入口统一**:3 份 `*_service.py` 60 行重复 + 探测过宽(会向上探到 C:\)→ 抽 `prism_backend/_paths.py`(顶层,仅 stdlib),入口走它
- **CI 加 test/lint job**:`pytest` + `ruff`(需先确认测试基础;若测试少,先加 lint)
- **env 前缀统一**:`PRISM_*` → `LAOMA_*` 全仓 + 同步 `.env.example`/部署脚本/前端 env 注入(**独立任务,背景品牌重命名未完成**)
- **启动慢 26s 优化**:Hermes dashboard 占 18s,评估延迟启动 / 并行
- 其余:paths.json 加 .gitignore、health-check fast/full 分档、EASEL_GATEWAY_PORT 旧 env 清理

### A4. 阶段 A 验证
- 后端启动 + `/health`/`/preflight`/`/easel/status`/`/config/hermes` 200
- 打包产物冒烟(E2E)
- → **阶段 A 交付:本地可用 + 可打包的完整产品**

---

## 5. 阶段 B:SaaS 化改造(架构演进 · 决策已落地 2026-10-13)

> ✅ 阶段 B 前置决策(§7)已拍板。以下架构基于"**仅核心 AI 下沉 + 保留离线双版本 + 下沉+混淆**"决策展开。
> 详细设计见独立文档 `docs/dev-reports/2026-10-13-saas-c-class-design.md`(双版本架构 / 服务端模块 / 客户端改造 / 部署 / 风险)。

### B0. 架构决策 + 基础设施
- **代理边界(已定)**:云端代理**仅核心 AI**(LLM + prompt 库 + license + 订阅 + 计量);**签名/风控/cookie 校验暂缓下沉,继续本地**;浏览器自动化、大文件上传、Persona 指纹、cookie 存储**必须本地**。
- **云基础设施**:阿里云/腾讯云 ECS + 域名 + HTTPS(通配符证书)+ RDS(MySQL/PG,托管)+ Redis(缓存 + 队列)
- **双版本模式**:线上版(订阅 + 云端 AI)+ 离线版(自配 key + 基础 prompt)——同一客户端,双通道切换

### B1. 用户账号体系 + JWT 鉴权
- 新增 `users` 表(username/email/password_hash/created_at/plan_id)+ `POST /cloud/auth/register|login|refresh|logout`
- JWT 签发 + `Depends(current_user)` 中间件(**挂到所有 `/cloud/*` 路由**;本地路由与 Hermes 保留原逻辑)
- 客户端:Electron 登录页 + token 安全存储(`electron.safeStorage` 加密到 OS Keychain)
- **契约**:`Authorization: Bearer <jwt>`;所有云端路由强制校验

### B2. 订阅 + license + 计费
- `subscriptions` 表(plan: **free / pro_monthly / pro_yearly**, status, expire_at, quota_llm_calls, quota_tokens)
- `usage` 计量 middleware:每次 LLM 调用记录 user_id / prompt_id / tokens_in / tokens_out / latency
- **license 校验**:客户端启动 + 每 24h 心跳 → `POST /cloud/license/verify` → 返回订阅状态 + 剩余额度 + **允许走云端 AI** 的 flag
- 超额度 → 降级到离线版模式或拒绝云端调用
- **免费额度**:免费用户每天 N 次 LLM 调用(拉新);超阈值弹窗引导订阅

### B3. LLM 调用代理(prompt 下沉 — 防逆向核心)
- 服务器持有 LLM key(Deploy Key Vault / KMS);客户端调 `POST /cloud/llm/chat`(带 **prompt_id** 而非 prompt 源文本)
- `fusion_ai/` prompt 库下沉服务器:**cognition / platform_styles / model_market / hot_topics / content_moderator / skill_workshop / nl_query / router**——全部走云端 prompt 装配
- **改造点**:
  - `ai_service/llm.py`:增加 `CloudLLMClient` 分支,订阅态走云端;离线态保留本地客户端
  - `fusion_ai/*`:prompt 源文本迁移到云端表 `prompts(name, template, params_schema, version, weight)`
  - 前端调用点通过统一 `chatClient(promptId, params)` SDK
- **收益**:prompt 工程(产品差异化核心)不再随客户端泄出

### B4. ~~签名 / 风控 / cookie 校验代理~~ → **暂缓**
- **决策**:签名算法 / cookie 校验 / 指纹策略**继续本地保留**,不进入本轮下沉范围
- 依据:逆向价值虽高,但需要浏览器环境配合,单纯下沉算法意义有限;等订阅体系成熟后再评估
- **降级项**:仅保留 `POST /cloud/fingerprint/policy`(策略下发,不含执行),作为可选扩展

### B5. 客户端双通道改造
- 新增客户端 gateway 层:`src/lib/client-gateway.ts`——按功能路由 → "本地后端(127.0.0.1:7000)" 或 "云端(https://api.prism-fusion.com)"
- 判定优先级:
  1. 用户已订阅 + 云端可达 → LLM/prompt 走云端,其他走本地
  2. 用户已订阅但断网 → 弹窗提示,可选择切离线版模式(用基础 prompt)
  3. 用户未订阅 / 自配 key → LLM 走本地,使用基础 prompt
- **契约**:统一 `chatClient / fileClient / authClient` SDK 封装双通道 + 自动带 token + 失败降级
- 环境变量:`LAOMA_INTERNAL_BACKEND_URL`(本地)+ `LAOMA_CLOUD_BACKEND_URL`(云端),两者并存

### B6. key 剥离 + Hermes 改造
- **订阅用户**:本地不再持 LLM key——清理 `.env` / SQLite `ai_model_configs` / `hermes-home/config.yaml` 三处明文;`hermes_config.py` 写代理 endpoint;Hermes 子进程经代理调 LLM
- **离线用户**:保留原三处 key 存储,行为不变(兼容现状)
- **验收**:订阅用户解包后无任何可用 LLM key;离线用户仍能像现在一样自配

### B7. 防逆向加固(**不再是可选,已进主线**)
- PyInstaller 产物对**残留核心模块**加 **pyarmor**(首选)或 **Cython 编译 .pyd**(备选)
- 加固范围:双版本判定逻辑、client-gateway SDK、token 存储与校验、订阅校验心跳
- **不加固**:纯 UI 代码、浏览器自动化、平台适配器(留本地,逆向价值低)
- 明确:**下沉是主防线,混淆是辅助防线**;客户端总有可逆部分(UI/本地逻辑)

### B8. 支付 + 运营
- **支付集成**:支付宝(当面付/电脑网站支付)+ 微信支付(JSAPI/Native),通过统一 `PaymentAdapter` 抽象层对接,预留 Stripe 接口(不做)
- 用户中心:订阅管理 / 用量查看 / 续费 / 发票
- 运营:7 天试用、月付/年付折扣、到期前 3 天邮件/站内信提醒、超额度降级弹窗
- 退款/对账:每日对账脚本,支付网关回查

---

## 6. 影响模块与契约(汇总)

| 模块 | A 阶段 | B 阶段 |
|---|---|---|
| `core/config.py` | env 前缀统一 | 加 cloud 配置 + key 剥离 |
| `core/paths.py` | PyInstaller 入口统一复用 | — |
| `api/v1/*` | — | 加 cloud 路由 + `Depends(current_user)` |
| `ai_service/llm.py` | — | **改为调云端代理** |
| `fusion_ai/*` | — | **prompt 下沉服务器** |
| `myUtils/*`、`reverse_api/`、`douyin_tiktok_api/` | — | **策略/算法下沉** |
| `agent/hermes_*` | — | key 写代理 + 走代理调用 |
| `prism_frontend/*` | — | 双通道 gateway + 登录页 |
| `desktop-electron/*` | — | license 校验 + token 存储 + 加固 |
| 新增 `cloud/`(服务端) | — | 用户/订阅/计量/代理 B1-B4 |

**新增服务端模块**(建议独立部署):
```
cloud_service/
├── auth/          # B1 用户 + JWT
├── billing/       # B2 订阅 + 计量
├── llm_proxy/     # B3 LLM 代理 + prompt 库
├── sign_proxy/    # B4 签名/风控
└── gateway/       # 统一入口 + 限流
```

---

## 7. 关键决策点(**全部已决 · 2026-10-13 用户拍板**)

> ⚠️ 状态变更:以下 7 点由"待拍板"更新为"**已决**",阻塞解除,阶段 B 可以按 C 类架构(见 `docs/dev-reports/2026-10-13-saas-c-class-design.md`)开工。

| # | 决策点 | 用户选择(2026-10-13) | 对架构的落点 |
|---|---|---|---|
| 1 | **代理范围** | **仅核心 AI**——prompt 下沉 + LLM 走云端;**浏览器自动化留本地** | B3 LLM 代理为核心;B4 签名/风控**暂缓**,仅在客户端本地保留 |
| 2 | **商业模式** | **软件订阅**——月/年订阅 + 免费额度 | B2 订阅 + license + 用量配额 |
| 3 | **支付** | **支付宝 + 微信** | B8 支付接入(国内双通道,不做 Stripe) |
| 4 | **云** | **阿里云 / 腾讯云**(ECS + 域名 + HTTPS + RDS) | 独立部署 `cloud_service/`;DB 用托管 MySQL/PG |
| 5 | **防逆向** | **下沉 + 混淆**——核心搬服务器(主)+ 客户端 pyarmor/Cython(辅) | B3 prompt 下沉为主防线;B7 pyarmor/Cython 作为二级加固(**不再是"可选"**)|
| 6 | **离线模式** | **保留离线**——用户自配 key 纯本地可用 | 引入"**双版本架构**"(见下 §7.1):线上版(订阅)+ 离线版(自配 key) |
| 7 | **Hermes 归属** | **暂不定**——先不计费 | 现阶段 Hermes 走本地 + 用户自配 key(等同离线版);后续视产品成熟度再评估 |

### 7.1 双版本架构总纲(核心设计原则)

决策 5+6 组合出一个**双版本共存**的架构:**同一个客户端二进制**,通过"是否有有效订阅 + 是否自配 key"决定走哪条通道。

- **线上版(订阅用户)**:LLM 调用走 `POST /cloud/llm/chat`,云端持有 LLM key + **完整高价值 prompt 库**(防逆向核心资产);必须联网 + 订阅校验。
- **离线版(自配 key)**:本地 LLM 调用,用**简化/基础 prompt**(逆向价值低);用户自配 LLM key,无需联网;不做订阅校验。
- **共用客户端**:同一份 exe/py 打包,通过设置面板切换模式(订阅登录 / 自配 key);`prism_frontend/src/lib/env.ts` 的 `backendBaseUrl` 增加 `cloudBaseUrl` 平行项,客户端 SDK 双通道 gateway。
- **prompt 分级**:高价值 prompt(cognition / platform_styles / model_market / hot_topics / content_moderator 等 `fusion_ai/` 中差异化逻辑)**只在云端**;离线版仅保留基础模板(greeting / simple-title / simple-tag 等逆向价值低的模板,即使泄出也不构成产品差异化损失)。

**核心权衡**:承认"离线版的 prompt 基础模板可能被逆向"是**可接受风险**——因为差异化资产已全部在云端,离线版泄出的只是"能用但不够聪明"的基础模板。

---

## 8. 阶段顺序与工作量(相对估)

```
阶段 A(本地收尾,可独立交付):
  A1 subprocess 剩余      [小]
  A2 E2E 打包烟测          [中·风险]
  A3 review 收尾          [中]
  A4 验证                 [小]

阶段 B(SaaS,依赖 §7 决策):
  B0 决策 + 基础设施       [决策为主]
  B1 用户体系 + JWT        [大]
  B2 订阅 + 计量           [中]
  B3 LLM 代理 + prompt 下沉 [大]  ← 核心防逆向
  B4 签名/风控代理         [中]
  B5 客户端双通道          [大]
  B6 key 剥离 + Hermes     [中]
  B7 防逆向加固            [可选]
  B8 支付 + 运营           [大]

关键路径:B1 → B5 → B3/B4 → B6
```

---

## 9. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 无用户体系,从 0 搭建 | B 工作量大 | 复用成熟方案(FastAPI + JWT + 现成支付 SDK) |
| 浏览器自动化强本地 | 代理边界受限,部分核心仍可逆 | 下沉"策略/算法",本地只执行;接受残留风险 |
| key 剥离影响 Hermes 子进程 | 改造复杂,易破坏 P3 自动更新 | 分步:先 LLM 主链路,再 Hermes |
| 离线模式矛盾 | 保留=逆向风险,强制=可用性下降 | 决策点 §7-6 拍板 |
| 云成本/运维 | 长期投入 | 按量计费覆盖成本 |
| 防逆向是猫鼠游戏 | 无法绝对防 | 下沉提高成本即可,不追求绝对 |
| 阶段 B 改动大 | 可能破坏 A 的稳定 | A 先交付并冻结基线,B 分支演进 |

---

## 10. 建议执行顺序

1. **先完成阶段 A**(A1→A2→A3→A4),拿到稳定可打包基线。
2. **同时拍板 §7 决策点**(尤其商业模式 + 离线模式)。
3. 阶段 B 按 B0→B1→B2→B3/B4→B5→B6→B7→B8 推进,B 用独立分支 + 独立服务端仓库/目录。

---

## 附:与既有 _review_productization_v1.md 的关系
本计划延续该审阅文档的 P0-P7 路线:A = P5 剩余 + P6 + P7;B = 新增的 SaaS 化(P8+)。

---

## 11. 详细任务清单与开发量估算(2026-10-13 更新)

> 基于当前已完成状态(P0-P5 主体 + P4 + review 批量 + C 盘防护 + get_logger/ci 硬守门修复)整理。估算是**纯开发工时**,不含决策/沟通/调试反复;实际日历周期 ×1.5~2。

### 11.1 A 类 · 立即收尾(无阻塞,~1 人日)

| # | 任务 | 估算 | 说明 |
|---|---|---|---|
| A1 | ci.yml modules 列表调整 | 0.3d | 硬守门后剔出 main/process_manager 等需运行时模块,避免下次 push CI 必红 |
| A2 | .env.example ↔ config.py 字段核对 | 0.3d | HOST/PORT、BACKEND_HOST/PORT、JWT_SECRET_KEY(注释)等出入 |
| A3 | P5 残留终检 | 0.2d | 确认白名单外裸 subprocess 真为 0(目前仅 process_manager 2 处) |
| A4 | video_transcoder 独立日志(可选) | 0.2d | utils/log.py 补 create_logger('video_transcoder', ...) |

### 11.2 B 类 · 本地产品化收尾(~8-10 人日)

| # | 任务 | 估算 | 说明 |
|---|---|---|---|
| B5 | E2E 打包烟测(P7) | 1.5d·风险 | e2e_packaged_test.ps1 + integration_test.py + CI e2e job;含中文/空格路径解压验证 /preflight |
| B6 | PyInstaller 入口统一重构 | 1d | 3 份 *_service.py 60 行重复+探测过宽 → 抽 prism_backend/_paths.py(仅 stdlib) |
| B7 | supervisor.py 服务列表统一 | 2-3d | "backend" 硬编码 20 处跨 8 类语义 → 设计 SERVICE_REGISTRY 再分批替换 |
| B8 | CI 加 test/lint | 1d | requirements-dev.txt(pytest/httpx/pytest-asyncio/pytest-cov/ruff)+ pytest + ruff job |
| B9 | env 前缀统一(PRISM_→LAOMA_) | 1.5d | 全仓 + 同步 .env.example/部署脚本/前端 env 注入(背景品牌重命名未完成) |
| B10 | 启动慢 26s 优化 | 1.5d | Hermes dashboard 占 18s,cProfile/py-spy 定位后延迟/并行启动 |

### 11.3 C 类 · SaaS 化(**决策已拍板 2026-10-13,~20-26 人日**)

> 决策落点:仅核心 AI 下沉 · 双版本(线上/离线)· 支付宝+微信 · 阿里云/腾讯云 · 下沉+混淆。
> 详细设计见 `docs/dev-reports/2026-10-13-saas-c-class-design.md`。

| # | 任务 | 估算 | 阻塞 | 备注 |
|---|---|---|---|---|
| C11 | B0 决策签核 | ~~0~~ **0**(2026-10-13 已完) | — | 七点已决,状态从"待拍板"改为"已决" |
| C12 | B1 用户体系 + JWT | **3-4d** | — | users 表 + register/login/refresh + Depends(current_user) 中间件 |
| C13 | B2 订阅 + license + 计费 | **2-3d** | C12 | subscriptions / usage 表 + license 心跳 + 免费额度 |
| C14 | **B3 LLM 代理 + prompt 下沉**(防逆向核心) | **4-5d** | C12 | `/cloud/llm/chat` + prompts 表 + `ai_service/llm.py` 双通道 |
| C14a | **双版本 prompt 库分层** | **1-1.5d** | C14 | 云端 prompts 表 vs 本地 `prompts_basic.py`(基础模板);标注哪些 prompt 高价值下沉、哪些留离线 |
| C14b | **离线版 prompt 简化 + 版本切换** | **1-1.5d** | C14a | 客户端 SDK 按订阅态/自配 key 态切换 chatClient 分支;UI 显示当前模式 |
| C15 | B4 签名/风控代理 | ~~3-4d~~ **0(暂缓)** | — | 决策 1 明确"仅核心 AI",B4 下沉暂缓;仅保留可选的 `/cloud/fingerprint/policy` |
| C16 | B5 客户端双通道 gateway | **3-4d** | C12/C14 | ✅ **2026-10-14:前端 `prism_frontend/src/lib/client-gateway.ts`(291 行)已落地;`cloud-auth.ts` 6 端点收敛到 `gatewayRequest`;心跳配置化。遗留:stream/SSE、单例化、前端测试(见 handover §6.6 F1–F6)** |
| C16a | **Hermes 双通道适配** | **1-1.5d** | C16 | `hermes_config.py` 订阅态写代理 endpoint,离线态保留原 config;Hermes 子进程经代理调 LLM |
| C17 | B6 key 剥离(订阅用户) | **1-1.5d** | C14/C16a | 订阅用户三处 key 存储清理(.env / SQLite / hermes-home);离线用户保留原行为 |
| C18 | B7 防逆向加固(pyarmor/Cython) | **2-3d** | C16/C17 | **不再可选**;加固范围:client-gateway SDK / token 校验 / 订阅心跳 / 双版本判定逻辑 |
| C19 | B8 支付 + 运营(支付宝+微信) | **4-5d** | C13 | PaymentAdapter 抽象 + 支付宝电脑网站支付 + 微信 Native/JSAPI + 对账 + 用户中心。✅ **2026-10-14 补:退款端点 / 日终对账 / 订单超时(mock 级,37 项测试通过);遗留见 handover §6.6 P1–P6** |
| C20 | 云基础设施(ECS + 域名 + HTTPS + RDS) | **1-1.5d** | — | 阿里云/腾讯云资源开通 + CI/CD 部署脚本 + 备份 |
| C21 | cloud_service 部署 + 监控 + 日志 | **1-1.5d** | C12/C13/C14 | 独立服务端仓库 + Nginx 反代 + 日志聚合 + 告警 |

**关键路径**:C12 → C13 → C14/C14a → C16 → C14b/C17/C16a → C19/C18 → C20/C21
**新增双版本相关任务**:C14a(prompt 分层)/ C14b(离线版切换)/ C16a(Hermes 适配)/ C17(key 剥离仅订阅用户)
**移除**:C15(B4 签名下沉暂缓)

### 11.4 D 类 · 长期 review(~2-3 人日,穿插)

- 6 模块前缀兼容层(`/api/v1/api/v1/`)观察期后移除
- easel_update `openclaw.json` 目录备份(不只文件)
- `openclaw@latest` pin 版本
- `paths.json` 在 repo 内的 git 追踪防护
- health-check fast/full 分档
- automation_worker 日志统一到 data/logs
- 跨会话计划编号口径统一(避免 P0-P7 定义混乱)
- hermes `get_update_status` 导出回滚字段(已做,确认)

### 11.5 总计与已投入

| 类 | 估算 | 备注 |
|---|---|---|
| A 立即收尾 | ~1 人日 | 半天可清,无阻塞 |
| B 本地收尾 | ~8-10 人日 | 约 2 工作周;B7 supervisor 和 B5 E2E 是重头 |
| C SaaS 化 | **~20-26 人日** | 决策已定;新增双版本相关任务(C14a/C14b/C16a/C17/C20/C21),移除 C15 签名下沉;C14 LLM 代理(4-5d)+ C19 支付(4-5d)仍是大头 |
| D review 杂项 | ~2-3 人日 | 零散穿插 |
| **剩余总计** | **~31-40 人日** | 纯开发工时(较之前收敛 2-4 人日,主要因 C15 暂缓) |
| **已投入(本主线)** | ~12-15 人日 | P0-P5 主体 + P4 + review 批量 + C 盘防护 + get_logger/ci 修 |

**单点最大(值得单独排期)**:C19 支付运营(4-5d)、C14 LLM 代理(4-5d)、C12 用户体系(3-4d)、C16 客户端双通道(3-4d)、C14a/C14b 双版本(合计 2-3d)。

**关键依赖**:§7 已决,C 类**不再阻塞**;可立即启动。核心决策落点:
- **仅核心 AI 下沉** → C15 签名下沉暂缓(节省 3-4d),C14 LLM 代理成为绝对重心。
- **双版本(线上+离线)** → 新增 C14a(prompt 分层)/ C14b(离线切换)/ C16a(Hermes 适配)/ C17(key 剥离仅订阅用户);这是本轮设计的核心复杂度来源。
- **下沉 + 混淆** → C18 从"可选"进入主线,估算升至 2-3d。
- **支付宝 + 微信** → C19 收敛(不做 Stripe),估算维持 4-5d。
- **Hermes 归属暂不定** → C16a 只做通道适配,不做计费归属,后续再议。

**建议推进序**:
1. A 类立即清(1d)
2. B5 E2E 烟测 → B8 CI test/lint → B6 PyInstaller 统一 → B9 env 统一 → B7 supervisor → B10 启动优化
3. **C 类**(§7 已决,可并行启动):
   - 基础设施先行:C20 云资源 → C21 cloud_service 骨架
   - 主干:C12 用户 → C13 订阅 → C14 LLM 代理 + C14a prompt 分层
   - 客户端:C16 双通道 → C16a Hermes 适配 → C14b 离线切换 → C17 key 剥离
   - 加固 & 支付:C18 混淆 → C19 支付接入
4. D 类长期 review 穿插

---

## 12. 复核清单与批次状态(2026-10-14)

> 用户口径:发现的问题**记录不阻塞**。权威清单位于 `docs/dev-reports/2026-10-13-project-handover.md` **§6.6**(支付批 P1–P6 · 前端网关批 F1–F6 · 跨批 X1–X2);此处只放状态与指针,避免两份清单漂移。

### 12.1 本批已完成(2026-10-14,未提交)

| 批 | 内容 | 产物 | 验证 |
|---|---|---|---|
| 支付遗留 | 退款端点 / 日终对账 / 订单超时关闭 | `cloud_service/payment/{router,models,adapter,schemas,__init__}.py` + 新增 `reconciliation.py` / `scheduler.py` / `test_payment_leftover.py` | **38** 项新测试 + 原 **42** 项回归(独立复跑确认,全部 PASS) |
| 前端网关 | client-gateway 统一 + 心跳配置化 | 新增 `prism_frontend/src/lib/client-gateway.ts`;改 `cloud-auth.ts` / `useLicenseHeartbeat.ts` / `.env.local.example` | 前端 `tsc` 三文件 0 错误;6 条 path 全部命中真实路由;heartbeat 优先级与时间解析规则核实(独立复跑) |

**全量回归(2026-10-14,权威数字)**:`pytest cloud_service -q` → **5 passed**(适配层已就位);5 个自运行脚本合计 **218 项 check 全绿**(payment 42 / payment_leftover 50 / billing 40 / llm 68 / e2e 18),**无回归**。计数口径:执行 agent 自报有过两次偏差(37/38、基线 41),一律以复跑为准。

### 12.1b 第二批完成(2026-10-14,未提交)

| 批 | 内容 | 产物 | 验证 |
|---|---|---|---|
| P4+P6 | 超时任务 lifespan 挂载 + 对账定时入口 | `cloud_service/main.py`(+lifespan)、`settings.py`(+6 env)、`payment/reconciliation.py`(`reconcile_task`)、`test_payment_leftover.py`(38 → 50) | 50 项全绿,`test_payment.py` 42 项回归通过 |
| X3 | cloud_service 测试进 CI | 新增 `cloud_service/conftest.py`、`.github/workflows/ci.yml`(+`cloud-service-tests` 硬门 job)、`requirements-dev.txt`(+PyJWT/bcrypt) | `pytest cloud_service -q` → 5 passed |
| F1 | LLM 代理 stream/SSE | `llm_proxy/router.py`(+`POST /cloud/llm/stream`)、`llm_proxy/llm_client.py`(+`stream_cloud_llm`)、`test_llm.py`(39 → 68)、`prism_frontend/src/lib/client-gateway.ts`(+`gatewayStream` / `parseSSEStream`) | 68 项全绿;前端 tsc 本次文件 0 错误;SSE 解析器 Node 探针 16/16 |

### 12.2 上线前必须处理(摘自 handover §6.6)

1. **P5 老库缺列** 🔴 —— `ALTER TABLE orders ADD COLUMN refunded_at DATETIME`(SQLAlchemy `create_all` 不补列)。
2. **X1 本批 12 项提交** 🟠 —— 拆两个 commit(支付 / 前端),显式路径提交。
3. **X2 commit 链一次 push** 🟠 —— 14 个新 API 目录与 `api/v1/router.py` 分散在不同 commit,必须一次 push。
4. ✅ **P4 超时调度挂载 + P6 对账定时入口已于 2026-10-14 完成**(lifespan 挂载,对账默认关闭);仍缺:**P3 真实账单接口接入**。新风险:P8 多 worker 重复执行 / P9 对账单次无超时保护 / P10 缺 `cloud_service/.env.example`。
5. **P7 对账隐式外部调用** 🟡 —— 真实 adapter 上线后,`reconcile_day(platform_bills=None)` 会直接拉商户账单接口;对账需改为显式定时入口。
6. ✅ **F1 stream/SSE 通道已于 2026-10-14 完成**(后端 `/cloud/llm/stream` + 前端 `gatewayStream`);**调用方接入**留待单独批次。新风险:F10 客户端中断不计费 / F11 usage 按字符估算。
7. **F3 license 离线误判策略** 🟡 —— 明确网络抖动时不得把有效订阅判失效。
8. ✅ **X3 cloud_service 测试进 CI 已于 2026-10-14 完成**(`cloud_service/conftest.py` + `ci.yml` 硬门 job,`pytest cloud_service -q` → 5 passed)。

### 12.3 尚未拍板(需决策)

- 退款是否撤销订阅(P1):`billing` 只有"延长"语义,需先定业务规则。
- 部分退款的状态语义(P2)。
- Hermes 归属(§7 决策 ⑦,仍"暂不定")。
