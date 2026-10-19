# Prism-Fusion GitHub 开源参考实现调研报告

- **报告日期**：2026-10-16
- **调研范围**：5 个功能模块的开源可复刻参考
- **调研方法**：WebSearch + GitHub README 直接抓取（stars/license/技术栈以 GitHub 首页为准）
- **调研作者**：SenseNova 6.8 Flash Lite（DimAgent 委派任务）

---

## 1. 执行摘要

| 模块 | 结论 | 一句话理由 |
|---|---|---|
| **M1 · AI 图片设计（文生图）** | ✅ **可集成** | 用 **ComfyUI + LiteLLM** 组合即可覆盖 SD/Flux/DALL-E 多模型路由，ComfyUI 已带完整 API Server |
| **M2 · 智能体风格训练** | ⚠️ **无开箱即用项目**（可自建 + 参考） | 找不到"喂样稿→提取风格 Profile"的成品 OSS，需要基于 promptfoo / 自建 few-shot pipeline 拼装 |
| **M3 · 积分制计费** | ✅ **可集成** | **Flexprice** 或 **Lago** 均提供 credit/wallet/top-up 完整能力，直接对得上需求 |
| **M4 · 工作流自动化** | ✅ **可参考 + 轻量自建** | n8n 太重；Trigger.dev / Inngest 提供 durable workflow，但首页场景向导更适合自建 3-4 步 Wizard + 用其做后台编排 |
| **M5 · 轻量图片编辑器** | ✅ **可集成** | Unlayer React Image Editor（MIT）+ react-image-crop 组合即可，完全浏览器端 |

**总体判断**：5 个模块中 4 个可以低成本集成现成开源能力，只有 M2 需要少量自研（本质是"prompt + RAG"的组合问题，无对应 OSS）。

---

## 2. 各模块详细分析

### 模块 1：AI 图片设计（文生图 / 多模型路由）

| # | 项目 | URL | Stars | 最后更新 | License | 技术栈 | 集成难度 |
|---|---|---|---|---|---|---|---|
| A | **Comfy-Org/ComfyUI** | https://github.com/Comfy-Org/ComfyUI | ~138k | 2026 活跃 | GPL-3.0 | Python + PyTorch，HTTP API Server | 中 |
| B | **BerriAI/litellm** | https://github.com/BerriAI/litellm | ~61.5k | 2026 活跃 | MIT（Python）/ Apache-2.0（部分） | Python + Rust 核心 | 低 |
| C | **QuantumNous/new-api** | https://github.com/QuantumNous/new-api | ~50.1k | 2026 活跃 | AGPL-3.0 | Go + Vue | 中 |

**候选详述**

- **ComfyUI**（首选后端）：目前文生图领域事实标准，138k stars，官方 API Server 端点齐全，支持 SD1.5/SDXL/Flux 全部主流权重，节点图编排。GPL-3.0 有传染性，但作为**独立服务进程 + HTTP 调用**不构成源码合并，法律上通常可接受（Prism-Fusion 后端调用它不算分发 ComfyUI 代码）。**不适合直接嵌入 Next.js**，必须作为独立 GPU 服务跑。
- **LiteLLM**（首选 API 网关）：61.5k stars，MIT，Rust + Python，天然多模型路由 + 统一 OpenAI 格式，**但原生只覆盖 LLM 类模型**，图片类需要自己扩展 provider。适合用来做统一 OpenAI-compatible API 层，把 ComfyUI、DALL-E、可灵（Kling）都归一化。
- **new-api**：50k stars，AGPL-3.0，Go 写的国内友好大模型网关，覆盖 LLM 和部分图片模型，但 AGPL 对商用有强制开源要求，**不建议**。

**推荐方案**
> **ComfyUI（GPU 服务）+ LiteLLM 或自建薄代理（Python FastAPI）**
> - ComfyUI 跑 SD/Flux 本地模型，走 HTTP API
> - DALL-E / 可灵走官方 API，通过 LiteLLM 或自写 proxy 统一格式
> - prism_backend/ 里加 `image_service/` 路由层，暴露 `POST /api/image/generate {prompt, model, size}` 到前端

---

### 模块 2：智能体风格训练（Style Profile）

| # | 项目 | URL | Stars | License | 说明 | 集成难度 |
|---|---|---|---|---|---|---|
| A | **promptfoo/promptfoo** | https://github.com/promptfoo/promptfoo | ~26.1k | MIT | LLM prompt 测试与红队评测 | 中 |
| B | **nidhinjs/prompt-master** | https://github.com/nidhinjs/prompt-master | ~14.6k | MIT | Claude skill，含 Brand Voice 提示词套路 | 低 |
| C | **lukataylo/ask-wisely** | https://github.com/lukataylo/ask-wisely | 数百 | MIT | prompt 库应用，含 Brand Voice / Copy Framework | 中 |

