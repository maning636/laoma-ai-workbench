"""M1 · image_generations 生成记录表。

表结构（对齐任务要求）：

  CREATE TABLE image_generations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT        NOT NULL,
    model_key       VARCHAR(64) NOT NULL,
    prompt          TEXT,
    agent_id        VARCHAR(64),
    aspect_ratio    VARCHAR(16),
    count           INTEGER DEFAULT 1,
    images_url      TEXT,       -- JSON 数组
    points_cost     REAL       DEFAULT 0.0,
    freeze_tx_id    INTEGER,
    status          VARCHAR(16) DEFAULT 'pending',  -- success / failed / pending
    error_message   TEXT,
    idempotency_key VARCHAR(64),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX idx_image_gen_user    ON image_generations(user_id);
  CREATE INDEX idx_image_gen_created ON image_generations(created_at DESC);

设计要点：
- 复用 fastapi_app.db.sqlalchemy_engine.get_engine() 的引擎，SQLite / MySQL 通用。
- 懒初始化：`ensure_table()` 幂等创建表和索引（表缺失时自动 CREATE）。
- 所有函数吞异常但不吞"业务逻辑"：写失败仅 log 不阻塞 generate 主流程。
- `images_url` 存 JSON 字符串数组，避免额外依赖（跨 SQLite / MySQL 兼容）。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional

try:
    from fastapi_app.core.logger import logger  # type: ignore
except Exception:  # pragma: no cover
    logger = None

_TABLE = "image_generations"
_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT        NOT NULL,
    model_key       VARCHAR(64) NOT NULL,
    prompt          TEXT,
    agent_id        VARCHAR(64),
    aspect_ratio    VARCHAR(16),
    count           INTEGER DEFAULT 1,
    images_url      TEXT,
    points_cost     REAL        DEFAULT 0.0,
    freeze_tx_id    INTEGER,
    status          VARCHAR(16) DEFAULT 'pending',
    error_message   TEXT,
    idempotency_key VARCHAR(64),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
)
""".format(table=_TABLE)

_INDEX_USER_SQL = "CREATE INDEX IF NOT EXISTS idx_image_gen_user ON {t}(user_id)".format(t=_TABLE)
_INDEX_CREATED_SQL = "CREATE INDEX IF NOT EXISTS idx_image_gen_created ON {t}(created_at DESC)".format(t=_TABLE)

_ensure_lock = threading.Lock()
_ensured = False


def _log(msg: str) -> None:
    if logger is not None:
        try:
            logger.info(msg)
        except Exception:
            pass


def _get_engine():
    """懒加载 engine；失败返回 None（调用方降级）。"""
    try:
        from fastapi_app.db.sqlalchemy_engine import get_engine  # type: ignore
        return get_engine()
    except Exception:
        return None


def ensure_table() -> bool:
    """幂等建表 + 索引。"""
    global _ensured
    if _ensured:
        return True
    engine = _get_engine()
    if engine is None:
        return False
    with _ensure_lock:
        if _ensured:
            return True
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(_TABLE_SQL)
                conn.exec_driver_sql(_INDEX_USER_SQL)
                conn.exec_driver_sql(_INDEX_CREATED_SQL)
            _ensured = True
            return True
        except Exception as exc:  # pragma: no cover
            _log(f"[image_gen_models] ensure_table failed: {exc}")
            return False


def reset_ensured() -> None:
    """测试用：强制下次访问重新 CREATE TABLE。"""
    global _ensured
    _ensured = False


def clear_all_records() -> None:
    """测试用：清空整张 image_generations 表。"""
    ensure_table()
    engine = _get_engine()
    if engine is None:
        return
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("DELETE FROM {t}".format(t=_TABLE))
    except Exception as exc:  # pragma: no cover
        _log(f"[image_gen_models] clear_all_records failed: {exc}")


