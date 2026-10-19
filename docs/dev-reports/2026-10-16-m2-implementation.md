# M2 · AI 智能体风格训练后端实现报告

- **日期**：2026-10-18
- **模块**：`prism_backend/fusion_ai/ai_agents.py`（新）+ M1 `ai_design.py` 集成
- **验证**：
  - 后端 `python tests/test_m2_agents.py` → **87/87 PASS**
  - 后端 `python tests/test_m1_ai_design.py` → **74/74 PASS**（M1 回归无破坏）
  - 前端 `npx vitest run` → **193/193 PASS**（新增 25 用例）
  - 前端 `npx tsc --noEmit` → **0 errors**

---

## 1. 设计原则（对齐任务要求）

| 约束 | 实现 |
|---|---|
| 无成品开源，自建 pipeline | LLM 抽取 style_prompt + 本地降级 |
| 参考澜途"AI AGENT STUDIO" | 端点语义、配额模型、字段结构对齐 |
| 复用现有 `platform_styles.py` 基座 | 保留原 `/fusion/platform-styles`；新模块独立并存 |
| LLM 分析走 `cloud_service/llm_proxy` | 通过 `cloud_gateway.CloudGateway.chat` → `/cloud/llm/chat` |
| 配额参考澜途（limit=2） | 默认 2，`CLOUD_AGENT_QUOTA` env 覆盖 |
| mock 测试，不真调 LLM | `set_llm_analyzer()` 注入同步 mock |
| M1 集成不改 `image_generators.py` | 只在 `ai_design.generate` 中把 style_prompt 拼到 prompt 头部 |
| 最小改动 | 只新增文件 + 3 行 include_router + 1 段注入逻辑 |

---

## 2. 文件清单

### 新增（后端）

| 文件 | 行数 | 职责 |
|---|---:|---|
| `prism_backend/fusion_ai/ai_agents.py` | ~570 | AgentStore（JSON 存储）+ LLM 抽取 + CRUD + 配额 + FastAPI 路由 + M1 注入 helper |
| `prism_backend/tests/test_m2_agents.py` | ~570 | 11 个用例组 / 87 个断言；覆盖存储、配额、LLM、校验、M1 集成、错误处理 |

### 新增（前端）

| 文件 | 行数 | 职责 |
|---|---:|---|
| `prism_frontend/src/lib/agent-studio.ts` | ~140 | 纯逻辑：类型 / 表单校验 / 请求体构造 / 配额 UI 派生 / style_prompt 摘要 |
| `prism_frontend/src/app/fusion/styles/agent-studio-panel.tsx` | ~230 | UI：列表 + 创建表单 + 删除 + style_prompt 展开 + 配额徽标 |
| `prism_frontend/src/lib/__tests__/agent-studio.test.ts` | ~200 | 25 个 vitest 用例（表单/配额/长度边界/摘要） |

### 修改

| 文件 | 变更 |
|---|---|
| `prism_backend/fusion_ai/ai_design.py` | +25 行：新增 `_apply_agent_style_from_m2` 内部函数；在 `generate_images` 里读 `agent_id`/`user_id` 后注入 style_prompt；响应体不变（`agent_id` 仍然透传） |
| `prism_backend/fastapi_app/api/v1/router.py` | +2 行：`from fusion_ai.ai_agents import router as ai_agents_router` + `api_router.include_router(ai_agents_router)` |
| `prism_frontend/src/app/fusion/styles/page.tsx` | +1 行 import + 1 行 `<AgentStudioPanel />`（在现有平台风格列表之前，参考澜途顶部入口） |

### 未动（关键）

- `prism_backend/fusion_ai/image_generators.py` — 5 provider 完全没改
- `prism_backend/fusion_ai/platform_styles.py` — 平台风格骨架保留
- `cloud_service/llm_proxy/` — 通过既有 `CloudGateway.chat` 复用，未改
- `cloud_service/billing/` — M3 完全没改

---

## 3. 风格训练 Pipeline 设计