**结论：无开箱即用成品。**

**关键发现**
- 主流开源社区对"从 3-5 篇样稿 → 抽取风格 Profile → 存 prompt 模板"这个闭环**没有直接成品**，因为这是一个"分析型 + 提示词工程"的复合任务，各家用法差异极大。
- 但**能力组件齐全**：
  - **promptfoo**：可用来评估"生成的内容是否符合 Profile"，做风格相似度打分
  - **prompt-master**：其 SKILL.md 已给出 Brand Voice 提示词结构模板（[TONE]/[AUDIENCE]/[BRAND VOICE]/[PRODUCT NAME]），可直接作为存储格式参考
  - 分析侧走 **LlamaIndex / LangChain + embedding + LLM 抽取**（Prism-Fusion 已有 Hermes Agent，直接可用）

**推荐方案**
> **自建轻量 pipeline，参考 prompt-master 的 Brand Voice 字段结构**
> 1. `POST /style/train` 接收 3-5 篇样稿
> 2. 走 Hermes Agent 分析：句长分布、语气词、标点习惯、段落结构、常用修辞、立场倾向
> 3. 输出为结构化 JSON：`{tone, audience, brandVoice, productHooks, examples[3], negativeExamples[2]}`（对齐 prompt-master 字段）
> 4. 存入 MariaDB 的 `style_profiles` 表
> 5. 生成内容时通过 Hermes Agent 拼装成 system prompt，用 promptfoo 做回归评估（可选）

**风险提示**
- 3-5 篇样稿的统计量偏少，风格抽取本质是 LLM 主观总结，用户"感觉没抓到"的概率不低，需要迭代 UI 让用户手动微调 Profile

---

### 模块 3：积分制计费（Credit-based Billing）

| # | 项目 | URL | Stars | 最后更新 | License | 技术栈 | 集成难度 |
|---|---|---|---|---|---|---|---|
| A | **getlago/lago** | https://github.com/getlago/lago | ~10.7k | 2026 活跃 | AGPL-3.0 | Ruby + React + ClickHouse | 中 |
| B | **flexprice/flexprice** | https://github.com/flexprice/flexprice | ~6.9k | 2026 活跃 | AGPL-3.0 | Go + React + PostgreSQL + Kafka | 中 |
| C | **openmeterio/openmeter** | https://github.com/openmeterio/openmeter | ~2.4k | 2026 活跃 | Apache-2.0 | Go + React + ClickHouse | 中 |

**推荐组合**
- **首选 Flexprice**：README 直接标注 "Usage-based pricing, credit-based, hybrid pricing, real-time metering, credits & top-ups"，几乎是需求的一字一句复刻，6.9k stars，社区活跃，AGPL 但自托管场景无问题。
- **次选 Lago**：10.7k stars，社区最大，Ruby 技术栈与 Prism-Fusion（Python + TS）不完全对齐，但 API 层是标准的，无差异。
- **备选 OpenMeter**：Apache-2.0（最宽松 License），2.4k stars 稍小，但企业级 Kong 生态背书，适合未来商业化。

**推荐方案**
> **自托管 Flexprice（Docker Compose），prism_backend 通过 REST API 集成**
> - 每个 AI 调用（文生图、文生文、视频生成）都上报 metering event
> - Flexprice 计算扣积分 → 余额不足时拦截
> - 用户支付走 Stripe / 支付宝 → 充值到 credits
> - 数据落库到 Flexprice 自有 PostgreSQL

**⚠️ License 注意**
- Flexprice / Lago 均 AGPL-3.0。若 Prism-Fusion 未来闭源商业化：
  - 方案 A：**网络使用条款**（AGPL §13）允许"服务形式提供"而不必开源，但一旦修改 Flexprice 源码，修改部分需开源
  - 方案 B：切到 **OpenMeter**（Apache-2.0）零风险
  - 方案 C：直接内嵌 Stripe Subscription + 自建 credit ledger（约 3-5 天工时，反而最快）

**务实建议**
> 如果 Prism-Fusion 只是简单"积分余额 - 扣费"模型，**不用 Flexprice/Lago 也完全可以自建**：MariaDB 加 `user_credits`, `credit_transactions` 两张表 + Redis 做扣减锁即可，1-2 天完工。**Flexprice/Lago 的价值在于**：多套餐、阶梯价、企业计费报表、支付网关抽象——这些是 6 个月后的问题。

---

### 模块 4：工作流自动化（场景引导 Wizard）

