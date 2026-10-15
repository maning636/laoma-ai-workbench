"""
FastAPI 主应用入口
"""
import os
import asyncio
import time
# Force Playwright to use global browsers BEFORE any imports
# os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'

from fastapi import FastAPI, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from datetime import datetime
from pathlib import Path
import sys
import shutil

# Windows: Ensure ProactorEventLoopPolicy for asyncio subprocess support.
# (Playwright needs subprocess to launch browser processes.)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 添加父目录到路径以导入现有模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from .core import settings, logger, setup_logging, AppException
from .schemas.common import ErrorResponse, HealthResponse
from .api.v1.router import api_router
# Removed: old login router - now using V2 auth router in api.v1.auth
# from .api.login import router as login_router


# 初始化日志
setup_logging()

# 创建FastAPI应用
app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.DESCRIPTION,
    version=settings.VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

@app.middleware("http")
async def _normalize_duplicated_api_prefix(request: Request, call_next):
    # Next.js rewrites may accidentally turn `/api/v1/...` into `/api/v1/v1/...`.
    # 过渡兼容:部分 6 模块(dedup/health/insight/receipts/review/webhooks)
    # 曾经的 router 自带 /api/v1 前缀,加上外层挂载后又形成 `/api/v1/api/v1/xxx`。
    # 现已从 router 中移除冗余前缀,但保留归一化规则让按旧双重 URL 调用的前端继续工作。
    path = request.scope.get("path") or ""
    if path.startswith("/api/v1/v1/"):
        request.scope["path"] = path.replace("/api/v1/v1/", "/api/v1/", 1)
    elif path.startswith("/api/v1/api/v1/"):
        request.scope["path"] = path.replace("/api/v1/api/v1/", "/api/v1/", 1)
    return await call_next(request)


# 配置CORS - 允许所有来源（开发环境）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，避免 CORS 问题
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# 配置静态文件服务（用于访问上传的封面图片等）
from fastapi.staticfiles import StaticFiles

# 确保上传目录存在
upload_dir = Path(settings.UPLOAD_DIR)
upload_dir.mkdir(parents=True, exist_ok=True)

# 挂载静态文件目录
app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")


# B-B (2026-10-16): 把 Douyin_TikTok_API 的 import+mount 从模块加载阶段挪到
# 启动后异步执行。import `douyin_tiktok_api.app.main` 会连带加载 pywebio /
# numpy / pyfiglet 等重依赖，实测单步耗时 ~4.8s，占了 uvicorn 冷启动
# 到 /health 200 的绝大部分时间。
# 挪到 async 后台任务后：
#   * /health 在 <300ms 内响应，主 API 立即可用
#   * douyin 端点（/api/v1/douyin-tiktok/*）在挂载完成后（约 +1s 后台）可用
#   * 失败降级：只在启动日志留 warning，主应用不受影响
#   * 关闭/缺失：settings.DOUYIN_TIKTOK_API_ENABLED=False 或目录不存在时
#     完全不产生导入成本
_DOUYIN_MOUNT_TASK: asyncio.Future | None = None  # legacy, replaced by _DEFERRED_MOUNT_TASK
_DEFERRED_MOUNT_TASK: asyncio.Future | None = None


async def _mount_crawler_router() -> None:
    """Lazy-mount the crawler API router (~1.5s import cost).

    The crawler module pulls in `crawlers.hybrid` plus tiktok/douyin
    pydantic-heavy models, and instantiates 3 crawler objects at import
    time.

    IMPORTANT: this is intentionally called via `loop.run_in_executor`
    (see ``_mount_deferred_components``) because the underlying import is
    synchronous.  Running it as a normal ``await`` inside the event loop
    would block every in-flight HTTP request until the import finishes,
    which silently re-introduces the exact cold-start latency we are
    trying to remove.
    """
    import asyncio as _asyncio

    loop = _asyncio.get_running_loop()

    def _do_mount() -> None:
        try:
            t0 = time.perf_counter()
            from fastapi_app.api.v1.crawler.router import router as crawler_router
            from fastapi_app.api.v1.router import api_router

            api_router.include_router(
                crawler_router, prefix="/crawler", tags=["混合爬虫"]
            )
            logger.info(
                f"[Crawler] Router mounted ({time.perf_counter() - t0:.2f}s, lazy)"
            )
        except Exception as exc:
            logger.warning(f"[Crawler] Lazy router mount failed: {exc}")

    await loop.run_in_executor(None, _do_mount)


