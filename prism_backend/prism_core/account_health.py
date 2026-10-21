"""
账号健康监控（Phase 0.4）

- AccountHealthSnapshot: 账号健康快照
- AccountHealthMonitor: 账号健康监控器（探测、冷却、封禁追踪）
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso
from fastapi_app.db.runtime import mysql_enabled, sa_connection

from prism_core.receipts import PLATFORM_NAMES, platform_name_for


# ── 账号健康状态 ──
class AccountHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"        # 最近有失败但可恢复
    COOLING = "cooling"           # 触发冷却期
    BLOCKED = "blocked"           # 被封禁
    EXPIRED = "expired"           # Cookie 过期


# ── 健康快照 ──
class HealthSnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: f"hs_{uuid.uuid4().hex[:12]}")
    account_id: str = ""
    platform: int = 0
    platform_name: str = ""
    health_status: AccountHealthStatus = AccountHealthStatus.HEALTHY
    total_publishes: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    consecutive_failures: int = 0
    cooldown_until: Optional[str] = None
    probe_status: Optional[str] = None  # healthy/degraded/unreachable
    probe_checked_at: Optional[str] = None
    created_at: str = Field(default_factory=now_beijing_iso)


# ── 表结构 ──
def _ensure_health_table(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS account_health_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            platform INTEGER DEFAULT 0,
            platform_name TEXT DEFAULT '',
            health_status TEXT DEFAULT 'healthy',
            total_publishes INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            success_rate REAL DEFAULT 0.0,
            last_success_at TEXT,
            last_failure_at TEXT,
            last_error_code TEXT,
            last_error_message TEXT,
            consecutive_failures INTEGER DEFAULT 0,
            cooldown_until TEXT,
            probe_status TEXT,
            probe_checked_at TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_health_account ON account_health_snapshots(account_id)")
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_health_status ON account_health_snapshots(health_status)")
    conn.commit()


# ── 保存快照 ──
def save_health_snapshot(snapshot: HealthSnapshot) -> str:
    from fastapi_app.db.session import open_main_db
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS account_health_snapshots (
                    snapshot_id VARCHAR(64) PRIMARY KEY,
                    account_id VARCHAR(200) NOT NULL,
                    platform INT DEFAULT 0,
                    platform_name VARCHAR(50) DEFAULT '',
                    health_status VARCHAR(20) DEFAULT 'healthy',
                    total_publishes INT DEFAULT 0,
                    success_count INT DEFAULT 0,
                    failure_count INT DEFAULT 0,
                    success_rate REAL DEFAULT 0.0,
                    last_success_at DATETIME,
                    last_failure_at DATETIME,
                    last_error_code VARCHAR(50),
                    last_error_message TEXT,
                    consecutive_failures INT DEFAULT 0,
                    cooldown_until DATETIME,
                    probe_status VARCHAR(20),
                    probe_checked_at DATETIME,
                    created_at DATETIME NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO account_health_snapshots 
                (snapshot_id, account_id, platform, platform_name, health_status,
                 total_publishes, success_count, failure_count, success_rate,
                 last_success_at, last_failure_at, last_error_code, last_error_message,
                 consecutive_failures, cooldown_until, probe_status, probe_checked_at, created_at)
                VALUES (:snapshot_id, :account_id, :platform, :platform_name, :health_status,
                        :total_publishes, :success_count, :failure_count, :success_rate,
                        :last_success_at, :last_failure_at, :last_error_code, :last_error_message,
                        :consecutive_failures, :cooldown_until, :probe_status, :probe_checked_at, :created_at)
            """), {
                "snapshot_id": snapshot.snapshot_id,
                "account_id": snapshot.account_id,
                "platform": snapshot.platform,
                "platform_name": snapshot.platform_name,
                "health_status": snapshot.health_status.value,
                "total_publishes": snapshot.total_publishes,
                "success_count": snapshot.success_count,
                "failure_count": snapshot.failure_count,
                "success_rate": snapshot.success_rate,
                "last_success_at": snapshot.last_success_at,
                "last_failure_at": snapshot.last_failure_at,
                "last_error_code": snapshot.last_error_code,
                "last_error_message": snapshot.last_error_message,
                "consecutive_failures": snapshot.consecutive_failures,
                "cooldown_until": snapshot.cooldown_until,
                "probe_status": snapshot.probe_status,
                "probe_checked_at": snapshot.probe_checked_at,
                "created_at": snapshot.created_at,
            })
    else:
        conn = open_main_db()
        _ensure_health_table(conn)
        conn.execute("""
            INSERT INTO account_health_snapshots 
            (snapshot_id, account_id, platform, platform_name, health_status,
             total_publishes, success_count, failure_count, success_rate,
             last_success_at, last_failure_at, last_error_code, last_error_message,
             consecutive_failures, cooldown_until, probe_status, probe_checked_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot.snapshot_id, snapshot.account_id, snapshot.platform, snapshot.platform_name,
            snapshot.health_status.value, snapshot.total_publishes, snapshot.success_count,
            snapshot.failure_count, snapshot.success_rate, snapshot.last_success_at,
            snapshot.last_failure_at, snapshot.last_error_code, snapshot.last_error_message,
            snapshot.consecutive_failures, snapshot.cooldown_until, snapshot.probe_status,
            snapshot.probe_checked_at, snapshot.created_at,
        ))
        conn.commit()
    logger.info(f"[AccountHealth] 快照: {snapshot.account_id} -> {snapshot.health_status.value}")
    return snapshot.snapshot_id


# ── 查询 ──
def get_latest_health(account_id: str) -> Optional[HealthSnapshot]:
    from fastapi_app.db.session import open_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(
                text("SELECT * FROM account_health_snapshots WHERE account_id = :aid ORDER BY created_at DESC LIMIT 1"),
                {"aid": account_id}
            ).mappings().first()
        if row: row = dict(row)
    else:
        conn = open_main_db()
        _ensure_health_table(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM account_health_snapshots WHERE account_id = ? ORDER BY created_at DESC LIMIT 1", (account_id,))
        row = cursor.fetchone()
        cols = [d[0] for d in cursor.description]
        if row: row = dict(zip(cols, row))
    if not row: return None
    return _row_to_snapshot(row)


def list_health_snapshots(
    account_id: Optional[str] = None,
    health_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[HealthSnapshot]:
    from fastapi_app.db.session import open_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        conditions = []
        params = {}
        if account_id:
            conditions.append("account_id = :aid")
            params["aid"] = account_id
        if health_status:
            conditions.append("health_status = :hs")
            params["hs"] = health_status
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params["limit"] = limit
        params["offset"] = offset
        with sa_connection() as conn:
            rows = conn.execute(
                text(f"SELECT * FROM account_health_snapshots{where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
                params
            ).mappings().all()
        rows = [dict(r) for r in rows]
    else:
        conn = open_main_db()
        _ensure_health_table(conn)
        cursor = conn.cursor()
        conditions = []
        params: list = []
        if account_id:
            conditions.append("account_id = ?")
            params.append(account_id)
        if health_status:
            conditions.append("health_status = ?")
            params.append(health_status)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.extend([limit, offset])
        cursor.execute(f"SELECT * FROM account_health_snapshots{where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params)
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in rows]
    return [_row_to_snapshot(r) for r in rows]


def _row_to_snapshot(row: Dict[str, Any]) -> HealthSnapshot:
    return HealthSnapshot(
        snapshot_id=row["snapshot_id"],
        account_id=row["account_id"],
        platform=row.get("platform", 0) or 0,
        platform_name=row.get("platform_name", "") or "",
        health_status=AccountHealthStatus(row.get("health_status", "healthy")),
        total_publishes=row.get("total_publishes", 0) or 0,
        success_count=row.get("success_count", 0) or 0,
        failure_count=row.get("failure_count", 0) or 0,
        success_rate=row.get("success_rate", 0.0) or 0.0,
        last_success_at=row.get("last_success_at"),
        last_failure_at=row.get("last_failure_at"),
        last_error_code=row.get("last_error_code"),
        last_error_message=row.get("last_error_message"),
        consecutive_failures=row.get("consecutive_failures", 0) or 0,
        cooldown_until=row.get("cooldown_until"),
        probe_status=row.get("probe_status"),
        probe_checked_at=row.get("probe_checked_at"),
        created_at=row["created_at"],
    )


# ── 从回执聚合计算健康状态 ──
def compute_health_from_receipts(account_id: str, platform: int = 0) -> HealthSnapshot:
    """从 publish_receipts 表聚合计算账号健康状态"""
    from prism_core.receipts import list_receipts, ReceiptStatus
    from fastapi_app.db.session import open_main_db

    receipts = list_receipts(account_id=account_id, limit=1000)
    
    if platform:
        receipts = [r for r in receipts if r.platform == platform]
    
    total = len(receipts)
    success_count = sum(1 for r in receipts if r.status == ReceiptStatus.SUCCEEDED)
    failure_count = sum(1 for r in receipts if r.status in (ReceiptStatus.FAILED_RETRYABLE, ReceiptStatus.FAILED_FINAL))
    success_rate = round(success_count / total, 4) if total > 0 else 0.0

    last_success = None
    last_failure = None
    last_error_code = None
    last_error_message = None
    consecutive_failures = 0

    sorted_receipts = sorted(receipts, key=lambda r: r.created_at, reverse=True)
    for r in sorted_receipts:
        if r.status == ReceiptStatus.SUCCEEDED:
            last_success = r.published_at or r.created_at
            consecutive_failures = 0
        elif r.status in (ReceiptStatus.FAILED_RETRYABLE, ReceiptStatus.FAILED_FINAL):
            if last_failure is None:
                last_failure = r.created_at
                last_error_code = r.error_code.value if r.error_code else None
                last_error_message = r.error_message
            if consecutive_failures == 0:
                consecutive_failures = 1
            else:
                consecutive_failures += 1
            if r.status == ReceiptStatus.FAILED_RETRYABLE and last_failure is None:
                last_failure = r.created_at
                last_error_code = r.error_code.value if r.error_code else None
                last_error_message = r.error_message
        if last_success and last_failure:
            break

    # 判定健康状态
    platform_name = platform_name_for(platform) if platform else ""
    if any(r.status == ReceiptStatus.FAILED_FINAL and r.error_code and r.error_code.value == "ACCOUNT_BLOCKED" for r in sorted_receipts[:5]):
        health_status = AccountHealthStatus.BLOCKED
    elif consecutive_failures >= 5:
        health_status = AccountHealthStatus.COOLING
    elif any(r.error_code and r.error_code.value in ("COOKIE_EXPIRED", "LOGIN_REQUIRED") for r in sorted_receipts[:3]):
        health_status = AccountHealthStatus.EXPIRED
    elif consecutive_failures >= 3:
        health_status = AccountHealthStatus.DEGRADED
    else:
        health_status = AccountHealthStatus.HEALTHY

    # 计算冷却截止时间
    cooldown_until = None
    if health_status == AccountHealthStatus.COOLING:
        cooldown_until = now_beijing_iso()  # 简化：记录当前时间作为冷却开始

    return HealthSnapshot(
        account_id=account_id,
        platform=platform,
        platform_name=platform_name,
        health_status=health_status,
        total_publishes=total,
        success_count=success_count,
        failure_count=failure_count,
        success_rate=success_rate,
        last_success_at=last_success,
        last_failure_at=last_failure,
        last_error_code=last_error_code,
        last_error_message=last_error_message,
        consecutive_failures=consecutive_failures,
        cooldown_until=cooldown_until,
    )


# ── AccountHealthMonitor 类 ──
class AccountHealthMonitor:
    """账号健康监控器"""

    def __init__(self):
        self._cooldown_accounts: Dict[str, str] = {}  # account_id -> cooldown_until

    def record_failure(self, account_id: str, platform: int, error_code: str, error_message: str = "") -> HealthSnapshot:
        """记录失败并更新健康状态"""
        from prism_core.receipts import list_receipts, ReceiptStatus

        snapshot = compute_health_from_receipts(account_id, platform)
        save_health_snapshot(snapshot)

        # 检查是否需要冷却
        if snapshot.consecutive_failures >= 5 and not snapshot.cooldown_until:
            from datetime import timedelta
            cooldown_until = now_beijing_iso()
            self._cooldown_accounts[account_id] = cooldown_until
            logger.warning(f"[AccountHealth] 账号 {account_id} 触发冷却 (连续失败 {snapshot.consecutive_failures} 次)")

        return snapshot

    def record_success(self, account_id: str, platform: int) -> HealthSnapshot:
        """记录成功并更新健康状态"""
        snapshot = compute_health_from_receipts(account_id, platform)
        save_health_snapshot(snapshot)
        # 清除冷却
        self._cooldown_accounts.pop(account_id, None)
        return snapshot

    def is_in_cooldown(self, account_id: str) -> bool:
        """检查账号是否在冷却期"""
        if account_id not in self._cooldown_accounts:
            return False
        # 简化：冷却期持续 1 小时
        return True  # 实际实现应比较时间

    def get_account_health(self, account_id: str) -> Optional[HealthSnapshot]:
        """获取账号最新健康状态"""
        return get_latest_health(account_id)

    def list_unhealthy_accounts(self) -> List[HealthSnapshot]:
        """列出所有不健康账号"""
        return list_health_snapshots(health_status="cooling") + \
               list_health_snapshots(health_status="blocked") + \
               list_health_snapshots(health_status="expired") + \
               list_health_snapshots(health_status="degraded")


# 全局实例
account_health_monitor = AccountHealthMonitor()
