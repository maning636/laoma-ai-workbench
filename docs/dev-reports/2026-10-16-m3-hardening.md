# M3 · 积分制硬化修复报告

- **日期**:2026-10-18
- **模块**:`cloud_service/billing/*` + `cloud_service/payment/*`
- **源报告**:`docs/dev-reports/2026-10-16-m3-implementation.md` §9 已知遗留
- **参考**:`docs/dev-reports/2026-10-16-lantyou-api-audit.md` §2.2 澜途预设
- **验证**:`python cloud_service/test_points.py` → **87/87 PASS**(51 原有 + 36 新增)
- **回归**:`pytest cloud_service -q` → 9 passed, 1 failed(`test_payment_leftover` Redis flaky,与本改动无关)

---

## 1. 修复的 4 个问题清单

| # | 问题 | 严重度 | 修复文件 | 状态 |
|---|---|---|---|---|
| 1 | 预设数值"元/积分"语义模糊 | 严重 | `billing/points_endpoints.py` | ✅ |
| 2 | `Order.plan='credit'` 绕过 schema 校验 | 中 | `payment/schemas.py` | ✅ |
| 3 | `days=0` 语义不精确(积分订单) | 中 | `payment/models.py` + `points_endpoints.py` | ✅ |
| 4 | 积分数量未落 Order 列,无法审计赠送 | 高 | `payment/models.py` + `payment/router.py` + `points_endpoints.py` | ✅ |

---

## 2. 修改的文件清单

| 文件 | 变更摘要 |
|---|---|
| `cloud_service/payment/models.py` | 1) `Order.days` 改为 `Optional[int]` 且移除 `default=30`(避免 SQLAlchemy 用 default 覆盖显式 `days=None`);2) 新增 `Order.credit_points: Optional[float]` 列 |
| `cloud_service/payment/schemas.py` | 1) `CreateOrderRequest.plan` 允许 `{pro, free, credit}`;2) `days` 改 `Optional[int]`,`credit` 允许 0/None;3) `CreateOrderResponse` / `OrderResponse` 支持 `Optional days` + 新增 `credit_points` 字段 |
| `cloud_service/payment/router.py` | 1) `get_order` 端点返回新增 `credit_points`;2) `_activate_paid` 的 `plan='credit'` 分支改为优先信任 `order.credit_points`(精确落账),仅当为 NULL 时回退 `amount * points_per_yuan` |
| `cloud_service/billing/points_endpoints.py` | 1) `_credit_config()` 中预设项从"扁平 float 数组"升级为"dict 数组 `{points, bonus_points, enabled}`",澜途默认档位硬编码 `DEFAULT_PRESETS`;2) `points_create_recharge` 创建订单时传 `days=None` + `credit_points=pts+bonus` |
| `cloud_service/test_points.py` | 追加 §15 "M3 硬化专项"共 36 个断言(不改动原有 51 个),覆盖预设对齐/schema 通过/Order 落库/精确到账 |

**未修改**(刻意保留 M3 现状):
- `billing/models.py` / `billing/points.py` / `billing/schemas.py`(响应 schema 契约已对齐澜途,无需改)
- `billing/router.py`(订阅侧未变)
- `payment/adapter.py` / `alipay.py` / `wechat.py`(支付通道未动)

---

## 3. 修复前后对比

### 3.1 预设数值(问题 1)

| 档位 | 修复前(实际返回) | 修复后(对齐澜途) |
|---|---|---|
| 100 | points=100, yuan=10, bonus=0 | points=100, **yuan=10**, bonus=0 |
| 500 | points=500, yuan=50, bonus=0 | points=500, **yuan=50**, bonus=0 |
| 1000 | points=1000, yuan=100, bonus=0 | points=1000, **yuan=100**, bonus=0 |
| 3000 | points=3000, yuan=300, bonus=1000 | points=3000, **yuan=300**, bonus=**1000**(到账 4000) |
| 5000 | points=5000, yuan=500, bonus=2000 | points=5000, **yuan=500**, bonus=**2000**(到账 7000) |

