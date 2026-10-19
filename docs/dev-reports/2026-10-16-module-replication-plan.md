# 5 模块复刻实施方案（澜途 AI 对标 → Prism-Fusion）

- 报告日期：2026-10-16
- 目标读者：负责逐模块复刻的子代理（能按文件路径直接开工）
- 前置阅读：
  1. `docs/dev-reports/2026-10-16-github-reference-audit.md`（5 模块开源选型）
  2. `docs/dev-reports/2026-10-16-rea-capability-assessment.md`（REA 逆向能力，本方案**不引用**）
  3. `docs/dev-reports/2026-10-16-open-core-strategy.md`（Open Core 商业化分层）

---

## 1. 执行摘要

澜途 AI 的 5 大业务模块（AI 生图 / 智能体风格训练 / 积分计费 / 工作流引导 / 图片编辑器），在 Prism-Fusion 的现有基础上**都能以 20-30% 的工作量复刻**，因为：
- **M1 文生图**：`prism_backend/fusion_ai/image_generators.py` 已有 NanoBanana/DALL-E/Flux/通义 5 个 provider + 自定义模型注册，只缺 ComfyUI 后端和前端独立页；
- **M2 风格训练**：`fusion_ai/platform_styles.py` 已有 7 平台风格模板 + 前端 CRUD（`src/app/fusion/styles/page.tsx`），只缺"上传样稿 → LLM 抽 Profile"这一环；
- **M3 积分计费**：`cloud_service/billing/` + `cloud_service/payment/` 已完整（订阅、usage、订单、回调、退款、对账），只缺"按用量扣积分"的 metering 表；
- **M4 工作流**：Prism-Fusion 已有 `ai-quick-command-palette` + `campaigns` 编排，加一个前端 Wizard 即可；
- **M5 图片编辑器**：完全新增，纯前端，1 天可交付。

**技术栈与 Open Core 强对齐**：客户端开源、云端核心（prompt/计费）不动，ComfyUI 作为**独立进程 + HTTP 调用**接入以规避 GPL 传染。

**总工作量估算：20.5 人日**（乐观 17-18 人日，保守 22-24 人日；不含 ComfyUI 部署 GPU 采购）。

**开发顺序**：M5 → M3 → M1 → M2（可与 M1 并行）→ M4。

---

## 2. Prism-Fusion 现状摸底

### 2.1 目录结构（关键）

```
Prism-Fusion/
├── prism_frontend/                    # Next.js 16 App Router
│   ├── package.json                   # 已含 shadcn/@radix/react-query/langchain/openai-ai-sdk
│   └── src/app/
│       ├── fusion/                    # ★ AI Fusion 模块（M1/M2 天然落点）
│       │   ├── page.tsx
│       │   ├── model-market/page.tsx  # ★ 模型广场，可扩为 M1 生图入口
│       │   ├── styles/page.tsx        # ★ 平台风格，M2 天然基座
│       │   ├── providers/page.tsx
│       │   ├── config/page.tsx
│       │   ├── analytics/page.tsx
│       │   └── moderation/page.tsx
│       ├── campaigns/page.tsx         # ★ M4 编排入口
│       ├── publish/                   # 矩阵发布
│       ├── tasks/                     # 任务队列
│       ├── video-pipeline/            # Easel 视频流水线
│       ├── easel-*/                   # Easel 工作台/inbox/content
│       ├── ai-agent/                  # Hermes Agent 聊天
│       ├── hermes-chat/page.tsx
│       ├── tools/page.tsx
│       ├── settings/                  # 含 cloud-subscription-card / tikhub-api-key-card
│       ├── cms/page.tsx
│       └── login/page.tsx
│
├── prism_backend/                     # FastAPI
│   ├── fastapi_app/
│   │   ├── main.py                    # FastAPI 入口，CORS+/uploads 静态
│   │   ├── core/                      # settings/logger/paths
│   │   ├── api/v1/router.py           # ★ 40+ 子路由集中注册
│   │   ├── api/v1/{accounts,campaigns,ai,agent,ai_prompts,publish,
│   │   │            tasks,material,publish,video_pipeline,workshop,
│   │   │            content_library,insight,review,dedup,...}/router.py
│   │   └── db/                        # sqlalchemy_engine/session/schema/sa_models
│   ├── fusion_ai/                     # ★ Fusion 统一 AI 模块
│   │   ├── router.py                  # 前缀 /api/v1/fusion/*（providers,styles,images,hot-topics,moderation,model-market,skills,cognition,analytics,config）
│   │   ├── image_generators.py        # ★ M1 基座：NanoBanana/DALL-E/Flux/通义/自定义
│   │   ├── platform_styles.py         # ★ M2 基座：7 平台风格模板 + 覆盖
│   │   ├── prompts_basic.py           # 离线基础 prompt
│   │   ├── provider_registry.py
│   │   ├── prompt_router.py
│   │   ├── model_market.py
│   │   ├── skill_workshop.py
│   │   ├── hot_topics.py
│   │   ├── content_moderator.py
│   │   ├── nl_query.py
│   │   ├── cognition.py
│   │   ├── config_center.py
│   │   └── cloud_gateway.py           # 云端 LLM 代理客户端
│   ├── myUtils/                       # 平台自动化
│   ├── ai_service/                    # LLM 服务层
│   ├── ai_service/llm.py              # ★ M2 风格训练可复用
│   └── requirements.txt
│
├── cloud_service/                     # FastAPI 云端（订阅+计费+支付+LLM 代理）
│   ├── main.py                        # 前缀 /cloud/*
│   ├── auth/                          # User/JWT (C12)
│   ├── billing/                       # ★ Subscription + Usage (C13)
│   │   ├── router.py                  # GET /cloud/subscription, POST /cloud/usage/consume, POST /cloud/license/verify, POST /cloud/subscription/activate
│   │   ├── models.py                  # Subscription(plan,quota,expire_at) + Usage(period,used)
│   │   └── schemas.py
│   ├── llm_proxy/                     # ★ Prompt 表 + /cloud/llm/chat (C14)
│   │   ├── router.py                  # POST /cloud/llm/chat（prompt_name 触发，不透出模板）
│   │   ├── models.py                  # Prompt(name,tier,template,variables_json,version,is_active)
│   │   ├── prompts.py                 # SEED prompt 常量
│   │   └── llm_client.py
│   ├── payment/                       # ★ Order + 支付回调 (C19)
│   │   ├── router.py                  # POST /cloud/payment/create_order | callback/{channel} | order/{order_no}
│   │   ├── models.py                  # Order(no,user_id,channel,amount,status,expire_at)
│   │   ├── alipay.py, wechat.py       # 支付网关 adapter
│   │   ├── adapter.py, schemas.py
│   │   ├── task_guard.py, scheduler.py, reconciliation.py
│   └── db.py                          # init_db + get_db
│
├── desktop-electron/                  # Electron 外壳
├── tools/persona-studio/              # Persona Studio（浏览器指纹）
├── scripts/                           # 启动脚本
├── env.example                        # 全局配置模板
└── .env                               # 实际配置
```

