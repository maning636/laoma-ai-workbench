"""
发布诊断工件采集（Phase 2.2）

发布失败时自动截图+DOM+URL+日志采集，脱敏存储。
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso
from fastapi_app.db.runtime import mysql_enabled, sa_connection


class DiagnosticArtifacts(BaseModel):
    artifact_id: str = Field(default_factory=lambda: f"diag_{uuid.uuid4().hex[:12]}")
    task_id: str = ""
    platform: int = 0
    platform_name: str = ""
    screenshot_path: Optional[str] = None
    dom_path: Optional[str] = None
    url_snapshot: Optional[str] = None
    error_stack: Optional[str] = None
    log_path: Optional[str] = None
    cookie_status: Optional[str] = None  # valid / expired / unknown
    ip_address: Optional[str] = None
    collector_version: str = "1.0"
    redacted: bool = True
    created_at: str = Field(default_factory=now_beijing_iso)


_SENSITIVE_PATTERNS = [
    (re.compile(r"(sessionid|session_id|passport_csrf_token|SESSDATA|bili_jct|web_session|cookie)=([^;\s]+)", re.I), r"\1=[REDACTED]"),
    (re.compile(r"(Bearer|token|api_key|apikey)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]+)['\"]?", re.I), r"\1=[REDACTED]"),
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?([^'\"\s]+)", re.I), r"\1=[REDACTED]"),
    (re.compile(r"(?i)authorization:\s*bearer\s+([a-zA-Z0-9._\-]+)", re.I), r"Authorization: Bearer [REDACTED]"),
]


def redact_sensitive_info(text: str) -> str:
    """脱敏处理：替换密码、token、cookie 等敏感信息"""
    if not text:
        return text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _ensure_diagnostics_table(conn: sqlite3.Connection) -> None:
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS diagnostics_artifacts (
            artifact_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            platform INTEGER DEFAULT 0,
            platform_name TEXT DEFAULT '',
            screenshot_path TEXT,
            dom_path TEXT,
            url_snapshot TEXT,
            error_stack TEXT,
            log_path TEXT,
            cookie_status TEXT,
            ip_address TEXT,
            collector_version TEXT DEFAULT '1.0',
            redacted INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    conn.cursor().execute("CREATE INDEX IF NOT EXISTS idx_diag_task ON diagnostics_artifacts(task_id)")
    conn.commit()


def save_diagnostic_artifacts(artifacts: DiagnosticArtifacts) -> str:
    from fastapi_app.db.session import open_main_db
    data = artifacts.model_dump()
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS diagnostics_artifacts (
                    artifact_id VARCHAR(128) PRIMARY KEY,
                    task_id VARCHAR(128) NOT NULL,
                    platform INT DEFAULT 0,
                    platform_name VARCHAR(50) DEFAULT '',
                    screenshot_path TEXT, dom_path TEXT, url_snapshot TEXT,
                    error_stack TEXT, log_path TEXT, cookie_status VARCHAR(20),
                    ip_address VARCHAR(64), collector_version VARCHAR(10) DEFAULT '1.0',
                    redacted TINYINT DEFAULT 1, created_at DATETIME NOT NULL,
                    INDEX idx_diag_task (task_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                INSERT INTO diagnostics_artifacts
                (artifact_id, task_id, platform, platform_name, screenshot_path, dom_path,
                 url_snapshot, error_stack, log_path, cookie_status, ip_address,
                 collector_version, redacted, created_at)
                VALUES (:artifact_id, :task_id, :platform, :platform_name, :screenshot_path,
                        :dom_path, :url_snapshot, :error_stack, :log_path, :cookie_status,
                        :ip_address, :collector_version, :redacted, :created_at)
            """), {"redacted": int(artifacts.redacted), **data})
    else:
        conn = open_main_db()
        _ensure_diagnostics_table(conn)
        conn.execute("""
            INSERT OR REPLACE INTO diagnostics_artifacts
            (artifact_id, task_id, platform, platform_name, screenshot_path, dom_path,
             url_snapshot, error_stack, log_path, cookie_status, ip_address,
             collector_version, redacted, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            artifacts.artifact_id, artifacts.task_id, artifacts.platform, artifacts.platform_name,
            artifacts.screenshot_path, artifacts.dom_path, artifacts.url_snapshot,
            artifacts.error_stack, artifacts.log_path, artifacts.cookie_status,
            artifacts.ip_address, artifacts.collector_version, int(artifacts.redacted),
            artifacts.created_at,
        ))
        conn.commit()
    logger.info(f"[Diagnostics] 采集完成: {artifacts.task_id} ({artifacts.platform_name})")
    return artifacts.artifact_id


def get_diagnostic_artifacts(task_id: str) -> Optional[DiagnosticArtifacts]:
    from fastapi_app.db.session import open_main_db
    row = None
    if mysql_enabled():
        from sqlalchemy import text
        with sa_connection() as conn:
            row = conn.execute(text("SELECT * FROM diagnostics_artifacts WHERE task_id = :tid ORDER BY created_at DESC LIMIT 1"), {"tid": task_id}).mappings().first()
        if row: row = dict(row)
    else:
        conn = open_main_db()
        _ensure_diagnostics_table(conn)
        c = conn.cursor()
        c.execute("SELECT * FROM diagnostics_artifacts WHERE task_id = ? ORDER BY created_at DESC LIMIT 1", (task_id,))
        row = c.fetchone()
        cols = [d[0] for d in c.description]
        if row: row = dict(zip(cols, row))
    if not row: return None
    return _row_to_artifacts(row)


def list_diagnostic_artifacts(task_id: Optional[str] = None, platform: Optional[int] = None, limit: int = 50, offset: int = 0) -> list:
    from fastapi_app.db.session import open_main_db
    rows = []
    if mysql_enabled():
        from sqlalchemy import text
        conds, params = [], {}
        if task_id: conds.append("task_id = :tid"); params["tid"] = task_id
        if platform is not None: conds.append("platform = :plat"); params["plat"] = platform
        where = " WHERE " + " AND ".join(conds) if conds else ""
        params["limit"], params["offset"] = limit, offset
        with sa_connection() as conn:
            rows = [dict(r) for r in conn.execute(text(f"SELECT * FROM diagnostics_artifacts{where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"), params).mappings().all()]
    else:
        conn = open_main_db()
        _ensure_diagnostics_table(conn)
        c = conn.cursor()
        conds, plist = [], []
        if task_id: conds.append("task_id = ?"); plist.append(task_id)
        if platform is not None: conds.append("platform = ?"); plist.append(platform)
        where = " WHERE " + " AND ".join(conds) if conds else ""
        plist.extend([limit, offset])
        c.execute(f"SELECT * FROM diagnostics_artifacts{where} ORDER BY created_at DESC LIMIT ? OFFSET ?", plist)
        rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
    return [_row_to_artifacts(r) for r in rows]


def _row_to_artifacts(row: dict) -> DiagnosticArtifacts:
    return DiagnosticArtifacts(
        artifact_id=row["artifact_id"], task_id=row["task_id"],
        platform=row.get("platform", 0) or 0, platform_name=row.get("platform_name", "") or "",
        screenshot_path=row.get("screenshot_path"), dom_path=row.get("dom_path"),
        url_snapshot=row.get("url_snapshot"), error_stack=row.get("error_stack"),
        log_path=row.get("log_path"), cookie_status=row.get("cookie_status"),
        ip_address=row.get("ip_address"), collector_version=row.get("collector_version", "1.0") or "1.0",
        redacted=bool(row.get("redacted", 1)), created_at=row["created_at"],
    )


def collect_diagnostics(task_id: str, platform: int, platform_name: str,
                        screenshot_path: Optional[str] = None, dom_path: Optional[str] = None,
                        url_snapshot: Optional[str] = None, error_stack: Optional[str] = None,
                        log_path: Optional[str] = None, cookie_status: Optional[str] = None,
                        ip_address: Optional[str] = None) -> DiagnosticArtifacts:
    """便捷构造并保存诊断工件"""
    if error_stack:
        error_stack = redact_sensitive_info(str(error_stack))
    if url_snapshot:
        url_snapshot = redact_sensitive_info(str(url_snapshot))
    a = DiagnosticArtifacts(
        task_id=task_id, platform=platform, platform_name=platform_name,
        screenshot_path=screenshot_path, dom_path=dom_path, url_snapshot=url_snapshot,
        error_stack=error_stack, log_path=log_path, cookie_status=cookie_status,
        ip_address=ip_address,
    )
    save_diagnostic_artifacts(a)
    return a


def capture_browser_screenshot(page, save_dir: str, task_id: str) -> Optional[str]:
    """从 Playwright page 截图"""
    try:
        from pathlib import Path
        d = Path(save_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{task_id}_screenshot.png"
        page.screenshot(path=str(path), full_page=False)
        logger.info(f"[Diagnostics] 截图已保存: {path}")
        return str(path)
    except Exception as e:
        logger.warning(f"[Diagnostics] 截图失败: {e}")
        return None


def capture_dom_snapshot(page, save_dir: str, task_id: str) -> Optional[str]:
    """捕获 DOM 并脱敏"""
    try:
        from pathlib import Path
        d = Path(save_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{task_id}_dom.html"
        html = page.content()
        html = redact_sensitive_info(html)
        path.write_text(html, encoding="utf-8")
        logger.info(f"[Diagnostics] DOM 已保存: {path}")
        return str(path)
    except Exception as e:
        logger.warning(f"[Diagnostics] DOM 捕获失败: {e}")
        return None


class DiagnosticsCollector:
    """诊断采集器全局实例"""

    def __init__(self):
        diag_dir = Path(settings.DATA_DIR) / "diagnostics"
        diag_dir.mkdir(parents=True, exist_ok=True)
        self.save_dir = str(diag_dir)

    def collect_on_failure(self, task_id: str, platform: int, platform_name: str,
                           page=None, error_stack: Optional[str] = None,
                           cookie_status: Optional[str] = None,
                           ip_address: Optional[str] = None) -> DiagnosticArtifacts:
        screenshot = dom_path = None
        url_snapshot = None
        if page:
            screenshot = capture_browser_screenshot(page, self.save_dir, task_id)
            dom_path = capture_dom_snapshot(page, self.save_dir, task_id)
            try:
                url_snapshot = page.url
            except Exception:
                pass
        return collect_diagnostics(task_id, platform, platform_name,
                                   screenshot_path=screenshot, dom_path=dom_path,
                                   url_snapshot=url_snapshot, error_stack=error_stack,
                                   cookie_status=cookie_status, ip_address=ip_address)


diagnostics_collector = DiagnosticsCollector()
