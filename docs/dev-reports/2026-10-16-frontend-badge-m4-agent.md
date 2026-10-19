# 前端 Open Core Badge + M4 AgentPickerStep 补全 · 实现报告

- **报告日期**：2026-10-19
- **负责人**：Prism-Fusion 前端子代理
- **前置阅读**：
  - `docs/dev-reports/2026-10-16-open-core-implementation.md`（feature_gate 10 项 flag）
  - `docs/dev-reports/2026-10-16-m4-implementation.md`（M4 场景引导）
  - `docs/dev-reports/2026-10-16-m2-implementation.md`（M2 智能体 API）
- **验证**：
  - `npx tsc --noEmit` → **0 error**
  - `npx vitest run` → **282/282 PASS**（原 255，新增 27 用例）

---

## 1. 任务范围

| # | 任务 | 交付 |
|---|---|---|
| 1 | 前端 Open Core badge UI | `plan-badge.tsx` + `plan-flags.ts`，接入侧边栏 |
| 2 | M4 AgentPickerStep agent_id 下拉补全 | 已具备 M2 API 集成；补齐 **Community 用户 agent_quota=0 时的升级提示** |
| 3 | 测试 | `plan-flags.test.ts`（27 用例）+ `tsc --noEmit` |

## 2. 关键决策

### 2.1 云端 API 端点

Open Core 报告写的是 `/billing/flags`，但 `cloud_service/billing/router.py:519` 实际注册的端点是 **`GET /cloud/feature-flags`**（`router = APIRouter()` 无 prefix，挂载前缀由 `cloud_service/app.py` 加）。前端统一走：

```ts
gatewayRequest({
  feature: "billing",   // CLOUD_FEATURES 白名单，自动路由到云端
  path: "billing/feature-flags",
  method: "GET",
  needToken: true,
})
```

由 `client-gateway.ts:resolveUrl` 拼出 `https://api.prism.local/cloud/billing/feature-flags`，与后端 `FeatureFlagsResponse`（`schemas.py:85`）结构一致：`{plan, flags, upgrade_url}`。

### 2.2 云端不可达 → 默认 Community

- 未登录 / 401 / 5xx / 网络错误 / 超时 → 全部走 `normalizeFlags({plan:"community", flags:{}})` 兜底
- 用 `DEFAULT_COMMUNITY_FLAGS` 补齐 10 项 flag（3 账号 / 3 平台 / 0 智能体 / 全关布尔型）
- UI 层**从不**因云端故障阻断功能，只是显示"Community 免费版"徽标

### 2.3 升级按钮 URL

- 云端 `upgrade_url` 字段当前 `router.py:539` 恒为 `None`
- 前端 `buildPlanBadgeView` 优先级：`opts.upgradeUrl` > `flags.upgrade_url` > `DEFAULT_UPGRADE_URL`（`/settings`，因该页已有 `<CloudSubscriptionCard />`）
- 未来计费侧填充 `upgrade_url` 后无需改前端代码

### 2.4 为什么选 sidebar 而不是 header

- 侧边栏在**所有页面**都渲染（`AppShell` 常驻），比 header 覆盖更广
- 与"System / Online" 底部区相邻，视觉上属于"账号 / 系统状态"栏，符合语义
- 折叠模式（`collapsed`）下退化为一个 40×40 图标按钮，不挤压侧栏空间

---

## 3. 新增 / 修改文件

### 3.1 新增

| 文件 | 行数 | 职责 |
|---|---:|---|
| `prism_frontend/src/lib/plan-flags.ts` | 192 | 纯逻辑：`FEATURE_NAMES` / `DEFAULT_COMMUNITY_FLAGS` / `normalizeFlags` / `buildPlanBadgeView` / `isFeatureAllowed` / `formatLimit` |
| `prism_frontend/src/lib/__tests__/plan-flags.test.ts` | 190 | 27 用例覆盖 FEATURE_NAMES / 默认 flags / normalizeFlags 边界 / buildPlanBadgeView Community 与 Pro / isFeatureAllowed |
| `prism_frontend/src/components/layout/plan-badge.tsx` | 250 | UI：Community/Pro badge + 三格配额 + 升级按钮 + 折叠模式 |

### 3.2 修改

| 文件 | 变更 |
|---|---|
| `prism_frontend/src/components/layout/sidebar-new.tsx` | +6 行：import `PlanBadge`；在底部 System 区上方插入 `<PlanBadge collapsed={collapsed} />` |
| `prism_frontend/src/components/wizard/agent-picker-step.tsx` | +55 行：并行拉取 feature flags；Community + `agent_quota=0` 时禁用下拉、显示 "升级 Pro 解锁智能体" 卡片 |

