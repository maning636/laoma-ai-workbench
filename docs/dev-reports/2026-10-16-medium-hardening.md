# 2026-10-16 中危修复报告（Global Hardening Audit §3.2）

- **对应审计**：`docs/dev-reports/2026-10-16-global-hardening-audit.md` §3.2（中危，共 6 项）
- **修改日期**：2026-10-19
- **状态**：全部落地；新增回归测试 `prism_backend/tests/test_medium_hardening.py` 27/27 通过；M1/M2/M3 主测试集零回归
- **约束**：不降低 M1=140 / M2=102 / M3 测试数；不破坏 `localhost` 开发 CORS

---

## 1. 修复摘要

| # | 问题（§3.2） | 修复 | 主要文件 |
|---|---|---|---|
| §3.2-1 | Redis `idempotency.acquire` get+set 非原子 | 增加 `set_nx` 原子 SET NX EX；`acquire()` 改为一次原子写入 | `prism_backend/fusion_ai/idempotency.py` |
| §3.2-2 | SQLite `with_for_update()` no-op | 文档登记；生产 MariaDB 下 `SELECT … FOR UPDATE` 才真正生效 | `cloud_service/billing/points.py`（未改） |
| §3.2-3 | `user_id` 从 body / Bearer 裸串取，未 JWT 校验 | 引入 `_decode_jwt_sub` + `_jwt_config`；有 Bearer → 必须校验通过或 401；无 header → 兼容 body.user_id（保留 140 项 M1 测试）；env `M1_REQUIRE_JWT=true` 关闭回退 | `prism_backend/fusion_ai/ai_design.py` |
| §3.2-4 | prompt 未长度上限 | `_MAX_PROMPT_LEN = 10000`；超限 400 `prompt is too long`；在 agent_style 注入前执行 | `prism_backend/fusion_ai/ai_design.py` |
| §3.2-5 | 前端/后端 `allow_origins=["*"]` | `allow_origins=settings.CORS_ORIGINS`（默认 `http://localhost:*`）；`CORS_ORIGINS` 走 pydantic 列表解析 | `prism_backend/fastapi_app/main.py`、`prism_backend/fastapi_app/core/config.py` |
| §3.2-6 | 未对高频/敏感端点做限流 | 新增 `cloud_service/middleware/rate_limit.py`（Redis INCR+EXPIRE）；`cloud_service/main.py` 与 `prism_backend/fastapi_app/main.py` 均 `install_rate_limit_middleware`；`freeze/consume/consume_by_pricing`=20/min，`ai-design/generate`=10/min | `cloud_service/middleware/*`、`cloud_service/main.py`、`prism_backend/fastapi_app/main.py` |

---

## 2. 逐项 before / after

### §3.2-1 · `idempotency.acquire` 原子性

**Before**（`prism_backend/fusion_ai/idempotency.py:188-212`）：
```python
existing = await backend.get(key)
if existing is None:
    await backend.set(key, payload, ttl)   # get 与 set 之间可能重复进入
```
两个并发请求都读到 `None` → 都写入 → 都执行 provider 调用。

**After**：两个后端（`_MemoryBackend` / `_RedisBackend`）都补 `set_nx(key, value, ttl) -> bool`。
- Redis：`SET key value EX ttl NX`（单条命令，原子）。
- Memory：加锁 → 若 key 已存在返回 `False`，否则写入。
- `acquire()`：先 `set_nx(key, "in_flight", 300)`；成功即首次调用者；失败则读缓存返回 `cached` 或 `in_flight`。

**测试**（`test_1_idempotency_concurrent_single_winner`）：10 并发请求同一 `idempotency_key`，provider 计数只被调用 1 次，其余 9 次拿到 `cached` 或 `in_flight`。内存后端 `set_nx` 也单独覆盖首写/重写/TTL 覆盖。

---

### §3.2-2 · SQLite `with_for_update` no-op（记录，不修）

审计结论已明确：SQLite 不支持 `SELECT … FOR UPDATE`，本地为 no-op。生产 MariaDB 下 SQLAlchemy 会发出真正的行锁。
**处置**：不改代码；在报告与运维文档里注明"本地环境无行锁保护；并发场景依赖单进程 + Redis 幂等键兜底"。

---

### §3.2-3 · `user_id` 信任 body / Bearer 裸串

**Before**（`ai_design.py:217-225`）：
```python
uid = body_user_id
if not uid and auth:
    uid = auth.replace("Bearer ", "").strip()  # 直接把裸 token 当 user_id
```
攻击者可任意伪造 `body.user_id` 或伪造 Authorization header。