| # | 项目 | URL | Stars | License | 用途 |
|---|---|---|---|---|---|
| A | **n8n-io/n8n** | https://github.com/n8n-io/n8n | ~208k | Sustainable Use License（fair-code，非 OSI） | 可视化 workflow，200+ 节点，AI 原生 |
| B | **triggerdotdev/trigger.dev** | https://github.com/triggerdotdev/trigger.dev | ~16.6k | Apache-2.0 | TypeScript durable workflow，适合后端编排 |
| C | **inngest/inngest** | https://github.com/inngest/inngest | ~6.0k | EE License（企业版）+ MIT 内核 | 事件驱动 + step function |

**推荐方案**
> **前端：自建 step-by-step Wizard（用 shadcn/ui + Zustand 状态机），3-4 步向导是纯 UI 问题**
> **后端：可选 Trigger.dev 做长任务编排（如"选题→生成→发布→回收"的异步流水线）**
>
> **不推荐 n8n**：208k stars 但 fair-code license，非 OSI 标准，二次分发受限；且它定位是外部服务编排（连接 GitHub、Slack、Notion），不是内嵌到 SaaS 首页的向导组件。

**关键设计**
- 场景向导本质是"表单 + 状态机"，直接 Next.js + shadcn Step 组件即可
- 若"生成→发布"这种异步耗时流程需要跨请求保持，用 Trigger.dev（Apache-2.0，Apache Next.js 一等公民支持）
- Prism-Fusion 已有 Hermes Agent + 视频流水线 Easel，实际已经具备 workflow 能力，无需再引入

---

### 模块 5：轻量图片编辑器（浏览器端 Canvas）

| # | 项目 | URL | Stars | 最后更新 | License | 说明 |
|---|---|---|---|---|---|---|
| A | **unlayer/react-image-editor** | https://github.com/unlayer/react-image-editor | ~259 | 2026 活跃 | MIT | React 组件，裁剪/缩放/画/文字/形状/贴纸/滤镜/AI 助手 |
| B | **danrollins/react-image-crop** | https://github.com/danrollins/react-image-crop | ~6k（估算，GitHub 未直连成功但 npm 显示活跃） | 2025 活跃 | MIT | 只做裁剪，React 界面上的黄金标准 |
| C | **tldraw/tldraw** | https://github.com/tldraw/tldraw | ~51k | 2026 活跃 | MIT（核心）/ 商业（部分） | 无限画布 SDK，可当拼图画板 |
| D | **nhn/tui.image-editor** | https://github.com/nhn/tui.image-editor | ~7.7k | ⚠️ **2026-09-02 归档** | MIT | 全功能 Canvas 编辑器，但已归档，**不推荐新用** |
| E | **FilerobotApp/filerobot-image-editor** | https://github.com/FilerobotApp/filerobot-image-editor | ~4k（估算） | 2024-2025 | MIT | 老牌的 JS 图片编辑器，非 React 特化 |

**推荐方案**
> **主力：Unlayer React Image Editor**
> - MIT License，明确商用友好
> - 功能覆盖需求全部：裁剪 / 拼图 / 加文字 / 滤镜
> - React 组件形式，Next.js 集成只需 `<ImageEditor src={url} />`
> - 77 commits 稍少但维护者（unlayer）是商业公司，稳定性有保障
>
> **辅助：danrollins/react-image-crop**（若只需极简裁剪场景）
>
> **可选升级：tldraw**（如果需要"多图层自由画布 + 图片作为 shape"的高级拼图）

**技术栈契合度**
- Unlayer 就是 React 组件，与 Next.js 16 零摩擦
- 输出走 Canvas API 导出为 base64/PNG，直接 POST 到 prism_backend

---

## 3. 集成路线建议（Prism-Fusion 视角）

