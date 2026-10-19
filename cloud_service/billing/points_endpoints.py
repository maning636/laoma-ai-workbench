"""M3 · 积分制端点(FastAPI router)。

前缀:`/points`(在 `billing/router.py` 中被 include 到 `/cloud` 之下,
最终路径为 `/cloud/points/*`)。

端点:
  GET  /points/account                   → 积分账户
  GET  /points/recharge/options          → 充值选项(5 档预设 + 自定义 + 赠送规则)
  GET  /points/history                   → 积分历史(分页)
  GET  /points/pricing                   → AI 价目表
  POST /points/recharge                  → 创建积分充值订单(复用 payment 通道)
  POST /points/freeze                    → 冻结(生成前预扣)
  POST /points/consume                   → 实扣(frozen→consumed)
  POST /points/rollback                  → 回滚(frozen→available)
  POST /points/consume_by_pricing        → 一次性按 pricing_key 扣积分
  POST /points/refund                    → 管理员手动退积分

复用:
  - `..auth.router.get_current_user`      JWT 依赖
  - `..db.get_db`                         SQLAlchemy session
  - `..payment.adapter.get_adapter`       支付参数生成(避免重复造支付)
  - `..payment.models.Order`              充值订单落库(plan='credit')
  - `billing/points.py`                   积分核心逻辑
"""

from __future__ import annotations

import hmac
import os as _os
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..auth.models import User
from ..auth.router import get_current_user
from ..db import get_db
from ..settings import get_settings
from . import points as _points
from .models import CreditLedger, TX_BONUS, TX_CONSUME, TX_FREEZE, TX_RECHARGE, TX_REFUND, TX_ROLLBACK
from .points import (
    FreezeInvalidStateError,
    FreezeNotFoundError,
    InsufficientPointsError,
    consume_freeze,
    freeze_points,
    get_account,
    list_pricing,
    points_for_pricing,
    refund_credit,
    rollback_freeze,
    seed_pricing,
)
from .schemas import (
    PointsAccountResponse,
    PointsConsumeByPricingRequest,
    PointsConsumeResponse,
    PointsFreezeRequest,
    PointsFreezeResponse,
    PointsHistoryResponse,
    PointsLedgerItem,
    PointsPricingItem,
    PointsPricingResponse,
    PointsRechargeCreateRequest,
    PointsRechargeCreateResponse,
    PointsRechargeOptionsResponse,
    PointsRechargePreset,
    PointsRefundAdminRequest,
)


router = APIRouter()


_ZERO = Decimal("0")