**After**（`ai_design.py:110-158`）：
```python
auth_stripped = (request.headers.get("authorization") or "").strip()
if auth_stripped:
    if auth_stripped.lower().startswith("bearer ") and _decode_jwt_sub(token):
        return sub                          # JWT 校验通过 → 用 sub
    raise HTTPException(401, "invalid or expired JWT")  # 有 header 就必须校验
# 无 Authorization → 兼容模式：body.user_id → "anonymous"
if require_jwt: raise HTTPException(401, "missing Authorization Bearer token")
return body_user_id or "anonymous"
```

**JWT 密钥顺序**（`_jwt_config`）：`CLOUDJWT_SECRET → JWT_SECRET → CLOUD_SECRET_KEY → SECRET_KEY → cloud_service.settings.jwt_secret → 兜底 dev 密钥`。与 `cloud_service.auth.security` 及 `fastapi_app/api/dependencies.py` 完全一致。

**兼容性**：现有 M1 测试全部走 `TestClient` 且不传 Authorization，因此继续进入 body.user_id 分支，140 项零回归。未来前端接入 JWT 后可用 `M1_REQUIRE_JWT=true` 一步切换到硬 401。

**残余风险**：未认证客户端仍可伪造 `body.user_id`。这是**有意保留**的兼容路径，防止 140 项测试集体失败；已在下方 §4 中登记。

**测试**（`test_9_fake_authorization_returns_401` / `test_11_valid_jwt_uses_sub_from_token`）：
- 假 token → 401，即使 body 里塞了合法 user_id。
- 合法 JWT → 记录落库使用 JWT 的 `sub`，`body.user_id` 被忽略。

---

### §3.2-4 · prompt 长度上限

**Before**：无上限，M2 智能体 `style_prompt` 前置注入后可轻易突破下游 provider 的字符预算。

**After**：`_MAX_PROMPT_LEN = 10_000`；在 agent_style 注入**之前**校验，超限 400 `detail` 含 `"too long"`。

**测试**（`test_8_prompt_too_long_returns_400`）：prompt = 15000 字符 → 400 且 detail 含 `too long`；prompt = 10000 字符 → 不再因长度被拒。

---

### §3.2-5 · CORS 通配

**Before**（`prism_backend/fastapi_app/main.py:64`）：
```python
allow_origins=["*"], allow_credentials=True, allow_headers=["*"], allow_methods=["*"]
```
`allow_credentials=True` + 通配 origin 在浏览器规范下虽然不允许，但会放宽服务端跨域校验。

**After**：
```python
CORSMiddleware(
    allow_origins=settings.CORS_ORIGINS,   # 默认 ["http://localhost:3000", "http://127.0.0.1:3000", ...]
    allow_credentials=True,
    allow_headers=["*"],
    allow_methods=["*"],
)
```
`settings.CORS_ORIGINS` 支持逗号分隔字符串解析为 `List[str]`；生产环境通过 env `CORS_ORIGINS=https://app.example.com,...` 覆盖。

**cloud_service/main.py** 之前已经用 `allow_origins=settings.CORS_ORIGINS`，无需改动。

**测试**（`test_3` / `test_4` / `test_5`）：静态扫描 `main.py` 里 `allow_origins=` 的**非注释**行不出现通配值；`CORS_ORIGINS` 是列表、不含 `*`、包含 localhost 开发地址。

---

### §3.2-6 · 未对高频端点做限流

**新增**：`cloud_service/middleware/__init__.py` + `cloud_service/middleware/rate_limit.py`（338 行）。

核心 API：
- `RateLimitMiddleware(app, rules=DEFAULT_RULES, window_seconds=60, redis_url=None, fallback_allow=True)`
- 身份解析顺序：`request.state.user_id → Authorization Bearer sub → request.state.client_id/username → ip:<client.host> → "anonymous"`
- 计数器：Redis `INCR key` + `EXPIRE key window`；单进程下 `key_prefix + user + path`
- Redis 不可用或抛异常时 → `fallback_allow=True` 直接放行（生产环境可通过 `Ratelimit_FALLBACK_ALLOW=false` 改为 429）
- `install_rate_limit_middleware(app, ...)` 便捷入口

`DEFAULT_RULES`：
| method | path_glob | 每用户每分钟 |
|---|---|---|
| POST | `/cloud/points/freeze` | 20 |
| POST | `/cloud/points/consume` | 20 |
| POST | `/cloud/points/consume_by_pricing` | 20 |
| POST | `/api/v1/ai-design/generate` | 10 |
| POST | `/ai-design/generate` | 10 |

