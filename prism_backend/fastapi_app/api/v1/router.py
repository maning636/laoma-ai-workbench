"""
API v1 路由总入口
"""
from fastapi import APIRouter

# 导入各模块路由
from .accounts.router import router as accounts_router
from .campaigns.router import router as campaigns_router
from .auth.router import router as auth_router
from .auth.browser_login import router as auth_browser_login_router
from .files.router import router as files_router
from .analytics.router import router as analytics_router
from .scripts.router import router as scripts_router
from .publish.router import router as publish_router
from .tasks.router import router as tasks_router
from .tasks.distribution_alias import router as distribution_router
from .recovery.router import router as recovery_router
from .data.router import router as data_router
from .ai.router import router as ai_router
from .ai.threads_router import router as ai_threads_router
from .ai_prompts.router import router as ai_prompts_router  # AI配置管理
from .dashboard.router import router as dashboard_router
from .system.router import router as system_router
from .verification.router import router as verification_router
from .agent.router import router as agent_router
from .matrix.router import router as matrix_router
from .manual_tasks.router import router as manual_tasks_router
from .campaigns.plans_alias import router as plans_router
from .campaigns.task_packages import router as task_packages_router
from .ip_pool.router import router as ip_pool_router
from .concurrency.router import router as concurrency_router
from .cookies.router import router as cookies_router
from .creator.router import router as creator_router
from .mediacrawler.router import router as mediacrawler_router
# from .crawler.router import router as crawler_router  # B-B (2026-10-16) 懒加载：由 main._mount_crawler_router 在 startup 后 include
from .tikhub.router import router as tikhub_router
from .persona_proxy.router import router as persona_proxy_router
from .persona.router import router as persona_router
from .easel_bridge.router import router as easel_bridge_router  # Easel 工作台托管（内嵌 iframe + 稿件桥）
from .skills.router import router as skills_router  # 技能库注册中心（Easel 技能 + 实时更新接口）
from .workshop.router import router as workshop_router  # 创作工坊（Easel 脚本表单直调）
from .video_pipeline.router import router as video_pipeline_router  # 视频流水线（HyperFrames 引擎，并行第二条流水线）
from .content_library.router import router as content_library_router  # 原生内容库（outputs 直读）
from .profile.router import router as profile_router  # 账号画像（build/list/get）
from .receipts.router import router as receipts_router  # 发布回执（Phase 0.1）
from .webhooks.router import router as webhooks_router  # Webhook（Phase 5）
from .health.router import router as health_router  # 账号健康（Phase 1）
from .review.router import router as review_router  # 审核队列（Phase 3.3）
from .artifacts.router import router as artifacts_router  # 统一产物总线（生图/素材/视频/审核/发布串通用）
from .dedup.router import router as dedup_router  # 去重查重（Phase 4.3）
from .insight.router import router as insight_router  # 数据洞察（Phase 4.2）

# 导入平台路由
from .platforms.douyin.router import router as douyin_router
from .platforms.kuaishou.router import router as kuaishou_router
from .platforms.xiaohongshu.router import router as xiaohongshu_router
from .platforms.tencent.router import router as tencent_router
from .platforms.bilibili.router_biliup import router as bilibili_router  # 使用 biliup 版本
from .platforms.tasks.router import router as platform_tasks_router
from .tools.router import router as tools_router
from .ccswitch.router import router as ccswitch_router  # CC Switch 桥接（读取本机 cc-switch 库并应用到项目内）
from .tool_catalog.router import router as tool_catalog_router  # 声明式工具注册中心（能力暴露为 tool）
from fusion_ai.router import router as fusion_router  # LaomaAI-Fusion 能力扩展（AI 多 Provider/平台风格/生图/热点/审核/模型广场/技能/认知/NL→SQL/配置中心）
from fusion_ai.ai_design import router as ai_design_router  # M1 AI 生图（澜途 /ai-design 复刻 + M3 积分扣费）
from fusion_ai.ai_agents import router as ai_agents_router  # M2 AI 智能体（澜途 /system/ai-agents 复刻；配额付费墙 + LLM 风格训练）

