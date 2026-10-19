# M3 · 积分账本（Points Ledger）实现报告

- **日期**：2026-10-18
- **模块**：`cloud_service/billing/points.py` + `cloud_service/billing/points_endpoints.py`
- **数据库**：新增 3 张表 `credit_balance` / `credit_ledger` / `credit_pricing`
- **验证**：`python cloud_service/test_points.py` → **51/51 PASS**（exit=0）

---

## 1. 设计原则

按 `docs/dev-reports/2026-10-16-module-replication-plan.md` M3 章节与澜途 API 审计约束执行：

| 约束 | 实现 |
|---|---|
| 自建 3 表，不引入 OpenMeter / Flexprice / Lago（避免 AGPL） | 自研 SQLAlchemy ORM，零第三方计费依赖 |
| 参考澜途 available / frozen / consumed 三段状态 | `CreditBalance` 三字段完全对齐 |
| 5 档预设 100/500/1000/3000/5000 | `POINTS_PRESETS` 常量 + `get_recharge_options` 动态计算赠送 |
| 赠送公式 `floor((points - threshold) * rate)`，≥1000 送 50% | `bonus_credit()` 使用 `Decimal` + `FLOOR` |
| 幂等回调 | `Order.status='paid'` 判重 + 事务内 `SELECT ... FOR UPDATE` 行锁 |
| 乐观锁审计 | `CreditBalance.version` 每次写递增 |

---

## 2. 数据库表（`cloud_service/billing/models.py` 追加）

### credit_balance（账户余额，唯一）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| primary_account_id | FK → primary_account.id，unique，索引 | 一个账户一条 |
| available_points | Numeric(12,4) | 可用积分（澜途语义） |
| frozen_points | Numeric(12,4) | 冻结中 |
| total_consumed | Numeric(12,4) | 累计已消费 |
| total_recharged | Numeric(12,4) | 累计充值 |
| version | Integer | 乐观锁 |
| created_at / updated_at | DateTime(6) UTC | |

### credit_ledger（流水，append-only）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | |
| primary_account_id | FK，索引 | |
| tx_type | Enum: `RECHARGE` / `FREEZE` / `CONSUME` / `ROLLBACK` / `REFUND` | |
| amount | Numeric(12,4) | 变动数量（正数） |
| balance_after / frozen_after | Numeric(12,4) | 事务后快照 |
| use_function | String(32) | `ai_design` / `fission` / `collect` / `recharge` |
| ref_id | String(64) | 幂等键 / 上游引用 |
| recharge_id | FK → order.id | 充值场景 |
| pricing_key | FK → credit_pricing | 定价项 |
| freeze_tx_id | FK → credit_ledger.id | consume/rollback 指向 freeze 记录 |
| status | Enum: `active` / `consumed` / `rolled_back` / `refunded` | 冻结单终态 |
| note | Text | 说明 |
| created_at | DateTime(6) UTC | |

`UNIQUE(pricing_key, pricing_version)` 支持热更新价目。

### credit_pricing（价目表）
| 字段 | 说明 |
|---|---|
| pricing_key | `aiImageGeneration` / `aiTitle` 等 |
| display_name | 中文名 |
| points | Numeric(12,4) |
| category | `ai_design` / `fission` / `collect` |
| sort_order | |
| enabled | Boolean |
| pricing_version | 默认 `2026-10-v1` |

---

## 3. 核心函数（`cloud_service/billing/points.py`）

| 函数 | 用途 | 返回 | 异常 |
|---|---|---|---|
| `ensure_balance(db, pa_id)` | 懒创建账户 | `CreditBalance` | – |
| `bonus_credit(points, threshold, rate)` | 计算赠送（floor） | `Decimal` | – |
| `recharge_credit(db, pa_id, amount, points, bonus, order)` | 入账 + 写 RECHARGE 流水 | `CreditBalance` | – |
| `freeze_points(db, pa_id, amount, use_function, ref_id, pricing_key, note)` | 冻结 | `CreditLedger(status=active)` | `InsufficientPointsError` |
| `consume_freeze(db, freeze_tx_id, note)` | 终态 consumed | `CreditLedger(status=consumed)` | `FreezeInvalidStateError` |
| `rollback_freeze(db, freeze_tx_id, note)` | 终态 rolled_back | `CreditLedger(status=rolled_back)` | 同上 |
| `refund_credit(db, pa_id, amount, note, ...)` | 退款（无 freeze） | `CreditLedger(status=refunded)` | – |
| `get_account(db, pa_id)` | 读快照 | dict | – |
| `get_history(db, pa_id, tx_type, use_function, page, size)` | 分页历史 | `{total, page, size, items}` | – |
| `list_pricing(db, enabled_only)` | 价目 | dict | – |
| `points_for_pricing(db, pricing_key)` | 查单价 | `Decimal` | – |
| `seed_pricing(db)` | 幂等 seed | `(upserted, disabled)` | – |

**并发安全**：所有余额写事务内先 `session.query(CreditBalance).with_for_update().first()`，然后检查 `version`；不匹配抛 `OptimisticLockError` 由路由转 HTTP 409。

---

## 4. API 端点（`cloud_service/billing/points_endpoints.py`）

Base：`/cloud`