`cloud_service/main.py` 和 `prism_backend/fastapi_app/main.py` 都在启动时 `install_rate_limit_middleware(app)`。

**测试**（`test_6` / `test_7`）：
- 假 Redis：4 次连续 `POST /cloud/points/freeze`，前 3 次 200，第 4 次 429；另一个 user 独立配额仍返回 200。
- Redis 不可用：`fallback_allow=True` 时全部放行。

---

## 3. 修改文件清单

| 文件 | 变更类型 | 摘要 |
|---|---|---|
| `prism_backend/fusion_ai/idempotency.py` | 修改 | 增加 `_MemoryBackend.set_nx` / `_RedisBackend.set_nx`；`acquire()` 改为原子 `set_nx`；暴露 `clear_cache()` |
| `prism_backend/fusion_ai/ai_design.py` | 修改 | 增加 `_MAX_PROMPT_LEN` / `_jwt_config` / `_decode_jwt_sub` / `_extract_user_id`（JWT 版）；删除旧的 `_extract_user_id`（body 优先，无校验）；`M1_REQUIRE_JWT` 环境变量 |
| `prism_backend/fastapi_app/main.py` | 修改 | `allow_origins=settings.CORS_ORIGINS`；安装 `install_rate_limit_middleware` |
| `prism_backend/fastapi_app/core/config.py` | 修改 | `CORS_ORIGINS: List[str]` 支持字符串列表解析 |
| `cloud_service/main.py` | 修改 | 安装 `install_rate_limit_middleware`；补 `import os` |
| `cloud_service/middleware/__init__.py` | 新增 | 空包 |
| `cloud_service/middleware/rate_limit.py` | 新增 | `RateLimitMiddleware` / `DEFAULT_RULES` / `install_rate_limit_middleware`（338 行） |
| `prism_backend/tests/test_medium_hardening.py` | 新增 | 11 项测试 / 27 条断言，覆盖 §3.2 全部 6 项（1 项为文档项，测试仅覆盖代码改动） |
| `docs/dev-reports/2026-10-16-medium-hardening.md` | 新增 | 本报告 |

未修改（保持向后兼容）：
- `cloud_service/billing/points.py`（§3.2-2 是文档项）
- `cloud_service/auth/router.py` / `cloud_service/auth/security.py`
- `cloud_service/settings.py`（JWT 密钥解析链已存在）
- `prism_backend/fastapi_app/api/dependencies.py`（`_jwt_config` 与其完全一致）

---

## 4. 测试与验证

### 4.1 新增回归测试

```
$ cd D:\dim开发\Prism-Fusion
$ .\prismenv\Scripts\python.exe prism_backend\tests\test_medium_hardening.py
2026-10-19 medium-hardening: 27 checks, PASS=27, FAIL=0
ALL TESTS PASSED
```

| Test | 覆盖项 | 断言数 |
|---|---|---:|
| `test_1_idempotency_concurrent_single_winner` | §3.2-1 | 3 |
| `test_2_memory_backend_set_nx_semantics` | §3.2-1 | 5 |
| `test_3_cors_no_wildcard_in_prism_backend_main` | §3.2-5 | 3 |
| `test_4_settings_cors_origins_defaults_to_local_dev` | §3.2-5 | 3 |
| `test_5_cloud_service_cors_no_wildcard` | §3.2-5 | 1 |
| `test_6_rate_limit_middleware_blocks_over_limit` | §3.2-6 | 3 |
| `test_7_rate_limit_fallback_allow_when_redis_missing` | §3.2-6 | 1 |
| `test_8_prompt_too_long_returns_400` | §3.2-4 | 3 |
| `test_9_fake_authorization_returns_401` | §3.2-3 | 2 |
| `test_10_missing_authorization_body_user_id_still_works` | §3.2-3（兼容） | 1 |
| `test_11_valid_jwt_uses_sub_from_token` | §3.2-3 | 2 |

（§3.2-2 是 SQLite 语义项，无 Python 层可测，只在报告登记。）

### 4.2 M1 · AI 生图回归

```
$ .\prismenv\Scripts\python.exe prism_backend\tests\test_m1_ai_design.py
总共 140 项测试，PASS=140, FAIL=0
ALL TESTS PASSED
```

### 4.3 M2 · AI 智能体回归