def _dec(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ──────────────────────────────────────────────────────────────
# 配置(与澜途对齐,env 可覆盖)
# ──────────────────────────────────────────────────────────────


def _credit_config() -> dict[str, Any]:
    """积分充值配置。

    预设档位以 **积分数** 表达(对齐澜途 `/points/recharge/options.presets`);
    价格 = `points / points_per_yuan`,例如 3000 积分 = ¥300。

    预设项支持两种输入:
      - dict:`{"points": 3000, "bonus_points": 1000, "enabled": True}`
      - float/int:旧结构(仅积分数),自动按 bonus_threshold/rate 推导赠送。
    环境变量 `CLOUD_POINTS_PRESETS` 若配置,按 JSON 解析。
    """
    cfg = get_settings().get("points", {})
    raw_presets = cfg.get("presets")

    # 澜途默认档位(2026-10-16 lantyou-api-audit §2.2)
    _DEFAULT_PRESETS = [
        {"points": 100,  "bonus_points": 0,    "enabled": True},   # ¥10,无赠送
        {"points": 500,  "bonus_points": 0,    "enabled": True},   # ¥50,无赠送
        {"points": 1000, "bonus_points": 0,    "enabled": True},   # ¥100,at threshold,无赠送
        {"points": 3000, "bonus_points": 1000, "enabled": True},   # ¥300,赠 1000 → 到账 4000
        {"points": 5000, "bonus_points": 2000, "enabled": True},   # ¥500,赠 2000 → 到账 7000
    ]

    if raw_presets is None:
        raw_presets = _DEFAULT_PRESETS
    elif isinstance(raw_presets, (int, float)):
        # 兼容旧 env:CLOUD_POINTS_PRESETS=3000 → 单档预设(积分数)
        raw_presets = [raw_presets]
    elif isinstance(raw_presets, str):
        # 允许 JSON 字符串,失败回退默认
        import json as _json
        try:
            parsed = _json.loads(raw_presets)
            if isinstance(parsed, list):
                raw_presets = parsed
            else:
                raw_presets = _DEFAULT_PRESETS
        except (ValueError, _json.JSONDecodeError):
            raw_presets = _DEFAULT_PRESETS

    # 归一化:每项转成 dict(points, bonus_points, enabled);纯数字项按公式推导赠送
    threshold = float(cfg.get("bonus_threshold", 1000.0))
    rate = float(cfg.get("bonus_rate", 0.5))
    normalized: list[dict] = []
    for p in raw_presets:
        if isinstance(p, dict):
            normalized.append({
                "points": float(p.get("points", 0)),
                "bonus_points": float(p.get("bonus_points", 0)),
                "enabled": bool(p.get("enabled", True)),
            })
        elif isinstance(p, (int, float)):
            pts = float(p)
            bonus = 0.0
            if pts > threshold:
                bonus = int(((pts - threshold) * rate) // 1)
            normalized.append({
                "points": pts,
                "bonus_points": float(bonus),
                "enabled": True,
            })
        else:
            # 跳过无法解析的项,避免线上崩溃
            continue

    return {
        "enabled": bool(cfg.get("enabled", True)),
        "points_per_yuan": float(cfg.get("points_per_yuan", 10.0)),
        "bonus_threshold": float(cfg.get("bonus_threshold", 1000.0)),
        "bonus_rate": float(cfg.get("bonus_rate", 0.5)),
        "min_points": float(cfg.get("min_points", 1.0)),
        "max_points": float(cfg.get("max_points", 10000.0)),
        "default_points": float(cfg.get("default_points", 3000.0)),
        "custom_enabled": bool(cfg.get("custom_enabled", True)),
        "presets": normalized,
    }


def _compute_bonus(points: Decimal, cfg: dict[str, Any]) -> Decimal:
    """按澜途规则:积分 >= bonus_threshold 时,赠送 floor((points - threshold) * bonus_rate)。

    澜途样例:1000→0, 3000→1000, 5000→2000。
    验证:(1000-1000)*0.5=0, (3000-1000)*0.5=1000, (5000-1000)*0.5=2000 ✓
    """
    p = _dec(points)
    threshold = _dec(cfg["bonus_threshold"])
    rate = _dec(cfg["bonus_rate"])
    if p <= threshold:
        return _ZERO
    bonus = ((p - threshold) * rate).to_integral_value(rounding="ROUND_FLOOR")
    return bonus if bonus > 0 else _ZERO


def _serialize_pricing(row) -> dict[str, Any]:
    return {
        "pricingKey": row.pricing_key,
        "displayName": row.display_name,
        "points": float(row.points),
        "category": row.category,
        "enabled": bool(row.enabled),
        "sortOrder": int(row.sort_order),
    }


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────


@router.get("/points/account", response_model=PointsAccountResponse)
def points_get_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PointsAccountResponse:
    """返回积分账户快照(对齐澜途 `/points/account`)。"""
    data = get_account(db, current_user.id)
    return PointsAccountResponse(
        primaryAccountId=current_user.id,
        availablePoints=data["availablePoints"],
        frozenPoints=data["frozenPoints"],
        totalPoints=data["totalPoints"],
        totalConsumed=data["totalConsumed"],
        totalRecharged=data["totalRecharged"],
    )


@router.get("/points/recharge/options", response_model=PointsRechargeOptionsResponse)
def points_recharge_options(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PointsRechargeOptionsResponse:
    """充值选项(参考澜途:5 档预设 + 自定义 + 赠送规则)。

    预设项语义(2026-10-16 M3 硬化):
      - `points`:档位主积分(**积分数**,单位=积分,非元);
      - `yuan = points / points_per_yuan`;
      - `bonusPoints`:档位显式配置的赠送积分数(澜途对齐);
      - 与用户任意 points 的赠送计算 `_compute_bonus` 保持公式一致。
    """
    cfg = _credit_config()
    presets: list[PointsRechargePreset] = []
    for preset in cfg["presets"]:
        pts = _dec(preset["points"])
        bonus = _dec(preset["bonus_points"])
        presets.append(PointsRechargePreset(
            points=float(pts),
            bonusPoints=float(bonus),
            yuan=round(float(pts) / cfg["points_per_yuan"], 2),
            enabled=bool(preset.get("enabled", True)),
        ))
    return PointsRechargeOptionsResponse(
        enabled=cfg["enabled"],
        pointsPerYuan=cfg["points_per_yuan"],
        bonusThreshold=cfg["bonus_threshold"],
        bonusRate=cfg["bonus_rate"],
        minPoints=cfg["min_points"],
        maxPoints=cfg["max_points"],
        defaultPoints=cfg["default_points"],
        customEnabled=cfg["custom_enabled"],
        presets=presets,
        paymentChannels=["alipay", "wechat"],
    )


@router.get("/points/history", response_model=PointsHistoryResponse)
def points_history(
    current_user: User = Depends(get_current_user),
    current: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    use_function: Optional[str] = Query(None, alias="use_function"),
    tx_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> PointsHistoryResponse:
    """分页查询积分流水。

    过滤:
      - `use_function`:业务场景过滤;
      - `tx_type`:RECHARGE / FREEZE / CONSUME / ROLLBACK / REFUND / BONUS。
    按 id DESC 排序(近似按 created_at DESC)。
    """
    query = db.query(CreditLedger).filter(CreditLedger.user_id == current_user.id)
    if use_function:
        query = query.filter(CreditLedger.use_function == use_function)
    if tx_type:
        allowed = {TX_RECHARGE, TX_BONUS, TX_FREEZE, TX_CONSUME, TX_ROLLBACK, TX_REFUND}
        if tx_type not in allowed:
            raise HTTPException(status_code=422, detail=f"invalid tx_type: {tx_type}")
        query = query.filter(CreditLedger.tx_type == tx_type)

    total = query.count()
    rows = (
        query.order_by(CreditLedger.id.desc())
        .offset((current - 1) * size)
        .limit(size)
        .all()
    )
    items = [PointsLedgerItem(
        id=r.id,
        txType=r.tx_type,
        amount=float(r.amount),
        balanceAfter=float(r.balance_after),
        frozenAfter=float(r.frozen_after),
        useFunction=r.use_function,
        refId=r.ref_id,
        rechargeId=r.recharge_id,
        pricingKey=r.pricing_key,
        freezeTxId=r.freeze_tx_id,
        status=r.status,
        note=r.note,
        createdAt=r.created_at.isoformat() if r.created_at else None,
    ) for r in rows]

    return PointsHistoryResponse(current=current, size=size, total=total, items=items)


@router.get("/points/pricing", response_model=PointsPricingResponse)
def points_pricing(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PointsPricingResponse:
    """AI 能力价目表(与澜途 `/system/config/ai-point-pricing` 对齐)。"""
    if list_pricing(db) == []:
        seed_pricing(db)
    rows = list_pricing(db)
    items = [PointsPricingItem(**_serialize_pricing(r)) for r in rows]
    return PointsPricingResponse(pricingVersion="2026-10-v1", items=items)


@router.post(
    "/points/recharge",
    response_model=PointsRechargeCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def points_create_recharge(
    payload: PointsRechargeCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PointsRechargeCreateResponse:
    """创建积分充值订单(复用 payment 通道,不重复造支付)。

    本端点**不直接落积分**,仅在支付回调时由 payment.router 触发
    `recharge_credit()` 落积分。见 `payment/router.py` 的回调分支。
    """
    cfg = _credit_config()
    if not cfg["enabled"]:
        raise HTTPException(status_code=400, detail="points recharge disabled")

    pts = _dec(payload.points)
    if pts < _dec(cfg["min_points"]) or pts > _dec(cfg["max_points"]):
        raise HTTPException(
            status_code=422,
            detail=f"points must be between {cfg['min_points']} and {cfg['max_points']}",
        )

    bonus = _compute_bonus(pts, cfg)
    amount = round(float(pts) / cfg["points_per_yuan"], 2)
    total_points = pts + bonus

    # 复用 payment 通道:直接落 Order(plan='credit'),避免依赖外部 create_order 端点
    from ..payment.adapter import get_adapter
    from ..payment.models import Order, STATUS_CREATED, SUPPORTED_CHANNELS
    from ..payment.router import _generate_order_no

    if payload.channel not in SUPPORTED_CHANNELS:
        raise HTTPException(
            status_code=422,
            detail=f"channel must be one of {sorted(SUPPORTED_CHANNELS)}",
        )
    order_no = _generate_order_no()
    # M3 硬化:
    #   - `days=None` 表达"积分永久有效"(不再借用 days=0 的模糊语义);
    #   - `credit_points` 落主积分 + 赠送积分,便于审计与回调幂等追溯。
    order = Order(
        user_id=current_user.id,
        order_no=order_no,
        amount=amount,
        plan="credit",
        days=None,
        credit_points=float(total_points),
        status=STATUS_CREATED,
        channel=payload.channel,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    adapter = get_adapter(payload.channel)
    if adapter is None:
        db.delete(order)
        db.commit()
        raise HTTPException(status_code=400, detail=f"unsupported channel: {payload.channel}")

    # 支付适配器仍需要 days 参数;plan='credit' 时传 0 让渠道层不扩展订阅(内部无副作用)
    pay_params = adapter.create_payment(
        order_no=order_no,
        amount=amount,
        plan="credit",
        days=0,
        notify_url=f"/cloud/payment/callback/{payload.channel}",
        return_url="/payment/success",
    )

    return PointsRechargeCreateResponse(
        orderNo=order_no,
        amount=amount,
        points=float(pts),
        bonusPoints=float(bonus),
        totalPoints=float(total_points),
        channel=payload.channel,
        payParams=pay_params,
    )


@router.post("/points/freeze", response_model=PointsFreezeResponse)
def points_freeze(
    payload: PointsFreezeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PointsFreezeResponse:
    """冻结积分(生成前预扣)。"""
    if payload.amount is None:
        raise HTTPException(status_code=422, detail="amount is required for freeze")
    try:
        ledger = freeze_points(
            db,
            current_user.id,
            amount=_dec(payload.amount),
            use_function=payload.use_function or "",
            ref_id=payload.ref_id,
            pricing_key=payload.pricing_key,
            note=payload.note,
        )
    except InsufficientPointsError as e:
        raise HTTPException(status_code=402, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    acct = get_account(db, current_user.id)
    return PointsFreezeResponse(
        freezeTxId=ledger.id,
        amount=float(ledger.amount),
        useFunction=ledger.use_function,
        refId=ledger.ref_id,
        pricingKey=ledger.pricing_key,
        status=ledger.status or "",
        availablePoints=acct["availablePoints"],
        frozenPoints=acct["frozenPoints"],
        createdAt=ledger.created_at.isoformat() if ledger.created_at else None,
    )


@router.post("/points/consume", response_model=PointsConsumeResponse)
def points_consume(
    payload: PointsFreezeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PointsConsumeResponse:
    """实扣:生成成功后调用,frozen→consumed。"""
    freeze_tx_id = payload.freeze_tx_id
    if not freeze_tx_id:
        raise HTTPException(status_code=422, detail="freeze_tx_id is required")
    try:
        ledger = consume_freeze(db, int(freeze_tx_id), note=payload.note)
    except FreezeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FreezeInvalidStateError as e:
        raise HTTPException(status_code=409, detail=str(e))

    acct = get_account(db, current_user.id)
    return PointsConsumeResponse(
        freezeTxId=ledger.freeze_tx_id,
        consumeTxId=ledger.id,
        amount=float(ledger.amount),
        status="consumed",
        availablePoints=acct["availablePoints"],
        frozenPoints=acct["frozenPoints"],
        totalConsumed=acct["totalConsumed"],
        createdAt=ledger.created_at.isoformat() if ledger.created_at else None,
    )


@router.post("/points/rollback", response_model=PointsConsumeResponse)
def points_rollback(
    payload: PointsFreezeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PointsConsumeResponse:
    """回滚:生成失败时调用,frozen→available。"""
    freeze_tx_id = payload.freeze_tx_id
    if not freeze_tx_id:
        raise HTTPException(status_code=422, detail="freeze_tx_id is required")
    try:
        ledger = rollback_freeze(db, int(freeze_tx_id), note=payload.note)
    except FreezeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FreezeInvalidStateError as e:
        raise HTTPException(status_code=409, detail=str(e))

    acct = get_account(db, current_user.id)
    return PointsConsumeResponse(
        freezeTxId=ledger.freeze_tx_id,
        consumeTxId=ledger.id,
        amount=float(ledger.amount),
        status="rolled_back",
        availablePoints=acct["availablePoints"],
        frozenPoints=acct["frozenPoints"],
        totalConsumed=acct["totalConsumed"],
        createdAt=ledger.created_at.isoformat() if ledger.created_at else None,
    )


@router.post("/points/consume_by_pricing", response_model=PointsConsumeResponse)
def points_consume_by_pricing(
    payload: PointsConsumeByPricingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PointsConsumeResponse:
    """一次性按 pricing_key 扣积分(内部先 freeze 再 consume,适合同步任务)。"""
    key = payload.pricing_key
    amount = _dec(payload.amount) if payload.amount else points_for_pricing(db, key)
    if amount <= 0:
        raise HTTPException(status_code=400, detail=f"pricing_key '{key}' not found or amount<=0")

    try:
        freeze = freeze_points(
            db,
            current_user.id,
            amount=amount,
            use_function=payload.use_function or "",
            ref_id=payload.ref_id,
            pricing_key=key,
        )
    except InsufficientPointsError as e:
        raise HTTPException(status_code=402, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    ledger = consume_freeze(db, freeze.id)
    acct = get_account(db, current_user.id)
    return PointsConsumeResponse(
        freezeTxId=freeze.id,
        consumeTxId=ledger.id,
        amount=float(ledger.amount),
        status="consumed",
        availablePoints=acct["availablePoints"],
        frozenPoints=acct["frozenPoints"],
        totalConsumed=acct["totalConsumed"],
        createdAt=ledger.created_at.isoformat() if ledger.created_at else None,
    )


def _get_admin_token_expected() -> str:
    expected = (_os.getenv("CLOUD_ADMIN_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin token not configured (CLOUD_ADMIN_TOKEN)",
        )
    return expected


@router.post("/points/refund", response_model=PointsConsumeResponse)
def points_refund_admin(
    payload: PointsRefundAdminRequest,
    x_admin_token: str = Header(default="", alias="X-Admin-Token"),
    db: Session = Depends(get_db),
) -> PointsConsumeResponse:
    """管理员手动退积分(从 available 扣减)。"""
    expected = _get_admin_token_expected()
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=403, detail="invalid admin token")

    ledger = refund_credit(
        db,
        payload.user_id,
        amount=_dec(payload.amount),
        recharge_id=payload.recharge_id,
        note=payload.note,
    )
    acct = get_account(db, payload.user_id)
    return PointsConsumeResponse(
        freezeTxId=None,
        consumeTxId=ledger.id,
        amount=float(ledger.amount),
        status="refunded",
        availablePoints=acct["availablePoints"],
        frozenPoints=acct["frozenPoints"],
        totalConsumed=acct["totalConsumed"],
        createdAt=ledger.created_at.isoformat() if ledger.created_at else None,
    )


__all__ = ["router"]