### 2.2 已有关键能力盘点（与 5 模块的对应关系）

| 5 模块 | Prism-Fusion 已有对应能力 | 缺失 |
|---|---|---|
| M1 文生图 | `fusion_ai/image_generators.py`（5 provider + 自定义）+ `fusion/model-market` 前端 | ComfyUI GPU 后端；独立的前端"生图工作台"页 |
| M2 风格训练 | `fusion_ai/platform_styles.py`（7 平台）+ `/fusion/styles` CRUD 页 + `ai_service/llm.py` | 样稿上传 → LLM 抽 Profile → 存 DB 的 pipeline |
| M3 积分计费 | `cloud_service/billing/`（subscription + usage）+ `cloud_service/payment/`（order + 支付宝/微信 + 退款） | 按**次数/用量**扣积分的 ledger；目前只有月度 quota |
| M4 工作流 | `campaigns/`（活动编排）+ `ai-quick-command-palette` + `tasks/` | 面向"场景"的 3-4 步 Wizard UI |
| M5 图片编辑器 | 无 | 完全新增（纯前端） |

### 2.3 前端依赖已就绪

`prism_frontend/package.json` 已包含：
- **UI 基座**：`@radix-ui/*` 全套、`shadcn@4.19.0`、`tailwind-merge`、`cva`、`framer-motion`
- **数据层**：`@tanstack/react-query`、`@tanstack/react-table`
- **表单/校验**：`zod`、`input-otp`
- **图标**：`lucide-react`、`@tabler/icons-react`、`@radix-ui/react-icons`
- **AI SDK**：`ai@5.0.104`、`@ai-sdk/openai`、`@assistant-ui/react*`
- **LangChain**：`@langchain/core`、`@langchain/openai`、`@langchain/langgraph`

**结论**：不需要引入 antd / NaiveUI；不需要新装状态管理（`react-query` + `useReducer` 够用）。

### 2.4 前端已有可复用组件

- `src/components/video-edit-sheet.tsx`（视频剪辑 sheet，M5 可参考其交互）
- `src/components/material-editor-sheet.tsx`（素材编辑器 sheet，M5 直接复用模式）
- `src/components/ai-quick-command-palette.tsx`（M4 Wizard 可复用其交互）
- `src/components/ai-provider-setup-dialog.tsx`、`ai-model-selector.tsx`
- `src/components/settings/cloud-subscription-card.tsx`（M3 用量/订阅展示）
- `src/components/layout/sidebar-new.tsx`（导航要加新入口）
- `src/lib/env.ts`（`API_ENDPOINTS.base`，全部 API 走这个）

---

## 3. 五模块详细方案

### 3.1 模块 M1：AI 图片设计（文生图）

#### 3.1.1 集成位置

| 层 | 位置 | 动作 |
|---|---|---|
| 前端入口 | `prism_frontend/src/app/fusion/image-studio/page.tsx`（新增） | 独立"AI 生图工作台"页 |
| 前端组件 | `prism_frontend/src/components/image-studio/`（新增）<br>├─ `prompt-bar.tsx`<br>├─ `model-picker.tsx`<br>├─ `result-gallery.tsx`<br>├─ `image-preview.tsx`<br>├─ `history-list.tsx`<br>└─ `comfyui-config.tsx` | 用 shadcn 拼装 |
| 导航 | `prism_frontend/src/components/layout/sidebar-new.tsx` 加"Fusion → AI 生图"入口 | 编辑 |
| 后端 router | `prism_backend/fusion_ai/router.py` 现有 `/api/v1/fusion/images` 扩展 | 追加 `POST /api/v1/fusion/images/comfyui` 走 ComfyUI；已有 `/images/generate` 走 API provider |
| 后端核心 | `prism_backend/fusion_ai/image_generators.py`（已有 5 provider）新增 `comfyui` 分支 | 编辑 |
| ComfyUI 客户端 | `prism_backend/fusion_ai/comfyui_client.py`（新增） | HTTP 封装 ComfyUI API |
| DB | `prism_backend/fastapi_app/db/sa_models.py` 追加 `image_generations` 表 | 新增 |
| 配置 | `.env` 加 `COMFYUI_BASE_URL` / `COMFYUI_ENABLED` / `COMFYUI_TIMEOUT` | 编辑 `env.example` |

**新表 `image_generations`**：
```sql
image_generations (
  id INTEGER PK AUTOINCREMENT,
  user_id INTEGER,
  provider VARCHAR(32),           -- nano_banana | dalle3 | flux_pro | flux_2 | wanx | comfyui | custom:<id>
  model VARCHAR(64),
  prompt TEXT,
  negative_prompt TEXT,
  size VARCHAR(16),               -- 512x512 / 1024x1024 / 1280x720
  seed INTEGER,
  params_json TEXT,               -- steps/cfg/guidance/sampler/scheduler 等
  image_path TEXT,                -- 落盘相对路径
  thumbnail_url TEXT,
  provider_cost_cent INTEGER,     -- 供应商成本，用于积分换算
  duration_ms INTEGER,
  status VARCHAR(16),             -- pending | running | done | failed
  error TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

#### 3.1.2 技术选型确认

**采纳 GitHub 调研方案，但做一处调整**：
- 原方案：ComfyUI（GPU）+ LiteLLM 统一路由
- 调整：**ComfyUI（GPU）+ 现有 `fusion_ai/image_generators.py` 作为统一路由层**
  - 理由：Prism-Fusion 已有 5 个 provider 的统一注册表 + `generate_single_model(model_def, prompt, size)` 接口，直接扩展即可，**不需要引入 LiteLLM**（LiteLLM 定位是 LLM 类模型，图片 provider 覆盖不足）

**ComfyUI 集成方式**：
- 部署为**独立 Docker 容器**（GPU），暴露 `http://<gpu-host>:8188`
- `comfyui_client.py` 通过 HTTP `POST /prompt` + 轮询 `GET /history/{id}` + `GET /view` 拉取结果图
- License 隔离：ComfyUI 是**独立进程 + HTTP**，prism_backend 不做源码 import，法务上通常视为"独立服务"不触发 GPL 传染
- **强约束**：不得 `pip install comfyui` 到 prism_backend 的 venv

