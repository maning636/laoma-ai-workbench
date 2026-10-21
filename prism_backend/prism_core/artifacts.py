"""
统一产物总线（Unified Artifact Bus）

解决的问题
----------
项目里原本有四套互不相通的 ID 空间：

  image_generations.id（AI 生图） / file_records.id（素材库）
  review_queue.review_id（审核队列） / publish_tasks.task_id（发布任务）

四套 ID 空间互不相通 → 「上一步的产出接不到下一步的调用」，
功能之间无法串联。本模块引入统一产物 ID `artifact_id`（art_ + 12 位十六进制），
让生图 / 上传 / 视频渲染 / 审核 / 发布共享同一条流水线。

数据模型
--------
主库 `artifacts` 表（DDL 真源在 fastapi_app/db/schema.py:ensure_artifacts_table）：

  artifact_id   TEXT PK     统一产物 ID（art_ + 12 hex）
  stage         TEXT        阶段：generated/uploaded/reviewing/approved/rejected/published
  kind          TEXT        image/video/audio/text/file/other
  title         TEXT        展示标题
  path          TEXT        本地路径或远程 URL（产出本体）
  thumb         TEXT        缩略图
  media_type    TEXT        mime / 后缀
  source        TEXT        来源域：image_gen / upload / video_pipeline / manual ...
  ref_type      TEXT        本域记录类型：image_generation / file_record / review / publish_task
  ref_id        TEXT        本域记录 ID
  parent_id     TEXT        血缘：父产物 artifact_id
  campaign_id   TEXT        所属营销活动
  platform      TEXT        目标平台
  review_id     TEXT        关联审核项 review_id
  publish_task_id TEXT      关联发布任务 task_id
  dedupe_key    TEXT UNIQUE 登记幂等键 = sha1(ref_type|ref_id|path)
  meta          TEXT        附加 JSON

阶段机
------
    generated ─┐
    uploaded  ─┴─→ reviewing ─→ approved ─→ published
                    └──────→ rejected ─→(重新送审)─→ reviewing

约定
----
- 登记幂等：同一 (ref_type, ref_id, path) 重复登记返回同一个 artifact_id；
  一次生图 count>1 会产生多张图共享同一 ref_id，靠 path 区分。
- 登记失败只记日志、不阻断主业务（调用方用 safe_register_* 包装）。
- 本模块只做 CRUD，不建表（DDL 真源在 schema.py）。
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso
from fastapi_app.db.session import open_main_db

# ──────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────

#: 统一产物 ID 前缀
ARTIFACT_ID_PREFIX = "art_"

#: 产物阶段
STAGE_GENERATED = "generated"   # AI 生成产出
STAGE_UPLOADED = "uploaded"     # 用户上传产出
STAGE_REVIEWING = "reviewing"   # 审核中
STAGE_APPROVED = "approved"     # 审核通过
STAGE_REJECTED = "rejected"     # 审核拒绝 / 被打回
STAGE_PUBLISHED = "published"   # 已发布

ALL_STAGES = (
    STAGE_GENERATED,
    STAGE_UPLOADED,
    STAGE_REVIEWING,
    STAGE_APPROVED,
    STAGE_REJECTED,
    STAGE_PUBLISHED,
)

#: 允许的阶段流转。key=当前阶段，value=允许迁入的阶段集合。
ALLOWED_TRANSITIONS: Dict[str, set] = {
    STAGE_GENERATED: {STAGE_REVIEWING, STAGE_REJECTED, STAGE_PUBLISHED},
    STAGE_UPLOADED: {STAGE_REVIEWING, STAGE_REJECTED, STAGE_PUBLISHED},
    STAGE_REVIEWING: {STAGE_APPROVED, STAGE_REJECTED, STAGE_REVIEWING},
    STAGE_APPROVED: {STAGE_PUBLISHED, STAGE_REVIEWING},
    STAGE_REJECTED: {STAGE_REVIEWING, STAGE_GENERATED, STAGE_UPLOADED},
    STAGE_PUBLISHED: set(),
}

#: 产物类型
KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_AUDIO = "audio"
KIND_TEXT = "text"
KIND_FILE = "file"
KIND_OTHER = "other"

#: 来源域（哪个功能产出的）
SOURCE_IMAGE_GEN = "image_gen"
SOURCE_UPLOAD = "upload"
SOURCE_VIDEO_PIPELINE = "video_pipeline"
SOURCE_MANUAL = "manual"
SOURCE_WORKSHOP = "workshop"


# ──────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────


def new_artifact_id() -> str:
    """生成统一产物 ID：art_ + 12 位十六进制。"""
    return f"{ARTIFACT_ID_PREFIX}{uuid.uuid4().hex[:12]}"


def is_artifact_id(value: Optional[str]) -> bool:
    """判断字符串是否像一个 artifact_id。"""
    if not value or not isinstance(value, str):
        return False
    if not value.startswith(ARTIFACT_ID_PREFIX):
        return False
    body = value[len(ARTIFACT_ID_PREFIX):]
    return len(body) == 12 and all(c in "0123456789abcdef" for c in body)


def _dedupe_key(ref_type: str, ref_id: str, path: str) -> str:
    """登记幂等键：sha1(ref_type|ref_id|path) 前 32 位。

    用 path 而不是只用 ref_id 是因为一次生图 count>1 会产生多张图
    共享同一个 image_generations.id。
    """
    raw = f"{ref_type or ''}|{ref_id or ''}|{path or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def _loads(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ensure_table(conn: sqlite3.Connection) -> None:
    """确保 artifacts 表存在（DDL 真源在 schema.py，这里只做兜底调用）。"""
    try:
        from fastapi_app.db.schema import ensure_artifacts_table

        ensure_artifacts_table(conn)
    except Exception as exc:  # pragma: no cover - 兜底，不应阻断业务
        logger.warning(f"[Artifacts] 确保 artifacts 表失败: {exc}")


def _row_to_dict(row: Any) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    if isinstance(row, dict):
        data = dict(row)
    else:
        try:
            data = {k: row[k] for k in row.keys()}
        except Exception:
            return None
    data["meta"] = _loads(data.get("meta"))
    return data


# ──────────────────────────────────────────────────────────────
# 登记
# ──────────────────────────────────────────────────────────────


def register_artifact(
    *,
    source: str,
    ref_type: str,
    ref_id: str,
    path: str = "",
    kind: str = KIND_OTHER,
    stage: str = STAGE_GENERATED,
    title: str = "",
    thumb: str = "",
    media_type: str = "",
    parent_id: Optional[str] = None,
    campaign_id: str = "",
    platform: str = "",
    review_id: str = "",
    publish_task_id: str = "",
    meta: Optional[Dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[str]:
    """登记一个产物，返回 artifact_id（幂等）。

    幂等键 = (ref_type, ref_id, path)。重复登记同一产出不会产生第二条记录，
    而是返回既有的 artifact_id。

    返回 None 表示登记失败（调用方应只记日志、不阻断主业务）。
    """
    if not ref_type:
        return None

    dedupe = _dedupe_key(ref_type, str(ref_id or ""), path or "")
    now = now_beijing_iso()
    try:
        c = conn or open_main_db()
        _ensure_table(c)

        # 已存在则直接返回（幂等）
        cur = c.execute(
            "SELECT artifact_id FROM artifacts WHERE dedupe_key = ?", (dedupe,)
        )
        row = cur.fetchone()
        if row:
            existing = row["artifact_id"] if not isinstance(row, (tuple, list)) else row[0]
            # 顺带补齐可能后写入的关联字段（不覆盖已有值）
            try:
                c.execute(
                    """UPDATE artifacts
                          SET review_id = COALESCE(NULLIF(review_id, ''), ?),
                              publish_task_id = COALESCE(NULLIF(publish_task_id, ''), ?),
                              campaign_id = COALESCE(NULLIF(campaign_id, ''), ?),
                              updated_at = ?
                        WHERE artifact_id = ?""",
                    (review_id or "", publish_task_id or "", campaign_id or "", now, existing),
                )
                c.commit()
            except Exception:
                pass
            return str(existing)

        artifact_id = new_artifact_id()
        c.execute(
            """INSERT INTO artifacts (
                artifact_id, stage, kind, title, path, thumb, media_type,
                source, ref_type, ref_id, parent_id, campaign_id, platform,
                review_id, publish_task_id, dedupe_key, meta,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact_id,
                stage if stage in ALL_STAGES else STAGE_GENERATED,
                kind or KIND_OTHER,
                title or "",
                path or "",
                thumb or "",
                media_type or "",
                source or "",
                ref_type,
                str(ref_id or ""),
                parent_id or None,
                campaign_id or "",
                platform or "",
                review_id or "",
                publish_task_id or "",
                dedupe,
                _dumps(meta or {}),
                now,
                now,
            ),
        )
        c.commit()
        logger.info(
            f"[Artifacts] 登记产物 {artifact_id} source={source} "
            f"ref={ref_type}/{ref_id} stage={stage}"
        )
        return artifact_id
    except Exception as exc:
        logger.warning(
            f"[Artifacts] 登记产物失败 source={source} ref={ref_type}/{ref_id}: {exc}"
        )
        return None


