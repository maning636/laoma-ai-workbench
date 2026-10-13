# Prism-Fusion · C 类 SaaS 化详细设计(基于 §7 决策)

> 日期:2026-10-13
> 前置文档:`_plan_productization_saas.md`(§5/§7/§11)、`2026-10-13-saas-decision-guide.md`、`2026-10-13-overall-assessment.md`
> 范围:**仅设计,不改代码**。基于用户 2026-10-13 拍板的 §7 七点决策。
> 关联计划任务:C11(决策签核,已完成) → C12-C21(见 §5 工时估算)

---

## 1. §7 决策落点回顾

| # | 决策点 | 用户选择 | 关键含义 |
|---|---|---|---|
| 1 | 代理范围 | **仅核心 AI** | 只下沉 LLM + prompt;签名/风控/cookie **留本地**(暂缓下沉) |
| 2 | 商业模式 | **软件订阅**(月/年 + 免费额度) | 建立 subscriptions + license + usage 体系 |
| 3 | 支付 | **支付宝 + 微信** | 不做 Stripe;双国内通道 |
| 4 | 云 | **阿里云/腾讯云** | ECS + 域名 + HTTPS + RDS + Redis |
| 5 | 防逆向 | **下沉 + 混淆** | 核心搬服务器(主)+ 客户端 pyarmor/Cython(辅) |
| 6 | 离线模式 | **保留离线**(自配 key) | **双版本架构**:线上版(订阅)+ 离线版(自配 key) |
| 7 | Hermes 归属 | **暂不定** | 只走通道适配,不做计费归属 |

**核心矛盾与解法**:决策 1(仅核心)+ 决策 6(保留离线)看似互斥——如果用户能自配 key 纯本地跑,那核心 AI 也就本地跑,下沉没意义。**解法:双版本 prompt 分层**。高价值 prompt 只在云端(线上版享受),离线版只有基础 prompt(逆向价值低,可接受)。

---

## 2. 双版本架构(核心设计)

### 2.1 版本定义

| 版本 | 触发条件 | LLM 调用路径 | Prompt 来源 | 需要联网 | 需要订阅 |
|---|---|---|---|---|---|
| **线上版** | 已订阅 + 云端可达 | 客户端 → `POST /cloud/llm/chat` → 云端 LLM | 云端 `prompts` 表(完整库) | ✅ | ✅ |
| **离线版** | 未订阅 / 断网 / 用户自配 key | 客户端本地 LLM 客户端 → 用户自配 endpoint | 本地 `prompts_basic.py`(基础模板) | ❌ | ❌ |

### 2.2 Prompt 分级(高价值 vs 基础)

依据 `prism_backend/fusion_ai/` 实际内容:

**高价值 prompt → 云端(下沉)**:
- `cognition.py`——用户画像 + 认知建模(产品差异化核心)
- `platform_styles.py`——8 平台风格适配(抖音/小红书/B 站/微信视频号/快手/知乎/头条/西瓜)
- `model_market.py`——模型市场匹配逻辑
- `hot_topics.py`——热点话题挖掘策略
- `content_moderator.py`——内容合规审核(涉及平台规则库)
- `skill_workshop.py`——技能工坊(高阶功能)
- `nl_query.py`——自然语言查询解析
- `router.py`——路由决策(哪些任务走哪个 prompt)

**基础 prompt → 本地(留离线)**:
- 简单标题生成(纯模板拼接,无平台风格)
- 简单标签生成(关键词抽取,无情感分析)
- 简单文案改写(基础句式变换)
- greeting / fallback 类兜底模板

**判据**:能形成产品差异化、抄袭有价值 → 云端;抄了也用不出产品优势 → 本地。

### 2.3 客户端切换逻辑

```
[启动] → 检查订阅状态(localStorage + license 心跳)
        ├─ 有订阅 + 云端可达 → 线上版(chatClient → /cloud/llm/chat)
        ├─ 有订阅 + 云端不可达 → 降级提示 → 用户选:重试 / 切离线模式
        └─ 无订阅 / 自配 key 模式 → 离线版(chatClient → 本地 LLM)
```