# B-B (2026-10-16): crawler_router 已改为懒加载——它 import 时会连带加载
# `crawlers.hybrid` / `crawlers.tiktok.web.models` / `crawlers.douyin.web.models`
# 等重模块（~1.5s），并在模块顶层实例化 3 个 crawler 对象。
# 该路由的延迟注册由 `fastapi_app.main._mount_crawler_router` 在 startup 后完成。

# 新增路由：任务状态机/平台字段/登录态检查/内容版本
from .task_state_machine.router import router as task_state_machine_router  # 幂等任务状态机（Phase 0.2）
from .platform_fields.router import router as platform_fields_router  # 平台字段管理（Phase 1.1-1.5）
from .platform_login_checker.router import router as platform_login_checker_router  # 登录态检查（Phase 1.6）
from .content_variant.router import router as content_variant_router  # 内容版本与审核队列（Phase 3.1+3.3）
from .diagnostics.router import router as diagnostics_router  # 诊断工件采集（Phase 2.2）
from .monitor.router import router as monitor_router  # 任务监控与告警（Phase 0.3）
from .selectors.router import router as selectors_router  # 选择器版本管理（Phase 2.1）
from .matrix_route.router import router as matrix_route_router  # 矩阵分组路由（Phase 2.3）

# 创建API路由器
api_router = APIRouter()

# 注册子路由
api_router.include_router(accounts_router, prefix="/accounts", tags=["账号管理"])
api_router.include_router(campaigns_router, tags=["计划管理"])  # router 已自带 /campaigns 前缀
api_router.include_router(auth_router, tags=["认证登录"])  # router 已自带 /auth 前缀
api_router.include_router(auth_browser_login_router, tags=["浏览器登录"])  # /auth/login/browser 前缀
api_router.include_router(files_router, tags=["文件管理"])  # router 已自带 /files 前缀
api_router.include_router(analytics_router)  # router 已自带 /analytics 前缀
api_router.include_router(scripts_router)  # router 已自带 /scripts 前缀
api_router.include_router(publish_router, tags=["视频发布"])  # router 已自带 /publish 前缀
# distribution_alias 必须排在 tasks_router 之前：
# tasks_router 有 `GET /tasks/{task_id}`，若先注册会把 `/tasks/distribution`
# 当成 task_id="distribution" 匹配掉（返回 404「任务不存在」），扫码派发列表永远取不到。
api_router.include_router(distribution_router)  # /tasks/distribution（真实实现）
api_router.include_router(tasks_router)  # router 已自带 /tasks 前缀
api_router.include_router(recovery_router)  # router 已自带 /recovery 前缀
api_router.include_router(data_router)  # router 已自带 /data 前缀
api_router.include_router(ai_router)  # router 已自带 /ai 前缀
api_router.include_router(ai_threads_router, prefix="/ai")  # 嵌套在 /ai/threads 下
api_router.include_router(ai_prompts_router, tags=["AI配置管理"])  # AI配置管理 /ai-prompts
api_router.include_router(dashboard_router)  # router 已自带 /dashboard 前缀
api_router.include_router(system_router)  # router 已自带 /system 前缀
api_router.include_router(verification_router)  # router 已自带 /verification 前缀
api_router.include_router(agent_router)  # router 已自带 /agent 前缀
api_router.include_router(matrix_router)  # router 已自带 /matrix 前缀
api_router.include_router(manual_tasks_router)  # router 已自带 /manual-tasks 前缀
api_router.include_router(plans_router)  # /plans (原 /api/plans 兼容入口升级为 v1)
api_router.include_router(task_packages_router)  # /task-packages (原 /api/task-packages 入口升级为 v1)
api_router.include_router(ip_pool_router)  # router 已自带 /ip-pool 前缀
api_router.include_router(concurrency_router)  # router 已自带 /concurrency 前缀
api_router.include_router(cookies_router)  # router 已自带 /cookies 前缀
api_router.include_router(creator_router)  # router 已自带 /creator 前缀
api_router.include_router(mediacrawler_router)  # /mediacrawler
# crawler_router (import cost ~1.5s due to crawlers.hybrid + tiktok/douyin models)
# is registered lazily by fastapi_app.main._mount_crawler_router after startup.
api_router.include_router(tikhub_router)  # router 已自带 /tikhub 前缀
api_router.include_router(persona_proxy_router)  # /persona-proxy 代理网关
api_router.include_router(persona_router)  # /persona Dashboard 托管
api_router.include_router(easel_bridge_router)  # /easel Easel 工作台托管
api_router.include_router(skills_router)  # /skills 技能库注册中心
api_router.include_router(workshop_router)  # /workshop 创作工坊
api_router.include_router(video_pipeline_router)  # /video-pipeline 视频流水线（HyperFrames）
api_router.include_router(content_library_router)  # /content-library 原生内容库（outputs 直读）
api_router.include_router(profile_router)  # /content-library/profile 账号画像（build/list/get）
api_router.include_router(receipts_router)  # /receipts 发布回执（Phase 0.1）
api_router.include_router(webhooks_router)  # /webhooks Webhook（Phase 5）
api_router.include_router(health_router)  # /health 账号健康（Phase 1）
api_router.include_router(review_router)  # /review 审核队列（Phase 3.3）
api_router.include_router(artifacts_router)  # /artifacts 统一产物总线
api_router.include_router(dedup_router)  # /dedup 去重查重（Phase 4.3）
api_router.include_router(insight_router)  # /insights 数据洞察（Phase 4.2）