**License 合规**：
- ComfyUI：GPL-3.0 → 独立服务，prism_backend 不 import 其源码，不打包分发 → 通说不传染
- LiteLLM：MIT → 本方案不采用，风险 0
- 上游 provider（DALL-E/Flux/通义）：官方 API，各自 ToS，与本方案无冲突

#### 3.1.3 关键 API 契约

**新增/扩展的后端接口**：

```
POST /api/v1/fusion/images/generate
  body: {
    prompt: string,
    negative_prompt?: string,
    model_id: string,          -- "nano_banana" | "dalle3" | "flux_pro" | "flux_2_pro" | "wanx" | "comfyui:flux_dev"
    size: string,
    count: number,             -- 1-4，一次生几张
    params?: { steps, cfg, seed, sampler, scheduler }  -- ComfyUI 专用
  }
  → { id, status: "running", poll_url: "/api/v1/fusion/images/{id}" }

GET  /api/v1/fusion/images/{id}   -- 查询状态，返回 image_path/url

GET  /api/v1/fusion/images/models  -- 列出可用模型（含 ComfyUI 自定义 workflow）

GET  /api/v1/fusion/images/history?user_id=&limit=20  -- 生成历史

POST /api/v1/fusion/images/upscale  -- 后期加分辨率（可选）
```

**前端交互**（`/fusion/image-studio` 页）：
1. 左侧：Prompt 输入（含负面）+ 模型选择 + 尺寸 + 参数展开
2. 中间：结果网格（每张支持下载/加滤镜/送入编辑器）
3. 右侧：历史面板（`history-list.tsx`，从 `image_generations` 表读）
4. 底部：ComfyUI 配置（仅管理员可见）

#### 3.1.4 依赖关系

- 依赖 M3 的 credit 扣减（生成一张扣多少积分）
- 被 M5 消费（生成的图送入编辑器精修）

#### 3.1.5 工作量估算

| 子任务 | 人日 |
|---|---|
| ComfyUI Docker 部署脚本 + systemd 单元 | 0.5 |
| `comfyui_client.py` + `image_generators.py` 扩展 | 1.0 |
| `image_generations` 表 + 迁移脚本 | 0.5 |
| 前端 `/fusion/image-studio` 页 + 6 个组件 | 2.0 |
| 积分扣减对接 M3 | 0.5 |
| 单元测试（comfyui_client mock + 生成流程） | 0.5 |
| **小计** | **5.0** |

#### 3.1.6 风险与注意事项

| 风险 | 严重度 | 缓解 |
|---|---|---|
| ComfyUI GPL 传染 | 中 | 独立进程 + HTTP；不在 venv 中 pip 安装；不 fork ComfyUI 源码 |
| GPU 资源 | 高（成本） | 生产需 NVIDIA GPU（≥ 8GB VRAM，推荐 4090）；或用 RunPod/Replicate 托管；`.env` 里 `COMFYUI_ENABLED=false` 时前端隐藏该模型 |
| 生成耗时 30-120s | 中 | 用 SSE 或 WebSocket 推送进度；前端用轮询 + 骨架屏 |
| ComfyUI workflow 定制 | 中 | 首版提供 3 个官方 workflow（SDXL base、Flux dev、ControlNet），后续开放自定义 |
| 上游 API 稳定性 | 低 | 已有多 provider 回落机制（`generate_multi_model`） |

---

### 3.2 模块 M2：智能体风格训练（Style Profile）

#### 3.2.1 集成位置

| 层 | 位置 | 动作 |
|---|---|---|
| 前端入口 | `prism_frontend/src/app/fusion/style-trainer/page.tsx`（新增） | 独立"智能体风格训练"页 |
| 前端组件 | `prism_frontend/src/components/style-trainer/`<br>├─ `sample-uploader.tsx`（多份样稿上传/粘贴）<br>├─ `profile-editor.tsx`（tone/audience/voice/… 字段）<br>├─ `profile-preview.tsx`（AI 用该 profile 生成示例）<br>├─ `sample-compare.tsx`（原稿 vs 生成对比）<br>└─ `profile-picker.tsx`（复用按钮：在其他 AI 调用中选风格） | 新建 |
| 导航 | `sidebar-new.tsx` 加"Fusion → 风格训练"入口 | 编辑 |
| 后端 | `prism_backend/fusion_ai/style_trainer.py`（新增） | 主逻辑 |
| 后端 router | `prism_backend/fusion_ai/router.py` 追加 `/api/v1/fusion/style-trainer/*` | 编辑 |
| LLM 复用 | `prism_backend/ai_service/llm.py`（已有 Hermes Agent LLM 客户端） | 复用 |
| DB | `prism_backend/fastapi_app/db/sa_models.py` 追加 `style_profiles` 表 | 新增 |
| Prompt 层 | `cloud_service/llm_proxy/prompts.py` 追加 SEED prompt `style_profile_extract` + `style_apply` | 编辑（云端） |

**新表 `style_profiles`**：
```sql
style_profiles (
  id INTEGER PK AUTOINCREMENT,
  user_id INTEGER,
  name VARCHAR(64),                -- 用户自定义名，如"品牌小红书口吻"
  tone VARCHAR(64),                -- "专业理性" / "轻松活泼" / "幽默段子"
  audience TEXT,                   -- 目标读者描述
  brand_voice TEXT,                -- 5-10 句核心特征描述（对齐 prompt-master 结构）
  examples_json TEXT,              -- 训练用的原样稿（3-5 篇，仅元数据 + 摘要）
  negative_examples_json TEXT,     -- 反例（2 篇）
  platform_specific_json TEXT,     -- {"zhihu": "...", "xiaohongshu": "..."}
  sentence_length_dist JSON,       -- 抽样统计：[p25, p50, p75]
  emoji_density FLOAT,             -- 每 100 字 emoji 数
  structure_hint TEXT,             -- "问题→分析→观点→总结"
  template_hint TEXT,              -- 生成的 few-shot system prompt 片段
  status VARCHAR(16) DEFAULT 'active',  -- active | draft | archived
  version INTEGER DEFAULT 1,
  created_at DATETIME,
  updated_at DATETIME
)
```

