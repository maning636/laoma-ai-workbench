"""Cloud Service 入口(FastAPI app)。

挂载:
  - `cloud_service/auth/router.py`       → `/cloud/auth/*`
  - `cloud_service/billing/router.py`    → `/cloud/subscription | /cloud/usage | /cloud/license`
  - `cloud_service/billing/points_endpoints.py` → `/cloud/points/*`
  - `cloud_service/billing/admin_router.py`      → `/cloud/admin/*`(人工充值运营入口)

商业闭环:人工充值(2026-10-23 起)
--------------------------------
平台支付手段(支付宝 / 微信支付)**已彻底删除**:整个 `cloud_service/payment/`
包、`POST /cloud/points/recharge`、订单超时清理与日终对账两个后台任务
一并移除,云端不再有「创建订单 / 支付回调 / 订单查询 / 退款」任何端点,
也没有 `orders` 表。

现在的唯一收款路径:
  用户加产品方微信 → 人工转账 → 人工签发注册码 → 客户端输入注册码激活。
积分入账同样有两条且都不依赖支付通道:
  - `POST /cloud/license/activate`   —— 注册码激活时注入注册码携带的积分;
  - `POST /cloud/admin/points/adjust` —— 管理端人工增减账户积分。

启动:
  开发: `uvicorn cloud_service.main:app --reload --port 8000`
  生产: `uvicorn cloud_service.main:app --host 0.0.0.0 --port 8000 --workers 4`

注意:本模块不做隐式 init_db,由 lifespan 触发;TestClient 场景也会自动走该钩子,
便于内存集成测试。
"""

from __future__ import annotations

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
from .settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """应用生命周期:启动时幂等建表 + seed prompt 库 + seed 价目表。

    2026-10-23 起不再启动任何后台任务 —— 原先的两个后台任务
    (订单超时清理 / 日终对账)都是**支付专用**,随平台支付删除一并移除。
    """
    get_settings()
    init_db()

    try:
        yield
    finally:
        pass


app = FastAPI(
    title=get_settings()["app_name"],
    version="0.3.0",
    description=(
        "Prism-Fusion Cloud Backend "
        "(C12 auth + C13 billing + C14 llm proxy;人工充值,无在线支付)"
    ),
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


@app.get("/health", tags=["meta"])
def health() -> dict:
    """存活探针(供负载均衡 / 容器编排使用)。"""
    return {"status": "ok", "service": "cloud", "version": "0.3.0"}


if __name__ == "__main__":  # pragma: no cover - manual dev convenience
    import uvicorn

    uvicorn.run("cloud_service.main:app", host="127.0.0.1", port=8000, reload=True)
