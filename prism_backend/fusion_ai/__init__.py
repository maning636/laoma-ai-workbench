"""
Prism-Fusion AI 能力层
━━━━━━━━━━━━━━━━━━━━━━
在 Prism 原生 ai_service / ai_router 之上，补充以下 CAP 缺的能力：
  - model_providers:  11+ 主流 LLM provider 注册表 + 自动探测
  - platform_styles:  7+ 平台差异化风格模板 + 前台 CRUD
  - image_generators: NanoBanana / DALL·E3 / 通义万象 / Flux + 自定义模型
  - hot_topics:       微博/知乎/抖音/头条/小红书热点话题抓取
  - content_moderator:三层内容审核（敏感词 / Qwen 语义 / AI 合规改写）
  - model_market:     模型广场（11+ 模型能力对比、API Key 管理）
  - skill_workshop:   技能工坊（AI 去 AIGC 味）
  - cognition:        内容 DNA / 认知矩阵 / 受众画像 / 选题雷达
  - nl_query:         自然语言 → SQL → 结构化数据
  - custom_config:    前台配置中心（敏感词/风格/预设等 CRUD）

所有功能通过 FastAPI 中间件集中注册到 /api/fusion/* 前缀下。
"""