```
用户浏览器                     后端 ai_agents.py                cloud_service/llm_proxy
    │                              │                                    │
    │ POST /ai-design/agents       │                                    │
    │ {name, description,          │                                    │
    │  sample_contents[],          │                                    │
    │  design_principles}          │                                    │
    ├──────────────────────────────►│                                    │
    │                              │ ① 参数校验                          │
    │                              │   - name ≤ 80 / sample 非空        │
    │                              │   - design_principles ≤ 12000      │
    │                              │ ② 配额检查                          │
    │                              │   - list(user_id).length < limit   │
    │                              │   - 超限 → 403 quota_exceeded      │
    │                              │ ③ LLM 风格抽取                      │
    │                              │── POST /cloud/llm/chat ────────────►│
    │                              │   raw_prompt =                     │
    │                              │     [system] + [样例] + [原则]      │
    │                              │◄── content = style_prompt ─────────│
    │                              │ ④ LLM 失败 → 本地降级抽取            │
    │                              │   - 拼接原则 + 样例节选              │
    │                              │ ⑤ 落库                              │
    │                              │   - id=agent_{uuid12}               │
    │                              │   - JSON 文件原子写（fcntl/msvcrt）  │
    │◄── 200 {id, style_prompt,    │                                    │
    │    style_tokens, ...} ──────│                                    │
    │                              │                                    │
    │ 之后：POST /ai-design/generate│                                    │
    │ {model_key, prompt,          │                                    │
    │  agent_id}                   │                                    │
    ├──────────────────────────────►│                                    │
    │                              │ ① 解析 agent_id → store.get(uid,id)│
    │                              │ ② 拼 prompt:                       │
    │                              │   "[风格指南: {style_prompt}]\n\n"  │
    │                              │   "用户请求: {user_prompt}"         │
    │                              │ ③ 走 M1 原流程（freeze→gen→consume）│
    │◄── {images, agent_id, ...} ──│                                    │
```

**关键点**：
1. **LLM 失败不阻塞**：云端不可达/未登录/额度耗尽时降级为本地启发式抽取（截取原则+样例），保证创建流程能跑通。真实生产环境依赖云端。
2. **原子写 + 跨进程锁**：`AgentStore` 用 `os.replace` + `fcntl.flock`/`msvcrt.locking`，避免多进程/多线程写文件时损坏 JSON。
3. **软删除**：`status='deleted'` 而非物理删除，便于未来回收。列表/详情只读 `active`，配额只算 `active`，删除后配额立即释放。
4. **user_id 隔离**：所有表按 `user_id` 分区；`_resolve_user_id` 优先级 = query > Authorization Bearer > `anonymous`。跨用户 `find_style_prompt` 返回空串，避免 M1 生成时被别人的 style_prompt 污染。

---

## 4. API 端点清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/ai-design/agents` | 列出当前用户所有智能体（按 updated_at 倒序） |
| GET | `/api/v1/ai-design/agents/quota` | 配额 `{limit, used, canCreate, upgrade_url}` |
| POST | `/api/v1/ai-design/agents` | 训练 + 创建；body `{name, description?, sample_contents, design_principles?}` |
| GET | `/api/v1/ai-design/agents/{id}` | 详情 |
| DELETE | `/api/v1/ai-design/agents/{id}` | 删除（释放配额） |

**通用 user_id 解析**（无需登录即可调用，与 M1 保持一致）：
- query `?user_id=xxx`（前端直连首选）
- Authorization Bearer token（token 值本身作为 user_id）
- 兜底 `"anonymous"`

**错误码**：
- `400` 参数错误（缺 name / 缺 samples / 超长）
- `403` 配额超限（detail 含 `{code, message, limit, used, upgrade_url}`）
- `404` agent 不存在 / 跨用户
- `502` LLM 抽取失败（不落库）
- `503` 未来扩展：云端不可达

**响应体示例（POST 200）**：
```json
{
  "id": "agent_34d9efe228dd",
  "name": "冷色调海报",
  "description": "极简排版",
  "style_prompt": "[风格指南]\n- Tone: 简洁、克制\n- Visual: 冷色调",
  "sample_contents": ["标题A\n正文A", "标题B\n正文B"],
  "design_principles": "主色 #2D3BFF；字号 ≤ 24",
  "style_tokens": 34,
  "created_at": 1792306266,
  "updated_at": 1792306266
}
```