- 用户设置页新增"AI 模式"选项:`订阅模式` / `自配 Key 模式`
- 订阅模式启用后:本地 LLM key 存储区清空(`.env` / SQLite `ai_model_configs` / `hermes-home/config.yaml` 三处)
- 自配 Key 模式:三处 key 存储保留原行为

### 2.4 核心权衡(设计决策)

| 决策 | 选择 | 理由 |
|---|---|---|
| 离线版 prompt 简化到什么程度 | **只保留基础模板(约 5-10 个)**,不含平台风格 / 认知建模 | 平衡"可用"和"防逆向";基础模板即使泄出也不构成产品差异化损失 |
| 线上/离线是否共用二进制 | **共用同一 exe**,通过设置面板切换 | 避免维护两份构建;用户升级成本低 |
| 订阅用户断网怎么办 | 弹窗提示 + 可选降级到离线版模式(临时) | 用户体验优先;不静默降级 |
| 离线版是否可能被滥用绕过订阅 | **接受此风险** | 差异化 prompt 只在云端,离线版本身"能用但不够聪明";用订阅引导用户升级,不硬封 |

---

## 3. 服务端架构(`cloud_service/`)

### 3.1 模块划分

```
cloud_service/                          # 独立仓库 / 独立部署
├── app/
│   ├── main.py                         # FastAPI 入口 + 全局中间件(JWT + 限流 + 日志)
│   ├── auth/                           # B1 用户 + JWT
│   │   ├── models.py                   # User 表 + PasswordHash
│   │   ├── router.py                   # /cloud/auth/register|login|refresh|logout
│   │   └── jwt_utils.py                # JWT 签发/校验
│   ├── billing/                        # B2 订阅 + 计量
│   │   ├── models.py                   # Subscription / Usage / Invoice
│   │   ├── router.py                   # /cloud/subscription|usage|license/verify
│   │   ├── plans.py                    # Free / Pro-Monthly / Pro-Yearly 定义
│   │   └── meter.py                    # 用量计量 middleware(装饰器)
│   ├── llm_proxy/                      # B3 LLM 代理(prompt 下沉核心)
│   │   ├── models.py                   # Prompt(name, template, params_schema, version, tier)
│   │   ├── router.py                   # POST /cloud/llm/chat / GET /cloud/prompts
│   │   ├── prompt_registry.py          # prompt 装配 + 参数校验 + 版本管理
│   │   ├── llm_gateway.py              # 上游 LLM(DeepSeek/SenseNova/SiliconFlow)统一封装
│   │   └── key_vault.py                # LLM key 存储(阿里云 KMS / 环境变量注入)
│   ├── payment/                        # B8 支付
│   │   ├── adapters/                   # PaymentAdapter 抽象
│   │   │   ├── alipay.py               # 支付宝(电脑网站支付 / 当面付)
│   │   │   ├── wechat.py               # 微信(Native / JSAPI)
│   │   │   └── base.py
│   │   ├── router.py                   # /cloud/payment/create|callback|reconcile
│   │   └── reconciliation.py           # 每日对账脚本
│   ├── gateway/                        # 统一入口(可选:独立网关 or 集成到 main.py)
│   │   ├── router.py                   # /cloud/* 统一前缀
│   │   ├── rate_limit.py               # 按 user / plan 限流
│   │   └── audit.py                    # 请求审计日志
│   └── core/
│       ├── config.py                   # 云端配置(env 前缀 PRISM_CLOUD_*)
│       ├── db.py                       # SQLAlchemy 2.0 + Alembic 迁移
│       ├── security.py                 # JWT 依赖 + Depends(current_user)
│       └── logger.py
├── alembic/                            # 数据库迁移
├── tests/
├── Dockerfile
├── docker-compose.yml                  # 本地开发栈(api + db + redis + worker)
└── deploy/                             # C20/C21
    ├── aliyun/                         # ECS + RDS + SSL
    ├── tencent/
    └── ci-cd/
```

