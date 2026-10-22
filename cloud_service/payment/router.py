"""Payment 端点(C19)。

⚠️ **2026-10-22 起默认下线** —— 线上支付通道已停用,商业闭环改为
「线下人工充值 + 注册码」(见 `cloud_service/settings.py` 的 `online_payment` 段)。

代码**保留不删**:备案与 ICP 许可证落地后,把
`CLOUD_ONLINE_PAYMENT_ENABLED=true` 打开即可完全恢复,不必重写。
关闭时本 router 的所有端点统一返回 403 + 人工充值指引(而不是 404,
让调用方知道「为什么没有」以及「该走哪条路」)。

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

⚠️ 积分入账不在本模块了:原先唯一入账点在支付回调里,现已由
`billing/license_activation.py`(注册码激活)与
`billing/admin_router.py`(管理端人工调整)承担,不依赖支付通道。
"""

from __future__ import annotations

import hmac
import json as _json
import os
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.models import User
from ..auth.router import get_current_user
from ..billing.router import activate_for_user, _serialize_subscription, _get_usage, _current_period
from ..db import get_db
from ..settings import get_settings
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


def _online_payment_enabled() -> bool:
    """线上支付是否启用(默认关闭,见 settings.online_payment)。"""
    return bool(get_settings().get("online_payment", {}).get("enabled", False))


def _require_online_payment_enabled() -> None:
    """FastAPI 依赖:线上支付关闭时统一拦截整个 router。

    返回 403 而不是 404,是为了让调用方拿到**可执行的指引**
    (「加微信人工充值」),而不是一个让人摸不着头脑的 404。
    """
    if _online_payment_enabled():
        return
    hint = get_settings().get("online_payment", {}).get("contact_hint", "")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "reason": "online_payment_disabled",
            "message": hint,
            "channel": "manual_recharge",
        },
    )


router = APIRouter(dependencies=[Depends(_require_online_payment_enabled)])


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


