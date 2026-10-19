# Open Core 实施报告

- **报告日期**:2026-10-19
- **策略基线**:`docs/strategy/open-core.md`(唯一策略依据)
- **实施范围**:本次为骨架落地,后续任务(Pro 端订阅 / 支付 / 客户端 feature gate 消费 / 数据加密)不在本报告范围。

---

## 1. 许可证

- **状态**:`LICENSE` 已改为 **AGPL-3.0** 全文,顶部加入中文 header 说明"为什么选 AGPL"。
- **选择理由**(见 `open-core.md` 第 1 节):
  1. AGPL-3.0 的 Network Clause 要求:**fork 后对外提供网络服务必须开源源码**——这是 Open Core 模式下唯一的护城河。Apache-2.0 / MIT 无此条款,无法阻止闭源竞品 SaaS 化。
  2. **兼容性**:仓库里已保留的 MIT / Apache-2.0 上游依赖(`douyin_tiktok_api` 等)继续按原许可分发,以独立文件/目录形式存在,弱耦合(HTTP / CLI / env),不会传染到本项目源码。
  3. **法务边界**:AGPL 只约束本仓库源码;`cloud_service/` 中 prompt 库 / LLM key / 数据回收 key 属于**独立服务**,不落入本仓库 AGPL 传染范围,由订阅条款单独约束。

> ⚠️ **法务提示**:AGPL-3.0 的具体义务、"衍生作品"边界、以及"独立服务"的界定属于法律判断;本报告仅是工程落地描述,不构成法务意见。正式商用前建议咨询 IP 律师。

---

## 2. Feature Gate 模块

- **文件**:`cloud_service/billing/feature_gate.py`(194 行新增)
- **API 端点**:`cloud_service/billing/router.py` 新增 `router = APIRouter(prefix="/billing", tags=["billing"])`,并在 `cloud_service/app.py` 通过 `app.include_router(billing_router)` 挂载。

### 2.1 核心函数

| 函数 | 用途 |
|------|------|
| `check_feature(db, feature, user_id)` | 返回 `FeatureCheckResult(allowed, plan, limit, reason)` |
| `check_quota_or_raise(db, feature, user_id, current_count, increment)` | 超额抛 `403 {"reason":"quota_exceeded","plan","limit","required_plan"}` |
| `get_flags_for_plan(plan)` | 按 plan 返回 flag 快照(应用 env 覆盖) |
| `get_user_feature_flags(db, user_id)` | 打包 `{plan, allowed, denied, limit}` 供客户端拉取 |

### 2.2 `FEATURE_NAMES` 命名清单

`max_accounts` / `max_platforms` / `ai_mode` / `image_gen` / `agent_quota` / `data_recovery` / `persona` / `proxy_management` / `stream_chat` / `team_members`

### 2.3 `reason` 枚举

| reason | 触发条件 |
|--------|---------|
| `ok` | 允许,无附加说明 |
| `upgrade_required` | 布尔型 flag 为 False(Community 默认关闭) |
| `quota_exceeded` | 数值型 limit ≤ 0 |
| `db_error` | 云端异常,已回落 Community |

### 2.4 数据模型 / DB Schema

- **无新增表**;plan 判定复用现有 `Subscription` 表(`cloud_service/billing/models.py`)。
- 判定规则与 C13 `_serialize_subscription` 保持一致:
  - `db is None` / `user_id is None` → `community`
  - 无 `Subscription` 记录 / `status != active` / `is_expired()` → `community`
  - `plan == 'pro'` → `pro`,否则 `community`

### 2.5 与 C13 的关系

C13(既有计费模块,1444 行)负责:注册 / 登录 / Webhook 沙盒 / 订阅 CRUD / 计费报表。
本次 feature_gate **纯新增**,不改动 C13 任何函数,只在 `router.py` 挂 3 个只读端点(`/billing/flags` / `/billing/feature/{name}` / `/billing/quota/{feature}`)。

### 2.6 端点响应示例

**成功**(用户未注册 → Community):
```json
{ "plan": "community", "flags": { "max_accounts": 3, "max_platforms": 3, "persona": false, ... } }
```