### 3.2 关键 API 契约

```
# 认证(B1)
POST /cloud/auth/register               { email, password, nickname? }
POST /cloud/auth/login                  { email, password } → { access_token, refresh_token, expires_in }
POST /cloud/auth/refresh                { refresh_token } → { access_token }
POST /cloud/auth/logout

# 订阅(B2)
GET  /cloud/subscription                                 → 当前订阅状态 + 剩余额度
POST /cloud/license/verify                              → 客户端心跳,返回订阅 + 允许云端 AI 的 flag
POST /cloud/usage/consume                               → 内部计量上报(带幂等 ID)

# LLM 代理(B3)
POST /cloud/llm/chat
  {
    prompt_id: "platform_styles.tiktok_short",   # 不用传 prompt 文本,只传 ID
    params: { "topic": "...", "tone": "幽默" },  # 参数由 params_schema 校验
    model_hint?: "fast" | "quality"              # 可选
  }
  → { content, tokens_in, tokens_out, prompt_version }

GET  /cloud/prompts?tier=cloud                    → 列出云端可用 prompt 目录(供 UI 展示)

# 支付(B8)
POST /cloud/payment/create                        → 支付宝/微信订单创建,返回支付链接/二维码
POST /cloud/payment/callback                      → 支付回调
GET  /cloud/payment/reconcile                     → 每日对账(内部)

# 用户中心
GET  /cloud/user/usage                            → 用量统计(按日/月)
POST /cloud/user/upgrade / downgrade              → 订阅变更
```

### 3.3 数据库关键表

```sql
-- B1 用户
users (id, email, password_hash, nickname, created_at, last_login_at, is_active)

-- B2 订阅
plans (id, name /*free|pro_monthly|pro_yearly*/, quota_llm_calls, quota_tokens, price, currency)
subscriptions (id, user_id, plan_id, status /*active|expired|cancelled*/, start_at, expire_at, auto_renew)
usage (id, user_id, prompt_id, tokens_in, tokens_out, latency_ms, called_at, idempotency_key)

-- B3 Prompt(高价值核心资产)
prompts (id, name /*unique*/, tier /*cloud*/, template /*Jinja2*/, params_schema /*JSON*/, version, weight, is_active, created_at)
prompt_versions (prompt_id, version, template, published_at)  -- 版本历史 + 灰度

-- B8 支付
orders (id, user_id, subscription_id, amount, currency, channel /*alipay|wechat*/, out_trade_no, status, created_at, paid_at)
invoices (id, order_id, tax_id, invoice_no, issued_at)

-- 运营
audit_logs (id, user_id, action, resource, ip, user_agent, created_at)
```

---

## 4. 客户端改造

### 4.1 双通道 gateway(`prism_frontend/src/lib/client-gateway.ts`)

**新增文件**,负责路由所有 API 调用:

