# 2026-10-21 端到端链路审计与修复报告

- **审计范围**：Prism-Fusion 全仓（后端 `prism_backend/` 475 个 OpenAPI 端点组 × 前端 `prism_frontend/src/` 51 个路由 + 37 个 Next API 代理）
- **审计目标**：用户诉求原文 —— 「后台的调用是通的，编某一个功能跟下一个功能是对接不上的，你的产出跟下一个步骤的调用是对不上的，这是不行的」
- **审计真源**：后端 `GET http://127.0.0.1:7000/api/openapi.json`（运行时真源，不是代码 grep）
- **断链判定**：真实 HTTP 实测。`404`=路由不存在；`404` 但 body 是「任务不存在/文件不存在」=路由存在只是资源缺失；`405`=方法不符；`500`=路由存在但服务端炸
- **修复状态**：全部落地并复验通过（28/28 链路实测 + 前端 tsc 0 错 / vitest 336/336 + 后端 pytest 136 passed）

---

## 1. 审计方法（以及两次自我纠错）

### 1.1 口径演进

| 版本 | 方法 | 结论 | 问题 |
|---|---|---|---|
| v1 | 只扫 `app/**/page.tsx` | 「164/471 命中、5 个死页」 | 只看页面文件，漏掉子组件/hooks/共享 lib，**假阴性** |
| v3 | 全量扫所有 `.ts/.tsx`，按**文件所在目录**归组 | 「173/475 命中、6 个死页」 | 归组方式错：`/`（根 `app/page.tsx`）、`/hermes-chat`（实现在 `app/ai-agent/components/`）、`/persona`（实现在 `components/persona/`）、`/login`（实现在 `lib/cloud-auth.ts`）的调用全被甩进兜底桶，**误判成死页** |
| **v4（本次采用）** | 以路由 `app/**/page.tsx` 为起点做 **import 闭包遍历**，闭包内所有文件里的 `/api/...` 字面量都算该路由可达；再把「页面 → Next 代理 → 后端」这一跳也算进去 | **475 端点组 / 164 可达 / 311 未触达 / 51 路由** | — |

v4 脚本：`tmp/audit_routes.py`，产物 `tmp/audit_v4.json`。

实现过程中踩到并修掉的三个坑（都会直接扭曲结论，记录在此避免重蹈）：

1. **Windows 路径分隔符**：`os.path.join(FRONT, "components/x")` 产出 `/` 分隔符，而 `os.walk` 产出 `\` 分隔符 → `c in files` 全部落空，import 闭包退化成「只有页面自己一个文件」。必须 `os.path.normpath()`。
2. **Next 代理路由前缀**：代理真实 URL 是 `/api/<rel>`，脚本一开始只算成 `/<rel>` → 所有「页面经代理中转后端」的可达性全部丢失。
3. **常量表污染**：`lib/schemas.ts` 里集中写了全端点 URL 字面量，代理的 import 闭包一旦包含它，每个代理都会算到同一批端点。改为代理归属只扫**代理自己目录**下的文件。

### 1.2 最终数据

```
后端端点组 = 475   路由可达命中 = 164   未触达 = 311
前端路由 = 51       Next API 代理路由 = 37
```

**51 个路由里，没有一个是死页。** 静态扫描显示「无后端调用」的 6 个，逐一核实后全部是合理形态：

| 路由 | 判定 | 依据 |
|---|---|---|
| `/analytics/trends` | 合法 | `redirect("/analytics")` |
| `/analytics/videos` | 合法 | `redirect("/analytics/videos/douyin")` |
| `/publish` | 合法 | `router.replace("/publish/matrix")` |
| `/tools/image-editor` | 合法 | 纯客户端画布编辑器（fabric.js + react-image-crop），本地裁剪导出，不需要后端 |
| `/dashboard-demo` | 合法（但需标注） | 纯 UI 组件样例，数字全是硬编码 → **本轮已加醒目横幅标注** |
| `/persona` | 合法 | 页面本身 `return null`，真实 UI 由 `AppShell` 注入的 `PersonaEmbeddedHost` 渲染 → 实测 `GET /api/v1/persona/dashboard/status` 返回 200 |

---

## 2. 发现的真问题（按严重度）

### P0-1 ★ 全仓系统性 bug：`get_main_db()` 被当成普通连接使用（13 模块 52 处）

**症状**：SQLite 部署下大量接口返回 **500 且响应体为空**（不是 JSON，浏览器 Network 面板显示空响应）。

**根因**：`fastapi_app/db/session.py` 的 `get_main_db()` 是 FastAPI **依赖注入生成器**：

```python
def get_main_db():
    conn = ...
    try:
        yield conn      # ← 生成器
    finally:
        conn.close()
