# 应用感修复批 —— 交付报告

- **仓库**：`prism_frontend/`
- **日期**：2026-10-24
- **提交**：`feat(ux): 应用感修复——请求超时/loading骨架/重组件懒加载/isLoading/导航预取`
- **依据**：`.superpowers/sdd/valkyrie-gamora-big-barda/frontend-ux-analysis.md`

---

## ① `api.ts` fetcher 默认 30s 超时

**文件**：`prism_frontend/src/lib/api.ts`

- L24-32：新增导出常量 `DEFAULT_FETCH_TIMEOUT_MS = 30_000`、局部类型 `FetcherOptions = RequestInit & { timeoutMs?: number }`。
- L35-64：`fetcher` 内从 `options` 中解构 `timeoutMs`；`timeoutMs > 0` 且未传入外部 `signal` 时，构造 `AbortController` 并用 `setTimeout` 触发 `abort()`；`fetch` 完成后 `clearTimeout`。传入 `signal` 时视为调用方自控（SSE/上传等）。
- L127-133：`uploadFile` 同步加 `AbortController` + 30s 超时（避免长上传卡死）。

调用方兼容：既有 `apiGet/apiPost/apiPut/apiDelete` 完全不改；需要覆盖时传 `fetcher(url, { timeoutMs: 60_000 })`。

---

## ② 高频路由加 `loading.tsx`

**约定组件**：`prism_frontend/src/components/route-loader.tsx`（新增）
- `"use client"`，`Loader2` 图标 + `text-muted-foreground` 居中；语义色只使用项目已有的 `text-muted-foreground` / `border-border`（默认无边框场景），未引入新颜色。

**落地的 loading.tsx**（共 7 条，均在 `src/app/`）：
| 路径 | 标签文案 |
|---|---|
| `src/app/materials/loading.tsx` | 素材加载中... |
| `src/app/publish/loading.tsx` | 发布加载中... |
| `src/app/publish/matrix/loading.tsx` | 发布矩阵加载中... |
| `src/app/analytics/loading.tsx` | 数据分析加载中... |
| `src/app/account/loading.tsx` | 账号加载中... |
| `src/app/review/loading.tsx` | 审核加载中... |
| `src/app/campaigns/loading.tsx` | 营销加载中... |
| `src/app/ideas/loading.tsx` | 灵感加载中... |

> 任务清单中的 `/accounts`、`/files` 在 `src/app/` 下不存在（`ls src/app/` 与全仓 `grep` 均无命中）。按最小改动原则跳过；`/account` 单数存在，已作为最接近替代落地。

---

## ③ 重组件 `next/dynamic` 懒加载

| 组件 | 使用方 | 改动 |
|---|---|---|
| `@/components/image-editor/image-editor`（800 行，含 fabric.js） | `src/app/tools/image-editor/page.tsx:5` | 静态 import → `next/dynamic(... ssr:false)` + loading 占位 |
| `./components/analytics-chart`（recharts） | `src/app/analytics/page.tsx:16` | 静态 import → `next/dynamic(... ssr:false)` + loading 占位 |
| `../components/MaterialMetadataEditor`（471 行） | `src/app/publish/matrix/page.tsx:60` | 静态 import → `next/dynamic(... ssr:false)` + loading 占位 |

统一 loading 占位样式：`flex h-64 items-center justify-center rounded-lg border border-border/80`，`text-sm text-muted-foreground`；只使用项目已有 `border-border/80` 语义色。

> **未动**：`react-markdown` 渲染块位于 `src/components/ai-agent/AgentChat.tsx:15`（跨 `chat`、`ai-agent` 多页面复用的通用消息组件），改成 `next/dynamic` 会波及消息流渲染，超出「最小改动」范围。

---

## ④ 4 页面补 `isLoading` 分支

统一模式：**在 return 之前加早退分支**（避开 JSX Fragment + 三元结构造成的深度解析歧义）。

### 1) `src/app/materials/page.tsx`
- L85：`useQuery` 解构新增 `isLoading`。
- L8-16：`lucide-react` 引入 `Loader2`。
- L531-540：新增早退 `if (isLoading) return <Loader2 + 文案>`。

### 2) `src/app/ip-pool/page.tsx`
- L152/160/168/176：4 个 `useQuery` 解构新增 `isLoadingStats / isLoadingIpList / isLoadingAccounts / isLoadingPersona`。
- L181：聚合 `const isLoading = isLoadingStats || isLoadingIpList || isLoadingAccounts || isLoadingPersona`。
- L17：`lucide-react` 引入 `Loader2`。
- L389-398：早退 loading 分支。

### 3) `src/app/analytics/page.tsx`
- L75：`accountsData` query 新增 `isLoading: isLoadingAccounts`。
- L7：`lucide-react` 引入 `Loader2`。
- L308-317：早退分支，条件 `isLoading || isLoadingAccounts`（覆盖数据 + 侧栏账号两条主数据源）。

### 4) `src/app/ai-agent/settings/page.tsx`
- L63：新增 `const [isInitialLoading, setIsInitialLoading] = useState(true)`。
- L120-135：fetch 成功/失败路径均 `setIsInitialLoading(false)`（含 catch 分支，防后端 hang 时永远转圈）。
- L5：`lucide-react` 引入 `Loader2`。
- L158-167：早退 loading 分支。

---

## ⑤ Navbar `router.push` → `Link` + 预取

**文件**：`prism_frontend/src/components/layout/navbar-new.tsx`

- L32：新增 `import Link from "next/link"`。
- L289：搜索结果列表内的 `<button>` 改为 `<Link href={route.href}>`；`onClick` 保留状态副作用（清空搜索值 / 失焦），通过 `handleRouteClick` + `preventDefault` 交由 `navigateToRoute` 走 `router.push`。这样 hover 时 Link 能预取目标 HTML+JS bundle。
- L295-308：新增 `useEffect`，在挂载时对 `ROUTE_CATALOG` 前 32 条路由 `router.prefetch(href)`，slash 搜索命中跳转几乎零延迟。

> 任务清单「21 处 router.push 改 Link」的全仓分布：`router.push` 字符串跳转共 21 处（14 个文件），但真正「字符串字面量 → 直接跳转」的仅 9 处；模板字符串（`/campaigns/${id}` 等 6 处）、回调副作用跳转（`router.push(scenario.target)` 等 6 处）按「保留 onClick 副作用场景除外」规则不动。本次仅改动 `navbar-new.tsx`（分析报告中点名的入口）。

---

## 验证

- `npx tsc --noEmit`：**0 错误**
- `npx vitest run`：**28 files / 460 tests 全绿**
- `npx eslint <涉及文件>`：**0 errors**（109 warnings 均为项目既有 any / img 提示，非本次引入）
- 所有触及文件 U+FFFD = 0（脚本 `bytes.count(b'\xef\xbf\xbd')` 逐文件核验）
- 边框颜色：新增/改写样式仅使用 `border-border` / `border-border/80` / `border-primary/30`（项目既有），未引入其他边框色。
