# L3-2 报告：ideas 前端区块 + 侧边栏折叠

## 任务背景

L3-1（commit `6135391`）已交付后端 `GET /api/v1/content-library/ideas/from-performance`，
但前端 ideas 页没有接线（L3-1 报告明确留到 L3-2）。同时用户已拍板：
`dashboard-demo` 与 `guide` 从侧边栏折叠入口（代码与路由保留）。

## 两件交付

### ① ideas 页「从我的表现生成」区块

`src/app/ideas/page.tsx`

在 `PageHeader` 后、选题列表前插入一个新 `Card` 区块：

- 头部：`Flame` 图标 + 标题「从我的表现生成选题」+ 说明文案 + 右侧按钮「从我的表现生成」
- 按钮点击调 `GET /api/v1/content-library/ideas/from-performance`（`cache: "no-store"`）
- **响应字段按后端实际**（`router.py` 行 193-205）：
  `result.suggestions[] = {id, title, note, heat, platform, video_id, source}`、
  `result.data_ready: boolean`、`result.hint: string | null`
- 三种展示状态：
  - `data_ready=false` 或空数组 → 展示 `result.hint` 原文
    （fallback 到「暂无视频回收数据。请先在发布中心完成一次发布并触发数据回收，再回来生成选题建议。」）
  - 有建议 → 逐条渲染 `title` + `note` + `heat` 进度条（`aria-valuenow` + `aria-label="热度 X%"`）
  - 加载态 → `Loader2` + 「正在读取你的视频表现…」，按钮 disable 防重复点击
- 请求失败：`toast` 带 `dedupeKey: "ideas-performance-failed"`
  （`variant: "destructive"`），走 use-toast 的 DEDUPE_MAX_COUNT=3 限流

### ② 侧边栏折叠 demo / guide

`src/components/layout/sidebar-new.tsx`

- `NavItem` interface 加 `visible?: boolean` 字段（附注释说明「仅折叠入口不删路由」）
- 「快速开始」`/guide`、「演示控制台」`/dashboard-demo` 两项加 `visible: false`
- 渲染层 `section.items.filter((item) => item.visible !== false)`
- **dedupe 计算同步排除**：`nativeHrefs` 收集时也 `continue` 掉 `visible === false` 的项
  —— 否则外部模块的 `/dashboard-demo` / `/guide` 会被错误地当作「已覆盖」压掉
- 路由文件（`src/app/dashboard-demo/`、`src/app/guide/`）**不删**，直达 URL 可用

## 测试

### 新增 DOM 测试

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `src/app/ideas/__tests__/page.dom.test.tsx` | 5 | 按钮触发 URL / data_ready=false 渲染 hint / 有建议条目+进度条 / 失败 dedupeKey toast / 加载态 |
| `src/components/layout/__tests__/sidebar-new.dom.test.tsx` | 3 | 展开态不含两项 / 折叠态也不含 / 其它原生入口保留（回归保护） |

ideas 页测试 mock 模式：
- `vi.mock("@/components/ui/use-toast")` 拦 `toast` 调用，用于断言 `dedupeKey`
- `vi.stubGlobal("fetch", mockedFetch)` 按 URL 分派响应
- ideas 列表端点返回空数组，避免干扰断言

sidebar 测试 mock 模式：
- `vi.mock("next/navigation")` stub `usePathname`
- `vi.mock("framer-motion")` 把 `motion.*` 用 `React.createElement` 透传成原生元素，
  只保留 `children / className / style / role / aria-label`（剥掉 `initial / animate / transition`
  等 framer props，否则 jsdom 会报「Received `false` for a non-boolean attribute」）

### 全量验证

| 命令 | 结果 |
|---|---|
| `vitest run` | 27 files / **458 tests passed**（含新增 8 用例） |
| `tsc --noEmit` | 0 error |
| `eslint` （4 个改动文件） | 0 error，3 warnings 全是预存（`CardContent` 未使用 + 两处 `<img>` logo） |
| U+FFFD（4 个改动文件） | 0 |

## 文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `prism_frontend/src/app/ideas/page.tsx` | 修改 | 加 icons、types、state、loadPerformance、区块 JSX |
| `prism_frontend/src/app/ideas/__tests__/page.dom.test.tsx` | 新增 | 5 用例 |
| `prism_frontend/src/components/layout/sidebar-new.tsx` | 修改 | `visible?:` 字段 + 两项 false + 渲染 filter + dedupe 排除 |
| `prism_frontend/src/components/layout/__tests__/sidebar-new.dom.test.tsx` | 新增 | 3 用例 |

## 边界说明

- 区块只覆盖「生成建议」交互，不含「一键加入选题库」——如需把建议落库，
  后续可在每条建议下加「加入选题」按钮调 `POST /api/v1/content-library/ideas`（L3-1 已具备）
- 后端 hint 文案在 `router.py` 行 121 / 156 / 168 三处；前端仅在 hint 为空字符串时兜底，
  非空一律展示接口原文，保持后端文案单点权威
- 折叠只影响侧边栏入口，`/dashboard-demo` 与 `/guide` 路由文件保留
  （分别 41KB / 20KB 页面代码 + 相关 API 依赖），不删不迁移