async def _mount_douyin_tiktok_api() -> None:
    """Lazy-mount douyin_tiktok_api sub-app after main app is up.

    Called from ``_mount_deferred_components`` after ``_mount_crawler_router``
    so the crawler import has already injected ``douyin_tiktok_api`` into
    ``sys.path`` — otherwise its transitive ``import crawlers.*`` fails with
    ``ModuleNotFoundError``.

    Runs the sync import inside ``loop.run_in_executor`` for the same
    reason as ``_mount_crawler_router``: keep the event loop free so
    ``/health`` responds immediately while this import happens in a worker
    thread.
    """
    if not settings.DOUYIN_TIKTOK_API_ENABLED:
        return

    import asyncio as _asyncio

    loop = _asyncio.get_running_loop()
    douyin_root = Path(settings.BASE_DIR) / "douyin_tiktok_api"
    if not douyin_root.exists():
        logger.warning(
            f"[Douyin_TikTok_API] Repo not found at {douyin_root}; skipping lazy mount"
        )
        return

    def _do_mount() -> None:
        try:
            t0 = time.perf_counter()
            from douyin_tiktok_api.app.main import app as douyin_tiktok_app  # type: ignore
            # Mutating the ASGI app from a worker thread while the loop is
            # serving requests is technically racy; FastAPI's `mount` is a
            # plain dict insertion on the routes list, which is safe under
            # the GIL.  If this ever becomes a problem we can hop back onto
            # the loop with `await loop.run_in_executor(None, app.mount, ...)`.
            app.mount(settings.DOUYIN_TIKTOK_API_PREFIX, douyin_tiktok_app)
            logger.info(
                f"[Douyin_TikTok_API] Mounted at {settings.DOUYIN_TIKTOK_API_PREFIX} "
                f"({time.perf_counter() - t0:.2f}s, lazy)"
            )
        except ImportError as exc:
            logger.warning(
                f"[Douyin_TikTok_API] Import failed: {exc}. Check dependencies (PyWebIO, etc.)"
            )
        except Exception as exc:
            logger.warning(f"[Douyin_TikTok_API] Mount failed: {exc}")

    await loop.run_in_executor(None, _do_mount)


async def _mount_deferred_components() -> None:
    """Chain: crawler router -> douyin sub-app.

    Both halves run their synchronous imports inside the default thread
    executor so the ASGI event loop stays responsive — without this,
    /health would still be blocked for ~2s (crawler 1.3s + douyin 0.5s)
    by imports that "look" lazy because they live in a create_task but
    actually still execute on the event loop thread.
    """
    await _mount_crawler_router()
    await _mount_douyin_tiktok_api()