def safe_register_artifact(**kwargs) -> Optional[str]:
    """登记产物的「不阻断」包装：任何异常都吞掉，只返回 None。"""
    try:
        return register_artifact(**kwargs)
    except Exception as exc:  # pragma: no cover - 防御
        logger.warning(f"[Artifacts] safe_register_artifact 失败: {exc}")
        return None


def persist_data_url(data_url: str, subdir: str = "generated") -> tuple[str, str]:
    """把 `data:image/png;base64,...` 落盘，返回 (相对路径, media_type)。

    为什么需要：AI 生图的 provider 有的直接返回远程 URL，有的返回 data:base64。
    data:base64 有几 MB，**不能**塞进 artifacts.path（那会把 DB 撑爆，
    也不利于后续送审/发布复用）。落盘到 `VIDEO_FILES_DIR/<subdir>/` 后：
      - artifacts.path 存相对路径（如 "generated/ab12.png"）；
      - 前端/发布侧可用 `/getFile?filename=generated/ab12.png` 直接取。

    落盘失败返回 ("", "")，调用方按「远程 URL 保持原样」处理。
    """
    if not data_url or not data_url.startswith("data:"):
        return "", ""
    try:
        header, _, payload = data_url.partition(",")
        if not payload:
            return "", ""
        media_type = header[5:].split(";")[0] or "application/octet-stream"
        ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }.get(media_type.lower(), ".png")

        from fastapi_app.core.config import settings

        base = Path(settings.VIDEO_FILES_DIR) / subdir
        base.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex[:16]}{ext}"
        target = base / name

        if "base64" in header.lower():
            raw = base64.b64decode(payload)
        else:
            from urllib.parse import unquote_to_bytes

            raw = unquote_to_bytes(payload)
        target.write_bytes(raw)
        rel = f"{subdir}/{name}"
        return rel, media_type
    except Exception as exc:
        logger.warning(f"[Artifacts] data URL 落盘失败: {exc}")
        return "", ""


