"""C-F · 退款 ↔ 订阅语义:接口预留测试(仅接口/数据结构,不改默认行为)。

覆盖:
  1. `billing.cancel_subscription(user_id, *, reason=...)`:
     正常取消 / 重复调用幂等 / 不存在的 user / 不影响其它用户的订阅;
  2. `billing.shorten_subscription(user_id, *, days_to_revoke=...)`:
     前移 N 天 / N 大于剩余天数 → 等同取消 / N<=0 → 422 /
     无 expire_at(free 订阅)→ no-op / 已取消/过期 → 幂等 no-op;
  3. **退款端点默认不改订阅**:全额退款后 Subscription.status / expire_at
     保持不变;`RefundResponse.subscription_touched` 恒为 False;
     新字段 `subscription_note` 存在且包含"未自动撤销"的说明;
     旧字段含义/类型不变(向后兼容)。

用法:
  python cloud_service/test_billing_refund_semantics.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 用临时 SQLite,不污染仓库 ─────────────────────────────────
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["CLOUD_DB_URL"] = f"sqlite:///{_tmp.name}"
os.environ["CLOUD_FREE_QUOTA"] = "5"
os.environ["CLOUD_PRO_QUOTA"] = "-1"
os.environ["CLOUD_ADMIN_TOKEN"] = "test-admin-secret"
os.environ["CLOUD_PAYMENT_NOTIFY_URL"] = "/cloud/payment/callback/alipay"
os.environ["CLOUD_PAYMENT_RETURN_URL"] = "/payment/success"
# 线上支付默认下线(2026-10-22);测试要覆盖支付代码路径,显式打开开关。
os.environ["CLOUD_ONLINE_PAYMENT_ENABLED"] = "true"

# 确保能导入仓库根
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def _mk_alipay_callback(order_no: str, trade_no: str, amount: float,
                        plan: str = "pro", days: int = 30) -> dict:
    from cloud_service.payment import alipay
    adapter = alipay.AlipayAdapter()
    payload = {
        "out_trade_no": order_no,
        "total_amount": f"{amount:.2f}",
        "plan": plan,
        "days": str(days),
        "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
        "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
    }
    sign = alipay._mock_sign(adapter._sign_secret, payload)
    return {
        "out_trade_no": order_no,
        "trade_no": trade_no,
        "total_amount": f"{amount:.2f}",
        "trade_status": "TRADE_SUCCESS",
        "plan": plan,
        "days": str(days),
        "notify_url": os.environ["CLOUD_PAYMENT_NOTIFY_URL"],
        "return_url": os.environ["CLOUD_PAYMENT_RETURN_URL"],
        "sign": sign,
    }


def _tzaware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def run() -> int:
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from cloud_service.main import app
    from cloud_service.db import SessionLocal
    from cloud_service.auth.models import User
    from cloud_service.billing.models import Subscription
    from cloud_service.billing.router import (
        activate_for_user,
        cancel_subscription,
        shorten_subscription,
        SubscriptionNotFoundError,
    )
    from cloud_service.payment.models import Order, STATUS_PAID

    fails = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal fails
        tag = "PASS" if cond else "FAIL"
        print(f"[{tag}] {label}" + (f" — {extra}" if extra else ""))
        if not cond:
            fails += 1

    with TestClient(app) as client:
        # ── 0. 注册用户 + JWT ─────────────────────────────
        for uname, email in [("alice_a", "a@example.com"),
                             ("bob_b", "b@example.com"),
                             ("carol_c", "c@example.com")]:
            r = client.post(
                "/cloud/auth/register",
                json={"username": uname, "email": email, "password": "supers3cret"},
            )
            check(f"register {uname}", r.status_code == 201, f"status={r.status_code}")

        r = client.post(
            "/cloud/auth/login",
            json={"username": "alice_a", "password": "supers3cret"},
        )
        check("login alice_a", r.status_code == 200, f"status={r.status_code}")
        access = r.json().get("access_token", "")
        H = {"Authorization": f"Bearer {access}"}

        # ── 1. cancel_subscription: 正常取消 ──────────────
        # 直接在 Session 里给 alice_a 激活一个 pro 30 天订阅,拿到订阅前状态。
        db = SessionLocal()
        try:
            alice = db.execute(
                select(User).where(User.username == "alice_a")
            ).scalar_one()
            activate_for_user(db, alice, plan="pro", days=30)
            alice_sub_before = db.execute(
                select(Subscription).where(Subscription.user_id == alice.id)
            ).scalar_one()
            status_before = alice_sub_before.status
            exp_before = alice_sub_before.expire_at
            plan_before = alice_sub_before.plan
            quota_before = alice_sub_before.quota

            check("precondition: alice_a subscription active + has expire_at",
                  status_before == "active" and exp_before is not None,
                  f"status={status_before} expire_at={exp_before}")

            result = cancel_subscription(db, alice.id, reason="test-cancel")
            check("cancel_subscription returns ok=True",
                  result.get("ok") is True, f"result={result}")
            check("cancel_subscription changed=True (first call)",
                  result.get("changed") is True, f"result={result}")
            check("cancel_subscription reason=='cancelled'",
                  result.get("reason") == "cancelled", f"result={result}")

            alice_sub_after = db.execute(
                select(Subscription).where(Subscription.user_id == alice.id)
            ).scalar_one()
            check("after cancel: status == 'cancelled'",
                  alice_sub_after.status == "cancelled",
                  f"status={alice_sub_after.status}")
            check("after cancel: expire_at unchanged",
                  alice_sub_after.expire_at == exp_before,
                  f"exp_before={exp_before} exp_after={alice_sub_after.expire_at}")
            check("after cancel: plan unchanged",
                  alice_sub_after.plan == plan_before,
                  f"plan={alice_sub_after.plan}")
            check("after cancel: quota unchanged",
                  alice_sub_after.quota == quota_before,
                  f"quota={alice_sub_after.quota}")
            check("after cancel: subscription dict serialised",
                  isinstance(result.get("subscription"), dict)
                  and result["subscription"].get("status") == "cancelled",
                  f"subscription={result.get('subscription')}")
        finally:
            db.close()

        # ── 2. cancel_subscription: 幂等 ──────────────────
        db = SessionLocal()
        try:
            result2 = cancel_subscription(db, alice.id, reason="second-time")
            check("cancel_subscription idempotent: ok=True",
                  result2.get("ok") is True, f"result={result2}")
            check("cancel_subscription idempotent: changed=False",
                  result2.get("changed") is False, f"result={result2}")
            check("cancel_subscription idempotent: reason=='already-invalid'",
                  result2.get("reason") == "already-invalid", f"result={result2}")

            alice_sub_again = db.execute(
                select(Subscription).where(Subscription.user_id == alice.id)
            ).scalar_one()
            check("cancel_subscription idempotent: status still 'cancelled'",
                  alice_sub_again.status == "cancelled",
                  f"status={alice_sub_again.status}")
            check("cancel_subscription idempotent: expire_at untouched",
                  alice_sub_again.expire_at == exp_before,
                  f"exp_before={exp_before} exp_now={alice_sub_again.expire_at}")
        finally:
            db.close()

        # ── 3. cancel_subscription: 不存在的 user ─────────
        db = SessionLocal()
        try:
            try:
                cancel_subscription(db, 999_999, reason="no-such-user")
                check("cancel_subscription with unknown user raises", False,
                      "no exception raised")
            except SubscriptionNotFoundError as e:
                check("cancel_subscription with unknown user raises "
                      "SubscriptionNotFoundError", True, f"msg={e}")
            except Exception as e:
                check("cancel_subscription with unknown user raises "
                      "SubscriptionNotFoundError", False, f"got {type(e).__name__}: {e}")
        finally:
            db.close()

        # ── 4. cancel_subscription: 不影响其它用户 ───────
        db = SessionLocal()
        try:
            bob = db.execute(
                select(User).where(User.username == "bob_b")
            ).scalar_one()
            # 先给 bob 激活一个 pro 订阅,让他在有订阅的状态下被"误伤检查"
            activate_for_user(db, bob, plan="pro", days=30)
            bob_before = db.execute(
                select(Subscription).where(Subscription.user_id == bob.id)
            ).scalar_one()
            bob_exp_before = bob_before.expire_at
            check("precondition: bob_b has active subscription",
                  bob_before.status == "active" and bob_exp_before is not None,
                  f"status={bob_before.status} exp={bob_exp_before}")

            # 再次取消 alice(幂等),验证 bob 完全不受影响
            cancel_subscription(db, alice.id)

            bob_after = db.execute(
                select(Subscription).where(Subscription.user_id == bob.id)
            ).scalar_one()
            check("cancel alice does NOT affect bob.status",
                  bob_after.status == "active",
                  f"bob.status={bob_after.status}")
            check("cancel alice does NOT affect bob.expire_at",
                  bob_after.expire_at == bob_exp_before,
                  f"before={bob_exp_before} after={bob_after.expire_at}")
            check("cancel alice does NOT affect bob.plan",
                  bob_after.plan == "pro", f"plan={bob_after.plan}")
        finally:
            db.close()

        # ── 5. shorten_subscription: 前移 N 天 ────────────
        db = SessionLocal()
        try:
            carol = db.execute(
                select(User).where(User.username == "carol_c")
            ).scalar_one()
            activate_for_user(db, carol, plan="pro", days=30)
            carol_before = db.execute(
                select(Subscription).where(Subscription.user_id == carol.id)
            ).scalar_one()
            exp_before = _tzaware(carol_before.expire_at)
            check("precondition: carol_c has active pro 30d subscription",
                  carol_before.status == "active",
                  f"status={carol_before.status}")

            result = shorten_subscription(db, carol.id, days_to_revoke=5)
            check("shorten_subscription 5d: ok=True",
                  result.get("ok") is True, f"result={result}")
            check("shorten_subscription 5d: changed=True",
                  result.get("changed") is True, f"result={result}")
            check("shorten_subscription 5d: reason=='shortened'",
                  result.get("reason") == "shortened", f"result={result}")

            carol_after = db.execute(
                select(Subscription).where(Subscription.user_id == carol.id)
            ).scalar_one()
            exp_after = _tzaware(carol_after.expire_at)
            delta = (exp_before - exp_after).total_seconds()
            # 允许 5s 误差(SQLite + tz-aware 序列化抖动)
            check("shorten_subscription 5d: expire_at moved ~5 days back",
                  abs(delta - 5 * 86400) < 5,
                  f"delta_s={delta}")
            check("shorten_subscription 5d: status unchanged ('active')",
                  carol_after.status == "active",
                  f"status={carol_after.status}")
        finally:
            db.close()

        # ── 6. shorten_subscription: N 大于剩余天数 → 等同取消 ──
        db = SessionLocal()
        try:
            # carol 已经 shortening 过 5 天(还剩 ~25 天),再减 60 天 → 应取消
            result = shorten_subscription(db, carol.id, days_to_revoke=60)
            check("shorten_subscription 60d (beyond remaining): ok=True",
                  result.get("ok") is True, f"result={result}")
            check("shorten_subscription 60d: changed=True",
                  result.get("changed") is True, f"result={result}")
            check("shorten_subscription 60d: reason=='cancelled'",
                  result.get("reason") == "cancelled", f"result={result}")

            carol_after = db.execute(
                select(Subscription).where(Subscription.user_id == carol.id)
            ).scalar_one()
            exp_after = _tzaware(carol_after.expire_at)
            check("shorten_subscription 60d: expire_at <= now",
                  exp_after <= datetime.now(timezone.utc),
                  f"exp_after={exp_after} now={datetime.now(timezone.utc)}")
            check("shorten_subscription 60d: status == 'cancelled'",
                  carol_after.status == "cancelled",
                  f"status={carol_after.status}")
        finally:
            db.close()

        # ── 7. shorten_subscription: N <= 0 → 422 ─────────
        db = SessionLocal()
        try:
            # 给 carol 重新激活(让 case 8 的 case-9 no-expire-at 有干净环境)
            from fastapi import HTTPException
            carol2 = db.execute(
                select(User).where(User.username == "carol_c")
            ).scalar_one()
            activate_for_user(db, carol2, plan="pro", days=30)
            carol_exp_saved = db.execute(
                select(Subscription).where(Subscription.user_id == carol2.id)
            ).scalar_one().expire_at

            for bad_n in (0, -1, -30):
                try:
                    shorten_subscription(db, carol2.id, days_to_revoke=bad_n)
                    check(f"shorten_subscription days_to_revoke={bad_n} -> 422",
                          False, "no exception raised")
                except HTTPException as e:
                    check(f"shorten_subscription days_to_revoke={bad_n} -> 422",
                          e.status_code == 422,
                          f"status={e.status_code} detail={e.detail}")
                except Exception as e:
                    check(f"shorten_subscription days_to_revoke={bad_n} -> 422",
                          False, f"got {type(e).__name__}: {e}")

            # 422 未落库:订阅应该保持激活
            carol_after = db.execute(
                select(Subscription).where(Subscription.user_id == carol2.id)
            ).scalar_one()
            check("shorten_subscription N<=0: expire_at unchanged after 422",
                  carol_after.expire_at == carol_exp_saved,
                  f"before={carol_exp_saved} after={carol_after.expire_at}")
        finally:
            db.close()

        # ── 8. shorten_subscription: 无 expire_at(free) → no-op ──
        db = SessionLocal()
        try:
            # 手动把 carol 订阅改为 free(永久)
            carol3 = db.execute(
                select(User).where(User.username == "carol_c")
            ).scalar_one()
            activate_for_user(db, carol3, plan="free", days=30)
            carol_after = db.execute(
                select(Subscription).where(Subscription.user_id == carol3.id)
            ).scalar_one()
            check("precondition: carol_c now free w/ expire_at=None",
                  carol_after.expire_at is None,
                  f"exp={carol_after.expire_at}")

            result = shorten_subscription(db, carol3.id, days_to_revoke=3)
            check("shorten_subscription on free (no expire_at): ok=True",
                  result.get("ok") is True, f"result={result}")
            check("shorten_subscription on free: changed=False",
                  result.get("changed") is False, f"result={result}")
            check("shorten_subscription on free: reason=='no-expire-at'",
                  result.get("reason") == "no-expire-at", f"result={result}")
        finally:
            db.close()

        # ── 9. shorten_subscription: 已取消 → 幂等 no-op ─
        db = SessionLocal()
        try:
            result = shorten_subscription(db, alice.id, days_to_revoke=3)
            check("shorten_subscription on cancelled: ok=True",
                  result.get("ok") is True, f"result={result}")
            check("shorten_subscription on cancelled: changed=False",
                  result.get("changed") is False, f"result={result}")
            check("shorten_subscription on cancelled: reason=='already-invalid'",
                  result.get("reason") == "already-invalid", f"result={result}")
        finally:
            db.close()

        # ── 10. 退款端点默认不改订阅 —— 全额退款 ───────────
        # 用 alice_a 走完整 create_order → callback → refund 流程。
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "alipay"},
            headers=H,
        )
        check("refund test: create_order → 201", r.status_code == 201,
              f"status={r.status_code}")
        order_no = r.json()["order_no"]
        r = client.post("/cloud/payment/callback/alipay",
                        json=_mk_alipay_callback(order_no, "TX_REFUND_A", 99.0))
        check("refund test: callback → 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")

        # 拿到退款前的订阅快照
        db = SessionLocal()
        try:
            alice_db = db.execute(
                select(User).where(User.username == "alice_a")
            ).scalar_one()
            alice_sub_before_refund = db.execute(
                select(Subscription).where(Subscription.user_id == alice_db.id)
            ).scalar_one()
            sub_status_before_refund = alice_sub_before_refund.status
            sub_exp_before_refund = alice_sub_before_refund.expire_at
            sub_plan_before_refund = alice_sub_before_refund.plan
        finally:
            db.close()

        check("precondition before refund: alice_a has active pro subscription",
              sub_status_before_refund == "active"
              and sub_exp_before_refund is not None
              and sub_plan_before_refund == "pro",
              f"status={sub_status_before_refund} exp={sub_exp_before_refund} "
              f"plan={sub_plan_before_refund}")

        r = client.post(
            "/cloud/payment/refund",
            json={"order_no": order_no},
            headers={**H, "X-Admin-Token": "test-admin-secret"},
        )
        check("refund test: refund → 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:300]}")
        body = r.json()
        check("refund test: subscription_touched == False",
              body.get("subscription_touched") is False,
              f"body={body}")
        check("refund test: order_status == 'refunded' (full)",
              body.get("order_status") == "refunded",
              f"body={body}")

        # 新字段:subscription_note 存在且提到未自动撤销
        note = body.get("subscription_note")
        check("refund test: subscription_note is present",
              isinstance(note, str) and len(note) > 0,
              f"subscription_note={note!r}")
        check("refund test: subscription_note mentions subscription unchanged",
              "unchanged" in (note or "").lower()
              or "not touched" in (note or "").lower(),
              f"subscription_note={note!r}")
        check("refund test: subscription_note mentions rule pending",
              "pending" in (note or "").lower()
              or "cancel_subscription" in (note or ""),
              f"subscription_note={note!r}")

        # ★ 关键断言:退款后订阅状态不变(默认行为未变)
        db = SessionLocal()
        try:
            alice_db2 = db.execute(
                select(User).where(User.username == "alice_a")
            ).scalar_one()
            alice_sub_after_refund = db.execute(
                select(Subscription).where(Subscription.user_id == alice_db2.id)
            ).scalar_one()
        finally:
            db.close()

        check("★ DEFAULT BEHAVIOR UNCHANGED: status unchanged after full refund",
              alice_sub_after_refund.status == sub_status_before_refund,
              f"before={sub_status_before_refund} after={alice_sub_after_refund.status}")
        check("★ DEFAULT BEHAVIOR UNCHANGED: expire_at unchanged after full refund",
              alice_sub_after_refund.expire_at == sub_exp_before_refund,
              f"before={sub_exp_before_refund} after={alice_sub_after_refund.expire_at}")
        check("★ DEFAULT BEHAVIOR UNCHANGED: plan unchanged after full refund",
              alice_sub_after_refund.plan == sub_plan_before_refund,
              f"before={sub_plan_before_refund} after={alice_sub_after_refund.plan}")

        # 响应 schema 向后兼容:老字段仍然存在
        check("RefundResponse still has order_no",
              "order_no" in body, f"keys={sorted(body.keys())}")
        check("RefundResponse still has refunded_amount",
              "refunded_amount" in body, f"keys={sorted(body.keys())}")
        check("RefundResponse still has order_status",
              "order_status" in body, f"keys={sorted(body.keys())}")
        check("RefundResponse still has subscription_touched",
              "subscription_touched" in body, f"keys={sorted(body.keys())}")
        check("RefundResponse still has note (may be None for full refund)",
              "note" in body, f"keys={sorted(body.keys())}")
        check("RefundResponse.subscription_touched type is bool",
              isinstance(body.get("subscription_touched"), bool),
              f"type={type(body.get('subscription_touched')).__name__}")

        # ── 11. 部分退款:订阅同样不变 + subscription_note 存在 ─
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "alipay"},
            headers=H,
        )
        check("partial refund: create_order → 201", r.status_code == 201,
              f"status={r.status_code}")
        order_no2 = r.json()["order_no"]
        r = client.post("/cloud/payment/callback/alipay",
                        json=_mk_alipay_callback(order_no2, "TX_REFUND_B", 99.0))
        check("partial refund: callback → 200", r.status_code == 200,
              f"status={r.status_code}")

        # 用 bob 的用户视角再拿一份订阅快照(bob 之前也激活了 pro)
        db = SessionLocal()
        try:
            bob_db = db.execute(
                select(User).where(User.username == "bob_b")
            ).scalar_one()
            # 让 bob 走自己的 order,与 alice 无关 —— 但 refund 是按 JWT
            # admin 校验的,JWT 仍是 alice。这里我们让 alice 再建一个 order
            # 来走 partial refund;bob 的状态用于"旁路对照"。
            bob_sub_exp_before = db.execute(
                select(Subscription).where(Subscription.user_id == bob_db.id)
            ).scalar_one().expire_at
        finally:
            db.close()

        # 再给 alice 一个 order,做 partial refund
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "alipay"},
            headers=H,
        )
        check("partial refund (alice): create_order → 201", r.status_code == 201,
              f"status={r.status_code}")
        alice_order2 = r.json()["order_no"]
        r = client.post("/cloud/payment/callback/alipay",
                        json=_mk_alipay_callback(alice_order2, "TX_REFUND_C", 99.0))
        check("partial refund (alice): callback → 200", r.status_code == 200,
              f"status={r.status_code}")

        # alice 当前订阅快照(partial 前)
        db = SessionLocal()
        try:
            alice_db3 = db.execute(
                select(User).where(User.username == "alice_a")
            ).scalar_one()
            alice_before_partial = db.execute(
                select(Subscription).where(Subscription.user_id == alice_db3.id)
            ).scalar_one()
            alice_status_before_partial = alice_before_partial.status
            alice_exp_before_partial = alice_before_partial.expire_at
        finally:
            db.close()

        r = client.post(
            "/cloud/payment/refund",
            json={"order_no": alice_order2, "amount": 30.0},
            headers={**H, "X-Admin-Token": "test-admin-secret"},
        )
        check("partial refund → 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:300]}")
        body2 = r.json()
        check("partial refund: subscription_touched == False",
              body2.get("subscription_touched") is False,
              f"body={body2}")
        check("partial refund: order_status == 'paid'",
              body2.get("order_status") == "paid",
              f"body={body2}")
        check("partial refund: note mentions 'partial' (legacy field preserved)",
              body2.get("note") is not None and "partial" in body2["note"].lower(),
              f"note={body2.get('note')!r}")

        note2 = body2.get("subscription_note")
        check("partial refund: subscription_note is present",
              isinstance(note2, str) and len(note2) > 0,
              f"subscription_note={note2!r}")
        check("partial refund: subscription_note mentions partial/shorten",
              "partial" in (note2 or "").lower()
              or "shorten_subscription" in (note2 or ""),
              f"subscription_note={note2!r}")

        # 部分退款后订阅也保持不变
        db = SessionLocal()
        try:
            alice_db4 = db.execute(
                select(User).where(User.username == "alice_a")
            ).scalar_one()
            alice_after_partial = db.execute(
                select(Subscription).where(Subscription.user_id == alice_db4.id)
            ).scalar_one()
            # bob 对照
            bob_db4 = db.execute(
                select(User).where(User.username == "bob_b")
            ).scalar_one()
            bob_after_partial = db.execute(
                select(Subscription).where(Subscription.user_id == bob_db4.id)
            ).scalar_one()
        finally:
            db.close()

        check("★ DEFAULT BEHAVIOR UNCHANGED: alice status unchanged after partial refund",
              alice_after_partial.status == alice_status_before_partial,
              f"before={alice_status_before_partial} "
              f"after={alice_after_partial.status}")
        check("★ DEFAULT BEHAVIOR UNCHANGED: alice expire_at unchanged after partial refund",
              alice_after_partial.expire_at == alice_exp_before_partial,
              f"before={alice_exp_before_partial} "
              f"after={alice_after_partial.expire_at}")
        check("★ DEFAULT BEHAVIOR UNCHANGED: bob expire_at unchanged (cross-user)",
              bob_after_partial.expire_at == bob_sub_exp_before,
              f"before={bob_sub_exp_before} after={bob_after_partial.expire_at}")

    try:
        Path(_tmp.name).unlink(missing_ok=True)
    except OSError:
        pass

    return fails


if __name__ == "__main__":
    rc = run()
    print(f"\n{'ALL TESTS PASSED' if rc == 0 else f'{rc} TEST(S) FAILED'}")
    sys.exit(0 if rc == 0 else 1)
