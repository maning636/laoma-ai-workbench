"""M3 · 积分制核心逻辑(Credit Ledger)。

对外暴露的原子操作(全部在事务内,配合 `with_for_update` 行锁 + `version` 乐观锁):

  get_or_create_balance(db, user_id)   → CreditBalance
  freeze_points(db, user_id, ...)      → CreditLedger  (冻结)
  consume_freeze(db, freeze_tx_id)     → CreditLedger  (实扣,frozen→consumed)
  rollback_freeze(db, freeze_tx_id)    → CreditLedger  (回滚,frozen→available)
  recharge_credit(db, user_id, ...)    → (CreditLedger, CreditLedger?)  (充值 + 可能的赠送)
  refund_credit(db, user_id, ...)      → CreditLedger  (管理员退款,负数入账)
  seed_pricing(db)                     → None          (价目表幂等 seed)
  get_pricing(db, pricing_key)         → CreditPricing | None

约定:
  - 所有金额使用 `Decimal`,避免二进制浮点误差;
  - 每次积分变动**必须**同时写 `CreditBalance` 和 `CreditLedger` 两条记录,
    否则审计链条断裂;
  - 冻结交易的 `CreditLedger.status` 字段追踪生命周期:
      active → consumed  (consume_freeze)
      active → rolled_back (rollback_freeze)
    终态下再次操作 → 幂等 no-op 或直接抛错,由调用方决定。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as _m


# ──────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────

_ZERO = Decimal("0")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value) -> Decimal:
    """安全转 Decimal(接受 Decimal / int / float / str)。"""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q2(value: Decimal) -> Decimal:
    """保留 4 位小数(与 `Numeric(14,4)` 一致);避免累加时精度漂移。"""
    return Decimal(value).quantize(Decimal("0.0001"))


def _bump_balance(
    db: Session,
    balance: _m.CreditBalance,
    *,
    delta_available: Decimal = _ZERO,
    delta_frozen: Decimal = _ZERO,
    delta_consumed: Decimal = _ZERO,
    delta_recharged: Decimal = _ZERO,
) -> tuple[Decimal, Decimal]:
    """就地更新 balance 表,返回 (new_available, new_frozen)。

    调用方负责 commit / rollback;本函数只做字段级加法。
    所有字段都不会低于 0(截断到 0),避免异常路径产生负数。
    """
    available = _dec(balance.available_points) + delta_available
    frozen = _dec(balance.frozen_points) + delta_frozen
    consumed = _dec(balance.total_consumed) + delta_consumed
    recharged = _dec(balance.total_recharged) + delta_recharged

    if available < 0:
        available = _ZERO
    if frozen < 0:
        frozen = _ZERO

    balance.available_points = _q2(available)
    balance.frozen_points = _q2(frozen)
    balance.total_consumed = _q2(consumed)
    balance.total_recharged = _q2(recharged)
    balance.version = int(balance.version or 0) + 1
    balance.updated_at = _utcnow()
    return balance.available_points, balance.frozen_points


def _write_ledger(
    db: Session,
    *,
    user_id: int,
    tx_type: str,
    amount: Decimal,
    balance: _m.CreditBalance,
    use_function: Optional[str] = None,
    ref_id: Optional[str] = None,
    recharge_id: Optional[str] = None,
    pricing_key: Optional[str] = None,
    freeze_tx_id: Optional[int] = None,
    status: Optional[str] = None,
    note: Optional[str] = None,
) -> _m.CreditLedger:
    """写一条流水(不 commit)。返回新建的 CreditLedger 行。"""
    row = _m.CreditLedger(
        user_id=user_id,
        tx_type=tx_type,
        amount=_q2(_dec(amount)),
        balance_after=balance.available_points,
        frozen_after=balance.frozen_points,
        use_function=use_function,
        ref_id=ref_id,
        recharge_id=recharge_id,
        pricing_key=pricing_key,
        freeze_tx_id=freeze_tx_id,
        status=status,
        note=note,
    )
    db.add(row)
    db.flush()
    return row


def _lock_balance(db: Session, user_id: int) -> _m.CreditBalance:
    """SELECT ... FOR UPDATE 锁住 balance 行;不存在则新建并 flush。

    SQLite 无真正的行锁,但 `with_for_update()` 在 SQLite 上是 no-op,
    因此并发保护主要靠事务隔离 + `version` 乐观锁检查。生产切 MySQL
    后自动启用行锁,代码无需改动。
    """
    balance = (
        db.query(_m.CreditBalance)
        .filter(_m.CreditBalance.user_id == user_id)
        .with_for_update()
        .first()
    )
    if balance is None:
        balance = _m.CreditBalance(user_id=user_id)
        db.add(balance)
        db.flush()
    return balance


# ──────────────────────────────────────────────────────────────
# 对外 API
# ──────────────────────────────────────────────────────────────


class InsufficientPointsError(ValueError):
    """可用积分不足(冻结时抛出)。"""


class FreezeNotFoundError(LookupError):
    """冻结交易不存在(用户/tx_id 组合不存在)。"""


class FreezeInvalidStateError(ValueError):
    """冻结交易已终态,不能再操作。"""


def get_or_create_balance(db: Session, user_id: int) -> _m.CreditBalance:
    """读取(或懒创建)用户的 CreditBalance。不 commit。"""
    balance = db.execute(
        select(_m.CreditBalance).where(_m.CreditBalance.user_id == user_id)
    ).scalar_one_or_none()
    if balance is None:
        balance = _m.CreditBalance(user_id=user_id)
        db.add(balance)
        db.flush()
    return balance


def get_account(db: Session, user_id: int) -> dict:
    """返回积分账户快照(对齐澜途 `/points/account`)。

    字段:availablePoints / frozenPoints / totalPoints / totalConsumed / totalRecharged
    """
    balance = get_or_create_balance(db, user_id)
    db.commit()
    return balance.to_dict()


def freeze_points(
    db: Session,
    user_id: int,
    *,
    amount: Decimal,
    use_function: str,
    ref_id: Optional[str] = None,
    pricing_key: Optional[str] = None,
    note: Optional[str] = None,
) -> _m.CreditLedger:
    """冻结积分(生成前预扣)。

    原子语义:
      1. 锁定 balance 行;
      2. 检查 available_points >= amount,否则抛 `InsufficientPointsError`;
      3. available -= amount; frozen += amount;
      4. 写 CreditLedger(tx_type='FREEZE', status='active');
      5. commit。

    返回新建的 CreditLedger 行(其 id 即 `freeze_tx_id`)。
    """
    amt = _dec(amount)
    if amt <= 0:
        raise ValueError(f"freeze amount must be > 0, got {amt}")

    balance = _lock_balance(db, user_id)
    if _dec(balance.available_points) < amt:
        db.rollback()
        raise InsufficientPointsError(
            f"insufficient points: available={balance.available_points}, "
            f"required={amt}"
        )

    _bump_balance(db, balance, delta_available=-amt, delta_frozen=amt)
    ledger = _write_ledger(
        db,
        user_id=user_id,
        tx_type=_m.TX_FREEZE,
        amount=amt,
        balance=balance,
        use_function=use_function,
        ref_id=ref_id,
        pricing_key=pricing_key,
        status=_m.FREEZE_ACTIVE,
        note=note,
    )
    db.commit()
    db.refresh(ledger)
    return ledger


def consume_freeze(
    db: Session,
    freeze_tx_id: int,
    *,
    note: Optional[str] = None,
) -> _m.CreditLedger:
    """实扣:将冻结交易状态改为 consumed,frozen→consumed。

    语义:
      - 找到 freeze_tx_id 对应的 FREEZE 行(status='active');不存在或已终态
        → 抛 `FreezeNotFoundError` / `FreezeInvalidStateError`;
      - 锁定 balance;
      - frozen -= amount; consumed += amount;
      - 更新 FREEZE 行 status='consumed';
      - 写一条新的 CreditLedger(tx_type='CONSUME', freeze_tx_id=原 id);
      - commit。
    """
    freeze = (
        db.query(_m.CreditLedger)
        .filter(
            _m.CreditLedger.id == freeze_tx_id,
            _m.CreditLedger.tx_type == _m.TX_FREEZE,
        )
        .with_for_update()
        .first()
    )
    if freeze is None:
        db.rollback()
        raise FreezeNotFoundError(f"freeze_tx_id {freeze_tx_id} not found")
    if freeze.status != _m.FREEZE_ACTIVE:
        db.rollback()
        raise FreezeInvalidStateError(
            f"freeze {freeze_tx_id} already {freeze.status}"
        )

    user_id = freeze.user_id
    amt = _dec(freeze.amount)

    balance = _lock_balance(db, user_id)
    _bump_balance(db, balance, delta_frozen=-amt, delta_consumed=amt)

    freeze.status = _m.FREEZE_CONSUMED
    db.flush()

    ledger = _write_ledger(
        db,
        user_id=user_id,
        tx_type=_m.TX_CONSUME,
        amount=amt,
        balance=balance,
        use_function=freeze.use_function,
        ref_id=freeze.ref_id,
        pricing_key=freeze.pricing_key,
        freeze_tx_id=freeze.id,
        note=note or f"consume from freeze #{freeze.id}",
    )
    db.commit()
    db.refresh(ledger)
    return ledger


def rollback_freeze(
    db: Session,
    freeze_tx_id: int,
    *,
    note: Optional[str] = None,
) -> _m.CreditLedger:
    """回滚:冻结交易失败,把积分从 frozen 归还到 available。

    语义同 `consume_freeze`,但 frozen → available 且 status='rolled_back'。
    """
    freeze = (
        db.query(_m.CreditLedger)
        .filter(
            _m.CreditLedger.id == freeze_tx_id,
            _m.CreditLedger.tx_type == _m.TX_FREEZE,
        )
        .with_for_update()
        .first()
    )
    if freeze is None:
        db.rollback()
        raise FreezeNotFoundError(f"freeze_tx_id {freeze_tx_id} not found")
    if freeze.status != _m.FREEZE_ACTIVE:
        db.rollback()
        raise FreezeInvalidStateError(
            f"freeze {freeze_tx_id} already {freeze.status}"
        )

    user_id = freeze.user_id
    amt = _dec(freeze.amount)

    balance = _lock_balance(db, user_id)
    _bump_balance(db, balance, delta_frozen=-amt, delta_available=amt)

    freeze.status = _m.FREEZE_ROLLED_BACK
    db.flush()

    ledger = _write_ledger(
        db,
        user_id=user_id,
        tx_type=_m.TX_ROLLBACK,
        amount=amt,
        balance=balance,
        use_function=freeze.use_function,
        ref_id=freeze.ref_id,
        pricing_key=freeze.pricing_key,
        freeze_tx_id=freeze.id,
        note=note or f"rollback freeze #{freeze.id}",
    )
    db.commit()
    db.refresh(ledger)
    return ledger


def recharge_credit(
    db: Session,
    user_id: int,
    *,
    points: Decimal,
    bonus_points: Optional[Decimal] = None,
    recharge_id: Optional[str] = None,
    note: Optional[str] = None,
) -> tuple[_m.CreditLedger, Optional[_m.CreditLedger]]:
    """充值积分(支付回调触发)。

    - `points`:实际到账的主积分(正数,>0);
    - `bonus_points`:赠送积分(可选,>=0);若不为 None 且 >0,写单独一条
      `TX_BONUS` 流水;
    - `recharge_id`:关联的充值订单号(如 `PF...`),用于幂等与审计。

    返回 `(主流水, 赠送流水 or None)`。
    """
    main = _dec(points)
    if main <= 0:
        raise ValueError(f"recharge points must be > 0, got {main}")
    bonus = _dec(bonus_points or 0)
    if bonus < 0:
        raise ValueError(f"bonus_points must be >= 0, got {bonus}")

    balance = _lock_balance(db, user_id)

    # 主充值
    _bump_balance(
        db, balance,
        delta_available=main, delta_recharged=main,
    )
    main_ledger = _write_ledger(
        db,
        user_id=user_id,
        tx_type=_m.TX_RECHARGE,
        amount=main,
        balance=balance,
        use_function="recharge",
        recharge_id=recharge_id,
        note=note or f"recharge {main} points",
    )

    bonus_ledger: Optional[_m.CreditLedger] = None
    if bonus > 0:
        _bump_balance(
            db, balance,
            delta_available=bonus, delta_recharged=bonus,
        )
        bonus_ledger = _write_ledger(
            db,
            user_id=user_id,
            tx_type=_m.TX_BONUS,
            amount=bonus,
            balance=balance,
            use_function="recharge_bonus",
            recharge_id=recharge_id,
            note=f"bonus {bonus} points (bonus on recharge_id={recharge_id})",
        )

    db.commit()
    db.refresh(main_ledger)
    if bonus_ledger is not None:
        db.refresh(bonus_ledger)
    return main_ledger, bonus_ledger


def refund_credit(
    db: Session,
    user_id: int,
    *,
    amount: Decimal,
    recharge_id: Optional[str] = None,
    note: Optional[str] = None,
) -> _m.CreditLedger:
    """管理员退款:从余额中扣减积分(amount>0,实际入账为负数)。

    与 FREEZE/CONSUME 不同,退款不影响 frozen 账户;直接从 available 扣减。
    若 available 不足,截断到 0(避免负余额);调用方应根据返回值判断实际扣减额。
    """
    want = _dec(amount)
    if want <= 0:
        raise ValueError(f"refund amount must be > 0, got {want}")

    balance = _lock_balance(db, user_id)
    available = _dec(balance.available_points)
    actual = want if available >= want else available
    if actual == 0:
        # 无可退;写一条 amount=0 的流水留痕,便于审计
        ledger = _write_ledger(
            db,
            user_id=user_id,
            tx_type=_m.TX_REFUND,
            amount=_ZERO,
            balance=balance,
            recharge_id=recharge_id,
            note=(note or "refund: no available points to deduct")
            + f" (wanted {want})",
        )
        db.commit()
        db.refresh(ledger)
        return ledger

    _bump_balance(db, balance, delta_available=-actual)
    ledger = _write_ledger(
        db,
        user_id=user_id,
        tx_type=_m.TX_REFUND,
        amount=actual,  # 用正数记录"退了多少";方向由 tx_type 决定
        balance=balance,
        recharge_id=recharge_id,
        note=note or f"refund {actual} points",
    )
    db.commit()
    db.refresh(ledger)
    return ledger


# ──────────────────────────────────────────────────────────────
# 价目表
# ──────────────────────────────────────────────────────────────


# 澜途 `/system/config/ai-point-pricing` 对齐(见审计报告 §2.3)
DEFAULT_PRICING: list[dict] = [
    {"key": "aiTitle",              "name": "AI标题",       "points": "0.10",  "category": "ai_design", "order": 10},
    {"key": "aiCategory",           "name": "AI分类",       "points": "0.20",  "category": "ai_design", "order": 20},
    {"key": "aiAttributes",         "name": "AI属性",       "points": "1.00",  "category": "ai_design", "order": 30},
    {"key": "aiVariants",           "name": "AI变体",       "points": "1.00",  "category": "ai_design", "order": 40},
    {"key": "aiAttributesVariants", "name": "AI属性变体",   "points": "1.50",  "category": "ai_design", "order": 50},
    {"key": "aiProductInfoCap",     "name": "AI商品信息",   "points": "1.50",  "category": "ai_design", "order": 60},
    {"key": "lowQualityBatch",      "name": "低质图批量",   "points": "0.20",  "category": "ai_design", "order": 70},
    {"key": "imageProcess",         "name": "图片处理",     "points": "1.00",  "category": "ai_design", "order": 80},
    {"key": "aiImageGeneration",    "name": "AI生图",       "points": "1.50",  "category": "ai_design", "order": 90},
    {"key": "aiImageGeneration2k",  "name": "AI生图2K",     "points": "1.50",  "category": "ai_design", "order": 91},
    {"key": "apparelSkcClassification", "name": "服饰SKU分类", "points": "1.00", "category": "ai_design", "order": 100},
    {"key": "productFissionAnalysis", "name": "裂变分析",   "points": "0.50",  "category": "fission",   "order": 110},
    {"key": "productFissionImage",  "name": "裂变图",       "points": "1.50",  "category": "fission",   "order": 120},
    {"key": "productCollection",    "name": "商品采集",     "points": "0.00",  "category": "collect",   "order": 130},
]


def seed_pricing(db: Session) -> int:
    """幂等写入默认价目表(按 pricing_key upsert)。

    返回实际写入或更新的记录数。已存在的项若 `enabled` 未被外部显式关闭,
    会同步 `display_name`/`points`/`category`/`sort_order` 以跟随代码升级;
    `enabled=False` 视为"管理员手动停用",seed 不动。
    """
    changed = 0
    for row in DEFAULT_PRICING:
        exists = db.execute(
            select(_m.CreditPricing).where(_m.CreditPricing.pricing_key == row["key"])
        ).scalar_one_or_none()
        if exists is None:
            db.add(_m.CreditPricing(
                pricing_key=row["key"],
                display_name=row["name"],
                points=Decimal(row["points"]),
                category=row["category"],
                enabled=True,
                sort_order=row["order"],
            ))
            changed += 1
        else:
            if exists.enabled:  # 未停用的项才跟随代码更新
                exists.display_name = row["name"]
                exists.points = Decimal(row["points"])
                exists.category = row["category"]
                exist_order = int(exists.sort_order or 0)
                if exist_order == 0 or exist_order == row["order"]:
                    exists.sort_order = row["order"]
                exists.updated_at = _utcnow()
                changed += 1
    db.commit()
    return changed


def get_pricing(db: Session, pricing_key: str) -> Optional[_m.CreditPricing]:
    row = db.execute(
        select(_m.CreditPricing).where(_m.CreditPricing.pricing_key == pricing_key)
    ).scalar_one_or_none()
    if row is None or not row.enabled:
        return None
    return row


def list_pricing(db: Session) -> list[_m.CreditPricing]:
    rows = (
        db.query(_m.CreditPricing)
        .order_by(_m.CreditPricing.sort_order.asc(), _m.CreditPricing.pricing_key.asc())
        .all()
    )
    return rows


def points_for_pricing(db: Session, pricing_key: str) -> Decimal:
    """读取 pricing_key 对应的积分;未启用/不存在返回 0(调用方可判定)。"""
    row = get_pricing(db, pricing_key)
    if row is None:
        return _ZERO
    return _dec(row.points)


__all__ = [
    "InsufficientPointsError",
    "FreezeNotFoundError",
    "FreezeInvalidStateError",
    "get_or_create_balance",
    "get_account",
    "freeze_points",
    "consume_freeze",
    "rollback_freeze",
    "recharge_credit",
    "refund_credit",
    "seed_pricing",
    "get_pricing",
    "list_pricing",
    "points_for_pricing",
    "DEFAULT_PRICING",
]
