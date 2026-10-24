# Prism-Fusion 前端「应用感」缺口盘点

- **仓库**：`prism_frontend/`（Next.js 16 App Router + React 19）
- **范围**：`src/app/**/page.tsx` 全部路由 + `src/lib/` 请求层 + `src/components/layout/` 导航
- **日期**：2026-10-24
- **结论**：dev 卡死的主因是按需编译（打包后消失），但当前代码**即使打包也白屏**——所有 53 个页面均无路由级 `loading.tsx`、`api.ts` 无超时、零代码分割、导航存在绕过 prefetch 的路径。

---

## 关键数字

| 指标 | 值 |
|---|---|
| 路由总数（`page.tsx`） | **53** |
| 有 `loading.tsx`（App Router 路由级 Suspense） | **0** |
| 无 `loading.tsx` 的路由 | **53 / 53（100%）** |
| 请求层封装有超时的 | **1**（`client-gateway.ts` 支持可选 `timeoutMs`）|
| 请求层封装**无**超时的 | **1**（`api.ts` 的 `fetcher` / `apiGet/Post/Put/Delete`、`uploadFile` — 全部）|
| 使用 `next/dynamic` 的组件 | **0** |
| `router.push` 字符串跳转（绕过 Link prefetch）| **21** 处 |
| Sidebar 是否用 `next/link`（默认 prefetch） | 是（`sidebar-new.tsx:5,407,435`）|
| Navbar 是否用 `next/link` | **否**（`navbar-new.tsx:275` `router.push`）|

---

## ① 无 `loading.tsx` 路由全清单

**全部 53 条路由均无 `loading.tsx`**（App Router 约定俗成的路由级 Suspense fallback 完全空缺）。任何导航都会阻塞到目标页组件首次渲染才出内容；慢后端 = 全屏白屏。

- `app/page.tsx`（首页仪表盘）
- `app/account`、`app/ai-agent`、`app/ai-agent/prompts`、`app/ai-agent/settings`
- `app/analytics`、`app/analytics/trends`、`app/analytics/videos`、`app/analytics/videos/[platform]`
- `app/artifacts`、`app/breakdown`、`app/calendar`
- `app/campaigns`、`app/campaigns/[id]`、`app/campaigns/[id]/new`
- `app/chat`、`app/cms`、`app/dashboard-demo`
- `app/easel-content`、`app/easel-inbox`、`app/easel-workbench`
- `app/fusion`、`app/fusion/analytics`、`app/fusion/config`、`app/fusion/image-studio`、`app/fusion/model-market`、`app/fusion/moderation`、`app/fusion/providers`、`app/fusion/styles`
- `app/guide`、`app/hermes-chat`、`app/ideas`、`app/ip-pool`、`app/login`
- `app/materials`、`app/persona`、`app/persona-proxy`、`app/profile`
- `app/publish`、`app/publish/distribution`、`app/publish/matrix`
- `app/review`、`app/settings`、`app/settings/model-providers`
- `app/skills`、`app/tasks`、`app/tasks/distribution`、`app/tasks/publish`
- `app/tools`、`app/tools/image-editor`
- `app/trends`、`app/video-pipeline`、`app/workshop`

---

## ② 无 loading 分支的代表页面（file:line）

按 `isLoading|Skeleton|Loader2|isFetching|pending` grep 命中数从低到高，抽读确认无 UI 分支：

| 命中 | 页面 | 问题 |
|---|---|---|
| 0 | `src/app/materials/page.tsx:85` | `useQuery({ queryKey: ['materials', keyword] })` 只解构了 `{data, refetch}`，**没有 isLoading**；`return (` 在 L530 直接渲染空态（materials=[]），后端 300ms 慢就是空 UI |
| 0 | `src/app/ip-pool/page.tsx:152,160,168,176` | 4 个 `useQuery`（stats / ipList / accounts / personaStatus）**全部**只取 `{data}`，无 loading 态；表格 mount 即渲染空 `<tbody>` |
| 0 | `src/app/ai-agent/settings/page.tsx:116,122` | 直接 `fetch('/api/v1/agent/config/hermes/runtime')` + `useState<HermesRuntime|null>(null)`，无 loading flag，`return (` 前不做任何守卫；后端 hang 就永远渲染 null 骨架 |
| 2 | `src/app/analytics/page.tsx:171` | `useQuery({data:analyticsData, isLoading, refetch})` **仅**在 L499 传给 `<VideoDataTable isLoading={isLoading}>`；顶部账号侧栏（`accounts` 也是独立 query）与统计卡片区**没有** loading 分支 |
| 2 | `src/app/campaigns/page.tsx:34` | `isLoading` 仅用于 L137 的一个分支；页面首屏骨架（列表、分页、筛选器）没有独立 loading 态 |
| 2 | `src/app/fusion/analytics`、`app/fusion/model-market`、`app/fusion/providers` | 同 analytics 模式：Loader2 只在极小范围内出现，主列表 / 卡片网格直接渲染空态 |
| 3 | `src/app/chat/page.tsx`、`app/breakdown`、`app/easel-content`、`app/fusion/config`、`app/fusion/moderation`、`app/fusion/styles`、`app/skills`、`app/trends`、`app/video-pipeline`、`app/workshop` | 有 `Loader2` 但命中次数低（3），多为「刷新按钮转圈」或「提交中」状态，**页面首屏数据加载**没有独立 loading 分支 |
| — | `src/app/publish/page.tsx:1` | 只是 `router.replace('/publish/matrix')`，白屏 1 帧（可接受但应做 loading 提示）|
| — | `src/app/hermes-chat/page.tsx:1` | 一行 re-export，本身无 loading，取决于 HermesChatPage 内部 |
| — | `src/app/dashboard-demo/page.tsx:1` | 硬编码假数据，无网络请求（不算问题，但也说明它不需要 loading）|

