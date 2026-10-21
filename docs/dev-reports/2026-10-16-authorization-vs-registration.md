# 授权制 vs 注册制 对比与取舍建议

> 调研日期：2026-10-18（文件名沿用计划里的 2026-10-16）
> 对象：`/opt/bidmaster`（授权制，OpenCloudOS 9.6 服务器 101.43.65.216）
>       vs. Prism-Fusion `cloud_service`（注册制，同一台服务器 8091）
> 只读分析，未对服务器和仓库做任何改动。
> **口径说明（2026-10-21 补充）**：本文为对照调研。bidmaster 属**另一条产品线**（AI 标书），与 Prism-Fusion 本体业务**无任何关系**；此处仅作「授权制 vs 注册制」的技术对照。Prism-Fusion 的定位是**自媒体矩阵发布 + AI 生图/生视频的内容生产平台**。

---

## 0. TL;DR

- **bidmaster 是「注册 + 授权码 + 硬件绑定 + 14 天离线 Token + 心跳」的混合模式**，不是纯注册制，也不是纯授权码制。
- **Prism-Fusion 目前是纯注册制 + 订阅/SaaS**（`cloud_service.auth` JWT + `cloud_service.billing` Subscription），**没有硬件绑定、没有离线凭据、没有激活码**。
- 二者定位不同：bidmaster 要保护"桌面客户端 + 私有部署"下的**付费版权**；Prism-Fusion 是 SaaS 云服务，用户数据/推理全部在云端，不需要"锁机器"。
- **建议**：Prism-Fusion 保持注册制为主，**只在需要交付"私有化桌面客户端"（企业版/离线版）时，把 bidmaster 的 Ed25519 + 硬件指纹模块作为可插拔的 provider 层加进来**，与现有 Subscription 表并挂。工作量约 5-8 人日。

---

## 1. bidmaster 项目概况

| 项 | 值 |
|---|---|
| 位置 | `/opt/bidmaster`（服务器 101.43.65.216） |
| 版本 | `laoma-bid 0.2.1`，README 自称"老马标书贤内助" |
| 技术栈 | Python 3.12（FastAPI + SQLAlchemy async + Alembic + Litellm + LangGraph + ChromaDB） |
| 部署形态 | **前后端分离**：后端 `services/`（端口 8031），前端 React `packages/desktop/`（Vite 5173） |
| 业务 | 招投标全流程 AI：招标解读 → 标书生成 → 23 项合规检查 → 排版输出 |
| 授权模块 | `core/license*.py` + `core/machine_id.py` + `services/routers/license.py` + `services/middleware/license_gate_middleware.py` |

**关键点**：bidmaster 支持**双部署形态**——

1. **服务器模式**：本进程就是授权源，`core.license` 使用 `OpenLicenseProvider`（永远有效），走数据库激活。
2. **客户端模式**：本地跑一份后端，通过 `BMP_SKILL_SERVER` 环境变量把授权/心跳请求转发到远程服务器。这就是"分布式部署"的场景——客户可能把整套后端跑在自己机器上。

---

## 2. bidmaster 授权逻辑详解

### 2.1 授权流程图（文字）

```
┌─────────────────┐    生成 20 字符激活码       ┌──────────────────┐
│ Admin 后台       │ ───────────────────────▶   │ License 表 (DB)  │
│ POST /admin/    │    code/customer/exp        │ code, expires,   │
│  licenses       │                            │ machine_id, sk...│
└─────────────────┘                            └────────┬─────────┘
                                                        │
                                                        │ 分配给用户 (assigned_user_id)
                                                        ▼
┌──────────────────────────────────────────┐
│ 客户端启动                                  │
│  1. GET /license/status → 未激活         │
│  2. 用户登录 → POST /license/auto-activate│
│  3. 服务器签 Ed25519 token (14 天有效)     │
│  4. 客户端落 .license_token               │
└──────────────────┬───────────────────────┘
                   │ 心跳 (每 3 天)
                   ▼
       POST /license/refresh → 换新 token + last_seen_at
                   │
                   ▼
    离线期间用 Ed25519 公钥离线验签 (client side)
```

### 2.2 关键代码片段

**（a）机器指纹（`/opt/bidmaster/core/machine_id.py`）**