def register_artifact_batch(items: Iterable[Dict[str, Any]]) -> List[str]:
    """批量登记（同一事务），返回 artifact_id 列表（失败的项不占位）。"""
    result: List[str] = []
    conn = open_main_db()
    try:
        _ensure_table(conn)
        for item in items:
            payload = dict(item)
            payload.pop("conn", None)
            aid = register_artifact(conn=conn, **payload)
            if aid:
                result.append(aid)
        conn.commit()
    except Exception as exc:
        logger.warning(f"[Artifacts] 批量登记失败: {exc}")
    return result


# ──────────────────────────────────────────────────────────────
# 查询
# ──────────────────────────────────────────────────────────────


def get_artifact(artifact_id: str) -> Optional[Dict[str, Any]]:
    """按 artifact_id 取单个产物。"""
    if not artifact_id:
        return None
    try:
        conn = open_main_db()
        _ensure_table(conn)
        cur = conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        )
        row = cur.fetchone()
        cols = [d[0] for d in cur.description] if cur.description else []
        if row is None:
            return None
        data = dict(zip(cols, row)) if not isinstance(row, dict) else dict(row)
        data["meta"] = _loads(data.get("meta"))
        return data
    except Exception as exc:
        logger.warning(f"[Artifacts] 查询产物失败 {artifact_id}: {exc}")
        return None


