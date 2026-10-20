# 开源AI平台调研：LLM接入方式/用户控制/Open Core分层

> 调研日期：2026-10-20  
> 调研目的：参考开源平台的LLM接入、用户控制、Open Core最佳实践，为Prism-Fusion设计参考

---

## 1. 调研平台清单

| # | 平台 | GitHub | Stars | License | 技术栈 | 活跃度 |
|---|------|--------|-------|---------|--------|--------|
| 1 | **One-API** | [songquanpeng/one-api](https://github.com/songquanpeng/one-api) | 37.2k | MIT | Go + React/Vue, SQLite/MySQL | 1210 commits, 活跃 |
| 2 | **New-API** | [Calcium-Ion/new-api](https://github.com/Calcium-Ion/new-api) | 50.3k | AGPL-3.0 | Go + Next.js, SQLite/MySQL | 6580 commits, 非常活跃 |
| 3 | **LiteLLM** | [BerriAI/litellm](https://github.com/BerriAI/litellm) | 61.6k | MIT (enterprise单独) | Python + Rust core, Svelte UI | 54912 commits, 极活跃 |
| 4 | **Dify** | [langgenius/dify](https://github.com/langgenius/dify) | 159k | Apache-2.0 + Dify OSS License | Python(Flask/FastAPI) + Next.js/React, PostgreSQL | 14299 commits, 极活跃 |
| 5 | **NextChat** | [ChatGPTNextWeb/NextChat](https://github.com/ChatGPTNextWeb/NextChat) | 88.9k | MIT | Next.js/React + Tauri | 3145 commits, 活跃 |
| 6 | **Flowise** | [FlowiseAI/Flowise](https://github.com/FlowiseAI/Flowise) | 55.5k | 见仓库(enterprise单独) | Node.js/TS + LangChain.js + React | 已归档(2026-08) |
| 7 | **FastGPT** | [labring/FastGPT](https://github.com/labring/FastGPT) | 29.9k | 自定义License(pro单独) | Next.js, MongoDB, Redis, pgvector | 3643 commits, 活跃 |

> **注**：自媒体/矩阵发布类开源工具调研中未找到成熟的高星开源项目。该类工具多为商业闭源产品（如融媒宝、包图云等），开源社区关注度较低。

---

## 2. LLM接入方式对比表

| 平台 | 接入方式 | 用户自配key | 云端代理 | 典型UX |
|------|----------|------------|----------|--------|
| **One-API** | 管理员配上游key → 用户用令牌调用 | ✅ 管理员配 | ✅ 平台做路由 | 管理员在"渠道"页面填key，用户在"令牌"页面生成自己的key |
| **New-API** | 管理员配上游key → 用户用令牌调用 | ✅ 管理员配 | ✅ 平台做路由 | 类似One-API，支持格式互转(OpenAI↔Claude↔Gemini) |
| **LiteLLM** | 配置文件集中配key | ✅ config.yaml | ✅ 统一OpenAI格式 | `config.yaml`中声明所有provider和key，通过Proxy Server暴露统一接口 |
| **Dify** | 用户在模型设置页配key | ✅ 用户自配 | ❌ 纯用户自配 | 管理后台→"模型供应商"→选择provider→填API key→保存 |
| **NextChat** | 用户直接在设置中填key | ✅ 用户自配 | ❌ 纯用户自配 | 点击设置→填API Key和Base URL→保存即用 |
| **Flowise** | 工作流节点中配置key | ✅ 用户自配 | ❌ 纯用户自配 | 拖拽节点→配置节点属性时填key |
| **FastGPT** | 管理后台配模型key | ✅ 管理员配 | ❌ 纯用户自配 | 管理后台→模型配置→选择provider→填key |

### 关键发现

1. **两种主流模式**：
   - **模式A（One-API/New-API/LiteLLM）**：管理员配上游key，用户通过令牌/虚拟key消费 → 适合**平台运营者**
   - **模式B（Dify/NextChat/FastGPT）**：用户直接配自己的key → 适合**个人/团队自用**

2. **最佳实践**：Dify的做法最值得参考 — 默认让用户自配key，同时提供Cloud版的message credits作为体验福利。credits用完后可切换为自己配的key。

3. **对于Prism-Fusion**：用户说"生图模型一定是用户自己接"，建议采用**模式B**（用户自配key）作为核心，可选提供**模式A**（云端代理）作为增值。

---

## 3. 用户控制方式对比表

| 平台 | 注册制 | 授权码/兑换码 | 积分/额度制 | 免费/付费分层 | 用户分组 |
|------|--------|-------------|------------|-------------|---------|
| **One-API** | ✅ 邮箱/GitHub/飞书/微信 | ✅ 兑换码充值 | ✅ 额度+倍率 | 开源免费（自运营者自定义） | ✅ 用户+渠道分组 |
| **New-API** | ✅ 邮箱/GitHub | ✅ 兑换码+易支付 | ✅ 额度+倍率 | AGPL开源+newapi.ai云服务 | ✅ 用户+渠道分组 |
| **LiteLLM** | ✅ 邮箱 | ❌ | ✅ cost tracking | MIT开源+enterprise | ✅ RBAC+虚拟key |
| **Dify** | ✅ 邮箱/GitHub/Google | ❌ | ✅ message credits | Cloud分层(Sandbox免费/$590/$1590/Enterprise) | ✅ 多工作区(Enterprise) |
| **NextChat** | ❌ 自部署版无 | ❌ | ✅ SaaS版按量付费 | MIT开源+SaaS(nextchat.club) | ❌ |
| **Flowise** | ❌ 自部署版无 | ❌ | ❌ | 开源+Flowise Cloud | ❌ |
| **FastGPT** | ✅ 邮箱 | ❌ | ✅ 积分制 | 社区版+Cloud+Enterprise | ✅ 团队管理 |

### 关键发现

1. **兑换码/授权码**：One-API和New-API做得最完善 — 支持批量生成兑换码、导出、用户兑换充值，这是自媒体运营场景的标准做法。

2. **积分制最佳实践**（Dify）：
   - 免费层给少量credits让用户体验
   - credits用完后可切换为自带key
   - 付费层按credits额度+功能数量分层
   - **核心逻辑**：credits是"体验福利"，不是唯一付费手段

3. **对于Prism-Fusion**：建议采用 **兑换码 + 积分制** 组合：
   - 注册免费，新用户送基础积分
   - 支持兑换码充值（对接微信支付/支付宝）
   - AI内容生成消耗积分，用户也可自配key免费使用
   - 矩阵发布功能可设免费/付费分层

---

## 4. Open Core方式对比表

| 平台 | 开源什么 | 付费什么 | 防fork策略 | License |
|------|---------|---------|-----------|---------|
| **One-API** | 全部 | 无（纯开源） | 无 | MIT |
| **New-API** | 核心功能 | 云服务newapi.ai | AGPL-3.0（copyleft，修改后需开源） | AGPL-3.0 |
| **LiteLLM** | 核心SDK+Proxy | enterprise/目录（高级功能）+ LiteLLm Cloud | enterprise/目录单独许可 | MIT + 企业许可 |
| **Dify** | 社区版核心功能 | Enterprise：SSO、多工作区、高级安全、商业许可、专属支持 | Dify Open Source License限制企业商用 | Apache-2.0 + 自定义 |
| **NextChat** | 全部前端 | SaaS版(nextchat.club) + Enterprise版 | 无 | MIT |
| **Flowise** | 核心功能 | Flowise Cloud + Enterprise | enterprise/目录单独许可 | 见仓库 |
| **FastGPT** | 社区版核心 | pro/目录(企业功能) + FastGPT Cloud | 自定义License限制商业使用 | 自定义 + pro单独 |

### Open Core分层模式总结

```
模式1: 纯开源（One-API）
  → 所有代码MIT开源，无付费层，靠社区赞助/个人运营

模式2: AGPL copyleft（New-API）
  → 核心AGPL开源，修改后必须开源，防止商业fork后不回馈

模式3: 目录隔离（LiteLLM/Flowise/FastGPT）
  → 核心MIT/自定义开源，enterprise/目录单独许可
  → 技术隔离：付费功能在单独目录中

模式4: License分层（Dify）
  → 社区版Apache-2.0开源，但限制企业商用
  → 企业版需购买商业许可才能使用企业功能
  → SSO、多工作区等高级功能仅Enterprise可用
```

### 对于Prism-Fusion的建议

推荐采用 **模式3 + 模式4混合**：
- **社区版**：MIT/Apache-2.0开源，包含基础AI内容生成+矩阵发布功能
- **Enterprise目录**：高级功能（多用户管理、团队协作、API限流、SSO、白标）
- **云服务**：提供托管版，按积分/订阅收费
- **防fork**：考虑AGPL-3.0（对新功能保护）或自定义License（对核心社区版限制商用）

---

## 5. 对Prism-Fusion的启示

### 5.1 LLM接入：用户自配key的最佳实践

**推荐方案**：参考Dify的用户自配key UX

```
用户配置流程：
1. 进入"模型管理"页面
2. 选择模型类型（文本生成/图片生成/视频生成）
3. 选择Provider（OpenAI/Anthropic/Stability AI/Replicate等）
4. 填写API Key（带验证按钮）
5. （可选）配置Base URL（支持自定义端点）
6. 保存 → 完成

技术方案：
- 前端：模型选择器 + key输入框 + 验证按钮
- 后端：加密存储key（AES-256-GCM），请求时动态注入
- 架构：Proxy模式，Prism-Fusion作为中间层转发请求到上游API
```

**关键UX要点**（来自Dify/NextChat）：
- ✅ Key输入框支持"显示/隐藏"切换
- ✅ 一键验证key是否有效
- ✅ 支持多个key（同一provider可配多个key做负载均衡）
- ✅ 支持Base URL自定义（方便接第三方中转）
- ✅ Key存储加密，不明文展示
- ✅ 新用户引导：注册后先配key才能使用AI功能

**对于生图模型的特殊处理**：
- 生图API通常比文本模型贵很多，必须用户自配
- 建议支持：OpenAI DALL-E、Stability AI、Replicate、Midjourney代理
- 生图请求需要展示预估费用，用户确认后再执行

### 5.2 用户控制：注册+积分的最佳实践

**推荐方案**：参考New-API的兑换码 + Dify的积分制

```
用户体系：
├── 注册登录（邮箱 + 手机 + 微信OAuth）
├── 用户等级
│   ├── 免费版：有限积分，基础功能
│   ├── 付费版：更多积分，高级功能
│   └── 团队版：协作功能，API访问
├── 积分系统
│   ├── 新用户赠送基础积分
│   ├── AI内容生成消耗积分（按模型类型定价）
│   ├── 矩阵发布消耗积分（按平台/次数定价）
│   ├── 积分充值（微信支付/支付宝/兑换码）
│   └── 积分明细/账单查询
└── 权限管理
    ├── 单用户：完整功能
    ├── 团队：成员管理、角色权限、用量共享
    └── 企业：SSO、审计日志、API限流
```

**兑换码系统**（参考New-API）：
- 管理员可批量生成兑换码（按金额/积分面额）
- 兑换码可设置有效期、使用次数限制
- 支持导出兑换码（CSV格式，方便打印或发放）
- 用户兑换后立即到账，记录兑换历史
- 对接易支付等支付渠道，自动生成兑换码

### 5.3 Open Core：哪些值得借鉴

**推荐分层**：

| 层级 | 功能 | 目标用户 |
|------|------|---------|
| **社区版（开源）** | 单用户、基础AI生成、基础矩阵发布、单模型接入 | 个人开发者/小团队 |
| **Pro版（付费SaaS）** | 多模型、高级模板、批量生成、定时发布、数据分析 | 自媒体创作者/工作室 |
| **企业版（许可）** | 团队协作、SSO、API限流、白标、私有部署、专属支持 | 企业/机构 |

**防fork策略**：
1. **社区版**：AGPL-3.0（copyleft，修改后需开源）或 自定义License（限制商用）
2. **企业功能**：放在单独目录（如`enterprise/`），企业许可
3. **云服务**：核心代码开源但部分关键逻辑在云端执行（如积分计费、配额管理）

---

## 6. 建议参考的Top 3平台

### 🥇 Dify — 最全面的参考

- **理由**：159k Stars，最成熟的Open Core实践
- **参考点**：
  - 用户自配key的UX（模型供应商设置页面）
  - 积分制设计（message credits作为体验福利，用完可切自有key）
  - Open Core分层（社区版/Professional/Team/Enterprise清晰分层）
  - License策略（Apache-2.0 + 自定义License限制企业商用）
- **GitHub**：https://github.com/langgenius/dify

### 🥈 New-API — 最贴合运营场景

- **理由**：50.3k Stars，最完善的兑换码+积分+渠道管理系统
- **参考点**：
  - 兑换码系统（批量生成、导出、兑换充值）
  - 用户分组+渠道分组+倍率体系
  - 积分计费（按模型类型/倍率扣费）
  - 支付对接（兼容易支付等国内支付渠道）
- **GitHub**：https://github.com/Calcium-Ion/new-api

### 🥉 LiteLLM — LLM接入的技术参考

- **理由**：61.6k Stars，最强大的LLM路由/代理能力
- **参考点**：
  - 多Provider统一管理（100+ LLM）
  - OpenAI格式统一（所有模型转OpenAI格式调用）
  - Cost tracking（按token计费）
  - 虚拟key管理（为不同用户/团队分配独立key）
  - Load balancing（多key负载均衡）
- **GitHub**：https://github.com/BerriAI/litellm

---

## 附录：技术架构对比

| 平台 | 后端 | 前端 | 数据库 | 部署方式 |
|------|------|------|--------|---------|
| One-API | Go (Gin) | React + Vite | SQLite/MySQL | Docker/单文件 |
| New-API | Go (Gin) | Next.js + React | SQLite/MySQL | Docker |
| LiteLLM | Python (FastAPI) + Rust | SvelteKit | SQLite/PostgreSQL | Docker/K8s |
| Dify | Python (Flask/FastAPI) | Next.js + React | PostgreSQL + Redis + RabbitMQ | Docker Compose |
| NextChat | Next.js API Routes | Next.js + React + Tauri | IndexedDB/LocalStorage | Vercel/Docker/Tauri |
| Flowise | Node.js (Express) | React | MongoDB/SQLite | Docker |
| FastGPT | Node.js (NestJS) | Next.js | MongoDB + Redis + PostgreSQL | Docker Compose |

---

## 附录：关键设计模式总结

### LLM接入模式决策树

```
是否需要平台统一计费？
├── 是 → 模式A：管理员配key + 用户令牌
│        → 参考：One-API/New-API/LiteLLM
│        → 适用：API中转站、企业内部分发
│        └── 优点：统一管控、可计费、可限流
│        └── 缺点：需要平台承担上游费用
│
└── 否 → 模式B：用户自配key
         → 参考：Dify/NextChat/FastGPT
         → 适用：工具平台、SaaS应用
         └── 优点：零成本运营、用户灵活
         └── 缺点：无法统一管控用量
```

### Prism-Fusion推荐架构

```
用户配置自己的LLM Key
        │
        ▼
Prism-Fusion Proxy层（中间件）
  ├── 加密存储key
  ├── 统一OpenAI格式
  ├── 请求转发+超时/重试
  ├── 积分消耗记录（可选，平台key）
  └── 用量统计/账单
        │
        ▼
上游LLM API（OpenAI/Anthropic/Stability AI等）
```

这样既满足"生图模型一定是用户自己接"的要求，又保留了平台作为中间层的能力（可以做用量统计、模板管理、发布调度等增值功能）。