def drop_table_for_test() -> None:
    """测试用：DROP 表 + 重置确保标记（下次访问时重新建表）。"""
    global _ensured
    engine = _get_engine()
    if engine is not None:
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql("DROP TABLE IF EXISTS {t}".format(t=_TABLE))
        except Exception as exc:  # pragma: no cover
            _log(f"[image_gen_models] drop_table_for_test failed: {exc}")
    _ensured = False


# ──────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────


def insert_record(*,
                  user_id: str,
                  model_key: str,
                  prompt: str = "",
                  agent_id: str = "",
                  aspect_ratio: str = "",
                  count: int = 1,
                  freeze_tx_id: Optional[int] = None,
                  idempotency_key: str = "",
                  status: str = "pending") -> Optional[int]:
    """插入一条 pending/failed 记录，返回自增 id；失败返回 None。"""
    ensure_table()
    engine = _get_engine()
    if engine is None:
        return None
    try:
        with engine.begin() as conn:
            result = conn.exec_driver_sql(
                """
                INSERT INTO {t} (user_id, model_key, prompt, agent_id, aspect_ratio,
                                 count, points_cost, freeze_tx_id, status,
                                 idempotency_key, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """.format(t=_TABLE),
                (
                    str(user_id),
                    str(model_key),
                    str(prompt),
                    str(agent_id),
                    str(aspect_ratio),
                    int(count),
                    int(freeze_tx_id) if freeze_tx_id else None,
                    str(status),
                    str(idempotency_key),
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                ),
            )
        return _row_id(result)
    except Exception as exc:  # pragma: no cover
        _log(f"[image_gen_models] insert failed: {exc}")
        return None


def update_success(record_id: int, *,
                   images: List[str],
                   points_cost: float,
                   status: str = "success") -> bool:
    ensure_table()
    engine = _get_engine()
    if engine is None:
        return False
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                UPDATE {t} SET status=?, images_url=?, points_cost=?, error_message=NULL
                WHERE id=?
                """.format(t=_TABLE),
                (status, json.dumps(images, ensure_ascii=False), float(points_cost), int(record_id)),
            )
        return True
    except Exception as exc:  # pragma: no cover
        _log(f"[image_gen_models] update_success failed: {exc}")
        return False


def update_freeze_tx_id(record_id: int, freeze_tx_id: int) -> bool:
    """冻结成功后回写 freeze_tx_id（供 generate 流程使用）。"""
    ensure_table()
    engine = _get_engine()
    if engine is None:
        return False
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                UPDATE {t} SET freeze_tx_id=? WHERE id=?
                """.format(t=_TABLE),
                (int(freeze_tx_id), int(record_id)),
            )
        return True
    except Exception as exc:  # pragma: no cover
        _log(f"[image_gen_models] update_freeze_tx_id failed: {exc}")
        return False


