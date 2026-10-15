"""Cloud Service 入口(FastAPI app)。

挂载:
  - `cloud_service/auth/router.py`       → `/cloud/auth/*`
  - `cloud_service/billing/router.py`    → `/cloud/subscription | /cloud/usage | /cloud/license`

启动:
  开发: `uvicorn cloud_service.main:app --reload --port 8000`
  生产: `uvicorn cloud_service.main:app --host 0.0.0.0 --port 8000 --workers 4`

注意:本模块不做隐式 init_db,由 lifespan 触发;TestClient 场景也会自动走该钩子,
便于内存集成测试。

Lifespan 内启动的后台任务(P4 / P6):
  - `close_expired_orders_task` : 订单超时清理,默认开启,只动 `created`。
  - `reconcile_task`            : 日终对账,**默认关闭**(env 开关),
                                   因为 `platform_bills=None` 会触发 adapter 的
                                   `fetch_bill()`,接入真实商户 adapter 后就是
                                   外部调用,不能默认在生产里悄悄跑。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth.router import router as auth_router
from .billing.router import router as billing_router
from .db import init_db
from .llm_proxy.router import router as llm_proxy_router
from .payment.reconciliation import reconcile_task
from .payment.router import router as payment_router
from .payment.scheduler import close_expired_orders_task
from .settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """应用生命周期:启动时幂等建表 + seed prompt 库 + 启动后台任务。"""
    settings = get_settings()
    init_db()

    timeout_cfg = settings.get("order_timeout", {})
    reconcile_cfg = settings.get("reconcile", {})
    lock_cfg = settings.get("task_lock", {})

    stop_event = asyncio.Event()
    background_tasks: list[asyncio.Task] = []

    # C-D: 是否启用跨 worker 分布式锁(Redis 不可达时会自动降级为无锁模式)
    task_lock_enabled = bool(lock_cfg.get("enabled", True))
    lock_ttl_seconds = int(lock_cfg.get("ttl_seconds", 0))
    if not task_lock_enabled:
        logger.info("task_lock DISABLED by env; each worker runs tasks independently")

    if timeout_cfg.get("enabled", True):
        background_tasks.append(asyncio.create_task(
            close_expired_orders_task(
                interval_seconds=float(timeout_cfg.get("interval_seconds", 3600)),
                hours=int(timeout_cfg.get("hours", 24)),
                stop_event=stop_event,
                lock_enabled=task_lock_enabled,
                lock_key="cloud:lock:order_timeout",
                lock_ttl_seconds=lock_ttl_seconds,
            ),
            name="close_expired_orders",
        ))
        logger.info(
            "order_timeout task started: interval=%ds hours=%d lock=%s",
            timeout_cfg.get("interval_seconds", 3600),
            timeout_cfg.get("hours", 24),
            task_lock_enabled,
        )
    else:
        logger.info("order_timeout task disabled by env")

    if reconcile_cfg.get("enabled", False):
        background_tasks.append(asyncio.create_task(
            reconcile_task(
                interval_seconds=float(reconcile_cfg.get("interval_seconds", 86400)),
                lookback_hours=int(reconcile_cfg.get("lookback_hours", 24)),
                stop_event=stop_event,
                # C-D: 分布式锁
                lock_enabled=task_lock_enabled,
                lock_key="cloud:lock:reconcile",
                lock_ttl_seconds=lock_ttl_seconds,
                # C-E: 超时/退避/限次
                fetch_timeout_seconds=float(
                    reconcile_cfg.get("fetch_timeout_seconds", 30.0),
                ),
                backoff_base_seconds=float(
                    reconcile_cfg.get("backoff_base_seconds", 300.0),
                ),
                backoff_max_seconds=float(
                    reconcile_cfg.get("backoff_max_seconds", 3600.0),
                ),
                daily_limit=int(reconcile_cfg.get("daily_limit", 10)),
                daily_limit_base_key=reconcile_cfg.get(
                    "daily_limit_base_key", "cloud:payment:reconcile",
                ),
            ),
            name="reconcile_day",
        ))
        logger.info(
            "reconcile task started: interval=%ds lookback_hours=%d lock=%s "
            "fetch_timeout=%.1fs backoff=%.1fs-%.1fs daily_limit=%d "
            "(platform_bills=None 会触发 adapter.fetch_bill,接入真实 "
            "adapter 后即为外部调用)",
            reconcile_cfg.get("interval_seconds", 86400),
            reconcile_cfg.get("lookback_hours", 24),
            task_lock_enabled,
            float(reconcile_cfg.get("fetch_timeout_seconds", 30.0)),
            float(reconcile_cfg.get("backoff_base_seconds", 300.0)),
            float(reconcile_cfg.get("backoff_max_seconds", 3600.0)),
            int(reconcile_cfg.get("daily_limit", 10)),
        )
    else:
        logger.info(
            "reconcile task DISABLED by default (set CLOUD_RECONCILE_ENABLED=true "
            "to enable; platform_bills=None would call adapter.fetch_bill)"
        )

    try:
        yield
    finally:
        stop_event.set()
        if background_tasks:
            # 用 wait_for 兜底,防止任务在意外场景卡住把整个 shutdown 挂住;
            # 但优先用 gather(return_exceptions=True),不吞掉 CancelledError 的
            # 语义 —— 各任务内部捕获普通 Exception 并记录日志,只在被外部
            # cancel 时才抛 CancelledError(此时本进程已经在退出,忽略即可)。
            await asyncio.gather(
                *background_tasks, return_exceptions=True
            )


app = FastAPI(
    title=get_settings()["app_name"],
    version="0.3.0",
    description="Prism-Fusion Cloud Backend (C12 auth + C13 billing + C14 llm proxy + C19 payment)",
    lifespan=_lifespan,
)

# CORS:允许前端(默认 3000)直连 cloud_service。
# allow_credentials=False:前端 client-gateway 使用 credentials:"omit",
# 不依赖 cookie 跨域;这样即便未来误配 "*" 也不会泄露跨站 cookie。
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings()["cors_origins"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/cloud/auth", tags=["cloud-auth"])
app.include_router(billing_router, prefix="/cloud", tags=["cloud-billing"])
# LLM 代理挂在 /cloud 下(router 内部路径含 /llm/* → 最终 /cloud/llm/*)
app.include_router(llm_proxy_router, prefix="/cloud", tags=["cloud-llm"])
# 支付(C19):router 内部路径含 /payment/* → 最终 /cloud/payment/*
app.include_router(payment_router, prefix="/cloud", tags=["cloud-payment"])


@app.get("/health", tags=["meta"])
def health() -> dict:
    """存活探针(供负载均衡 / 容器编排使用)。"""
    return {"status": "ok", "service": "cloud", "version": "0.3.0"}


if __name__ == "__main__":  # pragma: no cover - manual dev convenience
    import uvicorn

    uvicorn.run("cloud_service.main:app", host="127.0.0.1", port=8000, reload=True)