def list_artifacts(
    *,
    stage: Optional[str] = None,
    source: Optional[str] = None,
    ref_type: Optional[str] = None,
    ref_id: Optional[str] = None,
    kind: Optional[str] = None,
    campaign_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """按条件列出产物（按创建时间倒序）。"""
    conds: List[str] = []
    params: List[Any] = []
    if stage:
        conds.append("stage = ?")
        params.append(stage)
    if source:
        conds.append("source = ?")
        params.append(source)
    if ref_type:
        conds.append("ref_type = ?")
        params.append(ref_type)
    if ref_id:
        conds.append("ref_id = ?")
        params.append(str(ref_id))
    if kind:
        conds.append("kind = ?")
        params.append(kind)
    if campaign_id:
        conds.append("campaign_id = ?")
        params.append(campaign_id)
    if parent_id:
        conds.append("parent_id = ?")
        params.append(parent_id)
    if keyword:
        conds.append("(title LIKE ? OR path LIKE ? OR ref_id LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like, like])

    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    sql = (
        f"SELECT * FROM artifacts{where} ORDER BY created_at DESC, rowid DESC "
        "LIMIT ? OFFSET ?"
    )
    params.extend([int(limit), int(offset)])
    try:
        conn = open_main_db()
        _ensure_table(conn)
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            data = dict(zip(cols, row)) if not isinstance(row, dict) else dict(row)
            data["meta"] = _loads(data.get("meta"))
            out.append(data)
        return out
    except Exception as exc:
        logger.warning(f"[Artifacts] 列出产物失败: {exc}")
        return []


def find_artifacts_by_ref(ref_type: str, ref_id: str) -> List[Dict[str, Any]]:
    """按本域记录反查产物（生图记录 → 产物列表等）。"""
    return list_artifacts(ref_type=ref_type, ref_id=str(ref_id), limit=200)


def find_artifact_by_review_id(review_id: str) -> Optional[Dict[str, Any]]:
    """按审核项 ID 反查产物（审核决策回写用）。"""
    if not review_id:
        return None
    try:
        conn = open_main_db()
        _ensure_table(conn)
        cur = conn.execute(
            "SELECT * FROM artifacts WHERE review_id = ? ORDER BY updated_at DESC",
            (review_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description] if cur.description else []
        data = dict(zip(cols, row)) if not isinstance(row, dict) else dict(row)
        data["meta"] = _loads(data.get("meta"))
        return data
    except Exception as exc:
        logger.warning(f"[Artifacts] 按 review_id 反查产物失败 {review_id}: {exc}")
        return None


def count_artifacts(**filters) -> int:
    """统计产物数量（支持与 list_artifacts 相同的过滤条件）。"""
    filters = dict(filters)
    filters.pop("limit", None)
    filters.pop("offset", None)
    conds: List[str] = []
    params: List[Any] = []
    for field, column in (
        ("stage", "stage"),
        ("source", "source"),
        ("ref_type", "ref_type"),
        ("ref_id", "ref_id"),
        ("kind", "kind"),
        ("campaign_id", "campaign_id"),
        ("parent_id", "parent_id"),
    ):
        value = filters.get(field)
        if value:
            conds.append(f"{column} = ?")
            params.append(str(value))
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    try:
        conn = open_main_db()
        _ensure_table(conn)
        cur = conn.execute(f"SELECT COUNT(*) AS cnt FROM artifacts{where}", params)
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as exc:
        logger.warning(f"[Artifacts] 统计产物失败: {exc}")
        return 0


def artifact_stats() -> Dict[str, Any]:
    """产物统计：按阶段 / 来源 / 类型分组。"""
    empty = {
        "total": 0,
        "by_stage": {s: 0 for s in ALL_STAGES},
        "by_source": {},
        "by_kind": {},
    }
    try:
        conn = open_main_db()
        _ensure_table(conn)
        stats = dict(empty)
        cur = conn.execute("SELECT COUNT(*) FROM artifacts")
        row = cur.fetchone()
        stats["total"] = int(row[0]) if row else 0

        for column, key in (("stage", "by_stage"), ("source", "by_source"), ("kind", "by_kind")):
            cur = conn.execute(
                f"SELECT {column}, COUNT(*) FROM artifacts GROUP BY {column}"
            )
            for r in cur.fetchall():
                name = r[0] or ""
                count = int(r[1] or 0)
                if key == "by_stage":
                    stats["by_stage"][name] = count
                else:
                    stats[key][name] = count
        return stats
    except Exception as exc:
        logger.warning(f"[Artifacts] 统计产物失败: {exc}")
        return empty


def lineage(artifact_id: str) -> Dict[str, Any]:
    """产物血缘：父链 + 子链。"""
    result: Dict[str, Any] = {
        "artifact_id": artifact_id,
        "parent": None,
        "ancestors": [],
        "children": [],
    }
    current = get_artifact(artifact_id)
    if not current:
        return result

    # 父链（向上）
    seen = {artifact_id}
    node = current
    while node and node.get("parent_id"):
        parent = get_artifact(str(node["parent_id"]))
        if not parent or parent["artifact_id"] in seen:
            break
        seen.add(parent["artifact_id"])
        result["ancestors"].append(parent)
        node = parent
    if result["ancestors"]:
        result["parent"] = result["ancestors"][0]

    # 子链（向下）
    result["children"] = list_artifacts(parent_id=artifact_id, limit=200)
    return result


# ──────────────────────────────────────────────────────────────
# 阶段推进
# ──────────────────────────────────────────────────────────────


def can_transition(current: str, target: str) -> bool:
    """判断阶段流转是否合法。"""
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, set())


def set_stage(
    artifact_id: str,
    stage: str,
    *,
    review_id: Optional[str] = None,
    publish_task_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    platform: Optional[str] = None,
    meta_update: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> bool:
    """推进产物阶段。返回是否成功。

    非法流转返回 False（不抛异常、不静默改写），
    除非 force=True（仅供内部补偿用）。
    """
    if stage not in ALL_STAGES:
        return False
    try:
        conn = open_main_db()
        _ensure_table(conn)
        cur = conn.execute(
            "SELECT stage, meta FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        )
        row = cur.fetchone()
        if row is None:
            return False
        current = row[0]
        if not force and not can_transition(str(current), stage):
            logger.warning(
                f"[Artifacts] 非法阶段流转 {artifact_id}: {current} → {stage}（已忽略）"
            )
            return False

        meta = _loads(row[1])
        if meta_update:
            meta.update(meta_update)

        sets = ["stage = ?", "meta = ?", "updated_at = ?"]
        params: List[Any] = [stage, _dumps(meta), now_beijing_iso()]
        if review_id:
            sets.append("review_id = ?")
            params.append(review_id)
        if publish_task_id:
            sets.append("publish_task_id = ?")
            params.append(publish_task_id)
        if campaign_id:
            sets.append("campaign_id = ?")
            params.append(campaign_id)
        if platform:
            sets.append("platform = ?")
            params.append(platform)
        params.append(artifact_id)
        conn.execute(
            f"UPDATE artifacts SET {', '.join(sets)} WHERE artifact_id = ?", params
        )
        conn.commit()
        logger.info(f"[Artifacts] 阶段推进 {artifact_id}: {current} → {stage}")
        return True
    except Exception as exc:
        logger.warning(f"[Artifacts] 阶段推进失败 {artifact_id} → {stage}: {exc}")
        return False


def update_artifact(artifact_id: str, **fields) -> bool:
    """更新产物字段（白名单）。"""
    allowed = {
        "title", "path", "thumb", "media_type", "kind", "campaign_id",
        "platform", "review_id", "publish_task_id", "parent_id", "meta",
    }
    sets: List[str] = []
    params: List[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = ?")
        params.append(_dumps(value) if key == "meta" else value)
    if not sets:
        return False
    sets.append("updated_at = ?")
    params.append(now_beijing_iso())
    params.append(artifact_id)
    try:
        conn = open_main_db()
        _ensure_table(conn)
        conn.execute(
            f"UPDATE artifacts SET {', '.join(sets)} WHERE artifact_id = ?", params
        )
        conn.commit()
        return True
    except Exception as exc:
        logger.warning(f"[Artifacts] 更新产物失败 {artifact_id}: {exc}")
        return False


def attach_review(artifact_id: str, review_id: str, stage: str = STAGE_REVIEWING) -> bool:
    """把产物挂到审核项上（送审）。"""
    return set_stage(artifact_id, stage, review_id=review_id, force=True)


def apply_review_decision(
    review_id: str,
    decision: str,
    *,
    task_id: str = "",
    reason: str = "",
) -> Optional[str]:
    """审核决策回写到产物阶段。

    - decision=approved → stage=approved
    - decision=rejected / needs_edit / auto_rejected → stage=rejected

    返回被更新的 artifact_id（没有对应产物时返回 None）。
    """
    artifact_id = task_id if is_artifact_id(task_id) else ""
    if not artifact_id:
        # 回退：按 review_id 找已登记该审核项的产物
        found = find_artifact_by_review_id(review_id)
        if found:
            artifact_id = str(found.get("artifact_id") or "")
    if not artifact_id:
        return None

    decision = (decision or "").lower()
    if decision in ("approved", "auto_approved"):
        target = STAGE_APPROVED
    elif decision in ("rejected", "auto_rejected", "needs_edit"):
        target = STAGE_REJECTED
    else:
        return None

    ok = set_stage(
        artifact_id,
        target,
        review_id=review_id,
        meta_update={"review_decision": decision, "review_reason": reason} if reason
        else {"review_decision": decision},
        force=True,
    )
    return artifact_id if ok else None


__all__ = [
    "ARTIFACT_ID_PREFIX",
    "ALL_STAGES",
    "ALLOWED_TRANSITIONS",
    "KIND_IMAGE",
    "KIND_VIDEO",
    "KIND_AUDIO",
    "KIND_TEXT",
    "KIND_FILE",
    "KIND_OTHER",
    "SOURCE_IMAGE_GEN",
    "SOURCE_UPLOAD",
    "SOURCE_VIDEO_PIPELINE",
    "SOURCE_MANUAL",
    "SOURCE_WORKSHOP",
    "STAGE_GENERATED",
    "STAGE_UPLOADED",
    "STAGE_REVIEWING",
    "STAGE_APPROVED",
    "STAGE_REJECTED",
    "STAGE_PUBLISHED",
    "new_artifact_id",
    "is_artifact_id",
    "persist_data_url",
    "register_artifact",
    "safe_register_artifact",
    "register_artifact_batch",
    "get_artifact",
    "list_artifacts",
    "find_artifacts_by_ref",
    "find_artifact_by_review_id",
    "count_artifacts",
    "artifact_stats",
    "lineage",
    "can_transition",
    "set_stage",
    "update_artifact",
    "attach_review",
    "apply_review_decision",
]
