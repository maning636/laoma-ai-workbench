"""M3 · 积分制 TestClient 集成测试(不启动服务器,不落仓库文件)。

覆盖:
  1. **人工充值链路**:管理端加积分 → 账户余额 / 累计充值到账
     (2026-10-23 起平台支付已彻底删除,在线充值订单端点不存在)
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

# 管理端 token(人工充值 / 人工加积分用)
os.environ["CLOUD_ADMIN_TOKEN"] = "test-admin-token"
# 2026-10-23:平台支付已彻底删除,清掉残留开关变量,避免误导。
os.environ.pop("CLOUD_ONLINE_PAYMENT_ENABLED", None)
os.environ.pop("CLOUD_PAYMENT_NOTIFY_URL", None)
os.environ.pop("CLOUD_PAYMENT_RETURN_URL", None)

# 确保能导入仓库根
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


def _admin_recharge(client, user_id: int, points: float, note: str) -> dict:
    """走管理端人工加积分(= 人工充值到账的唯一路径)。"""
    r = client.post(
        "/cloud/admin/points/adjust",
        headers={"X-Admin-Token": "test-admin-token"},
        json={"user_id": user_id, "amount": points, "note": note},
    )
    return r.json() if r.status_code == 200 else {}


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

        # ── 4. 在线充值订单端点已删除(平台支付彻底删除) ──
        r = client.post("/cloud/points/recharge", headers=H, json={
            "points": 3000,
            "channel": "alipay",
        })
        check("POST /cloud/points/recharge → 404(在线充值已删除)", r.status_code == 404,
              f"status={r.status_code} body={r.text[:200]}")

        # ── 5. 人工充值到账:管理端加积分(3000 主 + 1000 赠 = 4000) ──
        my_uid = client.get("/cloud/points/account", headers=H).json()["primaryAccountId"]
        adj = _admin_recharge(client, my_uid, 4000, "微信充值 3000 积分 + 赠送 1000")
        check("管理端加积分 → 4000 到账",
              abs(float(adj.get("points", {}).get("availablePoints", 0)) - 4000.0) < 0.001,
              f"adj={adj}")

        r = client.get("/cloud/points/account", headers=H)
        acct = r.json()
        check("after manual recharge availablePoints == 4000",
              acct.get("availablePoints") == 4000,
              f"body={acct}")
        check("after manual recharge totalRecharged == 4000",
              acct.get("totalRecharged") == 4000,
              f"body={acct}")

        # ── 6. 人工充值会写流水(可审计) ─────────────────
        r = client.get("/cloud/points/history?tx_type=RECHARGE", headers=H)
        hist_r = r.json()
        check("RECHARGE 流水至少 1 条",
              hist_r.get("total", 0) >= 1,
              f"total={hist_r.get('total')}")

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
        # ── 15. M3 硬化专项:预设数值 / 支付代码移除 / 人工充值可审计 ──
        # ════════════════════════════════════════════════════

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

        # ── 问题2 · 支付代码与支付 schema 已彻底移除 ──
        import importlib.util as _ilu
        check("cloud_service.payment 包已不存在",
              _ilu.find_spec("cloud_service.payment") is None,
              "包仍在(平台支付未删干净)")
        from cloud_service.billing import schemas as _billing_schemas
        check("PointsRechargeCreateRequest schema 已移除",
              not hasattr(_billing_schemas, "PointsRechargeCreateRequest"))
        check("PointsRechargeCreateResponse schema 已移除",
              not hasattr(_billing_schemas, "PointsRechargeCreateResponse"))

        # ── 问题3 & 问题4 · 人工充值到账可审计(流水 + 余额) ──
        from cloud_service.billing.models import CreditLedger, TX_RECHARGE
        from cloud_service.db import SessionLocal
        db_sess = SessionLocal()
        try:
            recharge_ledgers = (
                db_sess.query(CreditLedger)
                .filter(CreditLedger.tx_type == TX_RECHARGE)
                .all()
            )
            check("人工充值写入 RECHARGE 流水",
                  len(recharge_ledgers) >= 1,
                  f"count={len(recharge_ledgers)}")
            led = recharge_ledgers[-1]
            check("人工充值流水金额 == 4000 (3000 主 + 1000 赠)",
                  led.amount is not None and abs(float(led.amount) - 4000.0) < 1e-6,
                  f"amount={led.amount}")
            check("人工充值流水 use_function == 'recharge'",
                  led.use_function == "recharge",
                  f"use_function={led.use_function}")
            check("人工充值流水有 note(可审计:备注写明微信充值档位)",
                  bool(led.note),
                  f"note={led.note!r}")
        finally:
            db_sess.close()

        # ── 问题4 加固 · 再人工加 100 积分(无赠送档)验证到账 = 100 ──
        adj2 = _admin_recharge(client, my_uid, 100, "微信充值 100 积分")
        check("第二次人工充值 +100 后余额 3998.4",
              abs(float(adj2.get("points", {}).get("availablePoints", 0)) - 3998.4) < 0.1,
              f"adj2={adj2}")

    # ── 汇总 ─────────────────────────────────────────
    print()
    if fails == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"{fails} test(s) FAILED")
    return fails


if __name__ == "__main__":
    sys.exit(run())