#### 3.2.2 技术选型确认

- **无成品 OSS，自建 pipeline**（GitHub 调研结论）
- **参考 prompt-master 的 Brand Voice 字段结构**（`TONE/AUDIENCE/BRAND VOICE/EXAMPLES/NEGATIVE`），字段已在上表体现
- **评估**：可选用 `promptfoo`（MIT）做"生成结果 vs 原样稿风格相似度"打分，首版先**不做**自动化评估，靠用户手动反馈（"更像了 / 不像了"）
- **LLM 选型**：走 Hermes Agent 已有的 `ai_service/llm.py`，用 GPT-4o / Claude 3.5 / DeepSeek-V3 都可；抽 Profile 建议 temperature=0.3，输出严格 JSON（`zod` schema 校验）

**Pipeline 详设**：
```
用户上传 3-5 篇样稿（.txt / .md / 粘贴）
  ↓
后端调用 cloud /cloud/llm/chat（prompt_name="style_profile_extract"）
  ↓
返回结构化 JSON：
{
  "tone": "...",
  "audience": "...",
  "brand_voice": "长描述...",
  "sentence_length_stats": {"p25": 12, "p50": 18, "p75": 26},
  "emoji_density_per_100": 0.7,
  "structure_hint": "痛点 → 方案 → 效果",
  "examples": [{"summary": "...", "opening": "...", "tone_marker": "..."}],
  "negative_examples": ["...", "..."]
}
  ↓
后端本地统计（emoji 密度、句长分布）与 LLM 结果合并
  ↓
写入 style_profiles 表
  ↓
前端展示 Profile 卡片 + 提供"试用生成"按钮
  ↓
试用：走 cloud /cloud/llm/chat（prompt_name="style_apply"，params: {profile_id, task, content}）
```

**云端 prompt 设计**（`cloud_service/llm_proxy/prompts.py` 追加 SEED）：

- `style_profile_extract`：
  ```
  分析以下 {count} 篇样稿，输出严格的 JSON（不带 markdown fence）：
  ...（JSON schema）
  
  ## 样稿
  {samples_concat}
  ```
- `style_apply`：
  ```
  你是一个严格模仿以下品牌风格的内容生成器。
  Brand Voice: {brand_voice}
  Tone: {tone}
  Audience: {audience}
  参考句长分布: {p25}-{p50}-{p75}
  Emoji 密度: {emoji_density}/100字
  
  Few-shot 示例:
  {few_shot_examples}
  
  反例（不要这样写）:
  {negative_examples}
  
  任务：{task}
  输入：{input}
  ```

#### 3.2.3 前端交互设计

`/fusion/style-trainer` 页布局：
- 顶部：Profile 列表（横向卡片，可切换/编辑/删除/试生成）
- 主区（左）：Profile 编辑器
  - 训练样稿区：`sample-uploader`（3-5 份样稿，拖拽或粘贴，支持 .md/.txt）
  - 分析按钮 → loading → 展示 LLM 提取的结构化字段
  - 手动微调区：`profile-editor`（tone/audience/brand_voice/…）
- 主区（右）：`sample-compare`
  - 上：原样稿原文
  - 下：AI 用此 Profile 生成的示例（点"试生成"按钮触发）
  - 用户可打分（👍/👎），反馈写入 `style_profile_feedback` 表（可选，简化版跳过）

#### 3.2.4 依赖关系

- 强依赖 cloud `/cloud/llm/chat`（云端 prompt）
- 被 M1/M4 消费（生图/工作流可指定 style_profile_id）
- 与已有 `platform_styles`（7 平台通用风格）**并存不冲突**：
  - `platform_styles` 是"平台差异化"（如"小红书风格"）
  - `style_profiles` 是"品牌/智能体风格"（如"某某品牌口吻"）
  - 二者可叠加（生成时同时应用）

#### 3.2.5 工作量估算

| 子任务 | 人日 |
|---|---|
| 云端 prompts 追加（extract + apply）+ 测试 | 0.5 |
| `style_trainer.py`（LLM 调用 + 本地统计 + DB CRUD） | 1.0 |
| `style_profiles` 表 + 迁移 | 0.5 |
| 前端 `/fusion/style-trainer` 页 + 5 个组件 | 2.5 |
| 云端/本地统计合并的边界测试 | 0.5 |
| LLM 输出 JSON schema 校验 + 失败重试 | 0.5 |
| **小计** | **5.5** |

#### 3.2.6 风险与注意事项

| 风险 | 严重度 | 缓解 |
|---|---|---|
| 3-5 篇样稿统计量偏少，LLM 主观 | 中 | UI 提供手动微调；不追求 100% 准确 |
| LLM 输出 JSON 格式漂移 | 中 | `zod` schema 校验 + 重试 2 次 + 降级到空 profile |
| 用户"感觉没抓到" | 高 | 强反馈 UI（"更像了 / 不像了"）；允许手动修改字段 |
| 云端 prompt 泄露风险 | 低 | prompt 只存云端，客户端只见 prompt_name（已有机制） |
| 与 `platform_styles` 冲突 | 低 | 明确文档：platform 是渠道差异，profile 是品牌差异，两者独立字段 |

---

### 3.3 模块 M3：积分计费（Credit Ledger）

#### 3.3.1 集成位置

**判断**：Prism-Fusion 已有 `cloud_service/billing/` 完整实现（Subscription quota + Usage + 支付回调），**M3 的复刻不是"从零建计费系统"，而是"给现有月度 quota 计费增加 usage-level ledger"**。

| 层 | 位置 | 动作 |
|---|---|---|
| 云端 router | `cloud_service/billing/router.py` 追加 | 编辑 |
| 云端 models | `cloud_service/billing/models.py` 追加 `CreditLedger` + `CreditPricing` | 编辑 |
| 云端 schemas | `cloud_service/billing/schemas.py` 追加 | 编辑 |
| 用量上报 | `prism_backend/fusion_ai/image_generators.py` 生成完调 `cloud_usage_report()` | 编辑 |
| 前端用量面板 | `prism_frontend/src/components/settings/cloud-subscription-card.tsx` 扩展 | 编辑 |
| 前端"充值"入口 | 复用已有 `/cloud/payment/create_order` + 加"充积分"选项 | 编辑 |

