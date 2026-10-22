"""C13 · Feature Gate 的 plan 判定回归测试。

为什么要有这个文件:
  历史上 `cloud_service/billing/feature_gate.py` 的 `_resolve_plan` 里用了
  `select(Subscription)`,但文件顶部**漏了 `from sqlalchemy import select`**。
  NameError 被 `except Exception` 静默吞掉,plan 永远回落 "community" ——
  **付费 Pro 用户拿到的全是 Community 权限**,且没有任何报错。

  本测试锁死三件事:
    1. active + 未过期的 pro 订阅 → plan 必须是 "pro",Pro flag 必须下发
    2. 各种非 Pro 情形 → 必须回落 "community"(这是**正确**的降级)
    3. **编程错误不得被伪装成降级**:DB 正常但代码出错时,必须向上抛,
       而不是悄悄回落 community(否则同类 bug 会再次静默存在)

用法:
    python cloud_service/test_feature_gate_plan.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# ── 环境准备:临时 SQLite,避免污染仓库 ────────────────────────
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["CLOUD_DB_URL"] = f"sqlite:///{_tmp.name}"

_repo_root = Path = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

_FAILED: list[str] = []


def check(cond: bool, label: str, extra: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    line = f"[{status}] {label}"
    if extra:
        line += f"  ({extra})"
    print(line)
    if not cond:
        _FAILED.append(label)
    return cond


def _mk_user(db, username: str) -> int:
    from cloud_service.auth.models import User

    u = User(username=username, password_hash="x", email=f"{username}@x.invalid")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u.id


def run() -> int:
    from cloud_service.db import SessionLocal, init_db
    from cloud_service.billing import feature_gate as FG
    from cloud_service.billing.models import Subscription

    init_db()
    now = datetime.now(timezone.utc)

    # ── 建 4 个用户,分别对应 4 种订阅状态 ────────────────────
    with SessionLocal() as db:
        uid_pro = _mk_user(db, "fg_pro")
        uid_expired = _mk_user(db, "fg_expired")
        uid_cancelled = _mk_user(db, "fg_cancelled")
        uid_free = _mk_user(db, "fg_free")
        uid_none = _mk_user(db, "fg_none")

        db.add(Subscription(user_id=uid_pro, plan="pro", status="active",
                            quota=-1, expire_at=now + timedelta(days=30)))
        db.add(Subscription(user_id=uid_expired, plan="pro", status="active",
                            quota=-1, expire_at=now - timedelta(days=1)))
        db.add(Subscription(user_id=uid_cancelled, plan="pro", status="cancelled",
                            quota=-1, expire_at=now + timedelta(days=30)))
        db.add(Subscription(user_id=uid_free, plan="free", status="active",
                            quota=3, expire_at=None))
        db.commit()

    # ── 1. Pro 用户必须拿到 Pro plan 与 Pro flag ──────────────
    with SessionLocal() as db:
        plan = FG._resolve_plan(db, uid_pro)
        check(plan == "pro", "active pro 订阅 → plan == 'pro'", repr(plan))

        payload = FG.get_user_feature_flags(uid_pro, db=db)
        check(payload["plan"] == "pro", "get_user_feature_flags.plan == 'pro'",
              repr(payload["plan"]))
        flags = payload["flags"]
        check(flags.get("persona") is True, "Pro flag persona == True", repr(flags.get("persona")))
        check(flags.get("proxy_management") is True, "Pro flag proxy_management == True",
              repr(flags.get("proxy_management")))
        check(flags.get("stream_chat") is True, "Pro flag stream_chat == True",
              repr(flags.get("stream_chat")))
        check(flags.get("max_accounts") == -1, "Pro flag max_accounts == -1",
              repr(flags.get("max_accounts")))
        check(flags.get("ai_mode") == "cloud", "Pro flag ai_mode == 'cloud'",
              repr(flags.get("ai_mode")))
        check(flags.get("image_gen") == "cloud", "Pro flag image_gen == 'cloud'",
              repr(flags.get("image_gen")))
        check(flags.get("agent_quota") == 2, "Pro flag agent_quota == 2",
              repr(flags.get("agent_quota")))
        # D7:数据回收社区版也可用,Pro 同样为 True
        check(flags.get("data_recovery") is True, "Pro flag data_recovery == True (D7)",
              repr(flags.get("data_recovery")))

    # ── 2. 非 Pro 情形必须回落 community ─────────────────────
    cases = [
        (uid_expired, "已过期订阅"),
        (uid_cancelled, "已取消订阅"),
        (uid_free, "free 订阅"),
        (uid_none, "无订阅记录"),
    ]
    for uid, label in cases:
        with SessionLocal() as db:
            plan = FG._resolve_plan(db, uid)
            check(plan == "community", f"{label} → plan == 'community'", repr(plan))
            payload = FG.get_user_feature_flags(uid, db=db)
            check(payload["plan"] == "community", f"{label} → flags.plan == 'community'",
                  repr(payload["plan"]))

    # ── 3. db=None / user_id=None → community ─────────────────
    check(FG._resolve_plan(None, uid_pro) == "community", "db=None → community")
    check(FG._resolve_plan(None, None) == "community", "user_id=None → community")

    # ── 4. 编程错误**不得**被伪装成降级 ────────────────────────
    #     若 `_resolve_plan` 又改回 `except Exception`,这里的 NameError 会被吞掉,
    #     plan 回落 community 而无人察觉 —— 这正是历史 P0 的成因。
    original_execute = None
    try:
        from sqlalchemy.orm import Session as _S

        original_execute = _S.execute

        def _boom(self, *a, **kw):
            raise NameError("name 'select' is not defined")

        _S.execute = _boom
        with SessionLocal() as db:
            try:
                plan = FG._resolve_plan(db, uid_pro)
                check(False, "编程错误应向上抛,而不是回落 community",
                      f"plan={plan!r} —— 又改回 except Exception 了")
            except NameError:
                check(True, "编程错误向上抛(没有伪装成降级)")
            except Exception as e:  # noqa: BLE001
                check(False, "编程错误应以 NameError 形式抛出", f"{type(e).__name__}: {e}")
    finally:
        if original_execute is not None:
            from sqlalchemy.orm import Session as _S

            _S.execute = original_execute

    # ── 5. 恢复后再确认一次(确保 monkeypatch 已还原) ──────────
    with SessionLocal() as db:
        plan = FG._resolve_plan(db, uid_pro)
        check(plan == "pro", "还原后 Pro 判定仍正确", repr(plan))

    print()
    if _FAILED:
        print(f"ALL TESTS FAILED: {len(_FAILED)} check(s) failed")
        for label in _FAILED:
            print(f"  - {label}")
        return len(_FAILED)
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