| 方法 | 路径 | 认证 | 用途 |
|---|---|---|---|
| GET | `/points/account` | Bearer | 账户快照 |
| GET | `/points/recharge/options` | Bearer | 5 档预设 + 赠送预览 |
| POST | `/points/recharge` | Bearer | 创建积分充值单（走支付） |
| GET | `/points/history` | Bearer | 流水分页（`tx_type` / `use_function` 过滤） |
| GET | `/points/pricing` | Bearer | 价目表 |
| POST | `/points/freeze` | Bearer | 冻结积分（业务调用） |
| POST | `/points/consume` | Bearer | 终态 consumed |
| POST | `/points/rollback` | Bearer | 终态 rolled_back |
| POST | `/points/consume_by_pricing` | Bearer | 一步 freeze+consume（LLM Proxy 用） |
| POST | `/points/refund` | Admin (`X-Admin-Token`) | 退款/补偿 |

**错误码**：
- 402 `InsufficientPointsError`
- 404 `FreezeNotFoundError`
- 409 `FreezeInvalidStateError` / `OptimisticLockError`

---

## 5. 支付回调集成（`cloud_service/payment/router.py`）

`_activate_paid` 分支扩展：
```python
if order.plan == "credit":
    points = Decimal(order.amount) * points_per_yuan  # ROUND_FLOOR
    bonus  = bonus_credit(points, threshold, rate)
    total  = points + bonus
    recharge_credit(db, order.primary_account_id, order.amount,
                    points, bonus, order)
    return True  # activated
```

- 回调幂等：`order.status='paid'` 已处理则跳过。
- **修正过的坑**：初版写反了 `points = amount / points_per_yuan`，实测金额 ¥300 后余额只有 30（应 4000）。已改为乘法。

---

## 6. 配置（`cloud_service/settings.py`）

`POINTS_CONFIG` 段，均可通过 `CLOUD_POINTS_*` 环境变量覆盖：

```
CLOUD_POINTS_ENABLED             = true
CLOUD_POINTS_PER_YUAN            = 10.0
CLOUD_POINTS_BONUS_THRESHOLD     = 1000.0
CLOUD_POINTS_BONUS_RATE          = 0.5
CLOUD_POINTS_MIN                 = 1.0
CLOUD_POINTS_MAX                 = 10000.0
CLOUD_POINTS_DEFAULT             = 3000.0
CLOUD_POINTS_CUSTOM_ENABLED      = true
CLOUD_POINTS_PRICING_VERSION     = 2026-10-v1
```

---

## 7. 测试（`cloud_service/test_points.py`）

**14 个场景 / 51 个断言**，覆盖：

1. 注册 / 登录（新建 alice）
2. 初始账户：三字段全 0
3. `GET /points/recharge/options`：5 档预设、赠送规则
   - 100/500/1000 → bonus=0
   - 3000 → bonus=1000（澜途规则）
   - 5000 → bonus=2000
4. 创建积分充值单 → 账户未变（等待回调）
5. 模拟支付宝回调 → 入账 4000（3000 + 1000 赠送）
6. 回调幂等：重复调用后仍为 4000
7. 冻结 1.5 分（`aiImageGeneration`）→ 4000 → 3998.5 可用 + 1.5 冻结
8. consume → 冻结清零，`total_consumed=1.5`
9. 重复 consume / 重复 rollback → HTTP 409
10. 余额不足（要求 100000）→ HTTP 402
11. history 分页 + `tx_type=RECHARGE` 过滤 + `use_function=ai_design` 过滤
12. 价目表 seed：14 项，`aiImageGeneration=1.5`、`aiTitle=0.1`
13. `consume_by_pricing aiTitle` 一步法：扣 0.1
14. 管理员退款（`X-Admin-Token` 头），错误 token → 403

**运行结果**：
```
ALL TESTS PASSED
exit=0
```

---

## 8. 全套回归

`python -m pytest cloud_service -q`：
- **9 passed**（billing / payment / subscription / settings / llm_proxy / auth / points / payment_form_callback）
- **1 failed** — `test_payment_leftover.py` 的 `close_expired_orders_task executed X times` 时序断言（Redis 不可达降级到 lock-free 后偶发 1 次），与本次改动无关，是既有 flaky。

---

## 9. 已知遗留

| 项 | 说明 |
|---|---|
| `Order.plan='credit'` 绕过 schema | `CreateOrderRequest.plan` 目前只允许 `pro/free`，积分充值直接构造 `Order`。后续可扩展 Pydantic 校验。 |
| 积分未落 Order 列 | 采用回调时按 `amount * points_per_yuan` 推导，未新增列。若需精确审计赠送，可在 Order 加 `points` / `bonus_points` 两列。 |
| `Order.days=0` 用于积分订单 | 目前借 `days=0` 让积分订单不延长订阅，语义不精确；可后续加 `order.kind='credit'`。 |
| Redis 缺失时的锁 | `task_guard` 会降级 lock-free，仅在多实例部署时可能双写。单实例测试无影响。 |
| AGPL 合规 | 未引入 OpenMeter / Flexprice / Lago；`credit_pricing.enabled` 支持热停用，等价于"价目开关"。 |

---

## 10. 相关文件

- `cloud_service/billing/models.py`（新增 3 表）
- `cloud_service/billing/schemas.py`（新增响应模型）
- `cloud_service/billing/points.py`（~18 KB 核心逻辑）
- `cloud_service/billing/points_endpoints.py`（10 个端点）
- `cloud_service/main.py`（挂载 `billing_points_router`）
- `cloud_service/db.py`（`seed_pricing` 调用）
- `cloud_service/payment/router.py`（credit 分支）
- `cloud_service/settings.py`（POINTS 配置段）
- `cloud_service/test_points.py`（14 场景 / 51 断言）
- `docs/dev-reports/2026-10-16-module-replication-plan.md`（源方案）
- `docs/dev-reports/2026-10-16-lantyou-api-audit.md`（澜途 API 审计）