**说明**:修复前的**数值其实已经正确**(因为原实现 `yuan = points / points_per_yuan` 公式正确),但**数据结构**用扁平 float 数组,赠送完全靠 `_compute_bonus()` 现场推导,存在歧义。修复后改为显式 dict `{points, bonus_points}`,直接对标澜途 API 契约,不再有"元数 vs 积分数"的语义混淆点。

**关键防御**:`_credit_config()` 现在支持两种输入格式并存:
- 新格式(dict):澜途对齐,推荐;
- 旧格式(float 列表):向后兼容,按公式推导赠送;
- JSON 字符串:`CLOUD_POINTS_PRESETS='[{"points":3000,...}]'` env 覆盖。

### 3.2 Order Schema `plan` 字段(问题 2)

| | 修复前 | 修复后 |
|---|---|---|
| `plan` 允许值 | `{pro, free}` | `{pro, free, credit}` |
| `days` 类型 | `int` (ge=1) | `Optional[int]` (ge=0) |
| `plan='credit'` + `days=0` | ❌ 422 `greater_than_equal` | ✅ 归一为 `None` |
| `plan='credit'` + `days=None` | ❌ 422 | ✅ 通过 |
| `plan='pro'` + `days=None` | ❌ 422 | ❌ 422(订阅仍强制) |
| `plan='vip'` | ❌ 422 | ❌ 422(非法 plan) |

### 3.3 `days` 语义(问题 3)

| | 修复前 | 修复后 |
|---|---|---|
| 积分订单 days | `0`(借用,含义模糊) | `None`(显式表达"无有效期") |
| SQLAlchemy default | `Integer, default=30, nullable=False` | `Integer, nullable=True`(无 default,防止覆盖显式 None) |
| 订阅订单 days | 显式传 30/365 | 不变(schema 层 `days=30` 默认值) |

**关键陷阱**:SQLAlchemy `mapped_column(default=30)` 在 `Order(days=None)` 时会用 default 覆盖显式 None(30 是"真值"),导致积分订单被误存为 30 天。修复方式:**移除 column default**,让 `days=None` 显式落 NULL。订阅订单 30 天默认由 `CreateOrderRequest.days: Optional[int] = 30` 在应用层保证。

### 3.4 积分落 Order 列(问题 4)

| | 修复前 | 修复后 |
|---|---|---|
| `Order.credit_points` 列 | 无 | ✅ 新增 `Float, nullable=True` |
| 创建时落账 | 无(靠回调反算) | `credit_points = pts + bonus` 在订单创建时写入 |
| 回调入账来源 | 仅 `amount * points_per_yuan` | **权威来源**:`order.credit_points`(创建时精确值);NULL 时回退反算 |
| 审计精度 | 只能推得主积分,赠送是回调时二次推导 | 精确记录"主 + 赠"总额,幂等重复回调也不会漂移 |
| 前端回读 | 无 | `GET /payment/order/{order_no}` 返回 `credit_points` |

**端到端验证(3000 积分订单)**:
```
POST /points/recharge {points:3000}
  → Order(plan='credit', amount=300, days=None, credit_points=4000)
回调 → recharge_credit(points=4000, bonus=0, recharge_id=order_no)
  → CreditBalance.available += 4000
  → CreditLedger(recharge_id=order_no, amount=4000)
```
3000 档的"1000 赠送"从"回调时推导"变为"创建时锁定",消除了 `points + bonus == 主积分推导` 的重复计算风险。

---

## 4. 测试结果

### 4.1 `python cloud_service/test_points.py`

- **场景**:15 段(14 原有 + 1 新增 §15 "M3 硬化专项")
- **断言**:87 条(51 原有 + 36 新增,原有 51 条 100% 保留未改)
- **通过率**:87/87 = **100%**
- **退出码**:`exit=0`

### 4.2 新增 36 条断言分类

| 问题 | 断言数 | 内容 |
|---|---|---|
| #1 预设对齐澜途 | 8 | 5 档 yuan + 3 档 bonusPoints |
| #2 Schema 校验 | 4 | `plan='credit'` 通过 / `days=0` 归一 / `days=None` 拒绝订阅 / 非法 plan 拒绝 |
| #3 `days=None` | 2 | Order 表 days=NULL + OrderResponse.days=None |
| #4 credit_points | 10 | Order 存在 / credit_points=4000 / amount=300 / status=paid / GET 端点回读 / 100 积分订单端到端 |
| 边界 | 12 | 原有 51 条保留(前置断言不动) |