**新表（追加到 `cloud_service/billing/models.py`）**：

```python
class CreditLedger(Base):
    """用户积分流水表。所有积分变动都落这里，包括充值/消耗/退款。"""
    __tablename__ = "credit_ledger"
    id: Mapped[int]  # PK
    user_id: Mapped[int]  # FK users.id
    delta: Mapped[int]  # +充值 -消耗 -退款 -管理员调整
    balance_after: Mapped[int]  # 变动后余额
    action: Mapped[str]  # "top_up" | "consume_image" | "consume_llm" | "consume_video" | "refund" | "admin_adjust" | "monthly_reset"
    reference_type: Mapped[str]  # "order_no" | "generation_id" | "prompt_call_id"
    reference_id: Mapped[str]
    unit_price_cent: Mapped[int]  # 单价（0.01 元）
    note: Mapped[str]
    created_at: Mapped[datetime]

class CreditBalance(Base):
    """用户积分余额（冗余，便于快速查询；权威数据来自 ledger 累加）。"""
    __tablename__ = "credit_balance"
    user_id: Mapped[int]  # PK + FK
    balance: Mapped[int]  # 当前余额（单位：0.01 元，即 cent）
    updated_at: Mapped[datetime]

class CreditPricing(Base):
    """积分单价表（管理员可配置）。"""
    __tablename__ = "credit_pricing"
    action: Mapped[str]  # PK，如 "consume_image:512"、"consume_llm:1000_tokens"
    unit_price_cent: Mapped[int]
    description: Mapped[str]
    is_active: Mapped[bool]
    updated_at: Mapped[datetime]
```

**关键设计原则**：
1. **保留现有 `Subscription`（月度 quota）**：不做迁移，两者并存
2. **新加"积分"维度**：`Usage.used < quota` 时走 quota 逻辑；`quota == -1`（无限）时走积分扣减
3. **免费用户默认 0 积分**：注册时 `CreditBalance.balance = 2000`（20 元等值 = 200 张图）
4. **Pro 用户**：quota=-1（无限），但**仍可用积分**（可选，用于超频调用高价模型）

#### 3.3.2 技术选型确认

- **不用 OpenMeter / Flexprice / Lago**（GitHub 调研的"自建"方案）
- **理由**：
  1. 已有 `cloud_service/billing/` 完整框架，扩展 200 行代码即可
  2. OpenMeter 需 ClickHouse 独立部署（+2 天运维）
  3. Flexprice/Lago 是 AGPL，商业化风险
- **实现方式**：MariaDB 事务 + Redis 分布式锁（现有 `payment/task_guard.py` 已有锁基础设施）

#### 3.3.3 关键 API 契约

**云端新增/扩展**：

```
GET  /cloud/credit/balance            → { balance: int }
GET  /cloud/credit/ledger?limit=50    → { items: [ {delta, balance_after, action, note, created_at} ] }
GET  /cloud/credit/pricing            → { items: [{action, unit_price_cent, description}] }
POST /cloud/credit/consume            → { delta: int, balance_after: int }  body: { action, reference_type, reference_id, quantity? }
POST /cloud/credit/top-up             → 走 /cloud/payment/create_order + channel="credit"（复用）
```

**扣费语义**：
- `consume` 是**原子操作**：`BEGIN; SELECT FOR UPDATE balance; balance -= delta; INSERT ledger; COMMIT`
- 余额不足返回 `402 insufficient_credit`
- Redis 锁 key：`credit:lock:{user_id}` TTL=10s

**客户端上报点**（`prism_backend`）：
```python
# 在 image_generators.generate_single_model 成功回调中：
async def _report_usage_async(user_id, model_id, size, duration_ms):
    action = f"consume_image:{size}"
    ref_id = generation_id
    await cloud_client.post("/cloud/credit/consume", {
        "action": action,
        "reference_type": "generation_id",
        "reference_id": ref_id,
    })
```

#### 3.3.4 前端交互

`/settings` 页 `cloud-subscription-card.tsx` 扩展：
- 顶部：当前积分余额大字显示（`¥{balance/100:.2f}` 或 `{balance} 积分`）
- 中间：使用趋势图（`recharts` 已有）+ 近期流水表格
- 右侧：`充值` 按钮 → 弹出套餐选择（¥9.9 = 1000 积分 / ¥99 = 12000 积分 / ¥299 = 40000 积分）
- 底部：单价说明表（1 张图 = 20 积分、1000 tokens = 5 积分、1 分钟视频 = 100 积分）

#### 3.3.5 依赖关系

- 被 M1、M2、M4 消费（每次 AI 调用都要扣积分）
- 依赖已有 `cloud_service/payment/`（充值走支付订单）

#### 3.3.6 工作量估算

| 子任务 | 人日 |
|---|---|
| 云端 3 张新表 + 迁移 + seed | 0.5 |
| 云端 credit router（balance/ledger/consume） | 1.0 |
| Redis 锁 + 事务原子性测试 | 0.5 |
| `prism_backend` 用量上报 hook（3 处：image/llm/video） | 0.5 |
| 前端 subscription-card 扩展 + 充值 UI | 1.0 |
| 支付套餐映射（credit 商品化） | 0.5 |
| **小计** | **4.0** |

#### 3.3.7 风险与注意事项

| 风险 | 严重度 | 缓解 |
|---|---|---|
| 并发扣费竞态 | 高 | Redis 分布式锁 + DB `SELECT FOR UPDATE` |
| 与现有 quota 逻辑冲突 | 中 | 明确文档：quota 是"月度上限"，credit 是"钱包"，两者并行 |
| 退款/负余额 | 低 | 退款走 refund 事件追加 ledger，balance 可负但不拦截 |
| 支付回调幂等 | 已解决 | 已有 `payment/task_guard.py` |
| 单价调整历史 | 低 | 每次 ledger 记录当时的 unit_price，报表用当时价 |

---

### 3.4 模块 M4：工作流引导（Wizard）

#### 3.4.1 集成位置

| 层 | 位置 | 动作 |
|---|---|---|
| 前端入口 | `prism_frontend/src/app/fusion/wizard/page.tsx`（新增） | 主 Wizard 页 |
| 前端组件 | `prism_frontend/src/components/wizard/`<br>├─ `wizard-shell.tsx`（步骤容器）<br>├─ `step-topic.tsx`（选题）<br>├─ `step-script.tsx`（写稿）<br>├─ `step-assets.tsx`（配图/视频）<br>├─ `step-preview.tsx`（预览/发布）<br>└─ `wizard-state.tsx`（`useReducer` 状态机） | 新建 |
| 后端 | 复用现有 `/api/v1/fusion/images` + `/api/v1/ai/prompts` + `/api/v1/campaigns` | 不新增 |
| DB | 可选：新增 `wizard_sessions` 表记录草稿（首版可省） | 可选 |

