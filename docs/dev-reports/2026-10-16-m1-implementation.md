# M1 · AI 生图后端实现报告

- **日期**：2026-10-18
- **模块**：`prism_backend/fusion_ai/` 扩展（复用现有 5 provider）
- **验证**：`python prism_backend/tests/test_m1_ai_design.py` → **74/74 PASS**（exit=0）

---

## 1. 设计原则（对齐任务要求）

| 约束 | 实现 |
|---|---|
| 不重写现有 5 个 provider | `image_generators.py` 完全不动，仅新增路由层 `model_key_registry.py` |
| 不重写 M3 积分 API | `points_client.py` 通过 HTTP 调云端，复用 `cloud_gateway` 的 token 机制 |
| 遵循 Prism-Fusion 现有约定 | FastAPI + `@router` 装饰器；错误统一走 `HTTPException`；provider 用 async |
| mock 测试，不真调商业 API | `MockProvider` + `MockCloud` 全内存注入 |
| mock 测试，不真扣积分 | `PointsClient(transport=...)` 注入内存版 `/cloud/points/*` |
| 如实声明能力，不伪造 | 现有 provider 全部只声明 `IMAGE_GENERATE`；不支持编辑/分析就不写 |
| 本次只做后端，不做前端 | 未动 `prism_frontend/` |

---

## 2. 文件清单

### 新增

| 文件 | 行数 | 职责 |
|---|---:|---|
| `prism_backend/fusion_ai/model_key_registry.py` | ~245 | 澜途 `/ai-design/capabilities` 格式的能力声明 + modelKey→provider 路由 |
| `prism_backend/fusion_ai/points_client.py` | ~340 | M3 积分 API HTTP 客户端（freeze/consume/rollback/pricing） |
| `prism_backend/fusion_ai/ai_design.py` | ~260 | `/ai-design/capabilities` + `/ai-design/generate` 路由 |
| `prism_backend/tests/test_m1_ai_design.py` | ~500 | 29 个用例 / 74 个断言 |

### 修改

| 文件 | 变更 |
|---|---|
| `prism_backend/fastapi_app/api/v1/router.py` | +2 行：import `ai_design_router` + `api_router.include_router(...)` |

### 未动（关键）

- `prism_backend/fusion_ai/image_generators.py` — 5 provider 完全没改
- `prism_backend/fusion_ai/router.py` — 老的 `/fusion/images/*` 端点保留不动
- `cloud_service/billing/` — M3 完全没改

---

## 3. modelKey 路由设计

### 3.1 能力清单（`GET /api/v1/ai-design/capabilities` 返回）

| modelKey | displayName | capabilities | supportedAspectRatios | maxOutputCount | maxReferenceImages |
|---|---|---|---|---:|---:|
| `nanobanana` | Nano Banana (Gemini 2.5 Flash Image) | `IMAGE_GENERATE` | `["1:1"]` | 1 | 0 |
| `dall-e-3` | DALL-E 3 | `IMAGE_GENERATE` | `["1:1","16:9","9:16"]` | 1 | 0 |
| `flux-pro` | Flux Pro | `IMAGE_GENERATE` | `["1:1","3:4","4:3","16:9","9:16"]` | 1 | 0 |
| `flux-2-pro` | Flux 2 Pro | `IMAGE_GENERATE` | `["1:1","3:4","4:3","16:9","9:16"]` | 1 | 0 |
| `wanx` | 通义万象 (Wanx2.1 Turbo) | `IMAGE_GENERATE` | `["3:2"]` | 1 | 0 |

**如实声明**：
- 所有 provider 都只声明 `IMAGE_GENERATE`（`image_generators.py` 里没实现 edit / product_analysis）
- `maxOutputCount=1`（现有 OpenAI 兼容调用硬编码 `n=1`）
- `maxReferenceImages=0`（现有 provider 不吃参考图）

**自定义模型动态注册**：`list_capabilities()` 每次调用都会把 `list_custom_models()` 里的模型追加进去，modelKey 用其 `id`；能力声明与 `flux-pro` 一致（保守）。

### 3.2 aspect_ratio → provider size 映射

| provider | 1:1 | 16:9 | 9:16 | 3:4 | 4:3 | 3:2 | CUSTOM |
|---|---|---|---|---|---|---|---|
| nano_banana | 1024x1024 | — | — | — | — | — | w×h |
| dalle3 | 1024x1024 | 1792x1024 | 1024x1792 | — | — | — | w×h |
| flux_pro / flux_2_pro | 1024x1024 | 1024x576 | 576x1024 | 768x1024 | 1024x768 | — | w×h |
| wanx | — | — | — | — | — | 1440*960 | — |

