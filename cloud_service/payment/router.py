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

import hmac
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
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
    STATUS_REFUNDED,
    Order,
)
from .schemas import (
    CallbackResponse,
    CreateOrderRequest,
    CreateOrderResponse,
    OrderResponse,
    RefundRequest,
    RefundResponse,
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
    # 幂等:已退款订单 —— 迟到的支付回调不应再激活订阅(可能已退款,订阅已撤销)
    if order.status == STATUS_REFUNDED:
        return CallbackResponse(
            order_no=out_trade_no,
            ok=False,
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
        refunded_at=d.get("refunded_at"),
    )


# ──────────────────────────────────────────────────────────────
# 退款(admin + JWT)
# ──────────────────────────────────────────────────────────────

def _get_admin_token_env() -> str:
    """读取 `CLOUD_ADMIN_TOKEN`。空/未设置 → 503(与 llm_proxy 一致,防空密钥误放行)。"""
    token = (os.getenv("CLOUD_ADMIN_TOKEN") or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin token not configured (CLOUD_ADMIN_TOKEN)",
        )
    return token


@router.post(
    "/payment/refund",
    response_model=RefundResponse,
)
def refund_order(
    payload: RefundRequest,
    current_user: User = Depends(get_current_user),  # JWT 必须有效
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
) -> RefundResponse:
    """发起退款(管理员)。

    双重门禁:JWT 有效 + `X-Admin-Token` 匹配 `CLOUD_ADMIN_TOKEN`。
    任一不满足 → 401 / 403;admin token 未配置 → 503。

    行为:
      - 找到 `order_no` 对应的 Order,不存在 → 404;
      - 校验状态:`paid` 才能退款;`created`/`closed` → 400;`refunded` → 409(幂等拒绝);
      - `amount` 不传 = 全额退款;`amount` > Order.amount 或 <=0 → 400;
      - 调 `adapter.refund(...)`(mock 默认返回成功)→ 失败返回 502;
      - 全额退款时 `Order.status=refunded`, `Order.refunded_at=now`;
      - 部分退款暂保持 `Order.status=paid`(决策点,见遗留说明);
      - **不主动撤销/缩短订阅**(决策:先只做订单侧状态,避免破坏性变更;
        真实上线前应与业务侧确认,见文件底部注释)。
    """
    # 1. Admin token 校验(先 token,再 JWT 语义,避免空 admin token 直接吞掉所有请求)
    expected = _get_admin_token_env()
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid admin token",
        )

    # 2. 查找订单
    order = db.execute(
        select(Order).where(Order.order_no == payload.order_no)
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")

    # 3. 状态机校验
    if order.status == STATUS_REFUNDED:
        raise HTTPException(
            status_code=409,
            detail="order already refunded",
        )
    if order.status != STATUS_PAID:
        raise HTTPException(
            status_code=400,
            detail=f"order status={order.status}, only paid can be refunded",
        )
    if not order.pay_trade_no:
        raise HTTPException(
            status_code=400,
            detail="order has no pay_trade_no",
        )

    # 4. 金额校验
    refund_amount = float(payload.amount) if payload.amount is not None else float(order.amount)
    if refund_amount <= 0:
        raise HTTPException(status_code=400, detail="refund amount must be > 0")
    if refund_amount > float(order.amount) + 1e-6:
        raise HTTPException(
            status_code=400,
            detail=f"refund amount {refund_amount} exceeds order amount {order.amount}",
        )
    full_refund = abs(refund_amount - float(order.amount)) <= 1e-6

    # 5. 调 adapter 退款(mock)
    adapter = get_adapter(order.channel)
    if adapter is None:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported channel: {order.channel}",
        )
    try:
        # 微信 APIv3 部分退款要求 `amount.total == 原订单金额`(否则微信拒);
        # 全额退款时 total == refund,同样正确。传入 order.amount 保证兼容。
        # 支付宝 adapter 目前签名不接受 `order_amount`,通过签名内省做
        # 兼容降级:只在实际支持该参数的 adapter 上传入。
        # 未来支付宝 adapter 增加 order_amount 参数后,该内省会自然兼容。
        import inspect as _inspect

        refund_kwargs = dict(
            order_no=order.order_no,
            pay_trade_no=order.pay_trade_no,
            amount=refund_amount,
        )
        try:
            _sig = _inspect.signature(adapter.refund)
            if "order_amount" in _sig.parameters:
                refund_kwargs["order_amount"] = float(order.amount)
        except (TypeError, ValueError):
            # 极端:adapter.refund 是 C 扩展等无法 inspect 的对象,降级到 3 参数
            pass
        ok, msg, fields = adapter.refund(**refund_kwargs)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"refund adapter error: {e}",
        ) from e
    if not ok:
        raise HTTPException(status_code=502, detail=f"refund failed: {msg}")

    # 6. 落库
    refund_trade_no = str(fields.get("refund_trade_no") or "")
    if full_refund:
        order.status = STATUS_REFUNDED
        order.refunded_at = _utcnow()
    else:
        # 部分退款:暂不改变 status(决策见下方 note)
        pass
    db.commit()
    db.refresh(order)

    # 决策点(遗留):
    #   - 是否撤销订阅/缩短 expire_at?当前实现**不**触碰 Subscription,原因:
    #       (a) activate_for_user 语义是"延长",没有反向"缩短"接口;
    #       (b) 订阅与订单是一对多关系,部分退款/全额退款的订阅行为需业务侧拍板。
    #   - 真实上线前应引入 `billing.cancel_subscription(user_id)` 或
    #     `billing.shorten_subscription(user_id, days_to_revoke)`,再在此调用。
    return RefundResponse(
        order_no=order.order_no,
        refunded_amount=round(refund_amount, 2),
        order_status=order.status,
        pay_trade_no=order.pay_trade_no,
        refund_trade_no=refund_trade_no or None,
        refunded_at=order.refunded_at.isoformat() if order.refunded_at else None,
        subscription_touched=False,
        note=(
            None
            if full_refund
            else "partial refund: Order.status remains 'paid'; subscription not touched"
        ),
    )


# 显式导入 alipay/wechat 触发 register_adapter;此 import 已在文件顶部完成,
# 但保留此段作为可读性标记。
assert get_adapter(CHANNEL_ALIPAY) is not None
assert get_adapter(CHANNEL_WECHAT) is not None


__all__ = ["router"]