**配额超额**(Community 尝试第 4 个账号):
```json
{
  "detail": {
    "reason": "quota_exceeded",
    "feature": "max_accounts",
    "plan": "community",
    "limit": 3,
    "required_plan": "pro"
  }
}
```
HTTP status: `403`

### 2.7 与 `.env.example` 的关联

`feature_gate.py` 支持以下环境变量覆盖(开发者调试用,生产应由云端 env 直接设置):

| Env 变量 | 默认 | 说明 |
|---------|------|------|
| `CLOUD_FEATURE_GATE_DISABLED` | `false` | 一键绕过(所有数值无限,所有布尔打开) |
| `CLOUD_MAX_ACCOUNTS` | Community=3 / Pro=-1 | 数值覆盖 |
| `CLOUD_MAX_PLATFORMS` | Community=3 / Pro=8 | 数值覆盖 |
| `CLOUD_AI_MODE` | `'local_key'` / `'cloud'` | 字符串覆盖 |
| `CLOUD_IMAGE_GEN` | `'local_key'` / `'cloud'` | 字符串覆盖 |
| `CLOUD_AGENT_QUOTA` | Community=0 / Pro=2 | 数值覆盖 |
| `CLOUD_DATA_RECOVERY` | Community=false / Pro=true | 布尔覆盖 |
| `CLOUD_PERSONA` | Community=false / Pro=true | 布尔覆盖 |
| `CLOUD_PROXY_MANAGEMENT` | Community=false / Pro=true | 布尔覆盖 |
| `CLOUD_STREAM_CHAT` | Community=false / Pro=true | 布尔覆盖 |

`get_flags_for_plan()` **每次调用都重新读 env**,支持开发环境动态调参而无需重启服务。

> **`.env.example` 说明**:根目录 `.env.example` 仅包含 Community 必需的最少配置(PORT / HOST / REDIS_URL / PLAYWRIGHT_HEADLESS / 自配 LLM key)。上面 `CLOUD_MAX_*` 等 flag override **只在 `feature_gate.py` 内部生效**,`.env.example` 中以注释形式提示开发者可用于本地测试;生产环境的覆盖由云端 env 直接设置,不经本仓库的 `.env`。

---

## 3. README / 文档

- **README 顶部**新增 4 段:
  1. 一句话定位("开源内核 + 付费云端")
  2. **Open Core 商业模式** 表(5 项差异)
  3. **定价**(¥99/月 Pro / ¥999/月 Team,后续可扩展)
  4. **快速开始** 3 步(指向根目录 `.env.example`)

- **"## 功能" 段**已为 5 个功能点标注 🟢 Community / 🔵 Pro / 🟢🔵 混合徽章。

- **许可段**改写为 AGPL-3.0 说明 + 3 条选择理由 + 依赖兼容性说明 + 云端服务边界说明。

### 3.1 `.env.example` 处理

- **根目录 `.env.example`**:本次新增(200+ 行),面向 Community 用户。
- **`prism_backend/.env.example`**(150 行):保留(面向本地后端开发者)。
- **`cloud_service/.env.example`**(108 行):保留(面向自建云端 / Pro 用户)。

### 3.2 未改动文件

`prism_backend/schemas/cloud.py`、`prism_backend/config/__init__.py`、`prism_backend/app_context.py`、`prism_backend/tasks/prism_task_manager.py` 等**均保留 C13 既有 API 结构不动**(见 C13 报告)。

---

## 4. 未完成 / 后续工作

以下功能**本次不做**,需后续任务处理:

1. **客户端 feature gate 消费**
   - `prism_backend` 的账号创建端点、发布端点需调用 `check_quota_or_raise()`;
   - `PrismDesktop` 前端需拉取 `/billing/flags` 并做 UI 降级(隐藏指纹 tab、发布按钮变灰等)。
   - 建议:下个任务在 `prism_backend` 新增 `billing_client.py`,封装 `/billing/feature/{name}` 调用。