# 全局异常处理
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """处理自定义应用异常"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.message,
            "detail": str(exc)
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求验证异常"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": "请求参数验证失败",
            "detail": exc.errors()
        }
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """处理未捕获的异常"""
    logger.error("未处理的异常: {}", str(exc), exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": "服务器内部错误",
            "detail": str(exc) if settings.DEBUG else "请联系管理员"
        }
    )


# 启动和关闭事件
async def _run_startup_preflight():
    """P1b-3: 启动末段异步执行一次 preflight 聚合。

    设计要点：
    - 通过 asyncio.create_task 调度，**不阻塞启动**
    - 全 try/except，任何异常仅 warning，绝不抛
    - 判定 missing：ready=False 且 installed=False 且 reachable=False（三者皆为真）
    """
    try:
        from fastapi_app.api.v1.system.preflight import run_preflight_check
        result = await run_preflight_check()
        missing = [
            k for k, v in result.items()
            if isinstance(v, dict)
            and not v.get("ready")
            and not v.get("installed")
            and v.get("reachable") is False
        ]
        if missing:
            logger.warning(f"[Startup] 组件未就绪: {missing}")
        else:
            logger.info("[Startup] 全部依赖就绪")
    except Exception as e:
        logger.warning(f"[Startup] preflight 失败: {e}")


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info(f" {settings.PROJECT_NAME} v{settings.VERSION} loading...")
    logger.info(f" API: http://{settings.HOST}:{settings.PORT}/api/docs")
    logger.info(f" 数据库: {settings.DATABASE_PATH}")

    # B-B (2026-10-16): fire-and-forget the deferred mounts as a single
    # chained task so the implicit sys.path dependency between crawler
    # and douyin_tiktok_api (crawler's import injects `crawlers` on the
    # path that douyin needs) is preserved.  Holding a strong ref
    # prevents the coroutine from being GC'd mid-flight.
    global _DEFERRED_MOUNT_TASK
    _DEFERRED_MOUNT_TASK = asyncio.create_task(_mount_deferred_components())

    try:
        os.environ.setdefault("LAOMA_DATA_DIR", str(settings.DATA_DIR))
    except Exception as e:
        logger.warning(f"[Startup] setdefault LAOMA_DATA_DIR failed: {e}")

    def _migrate_dir(label: str, old_path: Path, new_path: Path) -> None:
        try:
            if old_path.resolve() == new_path.resolve():
                new_path.mkdir(parents=True, exist_ok=True)
                return
        except Exception:
            pass

        if not old_path.exists():
            # If data was previously moved to LOCALAPPDATA, move it back when using project data dir.
            alt_root = os.getenv("LOCALAPPDATA")
            if alt_root:
                alt_path = Path(alt_root) / "老马AI工作台" / "data" / old_path.name
                if alt_path.exists() and not new_path.exists():
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(alt_path), str(new_path))
                    logger.info(f"[Data] Restored {label}: {alt_path} -> {new_path}")
                    return
            new_path.mkdir(parents=True, exist_ok=True)
            return

        new_path.parent.mkdir(parents=True, exist_ok=True)
        if not new_path.exists():
            shutil.move(str(old_path), str(new_path))
            logger.info(f"[Data] Moved {label}: {old_path} -> {new_path}")
            return

        # Both exist: move contents if destination is empty.
        try:
            if any(new_path.iterdir()):
                logger.warning(f"[Data] {label} exists in both locations, keeping new: {new_path}")
                return
        except Exception:
            logger.warning(f"[Data] {label} exists in both locations, keeping new: {new_path}")
            return

        moved = 0
        for item in old_path.iterdir():
            shutil.move(str(item), str(new_path / item.name))
            moved += 1
        try:
            old_path.rmdir()
        except Exception:
            pass
        logger.info(f"[Data] Moved {moved} items for {label} -> {new_path}")

    try:
        _migrate_dir("cookiesFile", Path(settings.BASE_DIR) / "cookiesFile", Path(settings.COOKIE_FILES_DIR))
        _migrate_dir("fingerprints", Path(settings.BASE_DIR) / "fingerprints", Path(settings.FINGERPRINTS_DIR))
        _migrate_dir("browser_profiles", Path(settings.BASE_DIR) / "browser_profiles", Path(settings.BROWSER_PROFILES_DIR))
    except Exception as e:
        logger.warning(f"[Data] Migration failed (continuing): {e}")

    # Ensure video directory exists in packaged/runtime environments
    try:
        Path(settings.VIDEO_FILES_DIR).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"[Data] Failed to ensure videoFile dir: {e}")

    # Ensure directories exist even if data was cleaned.
    for dir_path in (
        Path(settings.COOKIE_FILES_DIR),
        Path(settings.FINGERPRINTS_DIR),
        Path(settings.BROWSER_PROFILES_DIR),
        Path(settings.VIDEO_FILES_DIR),
    ):
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[Data] Failed to ensure dir {dir_path}: {e}")


    # Ensure local SQLite schema is initialized (fresh install / older DB compatibility)
    try:
        from fastapi_app.db.schema import ensure_main_db_schema
        from fastapi_app.db.session import main_db_pool

        with main_db_pool.get_connection() as conn:
            ensure_main_db_schema(conn)
        logger.info("[DB] Schema check completed")
    except Exception as e:
        logger.warning(f"[DB] Schema check failed (continuing): {e}")

    # If MySQL is enabled, ensure minimal tables exist (migration should still be run for data copy).
    try:
        from fastapi_app.db.runtime import mysql_enabled
        if mysql_enabled():
            from fastapi_app.db.sa_models import metadata
            from fastapi_app.db.sqlalchemy_engine import get_engine
            metadata.create_all(get_engine())
            logger.info("[DB] MySQL enabled; ensured SQLAlchemy tables exist")
    except Exception as e:
        logger.warning(f"[DB] MySQL table ensure failed (continuing): {e}")

    # Initialize task queue manager (SQLite-backed)
    try:
        from myUtils.task_queue_manager import get_task_manager

        task_db_path = Path(settings.BASE_DIR) / "db" / "task_queue.db"
        app.state.task_manager = get_task_manager(
            db_path=task_db_path,
            max_workers=settings.TASK_QUEUE_MAX_WORKERS,
        )
        logger.info(
            f"[TaskQueue] Initialized: db={task_db_path} workers={settings.TASK_QUEUE_MAX_WORKERS}"
        )
    except Exception as e:
        logger.warning(f"[TaskQueue] Init failed (tasks API disabled): {e}")

    # Ensure manual_tasks table exists (SQLite task_queue.db)
    try:
        try:
            from db.create_manual_tasks_table import create_manual_tasks_table
        except Exception:
            import importlib.util
            module_path = Path(settings.BASE_DIR) / "db" / "create_manual_tasks_table.py"
            spec = importlib.util.spec_from_file_location("create_manual_tasks_table", module_path)
            if not spec or not spec.loader:
                raise
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            create_manual_tasks_table = module.create_manual_tasks_table
        create_manual_tasks_table()
        logger.info("[TaskQueue] manual_tasks table ensured")
    except Exception as e:
        logger.warning(f"[TaskQueue] manual_tasks table init failed: {e}")

    # 初始化批量发布服务（不再需要 TaskQueueManager）
    try:
        from myUtils.batch_publish_service import get_batch_publish_service
        # 初始化服务（不再依赖任务队列）
        get_batch_publish_service()
        logger.info("Celery/Redis 发布队列已加载")
    except Exception as e:
        logger.warning(f"批量发布服务初始化失败: {e}")

    # AI 服务配置统一走 `/api/v1/ai` 的 model-configs（ai_model_configs 表）按需加载，
    # 不再在启动时初始化独立的 AIClient / ModelManager（旧的 ai_service/config.json 已废弃）。


    # Initialize OpenClaw/Hermes agent
    # B10 懒加载:startup 不再直接初始化 agent。agent 首次调用时(get_openclaw_agent /
    # get_hermes_agent / run_hermes_goal)由 hermes_agent.py 内的 _agent_init_lock
    # 保护并 await initialize,首次慢约 4s,后续直接返回。此处不再阻塞 startup。
    # 若启动需要预热,可通过环境变量或后续任务重新加回。

    # Hermes UI can be managed centrally by Supervisor in desktop mode.
    # B10 懒加载:startup 不再 create_task(start_hermes_dashboard())。
    # dashboard 首次真正请求时(POST /api/v1/agent/config/hermes/dashboard/start)
    # 由 ensure_hermes_dashboard_started() 触发,合并并发首次请求。
    # 首次请求会 await ~18s 启动流程,前端 hermes-embedded-host 已有 loading/重试 UI。
    # 注释:保留旧后台启动逻辑仅作参考,已在 hermes_agent 内实现等价的
    # 懒加载入口(见 ensure_hermes_dashboard_started),避免 startup 承担 ~18s。

    # 启动账号数据清理调度器（每6小时清理一次）
    try:
        from fastapi_app.core.account_cleanup_scheduler import start_cleanup_scheduler
        await start_cleanup_scheduler()
        logger.info("Account cleanup scheduler started (every 6 hours)")
    except Exception as e:
        logger.warning(f"账号数据清理调度器启动失败: {e}")

    try:
        from fastapi_app.agent.hermes_update import start_hermes_update_scheduler
        await start_hermes_update_scheduler()
        logger.info("Hermes upstream update scheduler started")
    except Exception as e:
        logger.warning(f"Hermes update scheduler startup failed: {e}")

    # P3-3a: 注册 Easel 上游更新调度器（默认 enabled=False，仅心跳 check，不自动 apply）
    try:
        from fastapi_app.agent.easel_update import start_easel_update_scheduler
        await start_easel_update_scheduler()
        logger.info("Easel update scheduler started")
    except Exception as e:
        logger.warning(f"Easel update scheduler startup failed: {e}")

    # P1b-3: 启动末段异步跑一次 preflight 聚合（不阻塞启动）
    asyncio.create_task(_run_startup_preflight())



@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info("应用正在关闭...")

    try:
        from fastapi_app.agent.hermes_update import stop_hermes_update_scheduler
        await stop_hermes_update_scheduler()
    except Exception as e:
        logger.warning(f"Hermes update scheduler shutdown failed: {e}")

    # P3-3a: 停止 Easel 上游更新调度器
    try:
        from fastapi_app.agent.easel_update import stop_easel_update_scheduler
        await stop_easel_update_scheduler()
    except Exception as e:
        logger.warning(f"Easel update scheduler shutdown failed: {e}")

    # 停止账号数据清理调度器
    try:
        from fastapi_app.core.account_cleanup_scheduler import stop_cleanup_scheduler
        await stop_cleanup_scheduler()
        logger.info("账号数据清理调度器已停止")
    except Exception as e:
        logger.warning(f"账号数据清理调度器停止失败: {e}")

    # Cleanup OpenClaw/Hermes agent
    try:
        agent = getattr(app.state, "openclaw_agent", None)
        if agent:
            await agent.cleanup()
            logger.info("OpenClaw/Hermes agent cleaned up")
    except Exception as e:
        logger.warning(f"OpenClaw/Hermes agent cleanup failed: {e}")

    try:
        from fastapi_app.agent.hermes_agent import stop_hermes_dashboard

        await stop_hermes_dashboard()
        logger.info("Hermes dashboard stopped")
    except Exception as e:
        logger.warning(f"Hermes dashboard shutdown failed: {e}")


    # 关闭数据库连接池
    from .db.session import main_db_pool, cookie_db_pool, ai_logs_db_pool
    main_db_pool.close_all()
    cookie_db_pool.close_all()
    ai_logs_db_pool.close_all()
    logger.info("应用已关闭")


# 根路由
@app.get("/", tags=["Root"])
async def root():
    """根路由"""
    return {
        "message": f"欢迎使用 {settings.PROJECT_NAME}",
        "version": settings.VERSION,
        "docs": "/api/docs"
    }


# 健康检查
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """健康检查接口"""
    return HealthResponse(
        status="healthy",
        version=settings.VERSION,
        timestamp=datetime.now().isoformat()
    )


# 注册API路由（唯一入口）
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# 注册文件服务路由（用于素材预览）
from .api.file_service import router as file_service_router
app.include_router(file_service_router, tags=["文件服务"])

# 注册登录SSE路由（已迁移到V2 auth router）
# Removed: old login router - now in /api/v1/auth
# app.include_router(login_router, prefix="/api", tags=["登录绑定"])


# 开发模式运行
if __name__ == "__main__":
    # Fix: Apply Playwright Windows Event Loop Policy for direct run
    try:
        from myUtils.automation_windows_fix import setup_windows_playwright_policy
        setup_windows_playwright_policy()
    except ImportError:
        pass

    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