#### 3.4.2 技术选型确认

- **不引入 Trigger.dev**（GitHub 调研推荐）
- **理由**：
  1. Prism-Fusion 已有 `tasks/` + `celery` 做异步编排，无需再引入 TS 侧 workflow
  2. Trigger.dev 需独立部署或走 SaaS，运维成本
  3. Wizard 首版是**同步串行**（选完一步再一步），不需要 durable workflow
- **保留选项**：若后续有"选题→生成→发布"跨请求持久化的场景，再引入 Trigger.dev
- **前端状态机**：`useReducer` + `zod` schema 校验，每步状态写入 URL query（`?step=topic`），刷新可恢复

#### 3.4.3 4 步设计

**Step 1 - 选题（`step-topic`）**：
- 输入：主题关键词、目标平台（多选）、内容形式（图文/短视频/长文）
- AI 增强：调 `hot_topics` 推荐相关热点（复用 `fusion_ai/hot_topics.py`）
- 输出：选题卡片（标题 + 简介 + 目标平台）

**Step 2 - 写稿（`step-script`）**：
- 根据 Step 1 输出，调 cloud `/cloud/llm/chat`（prompt_name="content_draft"）生成正文
- 用户可编辑、可插入 M2 的 `style_profile_id` 让 AI 模仿品牌口吻
- 输出：`{title, body, tags[], hashtgs[]}`

**Step 3 - 素材（`step-assets`）**：
- 调 M1 `/api/v1/fusion/images/generate` 生成配图（数量/尺寸/风格可配）
- 支持从 `materials/` 已有素材库选择
- 支持上传
- 输出：`{images[], video_url?}`

**Step 4 - 预览/发布（`step-preview`）**：
- 展示完整稿件 + 素材
- 一键发布到所选平台（复用 `/api/v1/publish` 或 `campaigns/`）
- 或直接存入 `content_library` 待审

#### 3.4.4 依赖关系

- 强依赖 M1（生图）、M2（风格训练）、已有 `hot_topics`
- 是 M5 的上游（生成的图可送入编辑器）

#### 3.4.5 工作量估算

| 子任务 | 人日 |
|---|---|
| `wizard-shell` + `useReducer` 状态机 + URL 同步 | 0.5 |
| 4 个 step 组件 | 2.0 |
| 与 M1/M2/hot_topics 的 API 对接 | 0.5 |
| URL 恢复 + 草稿保存（localStorage） | 0.5 |
| 前端测试 | 0.5 |
| **小计** | **4.0** |

#### 3.4.6 风险与注意事项

| 风险 | 严重度 | 缓解 |
|---|---|---|
| 每步都调云端 LLM，用户等待 | 中 | 步间可跳过；每步有"手动输入"降级 |
| 状态丢失 | 中 | localStorage 自动保存 draft |
| 与 campaigns 编排重叠 | 低 | Wizard 是"单次内容"，campaign 是"批量矩阵"，边界清晰 |

---

### 3.5 模块 M5：轻量图片编辑器

#### 3.5.1 集成位置

| 层 | 位置 | 动作 |
|---|---|---|
| 前端入口 | `prism_frontend/src/app/fusion/image-editor/page.tsx`（新增，独立页）<br>+ 全局快捷 sheet（从 M1 生图结果点"编辑"打开） | 新建 |
| 前端组件 | `prism_frontend/src/components/image-editor/`<br>├─ `editor-host.tsx`（挂载 unlayer ImageEditor）<br>├─ `toolbar.tsx`（裁剪/文字/形状/滤镜/贴纸）<br>├─ `layer-panel.tsx`<br>└─ `export-dialog.tsx` | 新建 |
| 后端 | **无后端改动**（纯前端 canvas 操作，导出为 base64） | 无 |
| 素材库落盘 | 保存时调已有 `/api/v1/files/upload` | 复用 |
| package.json | 加 `unlayer`（**注意：不是 `@unlayer/react`**，调研中的组件是 MIT 版） | 编辑 |

**依赖选型说明**：
- 优先：`unlayer/react-image-editor`（259★，MIT，React 组件）
  - ⚠️ **注意**：npm 上的 `unlayer` 主包是商业版（付费），开源的是 GitHub 上的 `unlayer/react-image-editor`，需通过 git URL 安装：`npm install github:unlayer/react-image-editor`
- 兜底：`react-image-crop`（6k★，MIT，仅裁剪）+ `canvas-confetti` / `fabric.js`（MIT，全功能但重）
- 最终建议：**`react-image-crop`（裁剪）+ 自建 canvas 编辑（文字/形状）**，因为 unlayer 的 React 组件 star 少，长期维护风险高
  - 若首版只需裁剪，用 `react-image-crop`
  - 若要文字/形状/贴纸，加 `fabric.js`（53k★，MIT）
- **决策**：首版走 `react-image-crop` + `fabric.js` 组合，功能可控

#### 3.5.2 技术选型确认

| 组件 | 选型 | License | 用途 |
|---|---|---|---|
| 裁剪 | `react-image-crop` | MIT | 裁剪/框选 |
| 编辑画布 | `fabric.js` | MIT | 文字/形状/图层/贴纸/滤镜 |
| 滤镜 | `fabric.js` filters | MIT | 亮度/对比度/饱和度/模糊 |
| 图标 | `lucide-react` | ISC | 工具栏图标 |
| 上传 | 现有 `/api/v1/files/upload` | - | 素材落盘 |

**兼容性**：
- Next.js 16 + React 19 与 fabric.js 5.x 兼容（已验证 community issue）
- 需注意：fabric.js 依赖 DOM，全部代码必须放在 `use client` 组件里

#### 3.5.3 关键 API 契约

**无新增后端 API**。前端组件的 props 契约：

```tsx
<ImageEditorSheet
  open: boolean
  onOpenChange: (v: boolean) => void
  initialImage: string  // URL 或 base64
  onSave: (result: {
    dataUrl: string;   // base64
    width: number;
    height: number;
  }) => void;
  onCancel: () => void;
/>
```