---

## 5. 存储（JSON 文件，与 platform_styles.py 对齐）

**文件路径**：`$DATA_DIR/ai_agents.json`（默认 `prism_backend/../data/`）

**schema**：
```json
{
  "<user_id>": [
    {
      "id": "agent_<uuid12>",
      "user_id": "u_123",
      "name": "冷色调海报",
      "description": "极简排版",
      "style_prompt": "Tone: ...\nVisual: ...",
      "sample_contents": ["...", "..."],
      "design_principles": "主色 #2D3BFF ...",
      "status": "active",
      "created_at": 1792306266,
      "updated_at": 1792306266
    }
  ]
}
```

**为何选 JSON 而非 SQL**：
- 与既有 `platform_styles.py` / `model_market.py` 保持一致（`_DATA_DIR` + `os.replace` 原子写）
- M2 数据量小（每用户 2 条配额），JSON 完全够用
- 无 SQL schema 迁移成本，部署零依赖
- 后续接云端 SaaS 时再迁到 DB

**并发**：
- 同一进程内 `threading.Lock`
- 跨进程 `fcntl.flock`（POSIX）或 `msvcrt.locking`（Windows），失败退化但不阻塞
- 原子写：先写 `.tmp` 再 `os.replace`

---

## 6. 配额实现

**默认值**：`limit = 2`（澜途免费档配额）

**可配置**：`CLOUD_AGENT_QUOTA` 环境变量（int）；无效/负值回退到默认。

**API**：
```python
def quota(user_id: str) -> dict:
    limit = _resolve_quota_limit()
    used = len(_store.list(user_id))  # 只算 status=active
    return {"limit": limit, "used": used, "canCreate": used < limit,
            "upgrade_url": "/billing/upgrade"}
```

**付费墙语义**：
- 创建时超限 → HTTP 403 + `detail.code = "quota_exceeded"`，前端读 `detail.message` 提示
- 删除任一 active agent → 配额立即释放（响应带新的 `quota` 对象）
- 升级套餐时由计费侧改 `CLOUD_AGENT_QUOTA` 或直接改 agent store（未来接入点）

---

## 7. M1 集成方式（agent_id → style_prompt 注入）

**集成点**：`prism_backend/fusion_ai/ai_design.py` `generate_images()` 内、参数校验后、provider 调用前。

**注入格式**（M1 报告里已声明的 agent_id 语义扩展）：
```
[风格指南: <style_prompt>]

用户请求: <user_prompt>
```

**关键实现**（`ai_design.py`）：
```python
def _apply_agent_style_from_m2(prompt: str, agent_id: str, user_id: str) -> str:
    """M1↔M2 集成点：把 M2 智能体的 style_prompt 注入到用户 prompt 头部。
    找不到智能体 / 权限不匹配时原样返回 prompt，不阻塞生成。"""
    if not agent_id or not prompt:
        return prompt
    try:
        from .ai_agents import _apply_agent_style
    except Exception:
        return prompt
    try:
        return _apply_agent_style(prompt, agent_id, user_id=user_id)
    except Exception:
        return prompt
```

**容错策略**（4 层降级，保证 M1 生成不受 M2 影响）：
1. `agent_id` 空 → 原样返回（M1 老调用方式 100% 兼容）
2. `agent_id` 不存在 → 原样返回（生成继续，不阻塞用户）
3. `agent_id` 属于别的用户 → 原样返回（避免跨用户数据泄露）
4. `style_prompt` 空 → 原样返回

**验证**（`test_ai_design_generate_with_agent_id` 用例）：
- 带 agent_id → mock provider 收到 `"[风格指南: Tone: ...]\n\n用户请求: 画一只猫"`
- 不带 agent_id → prompt 完全等于 `"画一只狗"`
- 无效 agent_id → 200 + prompt 原样（不阻塞生成）
- 跨用户 agent_id → 200 + prompt 原样（不泄露）

