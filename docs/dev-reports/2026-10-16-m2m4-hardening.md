# M2 / M4 遗留问题硬化报告

- 日期：2026-10-16
- 范围：M2 · Agent Studio JWT 强制鉴权、M4 · Suspense 包裹、M4 · AI 生图接入智能体选择
- 状态：全部完成；M2 后端 102/102 PASS，前端 193/193 PASS，`tsc --noEmit` 无错

---

## 一、总体结论

本轮修复了三条跨模块的遗留问题：

| # | 问题 | 模块 | 修复方式 |
|---|------|------|---------|
| 1 | M2 agent 端点信任 `?user_id=` 和 body `user_id`，缺 JWT | M2 | 新增 `verify_access_token` / `get_auth_user_id`，全端点强制 Bearer JWT；401 覆盖无 token / 非法 / 过期 / refresh-type / 缺 sub / query-body 伪造 |
| 2 | 前端 `useSearchParams` 在 Suspense 之外使用，Next.js 15 客户端水合告警 | M4 | `ScenarioGuide` 拆分为外层 `ScenarioGuideShell` + 内层 `ScenarioGuideContent`（后者直接调用 `useSearchParams`），外壳用 `<Suspense>` 包裹 |
| 3 | AI 生图场景没有选择智能体的入口，用户无法把 M2 训练出的风格智能体接入生图链路 | M4 + M2 | 新增 `AgentPickerStep` 组件；`AI_IMAGE_SCENARIO` 插入"智能体选择（可选）"步骤；调用 agent list / quota 时统一注入 `Authorization: Bearer` |

M1 回归验证：M2 改动后 `PASS=134, FAIL=4`，基线是 `PASS=132, FAIL=6`；剩余 FAIL 均为老问题（跨测试状态污染：配额累计、分页边界、幂等键），非本轮引入。

---

## 二、修改文件清单

### 后端
- `prism_backend/fastapi_app/api/dependencies.py` **（新增）**
  - `verify_access_token(credentials)`：HS256、`type == "access"`、`sub` 非空、未过期
  - `get_auth_user_id(credentials, request)`：支持从 FastAPI `Depends` 或直接 `request.headers` 两条路径取 `Authorization` 头
  - `create_test_access_token(subject)`：PyJWT 测试 helper
- `prism_backend/fusion_ai/ai_agents.py`
  - `_get_uid(request: Request)`：从 `Authorization` 头解 Bearer，直接调 `verify_access_token`，任何失败一律 `401 {"WWW-Authenticate": "Bearer"}`
  - `create_agent` 显式 `await _get_uid(request)`；不再读 body 里的 `user_id`
  - list / get / update / delete / quota 全部保留 `user_id: str = Depends(_get_uid)`
- `prism_backend/tests/test_m2_agents.py`
  - 重写为严格 JWT 契约：无 token → 401、非法 token（garbage / expired / refresh-type / no-sub）→ 401、body/query 伪造 → 忽略、每 subject 独立配额、正常 CRUD
  - 最终 `102 PASS / 0 FAIL`

### 前端
- `prism_frontend/src/components/wizard/scenario-guide.tsx`
  - `ScenarioGuide` 拆分为 `ScenarioGuideShell`（无 hook）+ `ScenarioGuideContent`（调用 `useSearchParams`）；外壳用 `<Suspense fallback={null}>` 包裹
  - 保持原 `ScenarioGuide` 名称的导出以最小化下游 diff
- `prism_frontend/src/components/wizard/agent-picker-step.tsx` **（新增）**
  - `AgentPickerStep` 组件：挂载时并发请求 `GET /api/v1/ai-design/agents` 和 `/quota`
  - 从 `cloudAuth.getAccessToken()` 读 access token，注入 `Authorization: Bearer` header
  - 401 展示"请先登录"提示；无 agent 展示禁用下拉 + 跳转提示
  - `Select` 首选项为"不使用智能体（默认）"
  - 模块级 `_agentIdCache`：因 Wizard 会在步骤切换时重挂载 step.render，选中值写入模块级 Map 跨步骤保留
  - 选择事件通过 `CustomEvent('prism-wizard:agent-selected')` 广播，未来生图接口读取即可
- `prism_frontend/src/components/wizard/scenarios.tsx`
  - `AI_IMAGE_SCENARIO.steps` 增加第 2 步 `title: "智能体选择（可选）"`，`render: () => <AgentPickerStep />`
  - description 更新为"上传原图 → 选择智能体 → 选择类型 → 生成 → 编辑发布"
- `prism_frontend/src/components/wizard/__tests__/scenarios.test.tsx`
  - AI 生图断言更新为 5 步，并校验顺序
- `prism_frontend/src/app/fusion/styles/agent-studio-panel.tsx`
  - `authFetch`：所有 fetch 统一注入 `Authorization: Bearer`
  - `load()`：list/quota 均 401 时进入 `unauthed` 状态
  - UI 顶部增加"请先登录以管理你的智能体"提示卡（跳转 `/login`）
  - `create` 也改走 `authFetch`

---

## 三、JWT 实现摘要

**Secret 来源**：`cloud_service.auth.settings.get_settings().JWT_SECRET`（pydantic-settings，`lru_cache` 单例）。测试 helper `create_test_access_token` 从同一 resolver 拿 secret，测试与运行时永远一致，不受 env 影响。

**验证规则**（`verify_access_token`）：
- `HTTPBearer(auto_error=False)` 提取 credentials；缺失 → 401 + `WWW-Authenticate: Bearer`
- `jwt.decode(..., algorithms=["HS256"])`；`jwt.exceptions.*` 一律 401
- `payload["type"] == "access"`（拒绝 refresh token）
- `payload["sub"]` 非空且是 `str`
- `exp` 由 PyJWT 内置检查；测试用过期 token 覆盖
- 成功返回 `payload["sub"]`

