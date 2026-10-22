"""Cloud Service 入口(FastAPI app)。

挂载:
  - `cloud_service/auth/router.py`       → `/cloud/auth/*`
  - `cloud_service/billing/router.py`    → `/cloud/subscription | /cloud/usage | /cloud/license`
  - `cloud_service/billing/points_endpoints.py` → `/cloud/points/*`
  - `cloud_service/billing/admin_router.py`      → `/cloud/admin/*`(人工充值运营入口)
  - `cloud_service/payment/router.py`    → `/cloud/payment/*`(**默认下线**,见下)

线上支付下线(2026-10-22)
------------------------
网站备案 / ICP 许可证未落地,线上收款不具备合规前提,商业闭环改为
「线下人工充值 + 注册码」。因此:
  - `/cloud/payment/*` 默认返回 403 + 人工充值指引
    (`CLOUD_ONLINE_PAYMENT_ENABLED=true` 可恢复);
  - 支付专用的后台任务(订单超时清理 / 日终对账)不启动;
  - 积分入账改由 `POST /cloud/license/activate`(注册码激活)与
    `POST /cloud/admin/points/adjust`(管理端人工调整)承担。

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
  - 两者在**线上支付下线**时都不启动(见上)。
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth.router import router as auth_router
from .billing.admin_router import router as admin_router
from .billing.points_endpoints import router as billing_points_router
from .billing.router import router as billing_router
from .db import init_db
from .llm_proxy.router import router as llm_proxy_router
from .middleware import RateLimitMiddleware
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

    # 线上支付默认下线(2026-10-22):订单超时清理与日终对账都是**支付专用**后台任务,
    # 没有线上订单时它们只是空转 + 无谓的 DB 访问,直接不启动。
    # 备案到位后 `CLOUD_ONLINE_PAYMENT_ENABLED=true` 即自动恢复。
    online_payment_enabled = bool(
        settings.get("online_payment", {}).get("enabled", False)
    )
    if not online_payment_enabled:
        logger.info(
            "online payment DISABLED by env; order_timeout/reconcile tasks "
            "will not start (manual recharge via license activation instead)"
        )

    stop_event = asyncio.Event()
    background_tasks: list[asyncio.Task] = []

    # C-D: 是否启用跨 worker 分布式锁(Redis 不可达时会自动降级为无锁模式)
    task_lock_enabled = bool(lock_cfg.get("enabled", True))
    lock_ttl_seconds = int(lock_cfg.get("ttl_seconds", 0))
    if not task_lock_enabled:
        logger.info("task_lock DISABLED by env; each worker runs tasks independently")

    if timeout_cfg.get("enabled", True) and online_payment_enabled:
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
        logger.info(
            "order_timeout task not started (enabled=%s, online_payment=%s)",
            timeout_cfg.get("enabled", True), online_payment_enabled,
        )

    if reconcile_cfg.get("enabled", False) and online_payment_enabled:
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

# 2026-10-19 medium-hardening：请求级限流（Redis INCR + EXPIRE）。
# 覆盖 M3 高频/敏感端点；Redis 不可达时默认降级放行（打 warning）。
# 关闭开关：CLOUD_RATE_LIMIT_ENABLED=false（生产灰度或调试用）。
_rate_limit_enabled = (
    os.getenv("CLOUD_RATE_LIMIT_ENABLED", "true").lower() in {"1", "true", "yes"}
)
if _rate_limit_enabled:
    app.add_middleware(
        RateLimitMiddleware,
        window_seconds=int(os.getenv("CLOUD_RATE_LIMIT_WINDOW_SECONDS", "60")),
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
app.include_router(billing_points_router, prefix="/cloud", tags=["cloud-billing-points"])
# 管理端(线下人工充值):积分调整 / 订阅开通 / 用户查询。
# 鉴权走 `X-Admin-Token` header + `CLOUD_ADMIN_TOKEN`,未配置则全部 503。
app.include_router(admin_router, prefix="/cloud", tags=["cloud-admin"])
# LLM 代理挂在 /cloud 下(router 内部路径含 /llm/* → 最终 /cloud/llm/*)
app.include_router(llm_proxy_router, prefix="/cloud", tags=["cloud-llm"])
# 支付(C19):线上支付默认下线,router 内部依赖会统一返回 403 + 人工充值指引;
# 备案到位后设 `CLOUD_ONLINE_PAYMENT_ENABLED=true` 即恢复。
app.include_router(payment_router, prefix="/cloud", tags=["cloud-payment"])


@app.get("/health", tags=["meta"])
def health() -> dict:
    """存活探针(供负载均衡 / 容器编排使用)。"""
    return {"status": "ok", "service": "cloud", "version": "0.3.0"}


if __name__ == "__main__":  # pragma: no cover - manual dev convenience
    import uvicorn

    uvicorn.run("cloud_service.main:app", host="127.0.0.1", port=8000, reload=True)