```

但 13 个模块把它当普通连接直接调用：

```python
conn = get_main_db()      # ← 拿到的是 generator，不是 Connection
cur = conn.cursor()       # → AttributeError: 'generator' object has no attribute 'cursor'
```

**为什么线上没爆**：MySQL 分支走 `sa_connection()`（真正的连接池），只有 SQLite 分支会炸。也就是说**生产 MariaDB 环境完全看不出来，本地开发 + Community 桌面版全线瘫**。这个 bug 精确地覆盖了用户最关心的「生成 → 审查 → 发布」主链路。

**修法**：新增 `open_main_db()`（直接返回 `sqlite3.Connection`，`row_factory=Row`），用脚本 `tmp/fix_db_conn.py` 机械替换 52 处连接获取 + 53 处 import，共 13 个文件：

```
prism_core/{account_health,content_variant,dedup,diagnostics,insight,matrix_route,
            monitor,receipts,review_queue,task_state_machine,webhook}.py
fastapi_app/api/v1/content_variant/router.py
db/migrate_receipts.py
```

**为什么不动 `get_main_db` 本身**：它是 `Depends(get_main_db)` 的合法用法（`publish/router.py` 6 处），改了会破坏连接池归还逻辑。新增独立函数风险最低。

**复验**：残留 0 处、`compileall` 通过、10/10 端点从 500 变 200（见 §4 表 A）。

---

### P0-2 ★ Hermes SSE 被 Next 的 fallback rewrite 缓冲 —— 浏览器端根本收不到事件

**症状**：UI 停在「正在连接 Hermes Agent…」，Network 面板里 `POST /api/v1/agent/hermes-stream` 一直是 **pending**，一个字节都收不到。

**根因**：`next.config.ts` 把后端代理放在 **`fallback` rewrites** 里：

```ts
return { beforeFiles: docsRewrites, afterFiles: [], fallback: backendRewrites }
```

fallback rewrite 走 Next 的通用代理，**会把上游响应整体缓冲后再吐给浏览器**。SSE 的增量事件因此全部卡在服务端，直到流结束才可能一次性吐出。

**修法**：新增真正的流式 Route Handler `app/api/v1/agent/hermes-stream/route.ts`，把上游 `ReadableStream` 原样透传：

```ts
export const runtime = "nodejs"
export const dynamic = "force-dynamic"
export const maxDuration = 300