优先级：TPM → 主板序列号 + 磁盘序列号 → `/etc/machine-id` → hostname 兜底。
双重 SHA256 + 硬编码盐，输出 64 字符 hex；token 里只存前 16 字符。

```python
_SALT = b"\x87\xd4\xb2\x1e\xa0\f3\x6c\x91\x5d\xe8\x37\xb0\x4a\xf6\x22\xcb"
_SECONDARY_SALT = b"\x3e\x91\x5d\xe8\x37\b0\x4a..."

h1 = hashlib.sha256(raw + _SALT).digest()
h2 = hashlib.sha256(h1 + _SECONDARY_SALT).digest()
_cached_fingerprint = h2.hex()   # 64 字符 hex
```

Windows 通过 PowerShell 读 `Win32_BaseBoard.SerialNumber` / `Win32_DiskDrive.SerialNumber`；Linux 读 `/sys/class/dmi/id/board_serial` + `/etc/machine-id`。

**（b）Token 结构（`core/license_ed25519.py`）**

```python
payload = {
    "uid": "customer-or-code",
    "products": ["bidmaster"],
    "device": "指纹前 16 位",
    "iat": 1758...,          # 签发时间
    "exp": 1760...,          # 到期时间（≤ 14 天）
    "sk_enc": base64(sk),    # 会话密钥，用于下发加密提示词
}
token = base64url(json(payload)) + "." + base64url(Ed25519_sign(payload))
```

**（c）客户端离线校验（`core/license_ed25519.py:_compute_status`）**

```python
# 1. 验签
payload = _verify_token(self._token, self._public_key)   # 公钥编进客户端
# 2. 验过期
if time.time() > payload["exp"]:  → "授权已过期，请联网续期"
# 3. 验设备绑定
if payload["device"] != get_machine_id():  → "授权绑定设备不匹配"
```

客户端拿到 token 后可以离线验，**不需要联网**。改本地时间也无效——`exp` 是服务端签名的一部分。

**（d）激活码格式（`services/routers/admin.py:_gen_code`）**

```python
alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # 去 0/O/1/I/L
raw = "".join(secrets.choice(alphabet) for _ in range(20))
return "-".join(raw[i:i+4] for i in range(0, 20, 4))
# 输出示例：K7XW-2M9P-6N3B-Q4RF-J8TZ
```

32 位随机，去易混淆字符，5 组 4 字符。

**（e）防暴力破解（`services/routers/license.py`）**

```python
_ACTIVATE_MAX_FAILS = 5
_ACTIVATE_WINDOW_SECONDS = 300
# 同一 activation_code 5 分钟内失败 5 次 → 429
```

**（f）License 数据模型（`services/models.py:515-540`）**

```python
class License(Base):
    __tablename__ = "licenses"
    code          = Column(String(64), primary_key=True)      # 激活码
    customer      = Column(String(255), index=True)           # 客户标识
    expires_at    = Column(DateTime, nullable=False, index=True)
    machine_id    = Column(String(128), unique=True, index=True)  # 一机一码
    status        = Column(String(20))  # inactive/active/disabled/expired
    activated_at  = Column(DateTime)
    last_seen_at  = Column(DateTime)       # 心跳时间
    assigned_user_id = Column(String(36))  # 分配给哪个用户
    assigned_at     = Column(DateTime)
    session_key   = Column(String(64))     # 32 字节 sk hex，用于加密下发提示词
```

**（g）状态机**

```
inactive ──激活──▶ active ──过期──▶ expired（惰性判断，看 expires_at）
   │                   │
   │                   └──管理员禁用──▶ disabled
   └──分配给用户(assigned_user_id)──▶（不影响状态机，只影响归属校验）
```

**（h）客户端 API 门控（`services/middleware/license_gate_middleware.py`）**

- 客户端模式下（有 `BMP_SKILL_SERVER`）：除白名单外的所有 `/api/*`，未激活一律 403。
- 白名单：`/api/health` `/api/auth/*` `/api/license/*` `/api/admin/*` `/api/skill/*`。
- 服务器模式：不启用中间件。

### 2.3 防破解措施清单