```ts
// 逻辑伪代码
const backendBaseUrl = env.LAOMA_INTERNAL_BACKEND_URL;   // 127.0.0.1:7000
const cloudBaseUrl   = env.LAOMA_CLOUD_BACKEND_URL;       // https://api.prism-fusion.com

export type Mode = 'cloud' | 'offline';
export const chatClient = {
  async chat(promptId: string, params: any): Promise<ChatResponse> {
    const mode = await detectMode();   // 检查订阅 + 云端可达性
    if (mode === 'cloud') {
      // 线上版:走云端,prompt 文本不下发
      return fetch(`${cloudBaseUrl}/cloud/llm/chat`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${await getJwt()}` },
        body: JSON.stringify({ prompt_id: promptId, params })
      }).then(r => r.json());
    } else {
      // 离线版:走本地,只能调基础 prompt
      return fetch(`${backendBaseUrl}/api/v1/ai/chat`, {
        method: 'POST',
        body: JSON.stringify({ prompt_id: promptId, params })
        // 本地 fusion_ai/router 判定 prompt_id 是否存在于本地基础库;不存在则报错提示切换订阅
      }).then(r => r.json());
    }
  }
};
```

### 4.2 现有代码改造点

| 文件 | 现状 | 改造 |
|---|---|---|
| `prism_frontend/src/lib/env.ts` | 仅 `backendBaseUrl` | 新增 `cloudBaseUrl` 平行项;保留原字段 |
| `prism_backend/ai_service/llm.py` | 单一本地 LLM 客户端 | 增加 `CloudLLMClient` 分支;订阅态走云端,离线态保留 |
| `prism_backend/fusion_ai/router.py` | prompt 装配统一入口 | 增加 `tier` 参数:订阅态取云端 prompt,离线态取本地基础库 |
| `prism_backend/fusion_ai/{cognition,platform_styles,model_market,hot_topics,content_moderator,skill_workshop,nl_query}.py` | prompt 内嵌源码 | **抽取** prompt 模板到云端 `prompts` 表;本地保留空壳 stub(仅参数校验 + 转调云端) |
| `prism_backend/fastapi_app/core/config.py` | `AI_API_KEY`/`SILICONFLOW_API_KEY` 存本地 | 订阅用户清空这些字段;离线用户保留 |
| `prism_backend/fastapi_app/agent/hermes_config.py` | 写 key 段到 hermes-home/config.yaml | 订阅态:写代理 endpoint;离线态:保留原逻辑 |
| `desktop-electron/main.ts` | 无 token 存储 | 新增 `electron.safeStorage` 存 JWT + refresh token;退出时清除 |
| 新增 `desktop-electron/license-heartbeat.ts` | 无 | 每 24h 调 `/cloud/license/verify`,更新订阅状态 |
| 新增 `desktop-electron/dual-channel-proxy.ts`(可选) | 无 | 若 Hermes 子进程也需要走云端,加本地透明代理(127.0.0.1:7001) |

### 4.3 关键实现细节

**Token 存储**:`electron.safeStorage.encryptString()` → 写入 `userData/prism-credentials.json`(Windows 走 DPAPI 加密)。

**心跳**:`setInterval` 每 24h 调用 `/cloud/license/verify`;若失败 3 次,UI 提示"云端不可达,已降级到离线模式"。

**双通道切换**:任何 chat 调用都走 `chatClient.chat()`;禁止直接调 `fetch()` 到 LLM endpoint,统一由 SDK 拦截。

---

## 5. 部署方案

### 5.1 云资源清单(阿里云或腾讯云,均可)

| 资源 | 规格 | 用途 |
|---|---|---|
| ECS / CVM | 4C8G 起,可扩 | 跑 `cloud_service` FastAPI(uvicorn worker × 4) |
| RDS MySQL/PG | 2C4G,100G 起 | 用户 / 订阅 / 用量 / prompt 表 |
| Redis 托管 | 1G 起 | 会话缓存 / 限流 / 队列 |
| OSS / COS | 500G | 支付凭证 / 审计日志备份 |
| CDN(可选) | — | 客户端更新包 / 静态资源 |
| 域名 + HTTPS | prism-fusion.com(示例) | 备案 + Let's Encrypt / 云厂商 SSL |
| KMS | — | 存储 LLM key(可选,替代环境变量注入) |

### 5.2 支付集成

**支付宝**:
- 接入:电脑网站支付(www 版) + 当面付(扫码)
- 文档:https://opendocs.alipay.com/open/02akfy
- 沙箱:支付宝开放平台沙箱环境测试

**微信支付**:
- 接入:Native(扫码)+ JSAPI(Electron 内 H5)
- 需要:商户号 + API 证书(申请周期 ~3 工作日)
- 文档:https://pay.weixin.qq.com/wiki/doc/apiv3/index.shtml

**统一抽象**:
```python
class PaymentAdapter:
    async def create_order(self, subscription_id, amount) -> PaymentLink
    async def handle_callback(self, raw: bytes) -> bool
    async def query_order(self, out_trade_no) -> OrderStatus
    async def refund(self, out_trade_no, amount) -> bool