// 直接透传上游流，保留 SSE 分帧
return new Response(upstream.body, {
  headers: {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
  },
})
```

文件系统路由优先级高于 fallback rewrite，所以这条路径会被 Route Handler 接住。顺带同源转发绕开了 CORS。

**复验**：见 §4 表 D —— 后端直连 32ms 出 header，Next 代理 1.6s（dev 首次编译）出 header，事件帧完整送达；浏览器 UI 实测渲染出「目标 / 系统 / 思考」事件流。

---

### P0-3 ★ `/hermes-chat` 被硬编码 iframe 劫持，**能用的原生实现反而看不见**

**Before**：`app-shell.tsx` 里

```tsx
{hermesChatActive && (
  <iframe src="http://127.0.0.1:9119/chat" ... />
)}
```

端口 9119 是本地 `hermes-webui` 进程。Community 桌面版**不带** hermes-webui 运行时 → 这条路由在社区版里永远白屏。而 `app/ai-agent/components/HermesChatPage.tsx` 里有一套**直连后端 `/api/v1/agent/hermes-stream` 的原生 SSE 客户端**，却被 `embeddedActive` 隐藏，浏览器永远访问不到。

**After**：
1. `app-shell.tsx`：删掉硬编码 iframe，`/hermes-chat` 不再进 `embeddedActive`，原生页面正常渲染。
2. 新增 `app/ai-agent/components/HermesWebuiPanel.tsx`：官方 WebUI 降级为**可选增强面板** —— 先读 `GET /api/v1/agent/config/hermes/runtime`，拿到真实 `dashboard_url` 才挂 iframe；没装就明确告诉用户去哪装，而不是白屏。
3. 顺带修正一处「注释与代码不符」：`useHermesStream.ts` 的注释写着「直接连后端 backendBaseUrl 绕过 Next rewrite 的 fallback 限制」，但代码用的是相对路径 `/api/v1/...`。这条注释其实是**当初就发现了这个坑**却没落实的遗留 —— 现在由 P0-2 的 Route Handler 真正解决。

---

### P1-1 ★ `/tasks/distribution` 被 `/{task_id}` 路由吃掉

**症状**：`GET /api/v1/tasks/distribution` → 404，body 是 `{"detail":"任务不存在"}`。

**根因**：`fastapi_app/api/v1/router.py` 里注册顺序是

```python
api_router.include_router(tasks_router)        # 先，含 GET /tasks/{task_id}
api_router.include_router(distribution_router) # 后，含 GET /tasks/distribution
```

FastAPI 按注册顺序匹配，`/tasks/{task_id}` 先注册 → 把 `distribution` 当成 task_id。

**修法**：`distribution_router` 提到 `tasks_router` 之前，并加注释说明为什么不能换回来。

---

### P1-2 ★ 扫码派发链路三处「空壳 + 打错库」

`myUtils/distribution_manager.py` 原本硬编码连 `prism_backend/db/database.db` —— 该库只有 6 张表，**从未建过** `distribution_tasks` / `task_videos`。同时 `fastapi_app/api/v1/tasks/distribution_alias.py` 是 TODO 空壳：`GET` 恒返回 `items: []`、`POST` 直接回 success。

**修法**（不重写，接真实现）：
- 库路径统一到 `settings.DATABASE_PATH`（`data/db/database.db`）
- `ensure_tables()` 自动建表
- 新增 `_resolve_file_id()`：把素材路径映射为 `file_id`（`publish/batch` 需要整数 ID）
- `distribution_alias.py` 整文件重写为真实实现：list / create / detail / add-videos / claim-by-task / claim-by-qr

---

### P1-3 ★ 后端缺 2 组端点（前端有调用、后端根本没这条路由）

| 端点 | 状态 | 说明 |
|---|---|---|
| `GET /api/v1/verification/otp-events` | **404 → 已补** | 前端 OTP 弹窗要轮询；后端 `platforms/verification.py` 新增 `peek_pending_events()`（**peek 不清空**，避免前端轮询和 AI 工具互相抢事件）；`ai_service/function_calling_tools.py` 的 `get_otp_events` 响应解析同步对齐（它自己也调这个端点，之前是断的） |
| `POST /api/v1/recovery/add` | **404 → 已补** | `recovery_snapshots` 表；删除操作前留快照 |
| `GET /api/v1/recovery/list` | **404 → 已补** | 列出快照 |
| `GET /api/v1/recovery/{recovery_id}` | **404 → 已补** | 单条快照 |

---

### P1-4 前端 10 条路径断链（全部实测确认 + 全部修复）

| # | 前端原来打的 | 后端真实存在的是 | 修法 |
|---|---|---|---|
| 1 | `POST /api/v1/analytics/collect`（聚合） | `POST /api/v1/analytics/collect/{platform}` | 改为按平台逐个分发（`PLATFORM_ROUTE` 映射 9 个平台），聚合结果，207 表示部分失败 |
| 2 | `/api/task-packages/${id}/generate` | `/api/v1/task-packages/${id}/generate-tasks` | 改路径；失败抛错 |
| 3 | `POST /api/task/create` | `POST /api/v1/tasks/distribution` | 改路径；请求体换 `{platform,title_template,poi_location,expire_time,video_files}`；成功判定改 `payload?.status !== "success"` |
| 4 | `/api/dispatch-tasks/${id}/publish` | 端点不存在 | 改**真实两步链路**：① `POST /api/v1/tasks/distribution/${id}/claim` 领素材拿 `file_id` → ② `POST /api/v1/publish/batch` 真发。同时删掉 `app/api/dispatch-tasks/[id]/publish/route.ts`（已无引用） |
| 5 | `/api/v1/assets/{id}` | `/api/v1/files/{file_id}` | 改路径 |
| 6 | `POST /api/tasks/${taskId}/cancel` | `POST /api/v1/tasks/cancel/${taskId}` | 改路径与方法；成功判定改 `res.ok && result.success`，错误回退读 `result.detail` |
| 7 | `/api/publish/otp-events` | `/api/v1/verification/otp-events` | 端点对齐 + 适配 `{success,data:{events,total}}`；**原本整段被注释掉的轮询已启用** |
| 8 | `/api/v1/video-pipeline/clips`、`/concat` | `GET /api/v1/video-pipeline/templates`、`POST /api/v1/video-pipeline/render` | 对齐真实后端（FormData: composition_dir/quality/fps）；接口字段重构为 `{id,name,description,category,tags,duration,size,dir}` / `{ok,outputs,file_ids,elapsed_seconds,error}`；文案「4312 片段库」→「HyperFrames 模板库」 |
| 9 | `GET /api/tasks/distribution` 期望数组 | 后端返回 `{result:{items:[…]}}` | 代理层解包为数组 |
| 10 | `GET /api/v1/review/queue` 等 | 路由存在但 500 | 见 P0-1 |

---

### P2-1 审查层全貌：**审查不在生成之后，在发布之前**

这轮把审查层的真实链路彻底摸清了（之前 20 个审查端点前端零调用）：

```
files → publish/batch(file_ids) → task_id → review/auto-check(task_id + content + title)
      → approve → 真发