async def _read_callback_body(request: Request) -> dict[str, Any]:
    """按 Content-Type 分派回调 body 解析。

    微信支付 APIv3 用 `application/json`,支付宝异步通知用
    `application/x-www-form-urlencoded`(官方规范),这里必须**按 Content-Type
    分派**,否则真实支付宝回调会解析失败。

    分派策略:
      - `application/json`               → JSON 解析
      - `application/x-www-form-urlencoded` → form-urlencoded 解析,转成 dict
      - 其它 / 缺失(含 `text/plain` 等)   → 先试 JSON,失败回退 form
        (保持与旧行为 / mock 兼容)

    实现细节:一次性 `await request.body()` 拿原始字节,再基于字节分别解析,
    避免 Starlette 的 `request.json()` / `request.form()` 会各自消费 stream
    导致兜底路径失败的问题。

    返回统一为 `dict[str, Any]`:
      - JSON body 字段可能是数字 / 字符串,adapter 内部会做 `float(...)`;
      - form body 值统一是字符串(form-urlencoded 天然是字符串);
      - 统一 dict 让 adapter 不必处理 form.MultiDict。

    解析失败(空 body / JSONDecodeError 等)统一包装为 400,与既有测试断言一致。
    """
    ct_raw = (request.headers.get("content-type") or "").lower()
    ct = ct_raw.split(";", 1)[0].strip()

    try:
        raw = await request.body()
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"unreadable callback body: {e}",
        ) from e

    def _parse_json(raw: bytes) -> dict[str, Any]:
        if not raw:
            raise ValueError("empty body")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"body is not valid UTF-8: {e}") from e
        obj = _json.loads(text)
        if not isinstance(obj, dict):
            raise ValueError("JSON body must be an object")
        return obj

    def _parse_form(raw: bytes) -> dict[str, str]:
        if not raw:
            raise ValueError("empty body")
        # parse_qsl 处理 URL 编码;keep_blank_values=True 保留空值(与 form.MultiDict 一致)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"body is not valid UTF-8: {e}") from e
        pairs = parse_qsl(text, keep_blank_values=True)
        # 同名多值只保留最后一个(与 request.form().get() 一致;实际回调字段都是唯一键)
        return dict(pairs)

    if ct == "application/json":
        try:
            return _parse_json(raw)
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"invalid JSON body: {e}",
            ) from e

    if ct == "application/x-www-form-urlencoded":
        try:
            return _parse_form(raw)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"invalid form body: {e}",
            ) from e

    # 兜底:未知 / 缺失 Content-Type。先试 JSON(与旧实现保持兼容),
    # 失败再试 form-urlencoded(兼容测试 / curl 直接 POST 表单)。
    try:
        return _parse_json(raw)
    except Exception:
        try:
            return _parse_form(raw)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"invalid callback body: expected JSON or "
                       f"x-www-form-urlencoded (got content-type={ct!r}): {e}",
            ) from e


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

    body = await _read_callback_body(request)

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

    # 拿到用户并按 plan 分派:
    #   - plan='pro'/'free' → 订阅激活
    #   - plan='credit'     → 积分充值(M3)
    from ..auth.models import User as _User
    user = db.get(_User, order.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="order.user not found")

    # ── plan='credit' 分支:走积分充值,不激活订阅 ──────────────────
    if order.plan == "credit":
        from ..billing import points as _billing_points
        from ..settings import get_settings as _get_settings
        from decimal import Decimal as _Decimal

        _pts_cfg = _get_settings().get("points", {})
        points_per_yuan = float(_pts_cfg.get("points_per_yuan", 10.0))
        bonus_threshold = float(_pts_cfg.get("bonus_threshold", 1000.0))
        bonus_rate = float(_pts_cfg.get("bonus_rate", 0.5))

        # 权威来源:Order.credit_points 存的是"充值总额 = 主积分 + 赠送积分"
        # (由 points_endpoints.points_create_recharge 在创建时按澜途规则算好)。
        # 若为 NULL(老订单/其他入口直接构造 Order),回退到 amount * points_per_yuan 推导。
        if order.credit_points is not None and float(order.credit_points) > 0:
            total_points = _Decimal(str(order.credit_points))
            main_points = total_points
            bonus = _Decimal("0")
        else:
            points_per_yuan_dec = _Decimal(str(points_per_yuan))
            main_points = (_Decimal(str(order.amount)) * points_per_yuan_dec).to_integral_value(
                rounding="ROUND_FLOOR"
            )
            bonus = _Decimal("0")
            if main_points > _Decimal(str(bonus_threshold)):
                bonus = ((main_points - _Decimal(str(bonus_threshold)))
                         * _Decimal(str(bonus_rate))).to_integral_value(
                    rounding="ROUND_FLOOR"
                )
                if bonus < 0:
                    bonus = _Decimal("0")
            total_points = main_points + bonus

        if total_points <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"recharge points derived <= 0 for amount {order.amount}",
            )

        try:
            _main, _bonus_ledger = _billing_points.recharge_credit(
                db,
                user.id,
                points=main_points,
                bonus_points=bonus,
                recharge_id=order.order_no,
                note=f"recharge {main_points} + bonus {bonus} via order {order.order_no}",
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"recharge failed: {e}") from e

        # 标记订单已支付
        order.status = STATUS_PAID
        order.pay_trade_no = pay_trade_no
        order.paid_at = _utcnow()
        db.commit()
        db.refresh(order)

        return CallbackResponse(
            order_no=out_trade_no,
            ok=True,
            activated=True,
            subscription=None,  # 积分订单不涉及订阅
        )

    # ── 订阅激活分支 ─────────────────────────────────
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
        credit_points=d.get("credit_points"),
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
    refund_kwargs = dict(
        order_no=order.order_no,
        pay_trade_no=order.pay_trade_no,
        amount=refund_amount,
        order_amount=float(order.amount),
    )
    try:
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

    # ──────────────────────────────────────────────────────────
    # 接入点(预留):退款 ↔ 订阅语义
    # ──────────────────────────────────────────────────────────
    # 业务规则未拍板前,退款端点**不**触碰 Subscription(见
    # `subscription_touched=False` 与下方 `subscription_note`),保证"退款
    # 已发但订阅仍有效"的现状不破坏线上体验。
    #
    # 一旦业务侧拍板以下规则之一,应在 `db.commit()` 之后、组装
    # `RefundResponse` 之前接入 `cloud_service.billing.router` 中的
    # 内部函数(均**幂等**、带 `with_for_update` 行锁):
    #
    #   规则 A · "全额退款立即撤销本期订阅":
    #       if full_refund:
    #           from ..billing.router import (
    #               cancel_subscription, SubscriptionNotFoundError,
    #           )
    #           cancel_subscription(db, order.user_id, reason=payload.reason or "refund")
    #
    #   规则 B · "部分退款按比例缩短到期时间":
    #       if not full_refund and order.expire_days_can_be_derived():
    #           from ..billing.router import shorten_subscription
    #           days_to_revoke = int(round(
    #               order.days * (refund_amount / float(order.amount))
    #           ))
    #           if days_to_revoke > 0:
    #               shorten_subscription(db, order.user_id,
    #                                    days_to_revoke=days_to_revoke)
    #
    # 取舍 / 注意事项(供产品决策时参考):
    #   - 撤销会导致**用户已付费但仍在用**的内容立即不可用
    #     (云端 prompt / pro 额度 / license/verify 心跳),客户体验风险大;
    #     是否给"冷静期"或"到期不撤销"需产品拍板。
    #   - 部分退款若缩短到期时间,可能与后续再购订单叠加产生边界
    #     (如 30 天订阅退 5 天后又买 30 天,总时长会因 expire_at 前移
    #     而少 5 天),需要明确"再购是否重新加满 30 天"。
    #   - 两个函数都是**幂等 + 行锁**,可在同一事务里再调用一次
    #     (如管理员重复点退款的极端路径)不会重复缩短。
    #   - 未来若加自动触发开关,建议 env 名
    #     `CLOUD_REFUND_AUTO_TOUCH_SUBSCRIPTION`(默认关闭);届时
    #     `RefundResponse.subscription_touched` 会在开关打开时才置 True,
    #     前端可继续据此决定是否重新拉取订阅状态。
    #
    # 见 `cloud_service/test_billing_refund_semantics.py` —— 其中
    # "退款端点默认不改订阅" 的断言即为"默认行为未变"的护栏。
    # ──────────────────────────────────────────────────────────

    # 面向后台/客服的说明文字(不改变旧字段含义):
    #   - 全额退款:明确"未自动撤销订阅,规则待定";
    #   - 部分退款:同 `note` 里"subscription not touched"的语义,但独立字段便于
    #     前端/客服侧只关心订阅动作时读取。
    subscription_note = (
        "subscription unchanged (rule pending): full refund; "
        "cancellation can be wired via billing.cancel_subscription"
        if full_refund
        else "subscription unchanged (rule pending): partial refund; "
             "shortening can be wired via billing.shorten_subscription"
    )

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
        subscription_note=subscription_note,
    )


# 显式导入 alipay/wechat 触发 register_adapter;此 import 已在文件顶部完成,
# 但保留此段作为可读性标记。
assert get_adapter(CHANNEL_ALIPAY) is not None
assert get_adapter(CHANNEL_WECHAT) is not None


__all__ = ["router"]