| 层次 | 措施 |
|---|---|
| 密码学 | Ed25519 签名（服务端持私钥，客户端持公钥）；token payload 整体签名，无法伪造 |
| 会话密钥 | 32 字节 `session_key` 落库、通过 token 的 `sk_enc` 传输；用于下发加密提示词 |
| 硬件绑定 | TPM + 主板 + 磁盘序列号，双层 SHA256 + 硬编码盐 |
| 时间 | token 14 天硬过期 + 每 3 天 refresh（兼心跳），改本地时间无效 |
| 速率限制 | 同码 5 分钟 5 次 → 429 |
| 归属校验 | `assigned_user_id` 防代抢激活码 |
| 一机一码 | `License.machine_id` UNIQUE 约束；续费自动解绑过期旧码 |
| 服务端兜底 | 客户端模式下 `license_gate_middleware` 拦截所有 API |
| 可禁用 | admin `DELETE /admin/licenses/{code}` → 下次心跳拒 |

**没有的东西**：代码混淆/加壳、VMProtect、时间回拨检测（改系统时间会挂掉 token 但也无法主动阻断）、多设备切换的白名单机制。

---

## 3. Prism-Fusion 注册制现状

### 3.1 认证（`cloud_service/auth/router.py` + `auth/models.py`）

```
POST /cloud/auth/register   { username, email, password } → 201
POST /cloud/auth/login      { username, password }         → { access_token, refresh_token }
POST /cloud/auth/refresh    { refresh_token }              → { access_token }
GET  /cloud/auth/me         (Bearer JWT)
```

- 用户表极简：`users(id, username, email, password_hash, is_active, created_at)`。
- 密码 bcrypt hash；JWT access + refresh；access TTL 从 settings 读。
- **无手机/邮箱验证、无邀请码、无第三方登录、无 MFA**（对当前 SaaS 定位够用）。

### 3.2 订阅/计费（`cloud_service/billing/`）

```
GET  /cloud/subscription                    → 当前订阅 + 本月已用量
POST /cloud/usage/consume                   → 消耗额度，超 402
POST /cloud/license/verify                  → 客户端心跳（订阅有效性 + is_pro）
POST /cloud/subscription/activate           → 模拟激活 pro（C19 支付接入前的桩）
```

- `Subscription(id, user_id, plan∈{free,pro,credit}, status, expire_at, quota)` 一对一。
- `Usage(user_id, period, used)` 月度聚合，`uq_usage_user_period`。
- M3 追加积分账本：`CreditBalance` / `CreditLedger` / `CreditPricing`（对齐澜途 API）。
- 客户端 hook `useLicenseHeartbeat.ts`：默认 **24 小时**一次 `verifyLicense`，可 env 覆盖。
- `cancel_subscription` / `shorten_subscription` 支持退款撤销。

### 3.3 关键差异

| 维度 | Prism-Fusion | bidmaster |
|---|---|---|
| 数据面 | 全在云端（LLM proxy + prompts 服务） | 客户端本地可跑后端 |
| 授权对象 | 云端用户账号 | 桌面客户端机器 |
| 凭据 | 长期 JWT refresh token | Ed25519 签名 token（14 天） |
| 硬件绑定 | 无 | 有 |
| 离线能力 | 无（必须联网） | 有（14 天内离线） |
| 客户端形态 | Web (React + Electron) | Web + 可选本地后端 |

---

## 4. 授权制 vs 注册制 对比表