```
┌──────────────────────────────────────────────────────────────┐
│  Prism-Fusion 集成架构图                                       │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Next.js 16 前端                                              │
│  ├── Style Profile UI (M2, 自建)                              │
│  ├── Scene Wizard UI (M4, 自建 shadcn)                         │
│  ├── Image Editor UI (M5, unlayer/react-image-editor)         │
│  └── Image Design UI (M1, 前端表单 + 图片预览)                  │
│                                                               │
│  prism_backend/ (FastAPI)                                     │
│  ├── image_service/ ← ComfyUI HTTP + 上游 DALL-E/Kling        │
│  ├── style_service/  (M2, LLM 抽取 + MariaDB 存储)             │
│  ├── billing_service/ (M3, Flexprice REST 或自建 credit ledger)│
│  └── workflow_service/ (M4, 可选 Trigger.dev SDK)              │
│                                                               │
│  独立服务                                                       │
│  ├── ComfyUI (Docker, GPU, M1)                                │
│  ├── Flexprice (Docker, PostgreSQL + Kafka, M3)               │
│  └── Trigger.dev (可选, M4)                                    │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

**落地顺序建议**（依赖关系 + 收益）：

1. **M5 图片编辑器**（最简单，1 天）→ 立刻给 Easel 视频流水线加个"封面编辑器"
2. **M3 计费**（关键路径）→ 若只是简单积分，自建 2 天；接 Flexprice 需 3-5 天
3. **M1 文生图**（需要 GPU 环境准备）→ ComfyUI 部署 1 天 + 后端接入 2 天
4. **M4 工作流**（先自建 Wizard，后端编排可后置）
5. **M2 风格训练**（最复杂，需要 Hermes Agent 调优 + UX 迭代，排 3-5 天）

---

## 4. 风险与注意事项

### License 冲突风险（按严重度排序）

| 项目 | License | 风险 |
|---|---|---|
| **ComfyUI** | GPL-3.0 | ⚠️ **高**：作为独立进程 + HTTP 调用通常安全，但不要在 prism_backend 里直接 `import comfyui` |
| **Lago** | AGPL-3.0 | ⚠️ **中高**：AGPL 网络使用触发开源义务，SaaS 场景需法务确认 |
| **Flexprice** | AGPL-3.0 | ⚠️ **中高**：同上 |
| **new-api** | AGPL-3.0 | ⚠️ **中高**：不建议采用 |
| **n8n** | Sustainable Use License | ⚠️ **中**：非 OSI，商用需申请 |
| **Inngest** | EE + MIT 内核 | ⚠️ **中**：核心 MIT，但高级功能商用需付费 |
| **LiteLLM** | MIT | ✅ 低 |
| **tldraw** | MIT（核心） | ✅ 低（注意 tldraw SDK 部分模块有商业 license） |
| **Unlayer react-image-editor** | MIT | ✅ 低 |
| **react-image-crop** | MIT | ✅ 低 |
| **promptfoo** | MIT | ✅ 低 |
| **prompt-master** | MIT | ✅ 低 |
| **Trigger.dev** | Apache-2.0 | ✅ 低 |
| **OpenMeter** | Apache-2.0 | ✅ 低 |

### 维护活跃度

**⚠️ 已归档项目**：
- **nhn/tui.image-editor**：2026-09-02 归档，不建议新项目采用

**⚠️ 需注意维护方**：
- Unlayer React Image Editor：star 数只有 259，维护者单一，但背后是商业公司 unlayer.com，稳定性尚可
- Flexprice：相对年轻（2024 年才开源），但 6.9k stars 增长快，社区活跃

### 技术栈兼容性

- **prism_backend 是 Python FastAPI**：Flexprice/Lago 是 Go/Ruby，**通过 HTTP API 集成而非代码集成**，无技术栈耦合问题
- **Next.js 16**：所有前端组件（Unlayer、tldraw、react-image-crop）都是纯 React，无问题
- **GPU 资源**：ComfyUI 需要 NVIDIA GPU + CUDA，若云主机无 GPU，考虑 **Replicate / RunPod / Modal** 托管（但成本上升）

### 未解决问题 / 剩余不确定性

1. **M2 风格训练的评估标准**：目前无社区共识的"风格相似度"量化指标，需要业务侧自定评分 rubric
2. **ComfyUI GPL 与分发边界**：需要法务确认"HTTP 调用 ComfyUI 是否触发 GPL 传染"——通说是不触发（独立进程，无源码链接），但严格合规场景需要咨询
3. **react-image-crop 具体 star 数与 owner**：WebFetch 未成功（GitHub 页面被 Cloudflare 挑战拦截），star 数从 npm 包侧推断约 6k，需要人工 double-check 精确值
4. **Filerobot Image Editor 的当前维护状态**：WebFetch 未成功，star 数为估算
5. **Flexprice vs Lago vs 自建**：三者的最终选择取决于 Prism-Fusion 未来 6-12 个月的商业化路线图，本调研只能给技术视角建议

---

## 附录：调研数据快照

- 数据抓取时间：2026-10-18
- GitHub stars/license 均从 GitHub 官方仓库首页抓取（README 首屏）
- 由于 GitHub 搜索 API 未授权，无法精确到"最近 7 天 commit 数"，"活跃度"基于最后 commit 时间 + 页面显示的 watchers/forks 综合判断
- WebSearch 工具在后期多次因配额受限失败（feature_not_entitled），已改用 WebFetch 直接抓取 repo 页面