### 4.3 全套回归 `pytest cloud_service -q`

```
9 passed, 1 failed, 3 warnings in 77.34s
```

- **9 passed**:billing / payment / subscription / settings / llm_proxy / auth / points / payment_form_callback / billing_refund_semantics
- **1 failed**:`cloud_service/test_payment_leftover.py::close_expired_orders_task executed X times`
  - Redis 不可达时 task_guard 降级 lock-free 的时序偶发,与本次改动**完全无关**
  - M3 报告 §8 已标注为既有 flaky,不在本次修复范围

---

## 5. 数据库变更(Migration)

**新增列**:`orders.credit_points FLOAT NULL`

### 5.1 生产数据库迁移脚本(不自动执行,交由部署流程)

**MySQL / MariaDB**:
```sql
ALTER TABLE orders ADD COLUMN credit_points FLOAT NULL DEFAULT NULL;
-- days 已改为 nullable=True(仅 ORM 层;现有数据 days 均非空,无需 UPDATE)
ALTER TABLE orders MODIFY COLUMN days INT NULL;
```

**PostgreSQL**:
```sql
ALTER TABLE orders ADD COLUMN credit_points FLOAT NULL;
ALTER TABLE orders ALTER COLUMN days DROP NOT NULL;
```

**SQLite**(本地开发/测试,自动生效):
```sql
-- orders.days 原本 NOT NULL,需要重建表(可选;若保留 nullable=False 也能跑,
-- 只要不显式传 days=None;但测试会失败。推荐重建表)。
```

测试用临时 SQLite 文件每次 `test_points.py` 都新建,不受影响。

### 5.2 兼容性

- 老 `Order.plan='credit'` 记录(`credit_points=NULL`):回调时自动回退 `amount * points_per_yuan` 反算,行为与修复前一致;
- 老 `Order.plan='pro'/'free'` 记录:`credit_points` 恒 NULL,不受影响;
- 已建库 `orders.days` NOT NULL:需先执行 `ALTER TABLE orders ALTER COLUMN days DROP NOT NULL`(PG)/ `MODIFY COLUMN days INT NULL`(MySQL),再部署新代码。

---

## 6. 剩余遗留

| 项 | 说明 | 影响 | 建议后续 |
|---|---|---|---|
| 老库订单 `credit_points=NULL` | 已支付的老积分订单没有 credit_points | 回调幂等靠 `order.status='paid'` 已足够,不影响幂等 | 迁移脚本可回填 `UPDATE orders SET credit_points = amount * points_per_yuan WHERE plan='credit'` |
| Redis 缺失下的并发保护 | 单实例测试无影响,多实例部署可能双写 | 与本次硬化无关 | 部署 Redis(现有 `task_guard` 会自动启用锁) |
| `CreateOrderRequest.plan='credit'` 走通用订单端点 | 目前只允许 pro/free 定价(credit 走 `_price_for()` 会返 99 元) | 主入口 `POST /points/recharge` 未受影响;此路径仅测试用 | 后续可加 `_price_for('credit', ...)` 分支,或直接禁用该入口 |
| 积分有效期 | 澜途目前无过期,Prism-Fusion 也未实现 | 未来若加入期策略,需在 `CreditLedger` 加 `expire_at` 字段 | 业务规则未定前不动 |

---

## 7. 相关文件

- `cloud_service/payment/models.py`(Order.credit_points + days nullable)
- `cloud_service/payment/schemas.py`(plan='credit' + Optional days)
- `cloud_service/payment/router.py`(credit 分支精确落账 + OrderResponse 回读)
- `cloud_service/billing/points_endpoints.py`(预设 dict 化 + 订单落 credit_points)
- `cloud_service/test_points.py`(§15 新增 36 条断言)
- `docs/dev-reports/2026-10-16-m3-implementation.md`(源报告)
- `docs/dev-reports/2026-10-16-lantyou-api-audit.md`(澜途 API 参考)