**未改动**：`cloud_service/**`、`prism_backend/**`、shadcn UI 组件、M1/M3 相关任何文件。

---

## 4. Badge UI 设计

### 4.1 Community（默认视图）

```
┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐
│ ✦ Community                 [⟳]           │   ← Badge(outline) + 刷新按钮
│ ┌────────┬────────┬────────┐              │
│ │   3    │   3    │   0    │              │   ← 3 格配额 grid
│ │ 账号   │ 平台   │ 智能体 │              │
│ └────────┴────────┴────────┘              │
│ [升级 Pro                    →]           │   ← Link /billing/upgrade
└─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘
```

- `border-border/60 bg-background/40`（低调灰色）
- `Sparkles` 图标 + `Badge variant="outline"`
- "3 账号 / 3 平台 / 0 智能体" 三格 grid（0 智能体标锁，title 提示"升级解锁"）
- "升级 Pro" 按钮（`border-primary/40 bg-primary/10 text-primary hover:bg-primary`）

### 4.2 Pro

```
┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐
│ 👑 Pro                      [⟳]           │   ← Crown 图标 + primary 高亮
│ ┌────────┬────────┬────────┐              │
│ │ ∞      │   8    │   2    │              │   ← 无限 → Infinity 图标
│ │ 账号   │ 平台   │ 智能体 │              │
│ └────────┴────────┴────────┘              │
│ [续费                       →]           │
└─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘
```

- `border-primary/40 bg-gradient-to-br from-primary/10`（金色渐变）
- `Crown` 图标 + `Badge` primary 变体
- `max_accounts=-1` → `InfinityIcon`（比"无限"文字更紧凑）
- "续费" 按钮

### 4.3 折叠模式

`collapsed=true` 时退化为 40×40 图标按钮：Community 显示 `Sparkles`（灰），Pro 显示 `Crown`（金色）。链接同样指向升级 URL。

---

## 5. AgentPickerStep 补全

### 5.1 前置现状（M2/M4 小修复子代理已交付）

- `agent-picker-step.tsx` 已挂上 M2 API（`authFetch + Bearer token`）
- 已处理 401 → 未登录提示
- 已通过 `CustomEvent("prism-wizard:agent-selected")` 通知 Wizard
- 有 module-scope `_agentIdCache` 保持跨步骤选择

### 5.2 本次补全

**新增**：并行拉取 Open Core feature flags，判断 `agent_quota=0` → 显示"升级 Pro 解锁智能体"卡片。

```
[未登录]       → 黄色卡片 "请先登录..."
[Community 0]  → 紫色卡片 "当前为 Community 免费版..." + 升级 Pro 按钮  ← 新增
[Community 有] → 与 Pro 相同（用户已开通智能体额度）
[Pro]          → Select 下拉正常显示
```

**关键实现**：

```ts
useEffect(() => {
  let cancelled = false
  async function loadFlags() {
    try {
      const token = await cloudAuth.getAccessToken()
      const r = await gatewayRequest<FeatureFlagsResponse>({
        feature: "billing",
        path: "billing/feature-flags",
        method: "GET",
        needToken: Boolean(token),
        token: token || "",
        timeoutMs: 5000,
      })
      if (cancelled) return
      if (r.ok && r.data) {
        setFlags(normalizeFlags(r.data))
      } else {
        // 云端不可达/未登录：回落 Community + agent_quota=0
        setFlags(normalizeFlags({ plan: "community", flags: {} }))
      }
    } catch (e) {
      if (!cancelled) setFlags(normalizeFlags({ plan: "community", flags: {} }))
    }
  }
  void loadFlags()
  return () => { cancelled = true }
}, [])
```

判定：

```ts
const agentLocked =
  !unauthed &&
  flags !== null &&
  flags.plan !== "pro" &&
  Number(flags.flags.agent_quota ?? 0) === 0
```

**关键设计**：
- **不阻断 M1 生图流程**：即使 agentLocked，用户仍可跳过该步骤（"不使用智能体（默认）"）
- 使用与 PlanBadge 相同的 `DEFAULT_UPGRADE_URL` 保持视觉一致
- 云端不可达时默认 agentLocked=true，与 Cloud 徽章显示一致（"Community 免费版"），无视觉冲突

---

## 6. 测试结果

### 6.1 静态检查

```
$ cd prism_frontend && npx tsc --noEmit
# 0 errors
```

### 6.2 单元/组件测试

```
$ cd prism_frontend && npx vitest run
 Test Files  12 passed (12)
      Tests  282 passed (282)
```

**新增 27 个测试用例**（原 255 全部保持通过）：

| 测试文件 | 用例数 | 覆盖点 |
|---|---:|---|
| `src/lib/__tests__/plan-flags.test.ts` | 27 | 见下 |