```

`/api/v1/review/*` 共 10 个端点、`/api/v1/content-variants/*` 全部前端零调用。**根因是生成层缺统一产物 ID**：生图/生视频的产物没有能传给审查层的稳定标识，所以「产出与下一步调用对不上」。

**本轮落地**：新建 `/review` 页面（3 个 Tab：审核队列 / 内容版本审批 / 敏感词库），把 `review/*`、`content-variants/*`、`fusion/moderation/sensitive-words` 全部接上真实端点。浏览器实测：`review/queue` 200、`review/stats` 200、`content-variants/variants/` 200、`content-variants/reviews/` 200、`sensitive-words` 200。

> **生成层产物 ID 统一**是下一阶段的核心工作项 —— 它是「产出 → 审查」自动衔接的前提。本轮只是把审查层的入口补齐，没有动生成层的数据模型。

---

### P2-2 侧边栏全量化 + 两个「找不到页面」的体验问题

- **`sidebar-new.tsx`** 重排为 **10 个分组**：概览 / 资源 / 内容 / 生成 / 分发 / 数据 / 智能 / AI-Fusion / 开发者工具 / 系统，覆盖除 `/login` 外**全部 49 个路由**（`/dashboard-demo` 归「开发者工具」，动态段由父级入口覆盖）。
- **返回键不可见**（用户原话：「返回键非常不明显，也没有颜色啊，没有边框，这样的话找不到」）→ `scenario-guide.tsx` 的返回键 ghost 改为 outline + 边框。
- **新建 `/guide`「快速开始」页**，作为侧边栏第一个落地页。
- **M4 写稿向导全 Mock**（`scenarios.tsx` 零 fetch，4 个场景全假数据，picsum 占位图）→ 卡片描述改为「演示流程」并注明未接真实 API；对应测试断言同步更新。

---

### P2-3 仪表盘「账号总数」显示 `—` —— 是 0 被当空值

**不是接口挂了**。后端 `GET /api/v1/dashboard/stats` 正确返回 `accounts.total = 0`（本地确实还没导入账号），但前端写的是

```tsx
value: accountTotal ? `${accountTotal}` : "—",   // ← 0 是 falsy，被渲染成破折号
```

用户看到「—」会以为是接口失败。修法：区分「加载中」与「真的是 0」。

---

### P2-4 `/dashboard-demo` 伪装成真数据

纯 UI 组件样例页，数字全是硬编码（`$45,231.89` / `+2350` / `+180.1%`），却没有任何说明。已加醒目横幅：本页仅演示 Sci-Fi 视觉组件，所有数字均为硬编码假数据，平台实况请看仪表盘。

---

## 3. 改了什么（文件清单）

### 后端 `prism_backend/`

| 文件 | 改动 |
|---|---|
| `fastapi_app/db/session.py` | 新增 `open_main_db()` |
| `prism_core/*.py`（11 个） | 52 处连接获取 → `open_main_db()` |
| `fastapi_app/api/v1/content_variant/router.py`、`db/migrate_receipts.py` | 同上 |
| `fastapi_app/api/v1/verification/router.py` | 新增 `GET /otp-events` |
| `platforms/verification.py` | 新增 `peek_pending_events()` |
| `ai_service/function_calling_tools.py` | OTP 响应解析对齐 |
| `fastapi_app/api/v1/recovery/router.py` | 新增 `/add`、`/list`、`/{recovery_id}` |
| `myUtils/distribution_manager.py` | 库路径统一 + `ensure_tables()` + `_resolve_file_id()` |
| `fastapi_app/api/v1/tasks/distribution_alias.py` | 整文件重写为真实实现 |
| `fastapi_app/api/v1/router.py` | `distribution_router` 提到 `tasks_router` 之前 |

### 前端 `prism_frontend/src/`

| 文件 | 改动 |
|---|---|
| `app/api/analytics/collect/route.ts` | 按平台分发 |
| `app/api/tasks/distribution/route.ts` | GET 解包为数组 |
| `app/api/publish/otp-events/route.ts` | 解包为 `{events,total}` |
| `app/api/v1/agent/hermes-stream/route.ts` | **新建**：SSE 流式透传 |
| `app/campaigns/[id]/new/page.tsx` | 路径对齐 |
| `app/tasks/publish/page.tsx` | 取消任务路径/方法/判定 |
| `app/tasks/distribution/page.tsx`、`app/publish/distribution/page.tsx` | 创建分发任务 |
| `app/tasks/distribution/components/task-drawer.tsx`、`app/publish/distribution/components/task-drawer.tsx` | 两步真实发布链路 + `platformCode()` 平台码映射 |
| `app/video-pipeline/page.tsx` | 对齐真实视频流水线后端 |
| `components/publish/publish-otp-dialog.tsx` | OTP 端点对齐 + 启用被注释的轮询 |
| `components/layout/app-shell.tsx` | 删硬编码 iframe |
| `components/layout/sidebar-new.tsx` | 10 分组全量化 |
| `app/ai-agent/components/HermesChatPage.tsx` | 新增「官方 WebUI」按钮 |
| `app/ai-agent/components/HermesWebuiPanel.tsx` | **新建**：官方 WebUI 运行时探测面板 |
| `app/review/page.tsx` | **新建**：审核队列 3 Tab |
| `app/guide/page.tsx` | **新建**：快速开始 |
| `components/wizard/scenario-guide.tsx`、`components/wizard/scenarios.tsx` | 返回键可见性 + Mock 标注 |
| `app/page.tsx` | 账号总数 0 显示 |
| `app/dashboard-demo/page.tsx` | 组件样例横幅 |
| `components/wizard/__tests__/scenarios.test.tsx` | 断言同步 |
| **已删除** `app/api/dispatch-tasks/[id]/publish/route.ts` | 指向不存在的后端 |

---

## 4. 复验证据

### 表 A：曾全线 500 的端点（修复后）

| 端点 | 修复前 | 修复后 |
|---|---|---|
| `GET /api/v1/review/queue` | 500（空 body） | **200** `[]` |
| `GET /api/v1/review/stats` | 500 | **200** `{pending:0, in_review:0, …}` |
| `GET /api/v1/content-variants/variants/` | 500 | **200** `[]` |
| `GET /api/v1/content-variants/reviews/` | 500 | **200** `[]` |
| `GET /api/v1/verification/otp-events` | 404（端点不存在） | **200** `{success,data:{events:[],total:0}}` |
| `GET /api/v1/recovery/list` | 404（端点不存在） | **200** `{status:success,result:{items:[],total:0}}` |
| `GET /api/v1/matrix/stats` | 500 | **200** |
| `GET /api/v1/tasks/stats` | 500 | **200** |
| `GET /api/v1/dashboard/tasks/summary` | 500 | **200** |
| `GET /api/v1/analytics/` | 500 | **200** |

### 表 B：写入→读取闭环

- `POST /api/v1/recovery/add` → `{"status":"success","result":{"recovery_id":"rc_…","object_id":"…"}}` → `GET /api/v1/recovery/list` 能查到 → `GET /api/v1/recovery/{id}` 能取到。**测试数据已清理（表内 0 行）**。
- `GET /api/v1/tasks/distribution` → `{"status":"success","result":{"success":true,"items":[]}}`（修复前恒 `items:[]` 且路由被吃成 404）。
- `POST /api/v1/tasks/distribution` 空素材 → 400「至少需要选择一条素材」（真校验，不是空 success）。

### 表 C：Hermes SSE 双通道

| 通道 | 首字节延迟 | Content-Type | 首事件 |
|---|---|---|---|
| 后端直连 `:7000/api/v1/agent/hermes-stream` | 32ms | `text/event-stream` | `data: {"type":"init",…}` |
| Next 代理 `:3000/api/v1/agent/hermes-stream` | 1.6s（dev 首次编译） | `text/event-stream` | `data: {"type":"init",…}` |

浏览器端 UI 实测：发送「列出当前可用的技能列表」后，页面实时渲染出「目标 / 系统 / 思考 / 思考…」事件流。

### 表 D：自动化复验

```
tmp/verify_chains.py   →  28 项，28 通过，0 失败
```

覆盖：A 后端 10 个 500 端点 / B 写入→读取闭环 / C 前端 10 条断链落点 / D SSE 双通道。

```
前端 tsc --noEmit        →  0 error
前端 vitest              →  18 文件 / 336 测试 全绿
后端 pytest              →  136 passed, 1 skipped
```

### 表 E：浏览器实测（Chrome DevTools 协议）

- `/review`：渲染 3 个 Tab，Network 里 `review/queue` 200、`review/stats` 200、`content-variants/variants/` 200、`content-variants/reviews/` 200、`sensitive-words` 200。
- `/hermes-chat`：原生 SSE 面板渲染，输入目标后事件流实时到达。
- 侧边栏：10 分组全覆盖渲染，51 个路由无一是死页。

---

## 5. 审计结论

### 5.1 用户关心的「对接得上吗」——分层回答

| 链路 | 修复前 | 修复后 |
|---|---|---|
| **对话式生成一切（Hermes）** | 页面被 iframe 劫持 + SSE 被缓冲，浏览器端**完全不可用** | **通**：原生 SSE + 流式代理，实测事件流到达 |
| **生图/生视频 → 审查** | 审查层 20 个端点前端零调用；生成层无产物 ID | 审查层入口补齐（`/review` 页 3 Tab 全部接真端点）；**生成层产物 ID 仍未统一**（下阶段） |
| **素材库 → 内容库** | 素材详情路径错（`/assets/{id}` → `/files/{file_id}`） | **通** |
| **内容 → 发布** | 派发任务是 TODO 空壳 + 打错库；发布步骤打不存在的端点 | **通**：claim 拿 file_id → `publish/batch` 真发，两步链路 |
| **发布 → 审查** | 审查队列接口 500 | **通** |
| **账号/素材 → 仪表盘** | 统计接口 500；0 显示成 `—` | **通** |

### 5.2 仍然未打通的部分（诚实记录）

1. **生成层缺统一产物 ID** —— 「生图/生视频产出 → 审查」无法自动衔接，只能人工带 ID。这是**下阶段第一优先**。
2. **311 个后端端点仍无前端入口** —— 绝大多数是 Open Core 内部能力、运维/诊断类、平台细粒度 API（例如 `/api/v1/system` 24 个、`/api/v1/platforms` 16 个、`/api/v1/fusion` 25 个）。**这是产品取舍面，不是缺陷**，是否给 Pro 做入口属于商业决策。
3. **审查链路的入口位置有争议** —— 现状是「发布前审查」，但用户表述是「生图生视频之后的融合与审查」。若要改成「生成后即审」，需要把审查挂到生成产物上（回到第 1 点）。

---

## 6. 未决事项（需要马哥拍板，本轮未擅自决定）

1. **Open Core 边界**：`POST /api/v1/recovery/add|list|{id}` 本轮**未加 feature gate**（不消耗 TikHub 额度，纯本地快照，社区版可用）。若要收进 Pro，需要在 `recovery/router.py` 补 `_require_data_recovery`。
2. **`cloud_service/llm_proxy/prompts.py`（18KB / 381 行）仍在开源树内**，DB dump 的 `prompts` 表也在。是否移出开源树属 Open Core 决策，未擅自处理。
3. **「8 平台」三套口径冲突未统一**：README 写一套、前端选知乎/头条/西瓜、后端实为百家号。涉及 Pro 付费承诺，等定。
4. **`/api/v1/platforms` 等平台细粒度 API 是否需要前端入口**，等定。
5. **标书工作区 `AIBidForge5.2-master/`（345 文件 AGPL 上游）仍以未跟踪状态残留**，有误提交风险 —— 需授权后加 `.gitignore`；另有三个乱码空壳路径目录待清理。
6. **另一台电脑的 Prism-Fusion 副本**与本机共用同一 `prism-server` 裸仓库 + 同一把 SSH key + 同一条 `main`，裸仓库未开 reflog，存在推送竞争风险 —— 是否冻结待定。
7. **Community 安装器无代码签名**（`Get-AuthenticodeSignature` = NotSigned），且未在干净 Windows VM 完成安装/启动/卸载/升级验证。
8. **真实生产联调零验证**：缺 `CLOUD_LLM_API_KEY`、支付宝/微信正式商户凭证与证书、TikHub Key —— 支付链路与 TikHub 链路目前一次都没跑通过。

---

## 7. 复现方式

```powershell
# 起后端（cwd 必须是 prism_backend）
$env:PYTHONPATH='D:\dim开发\Prism-Fusion\prism_backend'
Start-Process -FilePath 'D:\dim开发\Prism-Fusion\prismenv\Scripts\python.exe' `
  -ArgumentList 'fastapi_app\run.py' -WorkingDirectory 'D:\dim开发\Prism-Fusion\prism_backend' `
  -RedirectStandardOutput 'D:\dim开发\Prism-Fusion\tmp\backend_restart.log' `
  -RedirectStandardError  'D:\dim开发\Prism-Fusion\tmp\backend_restart.err'

# 起前端 dev（Next 16 Turbopack）
cd D:\dim开发\Prism-Fusion\prism_frontend
node node_modules\next\dist\bin\next dev

# 审计 / 复验
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python tmp\audit_routes.py      # 路由级可达性分析 → tmp/audit_v4.json
python tmp\verify_chains.py    # 端到端链路复验（28 项）
```

**注意**：打包版 Electron（`desktop-electron/dist-community/.../LaomaAICommunity.exe`）会自带一个 standalone server 抢占 3000 端口。跑 dev 前必须先停掉它，否则浏览器访问到的是旧打包产物 —— 本轮就踩过这个坑（表现为「侧边栏还是旧的、`/review` 404」）。
