"""C19 遗留补齐 · 集成测试(退款 + 对账 + 订单超时关闭)。

覆盖:
  1. 退款端点:admin token + JWT;paid → refunded;非 paid 拒绝;重复退款 409;
     部分退款不改 status;金额超限拒绝;未配置 admin token → 503。
  2. 对账函数:注入 mock 平台账单,验证 local_only / platform_only /
     amount_mismatch / matched 四类。
  3. 订单超时关闭:close_expired_orders 只关闭超过阈值的 created 订单;
     不影响 paid / refunded / closed / 未超时的 created。

用法(仓库根,已激活 prismenv 或直接用绝对路径 python):
  python cloud_service/test_payment_leftover.py
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

# 便于测试:免费/付费额度小;admin token 显式给出
os.environ["CLOUD_FREE_QUOTA"] = "5"
os.environ["CLOUD_PRO_QUOTA"] = "-1"
os.environ["CLOUD_ADMIN_TOKEN"] = "test-admin-secret"
os.environ["CLOUD_PAYMENT_NOTIFY_URL"] = "/cloud/payment/callback/alipay"
os.environ["CLOUD_PAYMENT_RETURN_URL"] = "/payment/success"

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


def run() -> int:
    from fastapi.testclient import TestClient
    from cloud_service.main import app
    from cloud_service.db import SessionLocal
    from cloud_service.payment.models import Order, STATUS_PAID
    from cloud_service.payment.reconciliation import reconcile_day
    from cloud_service.payment.scheduler import close_expired_orders

    fails = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal fails
        tag = "PASS" if cond else "FAIL"
        print(f"[{tag}] {label}" + (f" — {extra}" if extra else ""))
        if not cond:
            fails += 1

    with TestClient(app) as client:
        # ── 0. 用户 + JWT ─────────────────────────────
        r = client.post("/cloud/auth/register", json={
            "username": "payer1", "email": "p1@example.com",
            "password": "supers3cret",
        })
        check("register payer1", r.status_code == 201, f"status={r.status_code}")
        r = client.post("/cloud/auth/login", json={
            "username": "payer1", "password": "supers3cret",
        })
        check("login payer1", r.status_code == 200, f"status={r.status_code}")
        access = r.json().get("access_token", "")
        H = {"Authorization": f"Bearer {access}"}

        # ── 1. 无 JWT → 401 ──────────────────────────
        r = client.post(
            "/cloud/payment/refund",
            json={"order_no": "NOPE"},
            headers={"X-Admin-Token": "test-admin-secret"},
        )
        check("refund without JWT → 401", r.status_code == 401,
              f"status={r.status_code}")

        # ── 2. 错 admin token → 403 ───────────────────
        r = client.post(
            "/cloud/payment/refund",
            json={"order_no": "NOPE"},
            headers={**H, "X-Admin-Token": "wrong"},
        )
        check("refund with wrong admin token → 403",
              r.status_code == 403, f"status={r.status_code}")

        # ── 3. 创建订单 + 支付 → paid ─────────────────
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "alipay"},
            headers=H,
        )
        check("create_order → 201", r.status_code == 201,
              f"status={r.status_code}")
        order_no = r.json()["order_no"]
        r = client.post("/cloud/payment/callback/alipay",
                        json=_mk_alipay_callback(order_no, "TX_A1", 99.0))
        check("callback → paid", r.status_code == 200,
              f"status={r.status_code}")

        # ── 4. 状态校验:created 不能退 ────────────────
        r2 = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "alipay"},
            headers=H,
        )
        created_no = r2.json()["order_no"]
        r = client.post(
            "/cloud/payment/refund",
            json={"order_no": created_no},
            headers={**H, "X-Admin-Token": "test-admin-secret"},
        )
        check("refund created order → 400", r.status_code == 400,
              f"status={r.status_code} body={r.text[:200]}")

        # ── 5. 全额退款 → 200,Order.status=refunded ──
        r = client.post(
            "/cloud/payment/refund",
            json={"order_no": order_no},
            headers={**H, "X-Admin-Token": "test-admin-secret"},
        )
        check("refund paid order → 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:300]}")
        body = r.json()
        check("refund.refunded_amount == 99.0",
              body.get("refunded_amount") == 99.0,
              f"body={body}")
        check("refund.order_status == refunded",
              body.get("order_status") == "refunded",
              f"body={body}")
        check("refund.refund_trade_no present",
              bool(body.get("refund_trade_no")),
              f"body={body}")
        check("refund.refunded_at present",
              bool(body.get("refunded_at")),
              f"body={body}")
        check("refund.subscription_touched == False (current decision)",
              body.get("subscription_touched") is False,
              f"body={body}")

        # ── 6. 重复退款 → 409 ─────────────────────────
        r = client.post(
            "/cloud/payment/refund",
            json={"order_no": order_no},
            headers={**H, "X-Admin-Token": "test-admin-secret"},
        )
        check("duplicate refund → 409", r.status_code == 409,
              f"status={r.status_code}")

        # ── 7. Order.to_dict() 反映 refunded_at ───────
        from sqlalchemy import select as _sel_query
        db = SessionLocal()
        o = db.execute(
            _sel_query(Order).where(Order.order_no == order_no)
        ).scalar_one_or_none()
        d = o.to_dict()
        check("Order.to_dict().status == refunded",
              d["status"] == "refunded", f"d={d}")
        check("Order.to_dict().refunded_at not None",
              bool(d.get("refunded_at")), f"d={d}")

        # ── 8. 部分退款(第二个订单)──────────────────
        r = client.post(
            "/cloud/payment/create_order",
            json={"plan": "pro", "days": 30, "channel": "alipay"},
            headers=H,
        )
        o2_no = r.json()["order_no"]
        r = client.post("/cloud/payment/callback/alipay",
                        json=_mk_alipay_callback(o2_no, "TX_A2", 99.0))
        check("callback o2 → 200", r.status_code == 200)

        r = client.post(
            "/cloud/payment/refund",
            json={"order_no": o2_no, "amount": 30.0},
            headers={**H, "X-Admin-Token": "test-admin-secret"},
        )
        check("partial refund → 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        b2 = r.json()
        check("partial refund.order_status == paid",
              b2.get("order_status") == "paid", f"body={b2}")
        check("partial refund.note mentions partial",
              b2.get("note") is not None and "partial" in b2["note"].lower(),
              f"body={b2}")

        # 金额超限 → 400
        r = client.post(
            "/cloud/payment/refund",
            json={"order_no": o2_no, "amount": 200.0},
            headers={**H, "X-Admin-Token": "test-admin-secret"},
        )
        check("refund amount > order.amount → 400",
              r.status_code == 400, f"status={r.status_code}")

        # ── 9. 未配置 admin token → 503 ───────────────
        saved = os.environ.pop("CLOUD_ADMIN_TOKEN")
        try:
            r = client.post(
                "/cloud/payment/refund",
                json={"order_no": o2_no},
                headers={**H, "X-Admin-Token": "anything"},
            )
            check("refund with unset admin token → 503",
                  r.status_code == 503, f"status={r.status_code}")
        finally:
            os.environ["CLOUD_ADMIN_TOKEN"] = saved

        # ── 10. 对账:mock 平台账单 ───────────────────
        # 本地 o2 状态 = paid(amount 99);
        # 注入账单: 一条匹配(o2 99 元)、一条本地无(平台独有)、
        # 一条金额不符(o2 已匹配过,这里用 order_no 变体)、
        # 一条本地有但平台无(order_no=o2_no_ghost —— 通过 DB 造)
        #
        # 我们直接构造一个"日期内 paid 集合",通过 DB 造两条:
        #  * o2 (已 paid 99)
        #  * o3_ghost (手动创建 paid 订单,99 元)
        from sqlalchemy import select as _sel
        o3 = Order(user_id=o.user_id, order_no="MANUAL_PAID_GHOST",
                    amount=50.0, plan="pro", days=30,
                    status=STATUS_PAID, channel="alipay",
                    pay_trade_no="TX_GHOST",
                    created_at=datetime.now(timezone.utc),
                    paid_at=datetime.now(timezone.utc))
        db.add(o3)
        db.commit()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        platform_bills = [
            {"out_trade_no": o2_no, "pay_trade_no": "TX_A2",
             "amount": 99.0, "channel": "alipay",
             "trade_time": today, "trade_type": "payment"},
            # 平台独有
            {"out_trade_no": "PLATFORM_ONLY_1", "pay_trade_no": "TX_PLAT1",
             "amount": 12.0, "channel": "alipay",
             "trade_time": today, "trade_type": "payment"},
            # 本地 o3 amount=50,平台 amount=75 → mismatch
            {"out_trade_no": "MANUAL_PAID_GHOST", "pay_trade_no": "TX_GHOST",
             "amount": 75.0, "channel": "alipay",
             "trade_time": today, "trade_type": "payment"},
        ]
        report = reconcile_day(db, start_date=today, end_date=today,
                                platform_bills=platform_bills)
        s = report["summary"]
        check("reconcile: summary keys", set(s.keys()) == {
            "local_paid", "platform_rows", "matched",
            "local_only", "platform_only", "amount_mismatch"
        }, f"summary={s}")
        check("reconcile: matched == 1 (o2)", s["matched"] == 1, f"s={s}")
        check("reconcile: platform_only == 1",
              s["platform_only"] == 1, f"diffs={report['diffs']['platform_only']}")
        check("reconcile: amount_mismatch == 1",
              s["amount_mismatch"] == 1, f"diffs={report['diffs']['amount_mismatch']}")
        check("reconcile: local_only == 0",
              s["local_only"] == 0, f"diffs={report['diffs']['local_only']}")
        # 差异详情含关键字段
        am = report["diffs"]["amount_mismatch"][0]
        check("reconcile: amount_mismatch order_no == MANUAL_PAID_GHOST",
              am["order_no"] == "MANUAL_PAID_GHOST", f"am={am}")
        check("reconcile: amount_mismatch diff == 25.0",
              am["diff"] == 25.0, f"am={am}")

        # 空账单 → 所有本地都 local_only
        report2 = reconcile_day(db, start_date=today, end_date=today,
                                platform_bills=[])
        check("reconcile with empty bills → all local_only",
              report2["summary"]["local_only"] == report2["summary"]["local_paid"],
              f"s={report2['summary']}")

        # 非法日期 → ValueError
        try:
            reconcile_day(db, start_date="not-a-date", end_date=today)
            check("reconcile invalid date → ValueError", False)
        except ValueError:
            check("reconcile invalid date → ValueError", True)

        # ── 11. 订单超时关闭 ──────────────────────────
        from sqlalchemy import update as _upd
        now = datetime.now(timezone.utc)
        # 造 3 条 created 订单:一条 25h 前、一条 1h 前、一条 30h 前
        stale_ids = []
        for i, hours_ago in enumerate([25, 1, 30]):
            oid_no = f"STALE_CREATED_{i}"
            o = Order(user_id=o.user_id, order_no=oid_no,
                       amount=99.0, plan="pro", days=30,
                       status="created", channel="alipay",
                       created_at=now - timedelta(hours=hours_ago))
            db.add(o)
        db.commit()
        # 同时造一条 paid(超 25h),不能被关闭
        old_paid = Order(user_id=o.user_id, order_no="STALE_PAID",
                          amount=99.0, plan="pro", days=30,
                          status="paid", channel="alipay",
                          pay_trade_no="TX_OLDPAID",
                          created_at=now - timedelta(hours=25),
                          paid_at=now - timedelta(hours=24))
        db.add(old_paid)
        db.commit()

        closed_count = close_expired_orders(db, hours=24)
        check("close_expired_orders returned 2",
              closed_count == 2, f"count={closed_count}")

        # 验证状态
        rows = db.execute(_sel(Order).where(Order.order_no.like("STALE_%"))).scalars().all()
        status_map = {r.order_no: r.status for r in rows}
        check("STALE_CREATED_0 (25h) closed",
              status_map.get("STALE_CREATED_0") == "closed",
              f"status={status_map}")
        check("STALE_CREATED_1 (1h) stays created",
              status_map.get("STALE_CREATED_1") == "created",
              f"status={status_map}")
        check("STALE_CREATED_2 (30h) closed",
              status_map.get("STALE_CREATED_2") == "closed",
              f"status={status_map}")
        check("STALE_PAID not touched (paid)",
              status_map.get("STALE_PAID") == "paid",
              f"status={status_map}")

        # 幂等:再次运行应返回 0
        again = close_expired_orders(db, hours=24)
        check("close_expired_orders idempotent → 0", again == 0,
              f"again={again}")

        # 无效参数
        try:
            close_expired_orders(db, hours=0)
            check("close_expired_orders hours<=0 raises", False)
        except ValueError:
            check("close_expired_orders hours<=0 raises", True)

    # 收尾
    try:
        Path(_tmp.name).unlink(missing_ok=True)
    except OSError:
        pass
    return fails


if __name__ == "__main__":
    rc = run()
    print(f"\n{'ALL TESTS PASSED' if rc == 0 else f'{rc} TEST(S) FAILED'}")
    sys.exit(0 if rc == 0 else 1)