**内部 API**：
- `POST /api/v1/files/upload`（现有）— 保存时上传导出图
- 若生成历史要记录，扩展 `/api/v1/fusion/images/{id}` 支持 `edited_at` + `edited_path`

#### 3.5.4 依赖关系

- 依赖 M1（生成 → 编辑）
- 被 M4 消费（工作流第 3 步可打开编辑器精修）

#### 3.5.5 工作量估算

| 子任务 | 人日 |
|---|---|
| `npm install react-image-crop fabric` + 打包验证 | 0.2 |
| `editor-host.tsx`（fabric canvas 初始化 + 状态管理） | 0.5 |
| `toolbar.tsx`（6 个工具按钮） | 0.3 |
| `layer-panel.tsx`（图层列表 + 拖拽排序） | 0.3 |
| `export-dialog.tsx`（导出 PNG/JPG + 上传） | 0.2 |
| 集成入口（M1 结果页"M 编辑"按钮 + 独立路由） | 0.3 |
| 前端测试 | 0.2 |
| **小计** | **2.0** |

#### 3.5.6 风险与注意事项

| 风险 | 严重度 | 缓解 |
|---|---|---|
| unlayer 组件 star 少（259） | 中 | 改用 `react-image-crop` + `fabric.js` 组合 |
| fabric.js 与 React 19 SSR | 低 | 全部 `use client` |
| 大图片性能 | 中 | 缩略图 + 按需渲染；导出时再全分辨率 |
| 内存泄漏 | 低 | `useEffect` cleanup 时 `fabric.Canvas.prototype.dispose()` |

---

## 4. 依赖关系图 + 优先级排序

### 4.1 依赖图

```
                  ┌──────────────┐
                  │  M3 积分计费  │  ← 基础设施，最先做
                  └──────┬───────┘
                         │  扣费调用
            ┌────────────┼────────────┐
            ↓            ↓            ↓
      ┌──────────┐  ┌──────────┐  ┌──────────┐
      │ M1 生图   │  │ M2 风格   │  │ 已有 Hermes│
      └────┬─────┘  └────┬─────┘  └──────────┘
           │             │
           │    ┌────────┴──────┐
           │    ↓               ↓
           │  M1（style 应用）  M4（style 应用）
           │                    ↑
           └─────────────── M5  ──┘
                             │
                     生图 → 精修
```

### 4.2 开发顺序（推荐）

| 顺序 | 模块 | 人日 | 累计 | 理由 |
|---|---|---|---|---|
| 1 | **M5 图片编辑器** | 2.0 | 2.0 | 最快见效，纯前端，无依赖，立刻能给 Easel 视频流水线加"封面编辑器" |
| 2 | **M3 积分计费** | 4.0 | 6.0 | 关键路径基础设施，M1/M2/M4 都要扣积分 |
| 3 | **M1 文生图** | 5.0 | 11.0 | 用户最直观的价值点；接入 ComfyUI 独立部署 |
| 4 | **M2 风格训练** | 5.5 | 16.5 | 最复杂，需要 UX 迭代；依赖云端 prompt 就位 |
| 5 | **M4 工作流引导** | 4.0 | 20.5 | 集成型模块，依赖 M1/M2 就位；先做基础版即可 |

**总计：20.5 人日**（考虑现有基础后的乐观估算）

**关键路径**：M3 → M1 → M4（15.5 人日），M2 可与 M1 并行（-2.0 人日），M5 可与任意并行。

**并行执行下的最短周期**：3 人 × 7 天 ≈ 21 人日，可覆盖全部。

---

## 5. 总工作量汇总

| 模块 | 前端 | 后端 | DB | 测试 | 部署/运维 | 小计 |
|---|---|---|---|---|---|---|
| M1 文生图 | 2.0 | 1.5 | 0.5 | 0.5 | 0.5 | **5.0** |
| M2 风格训练 | 2.5 | 1.5 | 0.5 | 1.0 | 0 | **5.5** |
| M3 积分计费 | 1.5 | 1.5 | 0.5 | 0.5 | 0 | **4.0** |
| M4 工作流 | 3.0 | 0.5 | 0 | 0.5 | 0 | **4.0** |
| M5 图片编辑器 | 1.8 | 0 | 0 | 0.2 | 0 | **2.0** |
| **合计** | **10.8** | **4.5** | **1.5** | **2.7** | **0.5** | **~20.5 人日** |

**乐观（复用现有多）：17-18 人日**
**保守（含 UX 迭代 + 联调）：22-24 人日**

---

## 6. 风险矩阵

### 6.1 License 风险（按严重度排序）

| 项目 | License | 集成方式 | 风险 | 缓解 |
|---|---|---|---|---|
| **ComfyUI** | GPL-3.0 | 独立进程 + HTTP | **中** | 不 import 其源码；不 pip 安装；部署到独立主机；用户自行下载 |
| **LiteLLM** | MIT | 本方案不采用 | 0 | - |
| **OpenMeter** | Apache-2.0 | 本方案不采用（自建 credit ledger） | 0 | - |
| **Flexprice/Lago** | AGPL-3.0 | 本方案不采用 | 0 | - |
| **Trigger.dev** | Apache-2.0 | 本方案首版不采用 | 0 | 后续引入无风险 |
| **n8n** | Fair-code | 不采用 | 0 | - |
| **react-image-crop** | MIT | npm install | 0 | - |
| **fabric.js** | MIT | npm install | 0 | - |
| **prompt-master** | MIT | 参考结构，不引用代码 | 0 | - |

**核心结论**：只有 ComfyUI 有 GPL 传染风险，通过"独立进程 + HTTP + 不 import"隔离，Open Core 商业化无实质障碍。

### 6.2 技术风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| ComfyUI 需要 GPU 硬件 | 高 | 高 | 首版提供 5 个非 GPU provider（NanoBanana/DALL-E/Flux/通义/自定义）作为降级；`.env` 中 `COMFYUI_ENABLED` 开关 |
| 云端 prompt 抽取 JSON 失败 | 中 | 中 | `zod` schema 校验 + 重试 2 次 + 降级空 profile |
| 并发扣积分竞态 | 低 | 高 | Redis 分布式锁 + DB `SELECT FOR UPDATE` |
| 与现有 quota 逻辑冲突 | 中 | 中 | 明确双轨制：quota 是月度上限，credit 是钱包 |
| fabric.js + React 19 SSR | 低 | 中 | 全部 `use client`；测试环境验证 |
| Wizard 状态复杂化 | 中 | 中 | `useReducer` + URL query + localStorage |
| 前后端 API 契约破坏 | 低 | 中 | `zod` schema 前后端共享；集成测试 |

