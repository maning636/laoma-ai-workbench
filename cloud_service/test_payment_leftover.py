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

        # ── 12. close_expired_orders_task 生命周期(异步任务)──
        import asyncio as _aio
        from cloud_service.payment.scheduler import close_expired_orders_task

        # spy db_factory:每次被调用即记录一次,返回一个可用的 SessionLocal 会话
        calls = []
        def _spy_factory():
            calls.append(1)
            return SessionLocal()

        stop = _aio.Event()
        async def _run_close_task():
            await close_expired_orders_task(
                interval_seconds=0.05,
                hours=24,
                db_factory=_spy_factory,
                stop_event=stop,
            )

        async def _drive_close_task():
            task = _aio.create_task(_run_close_task())
            # 让任务跑约 2 个周期后 set stop_event
            await _aio.sleep(0.2)
            stop.set()
            await _aio.wait_for(task, timeout=1.0)

        _aio.run(_drive_close_task())
        check("close_expired_orders_task executed ≥2 times before stop",
              len(calls) >= 2, f"calls={len(calls)}")
        check("close_expired_orders_task returned cleanly (no exception)",
              True)  # 若上面 _drive_close_task 抛异常,check 就不会被调用

        # 负参回归: interval_seconds<=0 抛 ValueError
        async def _bad_interval():
            await close_expired_orders_task(interval_seconds=0, stop_event=_aio.Event())
        try:
            _aio.run(_bad_interval())
            check("close_expired_orders_task interval<=0 raises", False)
        except ValueError:
            check("close_expired_orders_task interval<=0 raises", True)

                # ── 13. 对账调度 reconcile_task:开关语义 + adapter 计数 ──
        from cloud_service.payment.reconciliation import reconcile_task
        from cloud_service.payment import alipay as _alipay_mod
        from cloud_service.payment import wechat as _wechat_mod

        # reconcile_day 遍历 SUPPORTED_CHANNELS(alipay / wechat),所以我们需要
        # monkey-patch 现有 adapter 实例的 fetch_bill,而不是新增注册。
        fetch_bill_calls = 0

        def _counting_fetch_bill(self, *, start_date, end_date):
            nonlocal fetch_bill_calls
            fetch_bill_calls += 1
            return []

        _orig_alipay_fetch = _alipay_mod.AlipayAdapter.fetch_bill
        _orig_wechat_fetch = _wechat_mod.WechatAdapter.fetch_bill
        _alipay_mod.AlipayAdapter.fetch_bill = _counting_fetch_bill
        _wechat_mod.WechatAdapter.fetch_bill = _counting_fetch_bill

        try:
            # 13a. stop_event 已 set → 立即退出,fetch_bill 0 次
            fetch_bill_calls = 0
            stop_immediate = _aio.Event()
            stop_immediate.set()
            _aio.run(reconcile_task(
                interval_seconds=0.05,
                lookback_hours=24,
                stop_event=stop_immediate,
            ))
            check("reconcile_task stop_event preset → 0 fetch_bill calls",
                  fetch_bill_calls == 0,
                  f"calls={fetch_bill_calls}")

            # 13b. 正常跑一次(等价于"开关打开"路径): fetch_bill ≥ 1
            # 注意:C-E 起 daily_limit 默认 10,若跑多轮可能触发限流;这里显式
            # daily_limit=0 关闭限流,只测"任务确实在跑"这一件事。
            fetch_bill_calls = 0
            stop2 = _aio.Event()
            async def _run_reconcile():
                await reconcile_task(
                    interval_seconds=0.05,
                    lookback_hours=24,
                    stop_event=stop2,
                    daily_limit=0,
                )
            async def _drive_reconcile():
                task = _aio.create_task(_run_reconcile())
                await _aio.sleep(0.15)
                stop2.set()
                await _aio.wait_for(task, timeout=2.0)
            _aio.run(_drive_reconcile())
            check("reconcile_task running → fetch_bill ≥ 1 call",
                  fetch_bill_calls >= 1,
                  f"calls={fetch_bill_calls}")

            # 13c. 负参:lookback_hours<=0 抛 ValueError
            try:
                _aio.run(reconcile_task(lookback_hours=0, stop_event=_aio.Event()))
                check("reconcile_task lookback_hours<=0 raises", False)
            except ValueError:
                check("reconcile_task lookback_hours<=0 raises", True)
        finally:
            _alipay_mod.AlipayAdapter.fetch_bill = _orig_alipay_fetch
            _wechat_mod.WechatAdapter.fetch_bill = _orig_wechat_fetch

    # ── 14. lifespan 挂载:默认关闭对账 + 显式打开时任务被启动 ──
    from cloud_service.settings import reset_settings_cache
    import cloud_service.main as _cloud_main_mod
    import importlib
    import asyncio as _aio
    from cloud_service.payment import alipay as _alipay_mod
    from cloud_service.payment import wechat as _wechat_mod

    # 14a. 默认(未设置 env):reconcile.enabled = False → lifespan 不启动对账
    os.environ.pop("CLOUD_RECONCILE_ENABLED", None)
    os.environ.pop("CLOUD_ORDER_TIMEOUT_ENABLED", None)
    reset_settings_cache()
    importlib.reload(_cloud_main_mod)

    settings_default = _cloud_main_mod.get_settings()
    check("settings.reconcile.enabled default is False",
          settings_default["reconcile"]["enabled"] is False,
          f"cfg={settings_default['reconcile']}")
    check("settings.order_timeout.enabled default is True",
          settings_default["order_timeout"]["enabled"] is True,
          f"cfg={settings_default['order_timeout']}")

    fetch_bill_calls2 = 0
    def _counting_fetch_bill2(self, *, start_date, end_date):
        nonlocal fetch_bill_calls2
        fetch_bill_calls2 += 1
        return []
    _orig_a = _alipay_mod.AlipayAdapter.fetch_bill
    _orig_w = _wechat_mod.WechatAdapter.fetch_bill
    _alipay_mod.AlipayAdapter.fetch_bill = _counting_fetch_bill2
    _wechat_mod.WechatAdapter.fetch_bill = _counting_fetch_bill2
    try:
        with TestClient(_cloud_main_mod.app) as _c_default:
            r = _c_default.get("/health")
            check("lifespan default: /health 200",
                  r.status_code == 200, f"status={r.status_code}")
            import time as _time
            _time.sleep(0.15)
            _c_default.get("/health")
        check("lifespan default: reconcile NOT started (fetch_bill == 0)",
              fetch_bill_calls2 == 0,
              f"calls={fetch_bill_calls2}")
    finally:
        _alipay_mod.AlipayAdapter.fetch_bill = _orig_a
        _wechat_mod.WechatAdapter.fetch_bill = _orig_w

    # 14b. 显式打开 reconcile → lifespan 启动 task,fetch_bill 被调用
    os.environ["CLOUD_RECONCILE_ENABLED"] = "true"
    os.environ["CLOUD_RECONCILE_INTERVAL_SECONDS"] = "0.05"
    # C-E: 老测试只关心"任务被启动",不测限流;显式关闭 daily_limit 避免累积污染
    os.environ["CLOUD_RECONCILE_DAILY_LIMIT"] = "0"
    reset_settings_cache()
    importlib.reload(_cloud_main_mod)
    check("settings.reconcile.enabled after env=true is True",
          _cloud_main_mod.get_settings()["reconcile"]["enabled"] is True,
          f"cfg={_cloud_main_mod.get_settings()['reconcile']}")

    fetch_bill_calls3 = 0
    def _counting_fetch_bill3(self, *, start_date, end_date):
        nonlocal fetch_bill_calls3
        fetch_bill_calls3 += 1
        return []
    _orig_a2 = _alipay_mod.AlipayAdapter.fetch_bill
    _orig_w2 = _wechat_mod.WechatAdapter.fetch_bill
    _alipay_mod.AlipayAdapter.fetch_bill = _counting_fetch_bill3
    _wechat_mod.WechatAdapter.fetch_bill = _counting_fetch_bill3
    try:
        with TestClient(_cloud_main_mod.app) as _c_enabled:
            _c_enabled.get("/health")
            import time as _time
            _time.sleep(0.2)
            _c_enabled.get("/health")
        check("lifespan with CLOUD_RECONCILE_ENABLED=true: fetch_bill ≥ 1",
              fetch_bill_calls3 >= 1,
              f"calls={fetch_bill_calls3}")
    finally:
        _alipay_mod.AlipayAdapter.fetch_bill = _orig_a2
        _wechat_mod.WechatAdapter.fetch_bill = _orig_w2
        os.environ.pop("CLOUD_RECONCILE_ENABLED", None)
        os.environ.pop("CLOUD_RECONCILE_INTERVAL_SECONDS", None)
        os.environ.pop("CLOUD_RECONCILE_DAILY_LIMIT", None)
        reset_settings_cache()
        importlib.reload(_cloud_main_mod)

        # __CD_CE_SENTINEL__
        # ── 15. C-D: 分布式锁 —— 抢到 / 抢不到 / Redis 不可达降级 ──────
        from cloud_service.payment.task_guard import (
            acquire_task_lock,
            release_task_lock,
            task_lock,
            check_daily_limit,
            daily_key,
            reset_redis_client,
            reset_daily_limit,
        )

        class FakeRedis:
            """最小 redis 桩:支持 SET NX PX / EVAL (Lua 释放) / INCR / EXPIRE / DEL / PING。"""

            def __init__(self):
                self.store: dict = {}

            def ping(self) -> bool:
                return True

            def set(self, key, value, nx=False, px=None):
                if nx and key in self.store:
                    return None
                self.store[key] = value
                return True

            def get(self, key):
                return self.store.get(key)

            def delete(self, key):
                if key in self.store:
                    del self.store[key]
                    return 1
                return 0

            def incr(self, key):
                self.store[key] = int(self.store.get(key, 0)) + 1
                return self.store[key]

            def decr(self, key):
                self.store[key] = int(self.store.get(key, 0)) - 1
                return self.store[key]

            def expire(self, key, seconds):
                return key in self.store

            def eval(self, script, numkeys, *keys_and_args):
                key = keys_and_args[0]
                arg = keys_and_args[1]
                if self.store.get(key) == arg:
                    del self.store[key]
                    return 1
                return 0

        # 15a. acquire → OK,release 匹配 owner
        fake = FakeRedis()
        owner1 = acquire_task_lock(
            key="cloud:lock:test", owner="w1", ttl_ms=60000, redis_client=fake,
        )
        check("C-D: acquire_task_lock returns owner when free",
              owner1 == "w1", f"owner1={owner1}")

        # 15b. 再次抢 → None
        owner2 = acquire_task_lock(
            key="cloud:lock:test", owner="w2", ttl_ms=60000, redis_client=fake,
        )
        check("C-D: acquire_task_lock returns None when held",
              owner2 is None, f"owner2={owner2}")

        # 15c. 释放 owner 不匹配 → 不删除
        released_mismatch = release_task_lock(
            key="cloud:lock:test", owner="WRONG", redis_client=fake,
        )
        check("C-D: release_task_lock with wrong owner → False",
              released_mismatch is False, f"ret={released_mismatch}")
        check("C-D: lock still held after mismatch release",
              "cloud:lock:test" in fake.store)

        # 15d. 释放 owner 匹配 → True 且删除
        released_ok = release_task_lock(
            key="cloud:lock:test", owner="w1", redis_client=fake,
        )
        check("C-D: release_task_lock with matching owner → True",
              released_ok is True, f"ret={released_ok}")
        check("C-D: lock deleted after matching release",
              "cloud:lock:test" not in fake.store)

        # 15e. task_lock context: Redis 不可达 → yield "unlocked"
        _saved_env = os.environ.get("CLOUD_REDIS_URL")
        os.environ["CLOUD_REDIS_URL"] = "redis://127.0.0.1:1/0"
        reset_redis_client()
        async def _drive_task_lock_unlocked():
            async with task_lock(
                key="cloud:lock:probe", ttl_seconds=60,
                redis_client=None, log_label="probe",
            ) as mode:
                return mode
        try:
            mode = _aio.run(_drive_task_lock_unlocked())
            check("C-D: task_lock yields 'unlocked' when redis unreachable",
                  mode == "unlocked", f"mode={mode}")
        finally:
            if _saved_env is not None:
                os.environ["CLOUD_REDIS_URL"] = _saved_env
            else:
                os.environ.pop("CLOUD_REDIS_URL", None)
            reset_redis_client()

        # 15f. task_lock context: 抢到锁 → "locked",退出时释放
        fake2 = FakeRedis()
        async def _drive_task_lock_locked():
            async with task_lock(
                key="cloud:lock:lockable", ttl_seconds=60,
                redis_client=fake2, log_label="probe",
            ) as mode:
                inside_key = "cloud:lock:lockable" in fake2.store
                return mode, inside_key
        result = _aio.run(_drive_task_lock_locked())
        check("C-D: task_lock yields 'locked' when redis up",
              result[0] == "locked", f"mode={result[0]}")
        check("C-D: task_lock held the key inside the context",
              result[1] is True, f"inside={result[1]}")
        check("C-D: task_lock released the key on exit",
              "cloud:lock:lockable" not in fake2.store)

        # 15g. task_lock context: 已持有 → "skipped"
        fake3 = FakeRedis()
        fake3.set("cloud:lock:busy", "other-w", nx=False)
        async def _drive_task_lock_skipped():
            async with task_lock(
                key="cloud:lock:busy", ttl_seconds=60,
                redis_client=fake3, log_label="probe",
            ) as mode:
                return mode
        mode = _aio.run(_drive_task_lock_skipped())
        check("C-D: task_lock yields 'skipped' when held by another",
              mode == "skipped", f"mode={mode}")
        check("C-D: 'skipped' does not delete the other's lock",
              fake3.store.get("cloud:lock:busy") == "other-w")

        # ── 16. C-E: fetch_all_bills_with_timeout 单 adapter 超时 ──
        import time as _time
        from cloud_service.payment.reconciliation import (
            fetch_all_bills_with_timeout,
            _compute_backoff,
            reconcile_task as _recon_task,
        )

        _orig_a3 = _alipay_mod.AlipayAdapter.fetch_bill
        _orig_w3 = _wechat_mod.WechatAdapter.fetch_bill

        def _sleep_alipay(self, *, start_date, end_date):
            _time.sleep(0.3)  # 阻塞线程,超过 timeout
            return []

        def _fast_wechat(self, *, start_date, end_date):
            return [
                {"out_trade_no": "FAST_W", "pay_trade_no": "TX_W",
                 "amount": 1.0, "channel": "wechat",
                 "trade_time": start_date, "trade_type": "payment"},
            ]

        _alipay_mod.AlipayAdapter.fetch_bill = _sleep_alipay
        _wechat_mod.WechatAdapter.fetch_bill = _fast_wechat

        try:
            async def _measure_fetch():
                t_start = _time.monotonic()
                rows = await fetch_all_bills_with_timeout(
                    start_date="2026-10-16",
                    end_date="2026-10-16",
                    timeout_seconds=0.05,
                )
                t_elapsed = _time.monotonic() - t_start
                return rows, t_elapsed
            rows, elapsed = _aio.run(_measure_fetch())
            errors = [r for r in rows if isinstance(r, dict) and r.get("_error")]
            norms = [r for r in rows if isinstance(r, dict) and not r.get("_error")]
            check("C-E: fetch_all_bills_with_timeout times out on slow adapter",
                  len(errors) == 1 and "timed out" in errors[0]["_error"],
                  f"errors={errors}")
            check("C-E: fetch_all_bills_with_timeout still returns fast adapter rows",
                  len(norms) == 1 and norms[0]["out_trade_no"] == "FAST_W",
                  f"norms={norms}")
            # 关键:业务层不阻塞 —— wait_for 应在 ~timeout 秒内返回,而不是等
            # to_thread 的线程 sleep 0.3s 完成。executor shutdown 发生在
            # _aio.run() 结束时,所以测"从 await 进入到返回"的耗时。
            check("C-E: wait_for actually cut off slow adapter (< 0.15s elapsed)",
                  elapsed < 0.15, f"elapsed={elapsed:.3f}s")
        finally:
            _alipay_mod.AlipayAdapter.fetch_bill = _orig_a3
            _wechat_mod.WechatAdapter.fetch_bill = _orig_w3

        # ── 17. C-E: 退避公式 & 每日限次 ──
        check("C-E: backoff attempt=1 = base",
              _compute_backoff(1, base=300.0, cap=3600.0) == 300.0)
        check("C-E: backoff attempt=2 = 2*base",
              _compute_backoff(2, base=300.0, cap=3600.0) == 600.0)
        check("C-E: backoff attempt=3 = 4*base",
              _compute_backoff(3, base=300.0, cap=3600.0) == 1200.0)
        check("C-E: backoff capped at cap",
              _compute_backoff(20, base=300.0, cap=3600.0) == 3600.0)
        check("C-E: backoff attempt<=0 returns base",
              _compute_backoff(0, base=300.0, cap=3600.0) == 300.0)

        # 17b. 每日限次:达到上限后拒绝
        fake4 = FakeRedis()
        reset_daily_limit(key="cloud:payment:reconcile", redis_client=fake4)
        used_history = []
        allowed_history = []
        for _i in range(5):
            allowed, used = check_daily_limit(
                key="cloud:payment:reconcile",
                limit=3,
                redis_client=fake4,
                day_utc="2026-10-16",
            )
            allowed_history.append(allowed)
            used_history.append(used)
        check("C-E: daily_limit allows first 3 calls",
              allowed_history[:3] == [True, True, True],
              f"allowed={allowed_history}")
        check("C-E: daily_limit denies calls 4 and 5",
              allowed_history[3:] == [False, False],
              f"allowed={allowed_history}")
        check("C-E: daily_limit used counter stable at 3 after denial",
              used_history[3] == 3 and used_history[4] == 3,
              f"used={used_history}")

        # 17c. daily_limit=0 关闭限流
        check("C-E: daily_limit=0 always allows",
              check_daily_limit(
                  key="cloud:payment:reconcile", limit=0,
                  redis_client=fake4, day_utc="2026-10-16",
              )[0] is True)

        # 17d. Redis 不可达 → fail-open
        _saved_env2 = os.environ.get("CLOUD_REDIS_URL")
        os.environ["CLOUD_REDIS_URL"] = "redis://127.0.0.1:1/0"
        reset_redis_client()
        try:
            allowed = check_daily_limit(
                key="cloud:payment:reconcile", limit=1,
                redis_client=None, day_utc="2026-10-16",
            )[0]
            check("C-E: daily_limit fail-open when redis unreachable",
                  allowed is True, f"allowed={allowed}")
        finally:
            if _saved_env2 is not None:
                os.environ["CLOUD_REDIS_URL"] = _saved_env2
            else:
                os.environ.pop("CLOUD_REDIS_URL", None)
            reset_redis_client()

        # 17e. daily_key 按 UTC 日切
        dk = daily_key("cloud:payment:reconcile", day_utc="2026-10-16")
        check("C-E: daily_key contains date suffix",
              dk == "cloud:payment:reconcile:daily:2026-10-16",
              f"dk={dk}")

        # ── 18. C-E 集成:reconcile_task 每日限次生效 ──
        fake5 = FakeRedis()
        reset_daily_limit(key="cloud:payment:reconcile:test18", redis_client=fake5)
        _orig_a4 = _alipay_mod.AlipayAdapter.fetch_bill
        _orig_w4 = _wechat_mod.WechatAdapter.fetch_bill
        _calls_18 = 0
        def _counting_18(self, *, start_date, end_date):
            nonlocal _calls_18
            _calls_18 += 1
            return []
        _alipay_mod.AlipayAdapter.fetch_bill = _counting_18
        _wechat_mod.WechatAdapter.fetch_bill = _counting_18

        stop18 = _aio.Event()
        async def _run_18():
            await _recon_task(
                interval_seconds=0.05,
                lookback_hours=24,
                stop_event=stop18,
                lock_enabled=True,
                lock_key="cloud:lock:test18",
                lock_ttl_seconds=60,
                redis_client=fake5,
                fetch_timeout_seconds=0.1,
                backoff_base_seconds=0.05,
                backoff_max_seconds=0.1,
                daily_limit=1,
                daily_limit_base_key="cloud:payment:reconcile:test18",
            )
        async def _drive_18():
            t = _aio.create_task(_run_18())
            await _aio.sleep(0.25)
            stop18.set()
            await _aio.wait_for(t, timeout=2.0)
        try:
            _aio.run(_drive_18())
            # 单次对账 = alipay + wechat 两个 channel 各 fetch_bill 一次;
            # daily_limit=1 时只允许第一轮的 2 次,后续轮次应全部拒绝。
            check("C-E: reconcile_task respects daily_limit (2 fetch_bill calls = 1 round)",
                  _calls_18 == 2, f"calls={_calls_18}")
        finally:
            _alipay_mod.AlipayAdapter.fetch_bill = _orig_a4
            _wechat_mod.WechatAdapter.fetch_bill = _orig_w4

        # ── 19. C-D 集成:抢不到锁 → 完全跳过 ──
        fake6 = FakeRedis()
        fake6.set("cloud:lock:test19", "other-worker", nx=False)
        _calls_19 = 0
        def _counting_19(self, *, start_date, end_date):
            nonlocal _calls_19
            _calls_19 += 1
            return []
        _orig_a5 = _alipay_mod.AlipayAdapter.fetch_bill
        _orig_w5 = _wechat_mod.WechatAdapter.fetch_bill
        _alipay_mod.AlipayAdapter.fetch_bill = _counting_19
        _wechat_mod.WechatAdapter.fetch_bill = _counting_19

        stop19 = _aio.Event()
        async def _run_19():
            await _recon_task(
                interval_seconds=0.05,
                lookback_hours=24,
                stop_event=stop19,
                lock_enabled=True,
                lock_key="cloud:lock:test19",
                lock_ttl_seconds=60,
                redis_client=fake6,
                fetch_timeout_seconds=0.1,
                backoff_base_seconds=0.05,
                backoff_max_seconds=0.1,
                daily_limit=0,
                daily_limit_base_key="cloud:payment:reconcile:test19",
            )
        async def _drive_19():
            t = _aio.create_task(_run_19())
            await _aio.sleep(0.2)
            stop19.set()
            await _aio.wait_for(t, timeout=2.0)
        try:
            _aio.run(_drive_19())
            check("C-D: reconcile_task skips when lock held by another worker",
                  _calls_19 == 0, f"calls={_calls_19}")
        finally:
            _alipay_mod.AlipayAdapter.fetch_bill = _orig_a5
            _wechat_mod.WechatAdapter.fetch_bill = _orig_w5

        # ── 20. C-D 集成:close_expired_orders_task 抢不到锁 → 跳过 ──
        fake7 = FakeRedis()
        fake7.set("cloud:lock:test20", "other-worker", nx=False)
        close_calls = []
        def _spy_factory_20():
            close_calls.append(1)
            return SessionLocal()
        stop20 = _aio.Event()
        async def _run_20():
            await close_expired_orders_task(
                interval_seconds=0.05,
                hours=24,
                db_factory=_spy_factory_20,
                stop_event=stop20,
                lock_enabled=True,
                lock_key="cloud:lock:test20",
                lock_ttl_seconds=60,
                redis_client=fake7,
            )
        async def _drive_20():
            t = _aio.create_task(_run_20())
            await _aio.sleep(0.2)
            stop20.set()
            await _aio.wait_for(t, timeout=2.0)
        _aio.run(_drive_20())
        check("C-D: close_expired_orders_task skips when lock busy",
              len(close_calls) == 0, f"calls={len(close_calls)}")

        # 20b. close_expired_orders_task 抢到锁 → 正常执行
        fake8 = FakeRedis()
        close_calls2 = []
        def _spy_factory_20b():
            close_calls2.append(1)
            return SessionLocal()
        stop20b = _aio.Event()
        async def _run_20b():
            await close_expired_orders_task(
                interval_seconds=0.05,
                hours=24,
                db_factory=_spy_factory_20b,
                stop_event=stop20b,
                lock_enabled=True,
                lock_key="cloud:lock:test20b",
                lock_ttl_seconds=60,
                redis_client=fake8,
            )
        async def _drive_20b():
            t = _aio.create_task(_run_20b())
            await _aio.sleep(0.15)
            stop20b.set()
            await _aio.wait_for(t, timeout=2.0)
        _aio.run(_drive_20b())
        check("C-D: close_expired_orders_task runs when lock free (>=1 call)",
              len(close_calls2) >= 1, f"calls={len(close_calls2)}")

        # 20c. close_expired_orders_task Redis 不可达 → 降级继续执行
        _saved_env3 = os.environ.get("CLOUD_REDIS_URL")
        os.environ["CLOUD_REDIS_URL"] = "redis://127.0.0.1:1/0"
        reset_redis_client()
        close_calls3 = []
        def _spy_factory_20c():
            close_calls3.append(1)
            return SessionLocal()
        stop20c = _aio.Event()
        async def _run_20c():
            await close_expired_orders_task(
                interval_seconds=0.05,
                hours=24,
                db_factory=_spy_factory_20c,
                stop_event=stop20c,
                lock_enabled=True,
                lock_key="cloud:lock:test20c",
                lock_ttl_seconds=60,
                redis_client=None,
            )
        async def _drive_20c():
            t = _aio.create_task(_run_20c())
            await _aio.sleep(0.2)
            stop20c.set()
            await _aio.wait_for(t, timeout=2.0)
        try:
            _aio.run(_drive_20c())
            check("C-D: close_expired_orders_task falls back when redis unreachable",
                  len(close_calls3) >= 1, f"calls={len(close_calls3)}")
        finally:
            if _saved_env3 is not None:
                os.environ["CLOUD_REDIS_URL"] = _saved_env3
            else:
                os.environ.pop("CLOUD_REDIS_URL", None)
            reset_redis_client()

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