---

## 8. 前端页面

**位置**：`src/app/fusion/styles/page.tsx` 顶部，先展示 AgentStudioPanel，再展示既有平台风格列表。

**参考澜途 "AI AGENT STUDIO"**：
- 顶部徽标显示配额 `0/2` / `2/2`
- 列表卡片：名称 + 描述 + 风格摘要 + token 数 + 更新时间 + 样例数
- "查看 style_prompt" 展开详情
- "删除" 释放配额
- "新建" 展开表单：名称（必填，≤80）/ 描述（≤500）/ 样例内容（必填，多行）/ 设计原则（≤12000，选填）
- "训练并创建" 按钮：训练中显示 "训练中（调云端 LLM 抽取风格特征）…"
- 配额满时禁用新建 + 显示 "已达配额上限，可升级套餐解锁更多智能体"

**分离纯逻辑**（便于测试）：`src/lib/agent-studio.ts` 导出 `validateAgentForm / buildCreatePayload / quotaUI / summarizeStylePrompt / AGENT_LIMITS`，UI 直接消费。

---

## 9. 测试结果

### 后端（87/87 PASS）

```
$ cd prism_backend && python tests/test_m2_agents.py
...
M2 backend tests: 87 PASS / 0 FAIL (total 87)
```

**覆盖 11 组用例**：
| 用例组 | 断言数 | 覆盖 |
|---|---:|---|
| `test_agent_store_crud` | 12 | add / list / get / remove / replace；软删除后不可见；重复 remove |
| `test_quota_default_and_release` | 14 | 0/2 → 2/2 → 403 → 删除释放 → 再创建 |
| `test_quota_env_override` | 1 | `CLOUD_AGENT_QUOTA=5` 覆盖 |
| `test_parse_samples_variants` | 8 | str / list[str] / list[dict] / 长度截断 / 数量上限 / 空值过滤 |
| `test_validation_errors` | 4 | 缺 name / 缺 samples / 原则超长 / 名字超长 |
| `test_llm_failure_returns_502` | 2 | LLM 抛异常 → 502；未落库 |
| `test_create_and_detail_and_delete` | 15 | 创建响应字段完整；详情；列表；404；跨用户；删除；重复删除 404 |
| `test_apply_agent_style_injection` | 5 | 注入 / agent_id 空 / 未知 id / style_prompt 空 / 跨用户 |
| `test_ai_design_generate_with_agent_id` | 14 | **M1 端到端**：agent_id 透传 / 注入 / 无 agent_id 兼容 / 无效 id 不阻塞 / 跨用户不阻塞 |
| `test_find_style_prompt_helper` | 5 | 直接调用 helper |
| `test_anonymous_user_fallback` | 6 | query / Bearer / anonymous 三种解析；配额隔离 |

### 后端 M1 回归（74/74 PASS）

```
$ cd prism_backend && python tests/test_m1_ai_design.py
...
总计 74 断言，PASS=74，FAIL=0
ALL TESTS PASSED
```

确认 M1 现有 5 个 provider 路由、freeze→consume、rollback、错误处理完全不受影响。

### 前端（193/193 PASS）

```
$ cd prism_frontend && npx vitest run
 Test Files  10 passed (10)
      Tests  193 passed (193)
```

**新增 25 个 vitest 用例**（`src/lib/__tests__/agent-studio.test.ts`）：
- `AGENT_LIMITS` 常量（3）
- `EMPTY_FORM` 初始状态（1）
- `validateAgentForm` 必填（3）
- `validateAgentForm` 长度上限（4，含边界值）
- `buildCreatePayload` 各种输入形态（5）
- `quotaUI` 各状态（5，含 null/0-2/5-5/无升级链接）
- `summarizeStylePrompt` 空/短/长/默认 maxLen（4）

### TypeScript 类型检查

```
$ cd prism_frontend && npx tsc --noEmit
# 0 errors
```

---

## 10. 遗留问题 / 后续接入点