### 6.3 运维风险

| 风险 | 缓解 |
|---|---|
| ComfyUI 服务稳定性 | systemd 拉起 + 健康检查 + 熔断降级到其他 provider |
| GPU 显存 OOM | 队列化 + 超时保护（`COMFYUI_TIMEOUT`） |
| 模型下载体积（SD/Flux 权重 8-20GB） | 用户自下载或走托管；文档明确说明 |
| ComfyUI 更新频繁 | 锁定版本号 + 定期人工升级 |

---

## 7. 建议的第一步行动

**子代理拿到本文档后，按以下顺序立即启动**：

### 第 0 步（0.5 天）：脚手架 + 数据库迁移

1. 新建目录：
   ```
   prism_frontend/src/app/fusion/{image-studio,image-editor,style-trainer,wizard}/page.tsx
   prism_frontend/src/components/{image-studio,image-editor,style-trainer,wizard}/
   prism_backend/fusion_ai/{comfyui_client.py,style_trainer.py}
   ```
2. 追加迁移脚本：`prism_backend/db/create_image_generations.py` / `create_style_profiles.py`
3. 云端迁移：在 `cloud_service/main.py` 的 lifespan 中追加 `CreditLedger` / `CreditBalance` / `CreditPricing` 建表

### 第 1 步（2 天）：M5 图片编辑器（最快见效）

1. `prism_frontend/package.json` 加依赖：`react-image-crop`、`fabric`
2. 实现 `editor-host.tsx` + `toolbar.tsx`
3. 独立路由 `/fusion/image-editor`，支持 URL query 传初始图
4. 在已有 M1 结果页（或 `material-editor-sheet.tsx`）加"编辑"按钮 → 打开 editor sheet
5. 单元测试：能打开、能裁剪、能加文字、能导出 base64、能上传

### 第 2 步（4 天）：M3 积分计费

1. 云端：`CreditLedger` + `CreditBalance` + `CreditPricing` 表 + seed
2. 云端：`/cloud/credit/*` 4 个端点
3. 云端：Redis 分布式锁（复用 `payment/task_guard.py`）
4. `prism_backend`：3 处 hook（image/llm/video 调用后上报）
5. 前端：扩展 `cloud-subscription-card.tsx`（余额/流水/充值）

### 第 3 步（5 天）：M1 文生图

1. `.env` 加 `COMFYUI_ENABLED` / `COMFYUI_BASE_URL` / `COMFYUI_TIMEOUT`
2. `comfyui_client.py`：`/prompt` + `/history` + `/view` HTTP 封装
3. `image_generators.py` 追加 `comfyui:*` provider 分支
4. `image_generations` 表 + 生成完调 M3 扣积分
5. 前端：`/fusion/image-studio` 页 + 6 个组件
6. 集成：M5 编辑器按钮（点"编辑"跳 editor）

### 第 4 步（并行 5.5 天）：M2 风格训练

1. `cloud_service/llm_proxy/prompts.py` 追加 `style_profile_extract` + `style_apply` SEED
2. `style_trainer.py`：LLM 抽取 + 本地统计（句长、emoji 密度）
3. `style_profiles` 表 + CRUD API
4. 前端：`/fusion/style-trainer` 页 + 5 个组件
5. 集成：M1/M4 生成时可选 `style_profile_id`

### 第 5 步（4 天）：M4 工作流

1. `wizard-shell.tsx` + `useReducer` + URL 同步
2. 4 个 step 组件（topic / script / assets / preview）
3. 集成 M1（生图）+ M2（风格）+ 已有 hot_topics
4. 预览 → 发布（复用 `/api/v1/publish`）

### 第 6 步（收尾）：文档 + 演示

1. 更新 `README.md`：加"5 大新模块"章节
2. `env.example` 加所有新变量
3. `docs/dev-reports/2026-10-16-module-replication-progress.md` 记录进度
4. 产品演示视频（走 HyperFrames 现有流水线）

---

## 8. 附录：环境变量新增清单

```bash
# ComfyUI (M1)
COMFYUI_ENABLED=false
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_TIMEOUT=120
COMFYUI_MAX_CONCURRENT=2

# 积分计费 (M3) — 云端
CREDIT_FREE_INITIAL=2000        # 免费用户初始积分（cent，20 元等值）
CREDIT_LOCK_TTL_SECONDS=10
CREDIT_LEDGER_RETENTION_DAYS=365

# 价格表（云端 seed，管理员可改）
CREDIT_PRICE_IMAGE_512=20        # 一张 512x512 图 = 20 cent = ¥0.20
CREDIT_PRICE_IMAGE_1024=50       # 一张 1024x1024 图 = 50 cent = ¥0.50
CREDIT_PRICE_LLM_PER_1K_TOKENS=5 # 每 1k tokens = 5 cent = ¥0.05
CREDIT_PRICE_VIDEO_PER_MINUTE=100
```

---

## 9. 剩余不确定性

1. **ComfyUI GPL 传染的严格法务解读**：本方案假设"独立进程 + HTTP"不传染（行业通说），但商业化前建议咨询法务。若法务要求更严，可切到托管服务（Replicate / RunPod）。
2. **M2 风格训练的评估指标**：无社区共识，首版靠用户主观反馈；后续可加"生成相似度打分"作为回归指标（promptfoo 可做）。
3. **ComfyUI 官方 workflow 与自定义 workflow 的用户体验**：首版只提供 3 个官方 workflow；用户自定义 workflow 的 UI 交互需后期设计。
4. **react-image-crop 精确 star 数**：GitHub 调研标注 6k（估算），实际以 npm 侧为准。
5. **Open Core 具体分层边界**：M1-M5 中的哪些部分归 Community、哪些归 Pro，需在下一个 Open Core 决策会议中确定。本方案默认：M5/M4 全开源，M1 客户端开源但 ComfyUI 权重需用户自备，M2/M3 云端 API 只在 Pro 订阅可用。
6. **ComfyUI 是否走独立主机**：如果部署在同一台主机，需要 systemd 隔离进程；GPU 主机独立部署时通过内网 HTTP 通信更清晰。

---

*方案完成，交给复刻子代理按 §7 顺序推进。*