def update_failed(record_id: int, *,
                  error_message: str = "",
                  status: str = "failed") -> bool:
    ensure_table()
    engine = _get_engine()
    if engine is None:
        return False
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                UPDATE {t} SET status=?, error_message=?
                WHERE id=?
                """.format(t=_TABLE),
                (status, str(error_message), int(record_id)),
            )
        return True
    except Exception as exc:  # pragma: no cover
        _log(f"[image_gen_models] update_failed failed: {exc}")
        return False


def list_records(*, user_id: str, current: int = 1, size: int = 20,
                 status: Optional[str] = None) -> Dict[str, Any]:
    """按 user_id 分页查询。current/size 对齐前端约定（澜途风格）。"""
    ensure_table()
    engine = _get_engine()
    if engine is None:
        return {"total": 0, "current": int(current), "size": int(size), "records": []}
    current = max(1, int(current or 1))
    size = min(200, max(1, int(size or 20)))
    offset = (current - 1) * size

    try:
        with engine.connect() as conn:
            if status:
                cnt_row = conn.exec_driver_sql(
                    f"SELECT COUNT(*) FROM {_TABLE} WHERE user_id=? AND status=?",
                    (str(user_id), str(status)),
                ).fetchone()
                rows = conn.exec_driver_sql(
                    """
                    SELECT id, user_id, model_key, prompt, agent_id, aspect_ratio,
                           count, images_url, points_cost, freeze_tx_id, status,
                           error_message, idempotency_key, created_at
                    FROM {t}
                    WHERE user_id=? AND status=?
                    ORDER BY id DESC LIMIT ? OFFSET ?
                    """.format(t=_TABLE),
                    (str(user_id), str(status), size, offset),
                ).fetchall()
            else:
                cnt_row = conn.exec_driver_sql(
                    f"SELECT COUNT(*) FROM {_TABLE} WHERE user_id=?",
                    (str(user_id),),
                ).fetchone()
                rows = conn.exec_driver_sql(
                    """
                    SELECT id, user_id, model_key, prompt, agent_id, aspect_ratio,
                           count, images_url, points_cost, freeze_tx_id, status,
                           error_message, idempotency_key, created_at
                    FROM {t}
                    WHERE user_id=?
                    ORDER BY id DESC LIMIT ? OFFSET ?
                    """.format(t=_TABLE),
                    (str(user_id), size, offset),
                ).fetchall()

        total = int(cnt_row[0]) if cnt_row else 0
        records: List[Dict[str, Any]] = []
        for row in rows:
            rec = _row_to_dict(row)
            images_raw = rec.get("images_url")
            if images_raw:
                try:
                    rec["images"] = json.loads(images_raw)
                except Exception:
                    rec["images"] = []
            else:
                rec["images"] = []
            records.append(rec)
        return {"total": total, "current": current, "size": size, "records": records}
    except Exception as exc:  # pragma: no cover
        _log(f"[image_gen_models] list_records failed: {exc}")
        return {"total": 0, "current": current, "size": size, "records": []}


def get_by_idempotency(user_id: str, idempotency_key: str) -> Optional[Dict[str, Any]]:
    """按 (user_id, idempotency_key) 查最近的生成记录。用于幂等重复请求的兜底查询。"""
    if not idempotency_key:
        return None
    engine = _get_engine()
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            row = conn.exec_driver_sql(
                """
                SELECT id, user_id, model_key, prompt, agent_id, aspect_ratio,
                       count, images_url, points_cost, freeze_tx_id, status,
                       error_message, idempotency_key, created_at
                FROM {t}
                WHERE user_id=? AND idempotency_key=?
                ORDER BY id DESC LIMIT 1
                """.format(t=_TABLE),
                (str(user_id), str(idempotency_key)),
            ).fetchone()
        if row is None:
            return None
        rec = _row_to_dict(row)
        images_raw = rec.get("images_url")
        if images_raw:
            try:
                rec["images"] = json.loads(images_raw)
            except Exception:
                rec["images"] = []
        else:
            rec["images"] = []
        return rec
    except Exception:  # pragma: no cover
        return None


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def _row_id(result: Any) -> Optional[int]:
    try:
        lastrowid = getattr(result, "lastrowid", None)
        if lastrowid is not None:
            return int(lastrowid)
    except Exception:
        pass
    try:
        if hasattr(result, "inserted_primary_key"):
            return int(result.inserted_primary_key[0])
    except Exception:
        pass
    try:
        r = result.fetchone()
        return int(r[0]) if r else None
    except Exception:
        return None


_FIELDS = ("id", "user_id", "model_key", "prompt", "agent_id", "aspect_ratio",
           "count", "images_url", "points_cost", "freeze_tx_id", "status",
           "error_message", "idempotency_key", "created_at")


def _row_to_dict(row: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for i, f in enumerate(_FIELDS):
        if i < len(row):
            out[f] = row[i]
        else:
            out[f] = None
    return out


__all__ = [
    "ensure_table", "reset_ensured",
    "clear_all_records", "drop_table_for_test",
    "insert_record", "update_success", "update_failed", "update_freeze_tx_id",
    "list_records", "get_by_idempotency",
]
