"""Payment 端点(C19)。

前缀:`/cloud`(在 `main.py` 中挂载)。
端点:
  POST /cloud/payment/create_order           (JWT) 创建订单,返回渠道支付参数
  POST /cloud/payment/callback/{channel}     (无 JWT) 支付回调,验签后激活订阅
  GET  /cloud/payment/order/{order_no}       (JWT) 查询订单状态

复用:
  - `..auth.router.get_current_user` (C12 的 JWT 依赖)
  - `..billing.router.activate_for_user` (C13 的激活函数)
  - `..db.get_db`

幂等约定:
  - 回调处理加锁 + 检查 `Order.status`;
  - 同一 order_no 重复回调 → 首次激活 + 置 paid;后续回调 → 直接 no-op 返回;
  - 因此同一订单重复调用 billing.activate 不会发生,不会重复延长时间。
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.models import User
from ..auth.router import get_current_user
from ..billing.router import activate_for_user, _serialize_subscription, _get_usage, _current_period
from ..db import get_db
from . import alipay as _alipay_module  # noqa: F401  -- 触发 register_adapter
from . import wechat as _wechat_module  # noqa: F401
from .adapter import get_adapter
from .models import (
    CHANNEL_ALIPAY,
    CHANNEL_WECHAT,
    SUPPORTED_CHANNELS,
    STATUS_CREATED,
    STATUS_PAID,
    Order,
)
from .schemas import (
    CallbackResponse,
    CreateOrderRequest,
    CreateOrderResponse,
    OrderResponse,
)


router = APIRouter()


# ──────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _price_for(plan: str, days: int) -> float:
    """按 plan/days 计算订单金额(元)。

    默认价目表(可通过 env `CLOUD_PAYMENT_PRICES` JSON 覆盖):
      - pro 30d  = ¥99.00
      - pro 365d = ¥799.00
      - free     = ¥0.00 (允许 0 元激活)
    其它 days 按 pro 30d 折算(每天 3.3 元)。
    """
    import json
    raw = os.getenv("CLOUD_PAYMENT_PRICES")
    table: dict[str, float] = {
        "pro_30": 99.00,
        "pro_365": 799.00,
        "free": 0.00,
    }
    if raw:
        try:
            table.update({k: float(v) for k, v in json.loads(raw).items()})
        except (ValueError, json.JSONDecodeError):
            pass  # 忽略畸形配置,回退默认
    if plan == "free":
        return float(table["free"])
    if days == 30:
        return float(table["pro_30"])
    if days == 365:
        return float(table["pro_365"])
    # 按比例折算(每天 3.3 元 ≈ 99/30),保留 2 位
    per_day = float(table["pro_30"]) / 30
    return round(per_day * days, 2)


def _generate_order_no() -> str:
    """生成唯一订单号: `PF{YYYYMMDDHHMMSS}{8位随机十六进制}`。"""
    ts = _utcnow().strftime("%Y%m%d%H%M%S")
    rnd = secrets.token_hex(4)
    return f"PF{ts}{rnd}"


def _notify_url(channel: str) -> str:
    """构造回调 URL(生产应使用真实域名,沙箱用相对路径)。"""
    return _get_str("CLOUD_PAYMENT_NOTIFY_URL") or f"/cloud/payment/callback/{channel}"


def _return_url() -> str:
    return _get_str("CLOUD_PAYMENT_RETURN_URL") or "/payment/success"


def _get_str(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────

@router.post(
    "/payment/create_order",
    response_model=CreateOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    payload: CreateOrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreateOrderResponse:
    """创建支付订单,返回渠道支付参数。

    - 生成全局唯一 order_no
    - 落库 status=created
    - 调 adapter.create_payment 生成 form_html / code_url
    """
    adapter = get_adapter(payload.channel)
    if adapter is None:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported channel: {payload.channel}",
        )

    amount = _price_for(payload.plan, payload.days)
    order_no = _generate_order_no()

    order = Order(
        user_id=current_user.id,
        order_no=order_no,
        amount=amount,
        plan=payload.plan,
        days=payload.days,
        status=STATUS_CREATED,
        channel=payload.channel,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    pay_params = adapter.create_payment(
        order_no=order_no,
        amount=amount,
        plan=payload.plan,
        days=payload.days,
        notify_url=_notify_url(payload.channel),
        return_url=_return_url(),
    )

    return CreateOrderResponse(
        order_no=order_no,
        amount=amount,
        plan=payload.plan,
        days=payload.days,
        channel=payload.channel,
        pay_params=pay_params,
    )


@router.post(
    "/payment/callback/{channel}",
    response_model=CallbackResponse,
)
async def payment_callback(
    channel: str,
    request: Request,
    db: Session = Depends(get_db),
) -> CallbackResponse:
    """第三方支付渠道回调。

    流程:
      1. adapter.verify_callback 验签 + 解析字段
      2. 按 out_trade_no 找订单;不存在 → 返回 400(可能被篡改 / 未创建)
      3. **幂等**: 若 order.status == paid,直接 no-op 返回
      4. 校验金额: 回调 amount 与订单 amount 不一致 → 拒绝(不置 paid)
      5. 调 billing.activate_for_user 激活订阅
      6. 置 order.status=paid, 记录 pay_trade_no / paid_at

    注:此端点用 `async def` 是因为 starlette 的 `Request.json()` 是 async;
    内部 SQLAlchemy 调用仍是同步的,在事件循环线程里跑,适合"短请求 + 无外部 IO"
    的支付回调场景。生产环境如回调变重,应改为 `def` + `Body(bytes)` 或拆后台任务。
    """
    if channel not in SUPPORTED_CHANNELS:
        raise HTTPException(status_code=404, detail=f"unknown channel: {channel}")

    adapter = get_adapter(channel)
    assert adapter is not None  # SUPPORTED_CHANNELS 已保证

    try:
        body: dict[str, Any] = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {e}") from e

    ok, fields = adapter.verify_callback(body)
    if not ok:
        raise HTTPException(status_code=400, detail="signature verify failed")

    out_trade_no = fields.get("out_trade_no")
    pay_trade_no = fields.get("pay_trade_no")
    amount = fields.get("amount")

    order = db.execute(
        select(Order).where(Order.order_no == out_trade_no)
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=400, detail="order not found")
    if order.channel != channel:
        raise HTTPException(
            status_code=400,
            detail=f"channel mismatch: order={order.channel} vs callback={channel}",
        )

    # 幂等:已支付订单直接 no-op 返回
    if order.status == STATUS_PAID:
        return CallbackResponse(
            order_no=out_trade_no,
            ok=True,
            activated=False,
            subscription=None,
        )

    # 金额一致性校验(元)
    try:
        if abs(float(amount) - float(order.amount)) > 0.01:
            raise HTTPException(
                status_code=400,
                detail=f"amount mismatch: order={order.amount} vs callback={amount}",
            )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid amount in callback")

    # 拿到用户并激活订阅
    from ..auth.models import User as _User
    user = db.get(_User, order.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="order.user not found")

    # 激活(内部会 commit)
    try:
        sub = activate_for_user(db, user, plan=order.plan, days=order.days)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"activate failed: {e}") from e

    # 标记订单已支付
    order.status = STATUS_PAID
    order.pay_trade_no = pay_trade_no
    order.paid_at = _utcnow()
    db.commit()
    db.refresh(order)

    used = _get_usage(db, user.id, _current_period())
    return CallbackResponse(
        order_no=out_trade_no,
        ok=True,
        activated=True,
        subscription=_serialize_subscription(sub, used=used),
    )


@router.get("/payment/order/{order_no}", response_model=OrderResponse)
def get_order(
    order_no: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderResponse:
    """查询订单状态。

    只允许订单所有者访问;非所有者返回 404(避免订单号枚举)。
    """
    order = db.execute(
        select(Order).where(Order.order_no == order_no)
    ).scalar_one_or_none()
    if order is None or order.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="order not found")

    d = order.to_dict()
    return OrderResponse(
        order_no=d["order_no"],
        status=d["status"],
        plan=d["plan"],
        days=d["days"],
        amount=d["amount"],
        channel=d["channel"],
        pay_trade_no=d["pay_trade_no"],
        created_at=d["created_at"],
        paid_at=d["paid_at"],
    )


# 显式导入 alipay/wechat 触发 register_adapter;此 import 已在文件顶部完成,
# 但保留此段作为可读性标记。
assert get_adapter(CHANNEL_ALIPAY) is not None
assert get_adapter(CHANNEL_WECHAT) is not None


__all__ = ["router"]
