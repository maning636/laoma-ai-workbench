"""Cloud Service 入口(FastAPI app)。

挂载:
  - `cloud_service/auth/router.py`       → `/cloud/auth/*`
  - `cloud_service/billing/router.py`    → `/cloud/subscription | /cloud/usage | /cloud/license`

启动:
  开发: `uvicorn cloud_service.main:app --reload --port 8000`
  生产: `uvicorn cloud_service.main:app --host 0.0.0.0 --port 8000 --workers 4`

注意:本模块不做隐式 init_db,由 lifespan 触发;TestClient 场景也会自动走该钩子,
便于内存集成测试。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .auth.router import router as auth_router
from .billing.router import router as billing_router
from .db import init_db
from .llm_proxy.router import router as llm_proxy_router
from .payment.router import router as payment_router
from .settings import get_settings


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """应用生命周期:启动时幂等建表 + seed prompt 库。"""
    init_db()
    yield


app = FastAPI(
    title=get_settings()["app_name"],
    version="0.3.0",
    description="Prism-Fusion Cloud Backend (C12 auth + C13 billing + C14 llm proxy + C19 payment)",
    lifespan=_lifespan,
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