```

### 5.3 部署脚本骨架(C20/C21)

```
deploy/
├── aliyun/
│   ├── ecs-bootstrap.sh              # ECS 初始化:装 nginx + uvicorn + pm2 + 证书
│   ├── rds-migrate.sql               # DB 初始化 schema
│   └── docker-compose.prod.yml
├── ci-cd/
│   ├── workflow.yml                  # CI/CD:lint → test → build → docker push → deploy
│   └── deploy.sh
└── monitoring/
    ├── nginx.conf                    # 反向代理 + SSL 终止
    └── alert-rules.yml               # 关键指标告警(CPU/DB/延迟/错误率)
```

---

## 6. 防逆向方案

### 6.1 主防线:核心下沉(决策 5 第 1 层)

- `fusion_ai/` 高价值 prompt → 云端 `prompts` 表(见 §3.3)
- LLM key → 云端 KMS / 环境变量(客户端 0 持有)
- 订阅校验 → 云端 `/cloud/license/verify` 签发

### 6.2 辅防线:客户端混淆(决策 5 第 2 层,C18)

**加固范围**(pyarmor 优先,Cython 备选):
- `desktop-electron/main.ts` 中的双版本判定逻辑(编译为 .exe 原生)
- `prism_frontend` build 产物中 `client-gateway.ts` / `license-heartbeat.ts`(前端构建时 minify + split + source-map 关闭)
- 订阅校验模块 Python 端(如 `fastapi_app/auth/`)pyarmor 加固
- JWT 校验 + token 存储逻辑(防止篡改)

**不加固**(留纯 .py):
- 浏览器自动化(patchright / playwright)
- 平台适配器(platforms/*)
- UI 组件(fusion_ai 空壳 stub 除外)

**权衡**:pyarmor 有启动成本(+300ms~1s)和调试困难;Cython 编译 .pyd 无法热更新。**推荐 pyarmor**,先只加固订阅校验核心链路,观察上线 1-2 周再扩展。

### 6.3 客户端完整性检查(可选,不进主线)

- 启动时校验 `sha256(exe)` 与云端签名比对
- 若不匹配:提示"客户端被篡改,请重新安装"
- **不进入 C 类主线**,列为 D 类长期项

---

## 7. 关键风险与设计决策记录(ADR)

| # | 风险 | 影响 | 缓解 / 决策 |
|---|---|---|---|
| R1 | 离线版被逆向拿到基础 prompt 后如何升级成"付费用户"体验 | 中等 | **接受此风险**。基础 prompt 抄了也没用;订阅用户走云端高价值 prompt 才有产品优势 |
| R2 | 云端 LLM key 泄露 | 严重 | (a) 用 KMS/环境变量注入,不落盘 (b) 每 key 每日调用配额上限 (c) 多 key 轮询分散风险 (d) 云厂商侧安全审计 |
| R3 | Hermes 子进程改造复杂(独立 config + venv) | 中高 | 决策 7 暂不定归属 → 先做通道适配(C16a),订阅态写代理 endpoint,离线态保留原逻辑;不做计费 |
| R4 | 客户端 pyarmor 混淆导致升级困难 | 中 | 先只做订阅校验链路(C18 收敛到最小加固范围);上线 1-2 周再扩展;保留"降级为不加固"回退方案 |
| R5 | 双版本架构导致 prompt 库分裂维护成本 | 中 | 云端 prompts 表 + 本地基础库通过**统一版本 tag** 对齐;云端 prompt 下线时同步本地基础库 |
| R6 | 支付宝/微信商户号申请周期与合规 | 中 | 提前启动申请(C19 依赖外部审批,不占开发工时但阻塞上线);先接沙箱测试 |
| R7 | 云成本 & 运维 | 低中 | 免费额度限制拉新成本;订阅价格覆盖云成本;监控 + 告警先行(C21) |
| R8 | 断网时用户 UX 断裂 | 中 | 订阅态断网 → 弹窗 + 明确降级选项,不静默降级;离线态永远可用(基础功能) |
| R9 | 客户端 JWT 泄露(electron safeStorage) | 中低 | safeStorage 走 OS Keychain(DPAPI),非明文;泄露风险主要在物理盗机场景;refresh token 短期过期 + 云端可撤销 |
| R10 | 离线用户绕过订阅直接修改客户端切换"订阅态" | 低 | 客户端双版本判定 = 云端签名 + 本地加密标记;单点修改无法完全伪造;且订阅校验在云端,本地篡改只是本地显示 |

---

## 8. 工时汇总与推进序

详见 `_plan_productization_saas.md` §11.3:

| 阶段 | 任务 | 估算 |
|---|---|---|
| 基础设施 | C20 云资源 + C21 cloud_service 部署 | 2-3d |
| 主干 | C12 用户 + C13 订阅 + C14 LLM 代理 | 9-12d |
| 双版本 | C14a prompt 分层 + C14b 切换 + C16a Hermes | 3-4.5d |
| 客户端 | C16 双通道 + C17 key 剥离 | 4-5.5d |
| 加固 & 支付 | C18 混淆 + C19 支付 | 6-8d |
| **合计** | | **24-31d**(不含沟通/调试反复) |

**关键路径**:C20 → C12 → C13 → C14 → C14a → C16 → C14b/C16a/C17 → C18 → C19

**外部依赖(阻塞上线,不阻塞开发)**:
- 支付宝 / 微信商户号申请(2-3 周)
- 域名备案(2-3 周,若新域名)
- 云资源账户与合规审核(1 周)

建议在开发启动同时**并行提交商户号申请**。

---

## 9. 与现有代码的最小侵入策略

**原则**:不改现有本地功能,通过"平行通道"接入云端。

- **本地后端(127.0.0.1:7000)**:保留原样,继续服务浏览器自动化 / 文件 / 平台发布 / Hermes / 离线 AI。
- **云端(cloud_service)**:独立部署,新增 `/cloud/*` API,不复用本地路由。
- **前端 gateway**:`client-gateway.ts` 是唯一的通道选择点,业务代码不感知。
- **`fusion_ai/` prompt 抽取**:分步执行——先只把高价值 prompt(§2.2)搬云端,基础 prompt 保留本地;`router.py` 增加 `tier` 分支即可,不改现有 prompt 逻辑。
- **Hermes**:决策 7 暂不定 → 只加"通道适配"(C16a),不改 Hermes 内部逻辑。

**验证方式**:所有 SaaS 改造都在独立分支/独立服务端仓库,不影响 A 类(本地产品化)基线。

---

## 附:文件路径速查

- 计划主文档:`_plan_productization_saas.md`(§5/§7/§11 已更新)
- 决策指南:`docs/dev-reports/2026-10-13-saas-decision-guide.md`
- 整体评估:`docs/dev-reports/2026-10-13-overall-assessment.md`
- **本设计文档**:`docs/dev-reports/2026-10-13-saas-c-class-design.md`

**代码入口(仅读参考)**:
- LLM key 存储:`prism_backend/fastapi_app/core/config.py:167-180`
- LLM 客户端:`prism_backend/ai_service/llm.py`
- prompt 库:`prism_backend/fusion_ai/{cognition,platform_styles,model_market,hot_topics,content_moderator,skill_workshop,nl_query,router}.py`
- Hermes config:`prism_backend/fastapi_app/agent/hermes_config.py`
- 现有 auth:`prism_backend/fastapi_app/api/v1/auth/`(第三方扫码,非用户体系)
- 前端 backend URL:`prism_frontend/src/lib/env.ts`

---

*本设计文档不涉及代码改动,仅作为 C 类 SaaS 化开工依据。开发按 §8 推进序分步执行,每步独立验收。*