> **规律**：`useQuery` 有返回 `isLoading`，但**大部分页面没有把它接入 UI 首屏骨架**——只在下拉框 / 提交按钮这类局部位置使用。

---

## ③ 请求超时现状

### `src/lib/api.ts` — **零超时**
- `fetcher`（L24-77）、`apiGet/apiPost/apiDelete/apiPut`（L79-105）、`uploadFile`（L108-131）
- 所有调用 `fetch(url, {...})` 都**不传 signal**、无 `AbortController`、无 `setTimeout` 看门狗
- 后端慢/hang = UI 永久转圈
- `zod` 校验异常路径会把网络错误转成 `ApiError(500, ...)`，但**根本走不到**——fetch 永远 pending

### `src/lib/client-gateway.ts` — 支持但不强制
- L81 定义 `timeoutMs?: number`；L198-208 有 `AbortController` + `setTimeout(() => ctrl.abort(), timeoutMs)` 实现
- **但**：`timeoutMs` 是**可选**，调用方不传就没有超时。抽查 `page.tsx` 里调用 `client-gateway` 的路径，未见统一注入默认 timeout
- L321-322 对 SSE 流明确「通常不主动超时」——合理，但要防止误用

### `src/lib/cloud-gateway-client.ts`、`cloud-chat.ts`、`tikhub-availability.ts`、`cloud-llm-availability.ts`
- 各自有 `AbortController` 使用（grep 命中），但没有形成「默认超时 + 可覆盖」的统一封装
- `api.ts` 的 fetcher 是唯一**通用**封装，却**没有超时**，这是最大隐患

---

## ④ 导航预载现状

### Sidebar — 好
- `src/components/layout/sidebar-new.tsx:5` `import Link from "next/link"`
- L407（子菜单）、L435（主菜单）都用 `<Link href={item.href || "#"}>`
- Next.js 16 Link 默认 `prefetch=true`（除非显式关）；hover 时预取 HTML+JS bundle
- **但**：由于 `src/` **零** `next/dynamic`，Link prefetch 拉取的 JS bundle 就是全量页面代码，收益只是 HTML+初始数据

### Navbar — 有 bypass
- `src/components/layout/navbar-new.tsx:21` `import { usePathname, useRouter, useSearchParams } from "next/navigation"`
- L213 `const router = useRouter()`；L275 `router.push(route.href)`
- `router.push` **不做** prefetch，点击瞬间才开始拉 HTML+JS
- **命中范围**：21 处 `router.push` 分散在 14 个文件（`grep -c "router.push"` 统计）
- 典型：全局搜索、快捷跳转、菜单点击 —— 这些是「用户点几个就卡」的主要嫌疑路径

### 其他
- `src/app/publish/page.tsx:11` `router.replace("/publish/matrix")` — 跳转中转页，可接受

---

## ⑤ 重组件懒加载现状

**`grep -rE "next/dynamic" src --include="*.tsx" --include="*.ts" -l` → 0 匹配。** 全仓**零**代码分割。

### 主要重组件（无 dynamic）
- `@/components/image-editor/image-editor`（`src/app/tools/image-editor/page.tsx:5`）— 图像编辑器，通常含 fabric.js / konva / canvas 相关
- `@/components/image-editor/*` 系列被 `src/app/fusion/image-studio/page.tsx`（854 行）与 `src/app/tools/image-editor/page.tsx` 同时 import
- `recharts` / `echarts` / `d3`：`src/app/analytics/components/analytics-chart.tsx`、`src/app/analytics/components/video-data-table.tsx`、`src/app/analytics/page.tsx`（732 行）、`src/app/dashboard-demo/page.tsx`、`src/app/publish/matrix/components/IntervalTimelinePreview.tsx`、`src/app/campaigns/[id]/new/page.tsx`
- `react-markdown`：`src/app/chat/page.tsx`、`src/app/ai-agent/prompts/page.tsx`、`src/app/ai-agent/components/HermesWebuiPanel.tsx`
- `framer-motion`：`src/app/settings/components/*`、`src/app/publish/components/*`、`src/app/tasks/distribution/components/task-drawer.tsx`
- `monaco-editor` / `@codemirror/*`：`src/app/publish/components/MaterialMetadataEditor.tsx`（未直接命中但按经验应在此类文件，需二次确认）
- `@radix-ui/*`：多处（相对轻，但聚合后仍是入口 bundle 大头）