| 维度 | 授权制（bidmaster） | 注册制（Prism-Fusion） |
|---|---|---|
| **用户体验** | 需申请激活码 → 输入 → 输入机器码；多设备/换机器需管理员干预，摩擦大 | 邮箱/用户名自助注册即用，零门槛 |
| **防破解强度** | 强：Ed25519 签名 + 硬件绑定 + 短 token + 心跳；破解需绕过 5 层 | 弱：只依赖账号密码；但**数据面在云端，破解本地也无法白嫖服务** |
| **运维复杂度** | 高：私钥管理、批量发码、机器换绑、心跳统计、限流 | 低：单 JWT + Subscription 表；标准 SaaS |
| **商业化灵活度** | 中：可按激活码定价，但订阅周期/多档位/自动扣费需自己搭 | 高：与支付/积分/退款/降档天然打通 |
| **离线能力** | 有（14 天硬过期，改时间无效） | 无 |
| **退款/迁移** | 麻烦：一台机器绑一条码，迁移要走 admin 手动解绑 | 天然支持：`cancel_subscription` / `shorten_subscription` / 退款扣减积分 |
| **多设备** | 弱：`machine_id` UNIQUE，一机一码；换机要 admin | 强：一个账号多设备登录，靠 refresh token 管理 |
| **数据回收** | 差：客户端本地后端可跑，用户数据可能留在本地 | 好：所有数据落 `cloud_service` 数据库，可审计可回收 |
| **破解面** | 客户端代码 + 密钥分发 + token 篡改 + 硬件伪造 | 无破解面（服务不可脱离云端） |
| **适用场景** | 桌面客户端 + 私有化交付；用户在意"我买了软件就永久持有" | SaaS / Open Core 免费层 + Pro 订阅；用户接受"服务" |
| **实现工作量** | bidmaster 已有 ~1500 行授权代码 + 中间件 + 前端入口 | 现有实现已完成，仅订阅扩展 |
| **合规** | 硬件指纹采集可能触发隐私合规（GDPR/个保法） | 无硬件采集 |

---

## 5. 取舍建议

### 5.1 Prism-Fusion 该用哪个？

**主方案：继续走注册制**（SaaS 模型已经完备，无需重造）。

理由：
1. Prism-Fusion 的 LLM 调用、Prompt 下发、文件解析、生成任务全部经过 `cloud_service`，**用户端拿不到"离线运行"的价值**——本地跑不出结果，硬件锁没有意义。
2. 现有 `Subscription + Usage + CreditLedger` 已经把"订阅 / 免费额度 / 积分 / 退款撤销"跑通，比 bidmaster 的激活码模型对消费者更友好。
3. Open Core 路线是"开源版免费跑 + 云端 Pro 订阅"，注册制天然贴合。

**辅方案：为「企业私有化客户端」预留授权制 provider**（可选，未来 3-6 个月）。

触发条件（出现以下任一情况再做）：
- 有大客户要买"离线版 / 本地后端 + 私有 LLM"版本，付费 5-50 万。
- 有客户明确要求"我们自己的部署，不需要上传数据到你们服务器"。
- 有桌面离线版产品计划（把 LLM 也跑在客户机器上，比如 Ollama）。

### 5.2 若结合，怎么设计？

**「账号 + 授权码」双层模型**：

```
[Cloud 主账号 (users 表)]          [私有化部署授权 (licenses 表)]
       │                                    │
       │  1:0..1                            │  1:1（一台私有后端）
       │                                    │
       └──── user_id / admin_user_id ───────┘
```

- **注册账号**仍然是唯一身份和主支付通道（保留 `users` + `subscriptions`）。
- **授权码**只针对"客户要私有化部署客户端"的场景签发，`licenses.customer` 关联到某个 `users.id` 或外部客户标识。
- 客户在**云端**买了 Pro 订阅 → 云调用用 `subscription`；同时若购买了"私有化部署许可" → 云端多签一条 license → 客户在自己的机器上跑一份客户端后端（复用 bidmaster 的客户端模式）→ 从云端领 token → 离线 14 天。

### 5.3 对 Open Core 商业化的影响

- 免费层：本地 Web UI + 云端 LLM 代理的每月免费额度（当前 `free_quota`）。
- Pro 订阅：月/年付费 + 更多额度 + 高级能力（对齐当前订阅模型）。
- **企业私有版**（可选，新增）：一次性或年付 license，客户自己部署后端 + 自带 LLM（Ollama / vLLM / 商用 API）。定价：10-50 万/套。这条路径需要 Ed25519 授权模块。
- 不做的坏处：无法承接大客户私有化订单；做得早了浪费人力。

---

## 6. 集成路径（若决定借鉴）

### 6.1 可直接复用的模块

从 `/opt/bidmaster` 拷贝以下文件即可，几乎无耦合：

