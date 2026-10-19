"""M3 · 积分制 TestClient 集成测试(不启动服务器,不落仓库文件)。

覆盖:
  1. 充值流程:create_order → mock callback → 积分到账(含赠送)
  2. 冻结/实扣/回滚:AI 生成场景三步
  3. 赠送规则计算:1000 档无赠送, 3000 档赠 1000, 5000 档赠 2000
  4. 乐观锁/并发:余额不足 402 + 冻结终态幂等
  5. 历史查询 + 价目表 seed

用法:
  python cloud_service/test_points.py
  # 或:python -m pytest cloud_service -q  (conftest 会把它当作单用例)
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ── 用临时 SQLite 文件,避免污染仓库 ────────────────────────────
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["CLOUD_DB_URL"] = f"sqlite:///{_tmp.name}"
os.environ.pop("CLOUD_ACCESS_TOKEN_EXPIRE_MINUTES", None)

# 便于测试:free quota 较小
os.environ["CLOUD_FREE_QUOTA"] = "5"
os.environ["CLOUD_PRO_QUOTA"] = "-1"

# 积分制配置(澜途对齐)
os.environ["CLOUD_POINTS_PER_YUAN"] = "10"
os.environ["CLOUD_POINTS_BONUS_THRESHOLD"] = "1000"
os.environ["CLOUD_POINTS_BONUS_RATE"] = "0.5"

# 支付回调 URL(mock 签名 payload 对齐)
os.environ["CLOUD_PAYMENT_NOTIFY_URL"] = "/cloud/payment/callback/alipay"
os.environ["CLOUD_PAYMENT_RETURN_URL"] = "/payment/success"
os.environ["CLOUD_ADMIN_TOKEN"] = "test-admin-token"

# 确保能导入仓库根
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def _mk_alipay_callback(order_no: str, trade_no: str, amount: float,
                        plan: str = "pro", days: int = 30) -> dict:
    """构造一份合法的支付宝回调 body(带 mock 签名)。"""
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
    """跑完整端到端,返回 0 = 全部通过,> 0 = 失败计数。"""
    from fastapi.testclient import TestClient
    from cloud_service.main import app
    from cloud_service.settings import reset_settings_cache
    reset_settings_cache()

    fails = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal fails
        tag = "PASS" if cond else "FAIL"
        print(f"[{tag}] {label}" + (f" — {extra}" if extra else ""))
        if not cond:
            fails += 1

    with TestClient(app) as client:
        # ── 1. 注册 + 登录 ─────────────────────────────
        r = client.post("/cloud/auth/register", json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "supers3cret",
        })
        check("POST /cloud/auth/register alice", r.status_code == 201,
              f"status={r.status_code}")
        r = client.post("/cloud/auth/login", json={
            "username": "alice", "password": "supers3cret",
        })
        check("POST /cloud/auth/login alice", r.status_code == 200,
              f"status={r.status_code}")
        access = r.json().get("access_token", "")
        H = {"Authorization": f"Bearer {access}"}

        # ── 2. 初始积分账户:0/0/0/0 ────────────────────
        r = client.get("/cloud/points/account", headers=H)
        check("GET /cloud/points/account initial", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        acct = r.json()
        check("initial availablePoints == 0",
              acct.get("availablePoints") == 0,
              f"body={acct}")
        check("initial frozenPoints == 0",
              acct.get("frozenPoints") == 0,
              f"body={acct}")
        check("initial totalConsumed == 0",
              acct.get("totalConsumed") == 0,
              f"body={acct}")

        # ── 3. 充值选项:5 档预设 + 赠送规则 ────────────
        r = client.get("/cloud/points/recharge/options", headers=H)
        check("GET /cloud/points/recharge/options", r.status_code == 200,
              f"status={r.status_code}")
        opts = r.json()
        check("options.pointsPerYuan == 10", opts.get("pointsPerYuan") == 10,
              f"opts={opts}")
        check("options.bonusThreshold == 1000",
              opts.get("bonusThreshold") == 1000, f"opts={opts}")
        check("options.bonusRate == 0.5",
              opts.get("bonusRate") == 0.5, f"opts={opts}")
        check("options.presets has 5 items",
              len(opts.get("presets", [])) == 5,
              f"presets={opts.get('presets')}")
        # 验证赠送规则
        preset_map = {p["points"]: p["bonusPoints"] for p in opts["presets"]}
        check("preset 100 → bonus 0",
              preset_map.get(100.0) == 0,
              f"got={preset_map.get(100.0)}")
        check("preset 500 → bonus 0",
              preset_map.get(500.0) == 0,
              f"got={preset_map.get(500.0)}")
        check("preset 1000 → bonus 0 (at threshold)",
              preset_map.get(1000.0) == 0,
              f"got={preset_map.get(1000.0)}")
        check("preset 3000 → bonus 1000 (澜途规则)",
              preset_map.get(3000.0) == 1000,
              f"got={preset_map.get(3000.0)}")
        check("preset 5000 → bonus 2000 (澜途规则)",
              preset_map.get(5000.0) == 2000,
              f"got={preset_map.get(5000.0)}")

        # ── 4. 创建 3000 积分充值订单(¥300,应赠 1000) ─
        r = client.post("/cloud/points/recharge", headers=H, json={
            "points": 3000,
            "channel": "alipay",
        })
        check("POST /cloud/points/recharge 3000", r.status_code == 201,
              f"status={r.status_code} body={r.text[:300]}")
        order = r.json()
        check("order.amount == 300", order.get("amount") == 300,
              f"got={order.get('amount')}")
        check("order.points == 3000", order.get("points") == 3000,
              f"got={order.get('points')}")
        check("order.bonusPoints == 1000", order.get("bonusPoints") == 1000,
              f"got={order.get('bonusPoints')}")
        check("order.totalPoints == 4000", order.get("totalPoints") == 4000,
              f"got={order.get('totalPoints')}")
        order_no = order["orderNo"]

        # 此时积分账户**还没变化**(等回调)
        r = client.get("/cloud/points/account", headers=H)
        check("account unchanged before callback",
              r.json().get("availablePoints") == 0,
              f"body={r.json()}")

        # ── 5. Mock 支付宝回调 → 积分到账 ──────────────
        r = client.post(
            "/cloud/payment/callback/alipay",
            json=_mk_alipay_callback(
                order_no, trade_no="MOCK_TRADE_001",
                amount=300.0, plan="credit", days=0,
            ),
        )
        check("POST /cloud/payment/callback/alipay", r.status_code == 200,
              f"status={r.status_code} body={r.text[:300]}")
        cb = r.json()
        check("callback.ok == True", cb.get("ok") is True, f"cb={cb}")
        check("callback.activated == True",
              cb.get("activated") is True, f"cb={cb}")

        r = client.get("/cloud/points/account", headers=H)
        acct = r.json()
        check("after callback availablePoints == 4000",
              acct.get("availablePoints") == 4000,
              f"body={acct}")
        check("after callback totalRecharged == 4000",
              acct.get("totalRecharged") == 4000,
              f"body={acct}")

        # ── 6. 幂等:重复回调不重复入账 ─────────────────
        r = client.post(
            "/cloud/payment/callback/alipay",
            json=_mk_alipay_callback(
                order_no, trade_no="MOCK_TRADE_001",
                amount=300.0, plan="credit", days=0,
            ),
        )
        check("idempotent callback status==200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        r = client.get("/cloud/points/account", headers=H)
        check("after duplicate callback still 4000",
              r.json().get("availablePoints") == 4000,
              f"body={r.json()}")

        # ── 7. 冻结 → 实扣:AI 生图场景 ─────────────────
        r = client.post("/cloud/points/freeze", headers=H, json={
            "amount": 1.5,
            "use_function": "ai_design",
            "ref_id": "gen-001",
            "pricing_key": "aiImageGeneration",
        })
        check("POST /cloud/points/freeze 1.5", r.status_code == 200,
              f"status={r.status_code} body={r.text[:300]}")
        fr = r.json()
        freeze_tx_id = fr.get("freezeTxId")
        check("freeze.freezeTxId is int",
              isinstance(freeze_tx_id, int), f"fr={fr}")
        check("freeze.status == active", fr.get("status") == "active",
              f"fr={fr}")
        check("freeze.availablePoints == 3998.5",
              abs(fr.get("availablePoints", 0) - 3998.5) < 0.001,
              f"fr={fr}")
        check("freeze.frozenPoints == 1.5",
              abs(fr.get("frozenPoints", 0) - 1.5) < 0.001,
              f"fr={fr}")

        # 实扣
        r = client.post("/cloud/points/consume", headers=H, json={
            "freeze_tx_id": freeze_tx_id,
        })
        check("POST /cloud/points/consume", r.status_code == 200,
              f"status={r.status_code} body={r.text[:300]}")
        cs = r.json()
        check("consume.status == consumed", cs.get("status") == "consumed",
              f"cs={cs}")
        check("consume.totalConsumed == 1.5",
              abs(cs.get("totalConsumed", 0) - 1.5) < 0.001,
              f"cs={cs}")
        check("consume.availablePoints == 3998.5",
              abs(cs.get("availablePoints", 0) - 3998.5) < 0.001,
              f"cs={cs}")
        check("consume.frozenPoints == 0",
              cs.get("frozenPoints", 1) == 0,
              f"cs={cs}")

        # ── 8. 冻结 → 回滚:生成失败 ────────────────────
        r = client.post("/cloud/points/freeze", headers=H, json={
            "amount": 10,
            "use_function": "ai_design",
            "ref_id": "gen-002",
        })
        fr2 = r.json()
        freeze_tx_id_2 = fr2["freezeTxId"]
        r = client.post("/cloud/points/rollback", headers=H, json={
            "freeze_tx_id": freeze_tx_id_2,
        })
        check("POST /cloud/points/rollback", r.status_code == 200,
              f"status={r.status_code} body={r.text[:300]}")
        rb = r.json()
        check("rollback.status == rolled_back",
              rb.get("status") == "rolled_back", f"rb={rb}")
        check("rollback.availablePoints == 3998.5 (原值)",
              abs(rb.get("availablePoints", 0) - 3998.5) < 0.001,
              f"rb={rb}")

        # ── 9. 终态幂等:重复 consume 应 409 ───────────
        r = client.post("/cloud/points/consume", headers=H, json={
            "freeze_tx_id": freeze_tx_id,  # 已 consume 过的
        })
        check("duplicate consume returns 409",
              r.status_code == 409,
              f"status={r.status_code} body={r.text[:200]}")
        r = client.post("/cloud/points/rollback", headers=H, json={
            "freeze_tx_id": freeze_tx_id_2,  # 已 rollback 过的
        })
        check("duplicate rollback returns 409",
              r.status_code == 409,
              f"status={r.status_code} body={r.text[:200]}")

        # ── 10. 余额不足:冻结 402 ─────────────────────
        r = client.post("/cloud/points/freeze", headers=H, json={
            "amount": 100000,
            "use_function": "ai_design",
        })
        check("insufficient freeze returns 402",
              r.status_code == 402,
              f"status={r.status_code} body={r.text[:200]}")

        # ── 11. 历史查询:分页 + 过滤 ──────────────────
        r = client.get("/cloud/points/history?size=100", headers=H)
        check("GET /cloud/points/history", r.status_code == 200,
              f"status={r.status_code}")
        hist = r.json()
        check("history.total >= 5",
              hist.get("total", 0) >= 5,
              f"total={hist.get('total')}")
        check("history.items has txType field",
              all("txType" in it for it in hist.get("items", [])),
              f"sample={hist.get('items', [])[:1]}")
        # 过滤 tx_type=RECHARGE
        r = client.get("/cloud/points/history?tx_type=RECHARGE", headers=H)
        hist_r = r.json()
        check("history tx_type=RECHARGE all items match",
              all(it["txType"] == "RECHARGE" for it in hist_r.get("items", [])),
              f"items={[it['txType'] for it in hist_r.get('items', [])]}")
        # 过滤 use_function=ai_design
        r = client.get("/cloud/points/history?use_function=ai_design", headers=H)
        hist_a = r.json()
        check("history use_function=ai_design all items match",
              all(it["useFunction"] == "ai_design"
                  for it in hist_a.get("items", [])),
              f"items={[it['useFunction'] for it in hist_a.get('items', [])]}")

        # ── 12. 价目表:seed 生效 ──────────────────────
        r = client.get("/cloud/points/pricing", headers=H)
        check("GET /cloud/points/pricing", r.status_code == 200,
              f"status={r.status_code}")
        pr = r.json()
        check("pricing.pricingVersion is set",
              bool(pr.get("pricingVersion")), f"pr={pr}")
        items_map = {it["pricingKey"]: it for it in pr.get("items", [])}
        check("pricing has aiImageGeneration",
              "aiImageGeneration" in items_map,
              f"keys={list(items_map.keys())}")
        check("pricing.aiImageGeneration.points == 1.5",
              abs(items_map["aiImageGeneration"]["points"] - 1.5) < 0.001,
              f"got={items_map['aiImageGeneration']['points']}")
        check("pricing.aiTitle.points == 0.1",
              abs(items_map["aiTitle"]["points"] - 0.1) < 0.001,
              f"got={items_map['aiTitle']['points']}")

        # ── 13. consume_by_pricing 一步扣积分 ──────────
        r = client.post("/cloud/points/consume_by_pricing", headers=H, json={
            "pricing_key": "aiTitle",
            "ref_id": "title-001",
            "use_function": "ai_design",
        })
        check("POST /cloud/points/consume_by_pricing aiTitle",
              r.status_code == 200,
              f"status={r.status_code} body={r.text[:300]}")
        csp = r.json()
        check("consume_by_pricing amount == 0.1",
              abs(csp.get("amount", 0) - 0.1) < 0.001,
              f"got={csp.get('amount')}")
        check("consume_by_pricing status == consumed",
              csp.get("status") == "consumed",
              f"csp={csp}")

        # ── 14. 管理员退款 ────────────────────────────
        r = client.get("/cloud/auth/register", headers=H)  # dummy
        # 需要 user_id:重新拿当前用户
        r = client.get("/cloud/points/account", headers=H)
        my_uid = r.json()["primaryAccountId"]
        r = client.post("/cloud/points/refund", json={
            "user_id": my_uid,
            "amount": 100,
            "note": "test refund",
        }, headers={
            **H,
            "X-Admin-Token": "test-admin-token",
        })
        check("POST /cloud/points/refund (admin)", r.status_code == 200,
              f"status={r.status_code} body={r.text[:300]}")
        rd = r.json()
        check("refund.status == refunded",
              rd.get("status") == "refunded", f"rd={rd}")

        # 无效 admin token → 403
        r = client.post("/cloud/points/refund", json={
            "user_id": my_uid, "amount": 100,
        }, headers={**H, "X-Admin-Token": "wrong"})
        check("invalid admin token → 403", r.status_code == 403,
              f"status={r.status_code}")

        # ════════════════════════════════════════════════════
        # ── 15. M3 硬化专项:预设/plan schema/days/credit_points ──
        # 修复 M3 遗留 §9 中 4 个问题,新增断言不改动原有 51 项。
        # ════════════════════════════════════════════════════
        from cloud_service.payment.models import Order as _Order
        from cloud_service.payment.schemas import (
            CreateOrderRequest as _COR,
            CreateOrderResponse as _CORes,
        )

        # ── 问题1 · 预设数值对齐澜途(points/yuan/bonusPoints) ──
        # 前面 options 已经取到 opts,这里再取一次以便读 yuan 字段
        r = client.get("/cloud/points/recharge/options", headers=H)
        opts2 = r.json()
        preset_full = {
            p["points"]: {"yuan": p["yuan"], "bonusPoints": p["bonusPoints"]}
            for p in opts2["presets"]
        }
        check("preset 100 -> yuan=10 (澜途对齐)",
              abs(preset_full[100.0]["yuan"] - 10.0) < 0.01,
              f"yuan={preset_full[100.0]['yuan']}")
        check("preset 500 -> yuan=50 (澜途对齐)",
              abs(preset_full[500.0]["yuan"] - 50.0) < 0.01,
              f"yuan={preset_full[500.0]['yuan']}")
        check("preset 1000 -> yuan=100 (澜途对齐)",
              abs(preset_full[1000.0]["yuan"] - 100.0) < 0.01,
              f"yuan={preset_full[1000.0]['yuan']}")
        check("preset 3000 -> yuan=300 (澜途对齐)",
              abs(preset_full[3000.0]["yuan"] - 300.0) < 0.01,
              f"yuan={preset_full[3000.0]['yuan']}")
        check("preset 5000 -> yuan=500 (澜途对齐)",
              abs(preset_full[5000.0]["yuan"] - 500.0) < 0.01,
              f"yuan={preset_full[5000.0]['yuan']}")
        check("preset 3000 bonus=1000 (澜途赠送)",
              preset_full[3000.0]["bonusPoints"] == 1000,
              f"bonus={preset_full[3000.0]['bonusPoints']}")
        check("preset 5000 bonus=2000 (澜途赠送)",
              preset_full[5000.0]["bonusPoints"] == 2000,
              f"bonus={preset_full[5000.0]['bonusPoints']}")
        check("preset 1000 bonus=0 (阈值边界,无赠送)",
              preset_full[1000.0]["bonusPoints"] == 0,
              f"bonus={preset_full[1000.0]['bonusPoints']}")

        # ── 问题2 · CreateOrderRequest schema 允许 plan='credit' ──
        try:
            _COR(plan="credit", days=None, channel="alipay")
            check("CreateOrderRequest plan='credit' days=None 通过校验", True)
        except Exception as e:
            check("CreateOrderRequest plan='credit' days=None 通过校验",
                  False, f"err={e}")
        try:
            _COR(plan="credit", days=0, channel="alipay")
            check("CreateOrderRequest plan='credit' days=0 兼容归一为 None", True)
        except Exception as e:
            check("CreateOrderRequest plan='credit' days=0 兼容归一为 None",
                  False, f"err={e}")
        # 订阅端点 pro/free 的 days 必填仍强制
        try:
            _COR(plan="pro", days=None, channel="alipay")
            check("CreateOrderRequest plan='pro' days=None 应拒绝", False,
                  "意外通过")
        except Exception:
            check("CreateOrderRequest plan='pro' days=None 应拒绝", True)
        # 非法 plan 仍拒绝
        try:
            _COR(plan="vip", days=30, channel="alipay")
            check("CreateOrderRequest plan='vip' 应拒绝", False, "意外通过")
        except Exception:
            check("CreateOrderRequest plan='vip' 应拒绝", True)

        # ── 问题3 & 问题4 · 直接查 Order 表验证落库 ──
        # 用当前 TestClient 上下文,直接从 cloud_service.db 拿 session
        from cloud_service.db import SessionLocal
        db_sess = SessionLocal()
        try:
            credit_orders = (
                db_sess.query(_Order)
                .filter(_Order.plan == "credit")
                .all()
            )
            check("Order 表存在 plan='credit' 记录",
                  len(credit_orders) >= 1,
                  f"count={len(credit_orders)}")
            o = credit_orders[-1]  # 最新一条 = 步骤 4 里创建的 3000 积分订单
            check("积分订单 days == None (语义:积分永久有效)",
                  o.days is None,
                  f"days={o.days}")
            check("积分订单 credit_points == 4000 (3000 主 + 1000 赠)",
                  o.credit_points is not None
                  and abs(float(o.credit_points) - 4000.0) < 1e-6,
                  f"credit_points={o.credit_points}")
            check("积分订单 amount == 300 (元)",
                  abs(float(o.amount) - 300.0) < 1e-6,
                  f"amount={o.amount}")
            check("积分订单 status == 'paid'", o.status == "paid",
                  f"status={o.status}")
        finally:
            db_sess.close()

        # ── 问题4 附加 · 通过 /payment/order 端点回读 credit_points ──
        r = client.get(f"/cloud/payment/order/{order_no}", headers=H)
        check("GET /cloud/payment/order/{order_no} → 200",
              r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        if r.status_code == 200:
            oresp = r.json()
            check("OrderResponse.plan == 'credit'",
                  oresp.get("plan") == "credit",
                  f"body={oresp}")
            check("OrderResponse.days is None",
                  oresp.get("days") is None,
                  f"days={oresp.get('days')}")
            check("OrderResponse.credit_points == 4000",
                  oresp.get("credit_points") == 4000,
                  f"credit_points={oresp.get('credit_points')}")

        # ── 问题4 加固 · 充值 100 积分(无赠送)验证到账 = 100 ──
        r = client.post("/cloud/points/recharge", headers=H, json={
            "points": 100,
            "channel": "alipay",
        })
        check("POST /cloud/points/recharge 100 积分",
              r.status_code == 201,
              f"status={r.status_code} body={r.text[:200]}")
        order2 = r.json()
        check("100 积分订单 amount == 10 元",
              abs(order2.get("amount", 0) - 10.0) < 0.01,
              f"amount={order2.get('amount')}")
        check("100 积分订单 totalPoints == 100 (无赠送)",
              order2.get("totalPoints") == 100,
              f"totalPoints={order2.get('totalPoints')}")
        r = client.post(
            "/cloud/payment/callback/alipay",
            json=_mk_alipay_callback(
                order2["orderNo"], trade_no="MOCK_TRADE_100",
                amount=10.0, plan="credit", days=0,
            ),
        )
        check("100 积分订单回调 ok", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        r = client.get("/cloud/points/account", headers=H)
        # 上一步余额 3898.4 + 100(100 积分订单赠 0)= 3998.4
        check("回调后余额增加 100 (无赠送) → 3998.4",
              abs(r.json().get("availablePoints", 0) - 3998.4) < 0.1,
              f"body={r.json()}")

    # ── 汇总 ─────────────────────────────────────────
    print()
    if fails == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"{fails} test(s) FAILED")
    return fails


if __name__ == "__main__":
    sys.exit(run())