### 唯一已用 `Suspense` 的例子
- `src/app/tools/image-editor/page.tsx:3` `import { Suspense, useMemo } from "react"` — 用来包 `useSearchParams()`（是 Next 15+ 的 SSR bailout 模式，**不是**动态懒加载组件）

### 结论
- 首屏 bundle = 所有页面代码 + recharts + image-editor + react-markdown 等大件的**并集**
- 首屏下载大、解析大、执行大 —— 打包版也会「卡一下」

---

## ⑥ 按「工作量 × 收益」排序的修复清单

> 工作量：S（<0.5d）/ M（0.5-1d）/ L（1-2d）；收益：高/中/低，按影响面 & 用户可见度

| # | 修复 | 工作量 | 收益 | 说明 |
|---|---|---|---|---|
| 1 | **给 `api.ts` 的 fetcher 加默认超时**（`AbortController` + 30s 默认，可覆盖） | S | **高** | 一处改动惠及全仓所有 `apiGet/Post/Put/Delete`；后端 hang 不再白屏 |
| 2 | **为高频路由加 `loading.tsx`**（`app/page.tsx`、`analytics`、`tasks`、`materials`、`campaigns`、`chat`、`fusion/image-studio` 各 1 个 loading.tsx，用 shadcn `Skeleton` 搭骨架） | M | **高** | App Router 自动接管，导航瞬间出骨架；用户可见感秒开 |
| 3 | **`materials/page.tsx` 补 `isLoading`**（L85 `useQuery` 加解构，L530 `return` 前做 `{isLoading ? <Skeleton/> : ...}`） | S | **高** | 该页数据量最大（987 行），首屏空态最刺眼 |
| 4 | **`ip-pool/page.tsx` 补 4 处 `isLoading`**（L152/160/168/176 各 useQuery 解构 isLoading，主表格前加 `<TableSkeleton>`） | S | **高** | 4 个 query 并行，最容易长时间空表 |
| 5 | **`analytics/page.tsx` 拆 isLoading 覆盖首屏**（L171 已有 isLoading，但账号侧栏 L~60 的 accounts query 无 loading；把 accounts query 也接入 loading 分支） | S-M | 中 | 分析页首屏有 3 个数据源，仅覆盖 1 个不够 |
| 6 | **`ai-agent/settings/page.tsx` 加 loading state**（L116-122 fetch 期间 `useState(true)`，return 前 `if (!runtime) return <Skeleton/>`） | S | 中 | 该页是 hermes runtime 探测，接口慢很常见 |
| 7 | **`next/dynamic` 化重组件**（`ImageEditor`、`AnalyticsChart`、`MaterialMetadataEditor`、`react-markdown` 渲染块、`framer-motion` 装饰卡片） | M | **高** | 首屏 bundle 从「全量并集」降到「当前页所需」；打包后 1-2s → 300-500ms |
| 8 | **`navbar-new.tsx:275` `router.push` 改为 `<Link>`**（把搜索命中项从 onClick → href） | S | 中 | 一次改动，去掉主要 bypass-prefetch 路径 |
| 9 | **清理其余 20 处 `router.push` 字符串跳转**（14 个文件，多数是「按钮内 navigate」，改用 `<Link>` 包按钮或传 `href`） | M | 中 | 逐个评估；能不用 useRouter 就不用 |
| 10 | **`client-gateway.ts` 设默认 `timeoutMs`**（比如默认 30s，SSE 明确 `timeoutMs: 0` 关闭） | S | 中 | 与 #1 呼应，覆盖 cloud-gateway 路径 |
| 11 | **`materials`/`analytics`/`campaigns` 等 useQuery 加 `staleTime` + `placeholderData`** | S | 低-中 | 减少重复请求、避免每次切换 tab 都闪 loading |
| 12 | **给 `tasks/page.tsx`（915 行）、`materials/page.tsx`（987 行）、`analytics/page.tsx`（732 行）、`fusion/image-studio/page.tsx`（854 行）拆组件** | L | 中 | 4 个大文件既是懒加载障碍也是维护负担；拆分后才能有效 dynamic |

### Top 5（推荐先做）
1. **#1** api.ts 默认超时 — S，一劳永逸
2. **#2** 高频路由 loading.tsx — M，秒开体感最直接
3. **#7** 重组件 next/dynamic — M，打包后提速核心
4. **#3+#4+#5+#6** 补 isLoading（4 个 S 工作量，一次改完）
5. **#8** navbar router.push → Link — S