- 请求不支持的比例 → HTTP 400，不发起 provider 调用。
- CUSTOM + 显式 width/height 只在通用映射的 provider 上支持；DALL-E 3 官方不支持 CUSTOM。

---

## 4. API 端点清单

### 4.1 `GET /api/v1/ai-design/capabilities`

**响应体**（澜途格式）：
```json
{
  "models": [
    {
      "modelKey": "dall-e-3",
      "displayName": "DALL-E 3",
      "version": 1,
      "capabilities": ["IMAGE_GENERATE"],
      "supportedAspectRatios": ["1:1", "16:9", "9:16"],
      "maxOutputCount": 1,
      "maxReferenceImages": 0,
      "supportedInputMediaTypes": ["TEXT"]
    },
    ...
  ]
}
```

### 4.2 `POST /api/v1/ai-design/generate`

**请求体**：
```json
{
  "model_key": "dall-e-3",       // 必填
  "prompt": "a red apple",       // 必填
  "reference_images": [],        // 可选（当前所有 provider maxReferenceImages=0，传非空即 400）
  "aspect_ratio": "1:1",         // 可选，默认 "1:1"
  "count": 1,                    // 可选，默认 1
  "agent_id": "agent_abc"        // 可选，仅透传（M2 智能体归因）
}
```

**成功响应体**：
```json
{
  "task_id": "gen_1792304286911_d909e437",
  "model_key": "dall-e-3",
  "aspect_ratio": "1:1",
  "count": 1,
  "images": ["https://img.example/1.png"],
  "agent_id": "",
  "points": {
    "unit": 1.5,
    "total": 1.5,
    "freeze_tx_id": 42,
    "status": "consumed"
  }
}
```

**错误码**：
| HTTP | 触发条件 |
|---:|---|
| 400 | 缺 `model_key` / `prompt` / 违反 provider 约束（宽高比/参考图/count） |
| 402 | 云端返回 402 积分不足 |
| 404 | 未知 `modelKey` |
| 502 | provider 调用失败（积分已回滚） |
| 503 | 积分云端不可达（生成被取消，避免用户白嫖） |

---

## 5. 积分扣费集成

### 5.1 流程

```
请求 /ai-design/generate
   ↓
PointsClient.get_pricing()          ← GET  /cloud/points/pricing
   ↓ 读 aiImageGeneration=1.5（缓存 5 分钟，失败降级到本地常量）
   ↓
POST /cloud/points/freeze           ← 生成前预扣
   body: {amount: unit*count, use_function:"AI设计中心",
          ref_id: task_id, pricing_key:"aiImageGeneration"}
   响应: {freezeTxId: 42, ...}
   ↓
调 provider × count 次
   ↓
   ├─ 全部成功 → POST /cloud/points/consume  {freeze_tx_id: 42}
   └─ 任一失败 → POST /cloud/points/rollback {freeze_tx_id: 42}
```

### 5.2 定价

| 项 | 值 | 来源 |
|---|---|---|
| `aiImageGeneration` | 1.5 积分/张 | 澜途审计 + M3 `seed_pricing` 默认 |
| 云端不可达时兜底 | 1.5 | `DEFAULT_AI_IMAGE_POINTS` 常量 |
| `use_function` | "AI设计中心" | 与澜途"AI设计中心"记录类别对齐 |

### 5.3 错误语义

| 场景 | 客户端行为 | 路由响应 |
|---|---|---|
| freeze 402 积分不足 | 抛 `PointsInsufficient` | HTTP 402，未调 provider |
| freeze 5xx / 网络 | 抛 `PointsCloudError` | HTTP 503，未调 provider |
| freeze 200 但无 `freezeTxId` | 路由层拒绝 | HTTP 502 |
| consume 失败（生成已成功） | 记录日志，不抛 | 响应 200 + `points.status="consumed_consume_pending"` |
| rollback 失败（生成已失败） | 记录日志，不抛 | 响应 502（provider 错误），不再报积分错 |

设计意图：**用户已经拿到图，积分扣费失败不应让响应变 500**；但**用户没拿到图，必须先回滚积分再报错**（避免白嫖）。

---

## 6. 测试结果

**运行方式**：
```powershell
cd prism_backend
& '.venv\Scripts\python.exe' '.\tests\test_m1_ai_design.py'
```

**结果**：`总计 74 断言，PASS=74，FAIL=0  → ALL TESTS PASSED  (exit=0)`

### 覆盖矩阵（29 个用例）