| 源文件 | 目标位置建议 | 依赖 |
|---|---|---|
| `core/machine_id.py` | `cloud_service/license/machine_id.py` | 无（纯 stdlib） |
| `core/license.py`（Provider 抽象） | `cloud_service/license/provider.py` | 无 |
| `core/license_ed25519.py`（Ed25519 Provider） | `cloud_service/license/ed25519_provider.py` | `cryptography` |
| `core/license_public_key.py`（编译进客户端） | 客户端包 | `cryptography` |
| `services/routers/license.py` 的核心部分（去转发层） | `cloud_service/license/router.py` | FastAPI + SQLAlchemy |
| `services/models.py:License` 表 | `cloud_service/license/models.py` | SQLAlchemy |
| `services/middleware/license_gate_middleware.py` | 私有化客户端自带（**不进 cloud_service**） | Starlette |

**要改动的**：
- 去掉 `License.session_key`（提示词加密下发是 bidmaster 独有的 skill server 需求，Prism-Fusion 不需要）。
- 去掉 `_forward_to_remote` 客户端/服务器双模式——Prism-Fusion 的 cloud_service 就是权威端。
- 保留：激活码生成、Ed25519 签名、心跳 refresh、硬件绑定、状态机、限流、审计日志。

### 6.2 集成步骤

1. **新增数据库表** `licenses`（≈5 分钟）
2. **新增路由** `/cloud/license/*`：`/status` `/activate` `/refresh` `/deactivate` `/machine-id` `/auto-activate`（≈1 天）
3. **管理后台**：加"私有化授权"页面：生成/禁用/分配/查看激活码（≈1 天）
4. **客户端 SDK**（Python）：新包 `prism-license-client`，供私有化部署方引用；封装 machine_id + Ed25519 验签 + 心跳调度（≈1.5 天）
5. **私有化部署镜像**：`cloud_service --license-mode=private` 启动，接 Ed25519 provider；把 skill_server 概念换掉（可选）（≈1 天）
6. **前端**：设置页加"私有化部署码"输入框 + 状态展示（≈1 天，Electron 侧）
7. **测试 + 文档**（≈1.5 天）

**总工作量估算：5-8 人日**（不含私有化部署的运维/交付工具）。

### 6.3 落地风险

- **硬件指纹合规**：`machine_id` 采集主板/磁盘序列号，在部分行业（金融、医疗）可能触发隐私审查。文档需说明采集范围、可关闭。
- **私钥泄露**：`BMP_LICENSE_PRIVATE_KEY` 一旦泄露等于全线授权失守。上线时必须用 KMS/HSM 存，不能只放 `.env`。
- **时间回拨**：Ed25519 方案对本地改时间不敏感（token exp 是服务端签名，改本地时间会让"未过期 token 变过期"，但不会主动上报——用户可能利用短暂窗口多跑）。可考虑加"上次心跳时间戳 > 当前 token iat"的 sanity check。
- **换机流程**：客户机器坏了 → 联系运营 → admin 手动解绑 → 客户端重新激活。目前 bidmaster 支持 admin 接口，但**没有自助换机次数配额**，建议加上（比如每年 2 次）。

---

## 7. 剩余不确定性 / 未确认项

- 未确认 `/opt/bidmaster` 里 `admin.py` 中 `CreateLicenseRequest` / `AssignLicenseRequest` 的完整字段清单（只看到用法），推测：`{customer, expires_at?, valid_days?}` / `{user_id}`。
- 未连数据库实查 `licenses` 表的实际行数、活跃激活码数量、心跳分布——本次任务只读代码，未连 MySQL/PG。
- 未查看 `core/skill_client.py` 与 `routers/skill_server.py` 的完整实现——`session_key` 用途已确认是"加密下发提示词"，但加密算法（AEAD / 对称算法）未逐字节读完。若将来引入此模式，需再补一轮调研。
- 未验证 `LICENSE` 文件中的 AGPL-3.0 授权对 Prism-Fusion 是否有传染性风险——**bidmaster 是 AGPL-3.0**，直接拷贝代码进 Prism-Fusion 若走 SaaS 分发路径，需注意 AGPL §13 的"网络服务用户"条款。建议集成时**重写而非拷贝**核心实现（思路借鉴，代码不复用），或者在 Prism-Fusion 中另立 `vendor/` 目录加 SPDX 标注。
- 前端"未激活灰化 UI"逻辑（`prism_frontend/src/hooks/useLicenseHeartbeat.ts`）只看到了心跳，未逐像素核对激活码输入 UI 是否存在——现有前端看起来是纯订阅模型，没有激活码入口。若引入授权制需要新建入口。