**覆盖点细目**：
- `FEATURE_NAMES`：10 项完备、含 4 个数值型、无重复（3 用例）
- `DEFAULT_COMMUNITY_FLAGS`：所有 FEATURE_NAMES 都有默认值、Community 默认 3/3/0（2 用例）
- `formatLimit`：-1 → 无限、普通数字、字符串、空值 → 占位符（4 用例）
- `normalizeFlags`：pro 保留、未知 plan 回落 community、空响应 → 默认、缺失 flag 补齐、忽略未知 key、忽略非标准类型（6 用例）
- `buildPlanBadgeView`：Community 3/3/0 + "升级 Pro"、Pro -1/8/2 + "续费"、upgrade_url 三种优先级、缺失 flag 回落默认（6 用例）
- `isFeatureAllowed`：数值型 0/-1/正数、布尔型、字符串型、缺失（7 用例）

### 6.3 回归

原 255 测试全部通过：
- `wizard-core` (19) + `url-sync` (13) + `scenarios` (15) 无改动
- `agent-studio` (25) + `client-gateway` (33) + `cloud-auth` (13) + `cloud-chat` (22) + `cloud-gateway-client` (26) 无改动
- `image-editor-logic` (13) + `image-studio` (61) + `useLicenseHeartbeat` (15) 无改动

---

## 7. 遗留问题 / 后续接入点

### 7.1 计费侧

1. **`upgrade_url` 当前恒为 `None`**：`cloud_service/billing/router.py:539` 需返回真实 URL（如 `/billing/upgrade` 或支付平台跳转）；前端 `DEFAULT_UPGRADE_URL = "/settings"` 是占位。
2. **`/billing/flags` vs `/billing/feature-flags` 命名不一致**：Open Core 报告 §2.6 写的是 `/billing/flags`，实际实现是 `/billing/feature-flags`。建议后续统一（更新报告 or 后端加 alias）。
3. **`Subscription.plan` 只有 `free`/`pro`**：Open Core 报告预留 `team_members` flag，未来 Team 档位需扩展 plan 枚举；前端 `normalizeFlags` 已保守处理（非 pro 一律视为 community）。

### 7.2 客户端

4. **`agent_quota` 是全局 env**：M2 报告已声明未来接 M3 后按 plan 分档；当前 flag 值来自后端 `CLOUD_AGENT_QUOTA` 环境变量（默认 Community=0 / Pro=2），与 `/ai-design/agents/quota` 端点的配额**可能不一致**（前者 0/2，后者 2/2）。前端 AgentPickerStep 用 flags 判断锁定，M2 API 端点用自身 limit；后续应统一到 feature_gate 单一权威源。
5. **`PlanBadge` 轮询 4 分钟**：低频、不干扰用户；如需更实时可在"升级完成"后主动 `load()`。
6. **无 SSR**：`plan-badge.tsx` 是 `"use client"`，首屏会闪一下骨架屏。当前 AppShell 是纯 CSR（`next dev` 客户端渲染），无 SSR 首屏问题。
7. **`agentLocked` 判定与 M2 `/quota` 端点脱耦**：M2 端点返回 `{limit, used}`，`limit` 也可能为 0（若接了同一套 feature_gate）；前端 AgentPickerStep 只用 flags 判断锁定，未读取 M2 quota.limit，未来两者一致后可二选一。

### 7.3 视觉验证

8. **未做实际浏览器视觉验证**：本次只跑了 tsc + vitest 单测；建议后续在 `next dev` 起服务后人工确认：
   - 侧边栏展开/折叠两种模式下 Badge 布局
   - Community 未登录 / Pro 已订阅两种状态
   - AgentPickerStep 三种分支（未登录 / agentLocked / 正常）

---

## 8. 关键实现取舍

1. **拆纯逻辑到 `plan-flags.ts`**：与 M2 的 `agent-studio.ts` / M4 的 `wizard-core.ts` 保持同一模式；27 用例脱离 DOM 直接跑，快且稳。
2. **复用 `gatewayRequest` 而非裸 `fetch`**：自动路由云端 + 自动 token 注入 + 错误归一化，不新增鉴权路径。
3. **Cloud 不可达不阻断 UI**：默认 Community + 兜底 flags，符合 Open Core "先能跑，再付费"的产品语义。
4. **`agentLocked` 与 PlanBadge 复用 `buildPlanBadgeView`**：两个组件对"升级入口 URL"、"agent 上限文案"的解读保持一致，避免 UI 分歧。
5. **未接入 Pro 支付流程**：`/billing/upgrade` 路径占位为 `/settings`，实际支付页面（CloudSubscriptionCard）已存在，只是尚未做真实跳转。后续接 C19 支付时只需改 `DEFAULT_UPGRADE_URL` 常量。