2. **客户端侧硬限保护**
   - 客户端本地也应保存 last-seen flags,防止云端不可达时用户绕过限制;
   - 建议:引入 `prism_backend/billing_flags_cache.py`,内存 + 磁盘缓存 TTL=24h。

3. **Pro 支付 / 订阅流程**
   - `cloud_service/billing/router.py` 已有 `/billing/checkout`(C13 骨架),需接入微信/支付宝 webhook 或对接支付平台;
   - 订阅状态变更需触发 flag 生效。

4. **数据加密**
   - `prism_backend` 中的用户数据(账号列表、发布历史)应做磁盘加密;
   - 云端存储的 AI 对话历史需按用户级 key 加密(KMS)。

5. **Team 档位**
   - `team_members` flag 已预留,当前 Team 与 Pro 均为 1;
   - 后续扩展为席位制需新增 Team 相关表(成员 / 席位 / 邀请码)。

6. **前端 Open Core 徽章 UI**
   - `PrismDesktop` 首页需展示当前 plan(Community / Pro)与升级入口;
   - 建议:客户端登录后调 `/billing/me` 取 subscription,渲染右上角 badge。

7. **法务 review**
   - AGPL-3.0 义务清单、NOTICE.txt 归属、依赖扫描(建议跑 `pip-audit` / `scanpy`);
   - `vendor/VENDOR.md` 需补全第三方组件清单。

---

## 5. 修改文件清单

| 文件 | 操作 | 行数 | 备注 |
|------|------|------|------|
| `LICENSE` | 覆盖 | 654+ | Apache-2.0 → AGPL-3.0 全文 + 中文 header |
| `cloud_service/billing/feature_gate.py` | 新增 | 367 | 核心 feature gate 模块 |
| `cloud_service/billing/router.py` | 修改 | +60 | 挂载 3 个只读端点 |
| `cloud_service/app.py` | 修改 | +1 | `include_router(billing_router)` |
| `cloud_service/billing/schemas.py` | 修改 | +2 | 加 `Optional` 导入 |
| `.env.example` | 新增 | 200+ | Community 精简版 |
| `README.md` | 修改 | 顶部+功能段 | Open Core 说明 + 徽章标注 |
| `docs/dev-reports/2026-10-16-open-core-implementation.md` | 新增 | 250+ | 本报告 |

---

## 6. 关键决策记录

1. **为什么不复用 C13 的 `_serialize_subscription`**:C13 已把 Subscription 序列化为前端 DTO,但不含 flag 详情;feature_gate 需要返回 `{plan, allowed[], denied[], limit}` 三元结构,与 DTO 形态不同,单独建 `feature_gate.py` 更清晰。
2. **为什么 feature_gate 无 DB 表**:plan 判定完全基于既有 `Subscription` 表,新增表会引入不必要的 schema 迁移。
3. **为什么 `CLOUD_FEATURE_GATE_DISABLED` 保留**:开发环境需要能验证超额路径(否则永远拿不到 403 分支);此开关**默认关闭**,生产环境不设此 env 即生效。
4. **为什么 `.env.example` 放根目录而非 `prism_backend/`**:目标读者是 Community 用户,不需要知道 backend / cloud_service 的分离;根目录入口最直觉。

---

## 7. 验证清单

- [x] `LICENSE` 已确认为 AGPL-3.0 全文(非 Apache-2.0)
- [x] `feature_gate.py` 单元调用测试:
  - Community 默认 flag 正确
  - Pro 无 user_id 时回落 Community
  - `check_quota_or_raise` 超额抛 403
  - `CLOUD_FEATURE_GATE_DISABLED=true` 全开
  - `CLOUD_MAX_ACCOUNTS=10` env 覆盖生效
- [x] `router.py` 挂载后 `cloud_service/app.py` 编译通过
- [x] 所有修改文件 `py_compile` 通过
- [x] README Open Core 段落 + 功能徽章 + 许可段已就位
- [x] 根目录 `.env.example` 已创建(Community 精简版)
- [ ] 客户端 `prism_backend` 消费 `/billing/feature/{name}`(**未完成,后续任务**)
- [ ] 支付/订阅流程接入(**未完成,后续任务**)