# 注册平台路由
api_router.include_router(douyin_router)  # router 已自带 /platforms/douyin 前缀
api_router.include_router(kuaishou_router)  # router 已自带 /platforms/kuaishou 前缀
api_router.include_router(xiaohongshu_router)  # router 已自带 /platforms/xiaohongshu 前缀
api_router.include_router(tencent_router)  # router 已自带 /platforms/tencent 前缀
api_router.include_router(bilibili_router)  # router 已自带 /platforms/bilibili 前缀
api_router.include_router(platform_tasks_router)  # router 已自带 /platforms/tasks 前缀
api_router.include_router(tools_router)  # 开发者工具 /tools 前缀
api_router.include_router(ccswitch_router)  # /ccswitch 前缀
api_router.include_router(tool_catalog_router)  # 声明式工具目录 /tool-catalog 前缀

# LaomaAI-Fusion 扩展（P0-P1 能力）
api_router.include_router(fusion_router)  # /fusion 前缀（AI多Provider/平台风格/生图/热点/审核/模型广场/技能工坊/认知/NL→SQL/配置中心）

# M1 · AI 生图（澜途 /ai-design/* 复刻；复用 fusion_ai.image_generators + M3 积分扣费）
api_router.include_router(ai_design_router)  # /ai-design 前缀（capabilities / generate）

# M2 · AI 智能体风格训练（澜途 /system/ai-agents 复刻；配额 + LLM 抽取 + M1 注入）
api_router.include_router(ai_agents_router)  # /ai-design/agents 前缀（列表/配额/CRUD）

# 新增路由：任务状态机/平台字段/登录态检查/内容版本（Phase 0.2/1.1-1.6/3.1+3.3）
api_router.include_router(task_state_machine_router, prefix="/task-state", tags=["任务状态机"])
api_router.include_router(platform_fields_router, prefix="/platform-fields", tags=["平台字段管理"])
api_router.include_router(platform_login_checker_router, prefix="/login-check", tags=["登录态检查"])
api_router.include_router(content_variant_router, prefix="/content-variants", tags=["内容版本管理"])
api_router.include_router(diagnostics_router, prefix="/diagnostics", tags=["诊断工件采集"])
api_router.include_router(monitor_router, prefix="/monitor", tags=["任务监控"])
api_router.include_router(selectors_router, prefix="/selectors", tags=["选择器管理"])
api_router.include_router(matrix_route_router)


@api_router.get("/ping")
async def ping():
    """测试接口"""
    return {"message": "pong"}