1. **M4 场景引导接入**（任务要求 §5）：
   - 现有 `src/components/wizard/scenarios.ts` 的 `AI_IMAGE_SCENARIO.steps[2]`（AI 生成步骤）尚未暴露 `agent_id` 选择器
   - 已埋好钩子：后端 `/ai-design/generate` 接受 `agent_id` 字段，前端只需在 wizard 步骤 2 增加一个下拉即可；建议 M4 收尾时补齐
   - M2 已把 M1 集成完全跑通（见测试 `test_ai_design_generate_with_agent_id`）

2. **真实 LLM 抽取质量**：
   - 当前 `_STYLE_EXTRACT_SYSTEM` prompt 是通用模板，未针对澜途样例做 few-shot
   - 生产环境建议：拉取 3-5 组澜途真实样例 → 加入 `_STYLE_EXTRACT_SYSTEM` → 提升抽取质量
   - 本地降级路径质量有限，仅保证 M1 端到端能跑通；生产依赖云端 LLM

3. **前端"训练并创建"耗时**：
   - LLM 抽取同步执行，前端要等几秒
   - 后续可改为后端异步 job：`POST` 返回 `task_id` → 前端轮询 `GET /agents/{id}` 查看状态
   - 当前实现符合澜途"提交即训练"的简单语义，先跑通再说

4. **user_id 解析**：
   - 当前 fallback 到 Bearer token 字符串本身，非真 JWT 校验
   - M1/M2 一致的这个策略便于联调；生产环境建议接入统一的 `get_current_user` 依赖（复用 `cloud_service/auth/router.py`）

5. **升级套餐接口**：
   - `upgrade_url` 目前硬编码为 `/billing/upgrade` 占位
   - 计费侧尚未提供套餐升级 API；接入后只需替换 `UPGRADE_URL_PLACEHOLDER`

6. **配额按订阅分档**（未来）：
   - 当前 `CLOUD_AGENT_QUOTA` 是全局 env
   - 未来接 M3 计费时，可按 sub.plan 分档（free=2 / pro=10 / enterprise=∞）
   - `_resolve_quota_limit(user_id=None, plan=None)` 扩展签名即可

---

## 附录：与澜途对照

| 澜途 | M2 |
|---|---|
| `GET /system/ai-agents` | `GET /api/v1/ai-design/agents` |
| `GET /system/ai-agents/quota` → `{limit:2, used:0, canCreate:true}` | `GET /api/v1/ai-design/agents/quota` → `{limit:2, used:0, canCreate:true, upgrade_url}` |
| `POST /system/ai-agents` body `{name, sample_contents, design_principles}` | `POST /api/v1/ai-design/agents` body `{name, description, sample_contents, design_principles}` |
| `DELETE /system/ai-agents/{id}` | `DELETE /api/v1/ai-design/agents/{id}` |
| 商品名（必填）+ 轮播图（必填）+ 详情图（选填）+ 设计原则（≤12000） | 名称（必填，≤80）+ 描述（选填，≤500）+ 样例内容（必填，多行文本）+ 设计原则（选填，≤12000） |
| 每用户 2 个 | 每用户 2 个（`CLOUD_AGENT_QUOTA` 可配置） |
| AI 自动生成标题/简介/设计规范 | AI 生成 `style_prompt`（含 Tone/Structure/Vocabulary/Visual/Layout 分维度） |
| AI AGENT STUDIO UI | 集成到 `/fusion/styles` 页面顶部（复用现有基座） |
| 生图时套用智能体 | `POST /ai-design/generate` 带 `agent_id` → 后端把 style_prompt 拼到 prompt 头部 |

**差异说明**：
- 澜途的样例是图片 URL，M2 支持多行文本（未来可扩 list[{type,url}]，后端 `_parse_samples` 已兼容 dict 格式）
- 澜途路径前缀是 `/system/ai-agents`，M2 统一到 `/ai-design/agents`（与 M1 同前缀）
- 澜途的"标题/简介/设计规范"是自动生成的三个字段，M2 合并为一个 `style_prompt`（更贴近 prompt engineering 的实际用法）