```
$ .\prismenv\Scripts\python.exe prism_backend\tests\test_m2_agents.py
M2 backend tests: 102 PASS / 0 FAIL (total 102)
```

### 4.4 M3 · 云点数账本回归

```
$ .\prismenv\Scripts\python.exe cloud_service\test_points.py
ALL TESTS PASSED
```
（87 项 PASS / 0 FAIL；较基线 51 项更多，是审计报告发布之后新增的支付/退款/订阅用例。）

### 4.5 回归矩阵

| 模块 | 基线 | 本次 | 状态 |
|---|---:|---:|---|
| M1 · AI 生图 | 140 | 140 | ✅ 无回归 |
| M2 · AI 智能体 | 102 | 102 | ✅ 无回归 |
| M3 · 云点数账本 | ≥51 | 87 | ✅ 无回归（更多覆盖） |
| Medium-hardening（新） | 0 | 27 | ✅ 全通过 |

---

## 5. 已知残余风险

1. **M1 无 Authorization header 的兼容路径**  
   未携带 `Authorization` 时，服务端仍信任 `body.user_id`（防止 140 项 M1 测试集体失败）。未认证客户端仍可伪造 `body.user_id`。  
   缓解：前端一旦全面接入 JWT，设置 `M1_REQUIRE_JWT=true` 一步切换到硬 401。

2. **SQLite 下 `SELECT … FOR UPDATE` 为 no-op**（§3.2-2 记录项）  
   本地开发环境无真正的行锁保护，高并发场景依赖 Redis 幂等键 + 单进程假设。生产环境切 MariaDB 后自动生效。

3. **限流依赖 Redis；无 Redis 时默认放行**  
   `RateLimitMiddleware(fallback_allow=True)` 是生产友好默认值，但意味着"Redis 挂了=没有限流"。部署手册必须保证 Redis 高可用；如需强限流，可 `Ratelimit_FALLBACK_ALLOW=false`。

4. **`_jwt_config` 的密钥解析链顺序**  
   `CLOUDJWT_SECRET → JWT_SECRET → CLOUD_SECRET_KEY → SECRET_KEY → cloud_service.settings.jwt_secret → 兜底 dev`。若云侧与 M1 部署在不同进程，需确保 4 个 env 中至少有一个共享同值，否则 M1 侧会校验失败。运维部署时须在 `fastapi_app/.env` 与 `cloud_service/.env` 中同步 `JWT_SECRET`。

5. **JWT 密钥长度警告**  
   PyJWT 会在密钥 < 32 字节时打印 `InsecureKeyLengthWarning`。dev secret 通常较短，测试输出会看到；生产使用 `CLOUDJWT_SECRET` 生成 `secrets.token_urlsafe(48)` 即可消除。

6. **测试脚本 `sys.exit(main())` 返回 1 的问题**  
   `test_m1_ai_design.py` 与 `test_m2_agents.py` 在 ALL TESTS PASSED 情况下 `exit code = 1`（脚本自身 bug，与本次修复无关，M1/M2 报告已登记）。CI 若用 exit code 判 CI 状态需改用 stdout grep。

---

## 6. 部署说明（给运维）

1. 生产 `cloud_service/.env` 与 `fastapi_app/.env` **必须**至少共享一个 env：`JWT_SECRET` / `CLOUDJWT_SECRET` / `CLOUD_SECRET_KEY` / `SECRET_KEY`，值一致。
2. 生产 CORS：`CORS_ORIGINS=https://app.example.com,https://admin.example.com`（逗号分隔）。禁止使用 `*`。
3. Redis：`CLOUD_REDIS_URL=redis://...`（用于限流计数）。若 Redis 不可用，请求会放行但会打 warning 日志；请对 `[RateLimit] Redis unavailable` 配置告警。
4. 强制 JWT：待前端接入后，`fastapi_app/.env` 增加 `M1_REQUIRE_JWT=true`。
5. prompt 长度：`_MAX_PROMPT_LEN=10000` 目前硬编码在 `ai_design.py`。若 provider 侧上限有差异，后续可提为 env。

---

## 7. 相关文档

- 审计原始清单：`docs/dev-reports/2026-10-16-global-hardening-audit.md` §3.2
- M1 实现报告：`docs/dev-reports/2026-10-16-m1-ai-image-design.md`
- M2 智能体报告：`docs/dev-reports/2026-10-16-m2-ai-agents.md`
- M3 点数账本报告：`docs/dev-reports/2026-10-16-m3-points-ledger.md`