| 类别 | 用例数 | 覆盖点 |
|---|---:|---|
| modelKey 路由层 | 9 | 5 个 modelKey 全部能路由；未知 key 返回 (None,{})；能力如实声明；`resolve_size` 6 组映射；3 组约束拒绝（宽高比/参考图/未实现能力） |
| capabilities 端点 | 2 | 返回 5 个内置模型；澜途 §3.1 字段齐全 |
| 成功路径（freeze→consume） | 3 | 单张 / count=3 累加 4.5 积分 / ref_id=task_id |
| 失败路径（freeze→rollback） | 2 | provider 全部失败 / 部分失败 |
| 错误处理 | 8 | 404 未知 key / 402 积分不足 / 503 云端不可达 / 400 宽高比 / 400 参考图 / 400 缺 model_key / 400 缺 prompt / agent_id 透传 |
| points_client 单元 | 5 | pricing 缓存 / freeze 402 抛异常 / consume 失败 swallow / rollback 失败 swallow / 云端不可达降级 |

### 断言示例

```
[PASS] POST /generate 成功 → 200
[PASS] points.unit == 1.5
[PASS] M3 收到 pricing GET + freeze POST + consume POST
[PASS] count=3 → 返回 3 张图，total 积分 4.5
[PASS] freeze 金额 = 4.5，pricing_key=aiImageGeneration，use_function=AI设计中心
[PASS] provider 失败 → 502，M3 rollback 1 次，consume 0 次
[PASS] 部分失败 → 502，M3 rollback 1 次，consume 0 次
[PASS] 未知 modelKey → 404，未调 M3，未调 provider
[PASS] 积分不足 → 402，未调 provider
[PASS] 云端不可达 → 503
[PASS] wanx 请求 16:9 → 400，未调 M3
[PASS] 传参考图 → 400
[PASS] get_pricing 缓存命中（第二次不发 HTTP）
[PASS] consume 失败不抛，返回 ok=False
[PASS] 云端不可达 → points_for_ai_image 降级到 1.5
```

### 回归

- `python -c "from fastapi_app.api.v1.router import api_router"`：新路由 `/ai-design/capabilities` + `/ai-design/generate` 已挂载到主 api_router，无副作用。
- 未修改 `image_generators.py` / `points_endpoints.py` 等既有文件，不影响 M3 已有 51 个测试。

---

## 7. 遗留问题（本次不做）

| 项 | 说明 | 后续处理 |
|---|---|---|
| 前端 AI 生图页面 | 本次只做后端，`/fusion/image-studio` 页面未做 | 后续单独开任务 |
| IMAGE_EDIT / PRODUCT_ANALYSIS | 现有 provider 都只支持 IMAGE_GENERATE；澜途的 gpt-image-1 有 IMAGE_EDIT，但代码里没实现 | 需要在 `image_generators.py` 加 `_openai_compatible_edit` / `_product_analysis`，再回来扩 capabilities |
| ComfyUI provider | 复刻方案 M1 提到 `comfyui_client.py` + `comfyui:*` provider，本次没做（GPU 硬件未就绪） | 后续单独开任务 |
| 生成记录落库 | 复刻方案 M1 提到 `image_generations` 表 + 前端可查记录，本次只返回结果不落库 | 后续可加，但 M3 已有 `credit_ledger.ref_id` 反查生成任务 |
| agent_id 校验 | 目前只透传不校验（M2 智能体还没实现） | M2 实现时接 `style_profiles` 表校验 |
| `consume_consume_pending` 状态 | 生成成功但 consume 失败时，用户已拿到图但云端仍显示冻结中；需后台任务重试 | 建议加异步重试任务；本次仅记日志 |
| CloudGateway token | `points_client._default_token_provider` 从 `get_gateway().ensure_access_token()` 拿；本地后端服务进程内跑时需要用户先登录 | 生产部署时通过 sidecar 或反向代理注入；本次没做 |
| 幂等 | 前端重复提交相同 task_id 会重新 freeze；M3 端点本身没有幂等（用 `ref_id` 记录但不查重） | 前端应做防抖；后端可后续加 Redis lock |

---

## 8. 相关文件

- `prism_backend/fusion_ai/model_key_registry.py` — 新增（澜途 capabilities 声明 + modelKey 路由）
- `prism_backend/fusion_ai/points_client.py` — 新增（M3 积分 HTTP 客户端）
- `prism_backend/fusion_ai/ai_design.py` — 新增（`/ai-design/*` 路由）
- `prism_backend/fastapi_app/api/v1/router.py` — 修改（+2 行挂载新路由）
- `prism_backend/tests/test_m1_ai_design.py` — 新增（29 用例 / 74 断言）
- `docs/dev-reports/2026-10-16-m1-implementation.md` — 本文档

**参考**：
- `docs/dev-reports/2026-10-16-module-replication-plan.md` §3.1（M1 复刻方案）
- `docs/dev-reports/2026-10-16-lantyou-api-audit.md` §3（澜途 capabilities）
- `docs/dev-reports/2026-10-16-m3-implementation.md`（M3 积分 API）

---

*完成于 2026-10-18*