**端点侧接入**（`ai_agents.py::_get_uid`）：
```python
async def _get_uid(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    return await verify_access_token(request, auth[7:])
```
- 无 `HTTPBearer` 全局依赖，避免"手动调用 `Depends` 对象" 的陷阱
- 所有端点通过 `Depends(_get_uid)` 复用；`create_agent` 显式 `await` 是因为要在 `Depends` 之外读取额外 body
- `user_id` 只来自 JWT `sub`；`?user_id=` 与 body `user_id` 一律忽略

**M1 保持不动**：`ai_design.py::_extract_user_id` 仍保留 body/query/匿名 fallback；`test_ai_design_generate_with_agent_id` 通过把 body `user_id` 对齐 JWT `sub` 保证 M1↔M2 联动通过。

---

## 四、Suspense 拆分

`ScenarioGuide` 原实现：

```tsx
function ScenarioGuide(props) {
  const searchParams = useSearchParams()  // 需要在 <Suspense> 中
  ...
}
```

Next.js 15 中 `useSearchParams` 在客户端路由下要求包裹于 `<Suspense>`，否则构建告警 `Page used `useSearchParams()` without a Suspense boundary`。

拆分为：
- `ScenarioGuideShell`：只做布局/props 透传，不使用 hook
- `ScenarioGuideContent`：调用 `useSearchParams`，是原来的核心逻辑
- 导出的 `ScenarioGuide` = `<Suspense fallback={null}><ScenarioGuideContent {...props} /></Suspense>`

外层 `<Suspense fallback={null}>` 保证客户端导航到 `?scene=xxx` 时水合不阻塞。

---

## 五、AI 生图接入智能体选择

**方案**：`AI_IMAGE_SCENARIO.steps` 从 4 步扩到 5 步，第 2 步为 `AgentPickerStep`：

```
1. 上传原图
2. 智能体选择（可选）   ← 新增
3. 选择图片类型
4. 生成
5. 编辑 / 发布
```

**关键决策**：

1. **鉴权走 `cloudAuth.getAccessToken()`**：与 Easel / 云聊天 / M2 studio 面板同源；Electron 场景下 `client-gateway` 已从 `safeStorage` 读出 access token 并注入 `cloudAuth`，浏览器场景走 localStorage 兜底。
2. **401 降级**：不隐藏错误，展示黄色提示卡 + "前往登录 →"链接，让"未登录但打开了 Studio 页"的运维流程可见。
3. **跨步骤持久化**：Wizard 是 `useReducer + 步骤切换重挂载`模型，step.render 返回的组件会在步骤切换时卸载。方案比较：
   - React Context：需要在 Wizard 上方再嵌一层 Provider，改动大且要动 `WizardStepDefinition` 接口
   - `sessionStorage`：跨刷新保留但不跨 tab；读写需序列化
   - **模块级 Map（采纳）**：最简；同一页面会话内保留上次选择；Wizard 卸载即释放
4. **对外契约**：选中值写入 `_agentIdCache`；同时派发 `CustomEvent('prism-wizard:agent-selected', { detail: { agent_id } })`。未来 `generate` API 接入时（M1 完成后）通过事件监听或直接读 cache 都可拿到。
5. **默认选项**：`__none__` 为 sentinel，映射到空 `agent_id`，走原有匿名生图流程，向后兼容。

**未来接生成接口的落点**（本轮未实现，只留接口）：
- 后端 `POST /api/v1/ai-design/generate` 已经接受 `agent_id`；M1 会把它拼成 prompt 前缀
- 前端生图入口读取 `prism-wizard:agent-selected` 事件的 `agent_id` 字段即可

---

## 六、测试结果

### M2 后端
```
M2 backend tests: 102 PASS / 0 FAIL (total 102)
```
覆盖：agent store CRUD、配额默认/env 覆盖/释放、`parse_samples` 变体、JWT 无效四型、body/query 伪造忽略、每 subject 独立配额、正常 CRUD 全链路。

### 前端
```
Test Files  10 passed (10)
Tests       193 passed (193)
```
- `scenarios.test.tsx`：AI_IMAGE_SCENARIO 5 步 + 顺序断言更新
- `wizard-core.test.ts`、`url-sync.test.ts`：无变化
- `agent-studio.test.ts`：`authFetch` 层测试不变（组件调用改走包装，纯逻辑测试不涉及）
- `cloud-auth.test.ts`、`cloud-gateway-client.test.ts`、`client-gateway.test.ts`：不变

### TypeScript
```
npx tsc --noEmit  # exit 0，无输出
```

### M1 回归
```
M1 backend tests: PASS=134, FAIL=4
```
基线 `PASS=132, FAIL=6`。剩余 FAIL 与本轮 JWT 工作无关（跨测试状态污染：总条数、分页、幂等键），未在本轮范围内处理。

---

## 七、遗留事项

以下项未纳入本轮范围，作为后续单独排期：

- **M1 状态污染**：`test_ai_design_generate_all` / `test_ai_design_pagination` / `test_ai_design_idempotency` 依赖进程内共享 store；建议加 test fixture 重置或加 `@IsolatedTest` decorator
- **AI 生图接口接入**：本轮仅完成选择器 UI；`AgentPickerStep` 派发的 `prism-wizard:agent-selected` 事件需要 M1 完成后由 `/api/v1/ai-design/generate` 调用方订阅
- **前端 Studio 面板集成测试**：`AgentPickerStep` 和 `AgentStudioPanel` 的 401 分支目前只做了类型检查，未加 vitest+jsdom 的组件测试；建议后续用 msw mock fetch 补上
