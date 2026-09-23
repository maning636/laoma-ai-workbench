"""
Easel outputs 原生直读服务 —— 磁盘即真相源，不经 Easel 服务器。

直接扫描 Easel 的 outputs 目录（.easel.json 元数据 + 文件树），
为 Prism 原生「内容库」「工作台」提供数据。Easel 退役后此模块继续工作
（outputs 目录约定保留，或迁到 Prism 自己的数据目录——路径可通过环境变量改）。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi_app.core.logger import logger
from fastapi_app.services.easel_workbench import EASEL_DIR

OUTPUTS_DIR = Path(os.getenv("PRISM_OUTPUTS_DIR") or (EASEL_DIR / "outputs"))
PROJECT_MANIFEST = ".easel.json"

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
TEXT_EXTS = {".md", ".txt", ".markdown", ".json", ".csv", ".srt", ".vtt", ".html", ".pdf"}

SYSTEM_PREFIXES = ("_", ".")


def _file_kind(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in TEXT_EXTS:
        return "text"
    return "binary"


def _file_meta(f: Path, rel: str) -> Dict[str, Any]:
    try:
        st = f.stat()
        mtime, size = int(st.st_mtime), st.st_size
    except OSError:
        mtime, size = 0, 0
    return {"name": f.name, "path": rel, "kind": _file_kind(f.name), "mtime": mtime, "size": size}


def _build_node(path: Path, rel: str) -> Dict[str, Any]:
    if path.is_dir():
        children = []
        for c in sorted(path.iterdir()):
            if c.name.startswith("."):
                continue
            children.append(_build_node(c, f"{rel}/{c.name}"))
        mtime = max((x["mtime"] for x in children), default=int(path.stat().st_mtime))
        file_count = sum(x.get("fileCount", 1) if x["type"] == "dir" else 1 for x in children)
        return {"name": path.name, "type": "dir", "path": rel, "mtime": mtime, "children": children, "fileCount": file_count}
    m = _file_meta(path, rel)
    m["type"] = "file"
    return m


def _read_project_meta(proj: Path) -> Dict[str, Any]:
    mf = proj / PROJECT_MANIFEST
    if not mf.is_file():
        return {}
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return {}
    meta = {k: data.get(k) for k in ("title", "summary", "platform", "kind", "status", "tags", "deliverables") if data.get(k) not in (None, "", [])}
    if not meta:
        return {}

    def _rel_if_exists(name: str) -> str:
        return f"{proj.name}/{name}" if name and (proj / name).is_file() else ""

    cover_rel = ""
    declared = data.get("cover")
    if declared and (proj / declared).is_file():
        cover_rel = f"{proj.name}/{declared}"
    if not cover_rel:
        for d in data.get("deliverables") or []:
            if _file_kind(d) in ("image", "video") and (proj / d).is_file():
                cover_rel = f"{proj.name}/{d}"
                break
    if cover_rel:
        meta["cover"] = cover_rel
    meta["deliverablePaths"] = [f"{proj.name}/{d}" for d in (data.get("deliverables") or []) if (proj / d).is_file()]
    return meta


def _scan_all() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not OUTPUTS_DIR.is_dir():
        return items
    for entry in sorted(OUTPUTS_DIR.iterdir()):
        if entry.name.startswith((".", "_")) or not entry.is_dir():
            continue
        node = _build_node(entry, entry.name)
        meta = _read_project_meta(entry)
        if meta:
            node["meta"] = meta
        items.append(node)
    items.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    return items


def list_outputs() -> Dict[str, Any]:
    return {
        "total": len(_scan_all()),
        "total_files": sum(i.get("fileCount", 0) for i in _scan_all()),
        "items": _scan_all(),
        "source_dir": str(OUTPUTS_DIR),
    }


def _safe_output_path(rel: str) -> Path:
    full = (OUTPUTS_DIR / rel).resolve()
    root = OUTPUTS_DIR.resolve()
    if root != full and root not in full.parents:
        raise PermissionError("非法路径")
    if not full.is_file():
        raise FileNotFoundError("文件不存在")
    return full


def read_output_text(rel: str) -> str:
    """读取文本类产物内容。"""
    full = _safe_output_path(rel)
    if _file_kind(full.name) not in ("text", "binary"):
        return ""
    return full.read_text(encoding="utf-8", errors="ignore")


def open_output(rel: str) -> Path:
    return _safe_output_path(rel)


# ---------- ideas（选题库） / schedule（排期） / accounts（登录态） ----------

def _read_json_file(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[Outputs] 读取 {path.name} 失败: {e}")
        return default


def get_ideas() -> List[Dict[str, Any]]:
    return _read_json_file(OUTPUTS_DIR / "_ideas.json", [])


def save_ideas(ideas: List[Dict[str, Any]]) -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "_ideas.json").write_text(json.dumps(ideas, ensure_ascii=False, indent=2), encoding="utf-8")


def get_schedule() -> List[Dict[str, Any]]:
    return _read_json_file(OUTPUTS_DIR / "_schedule.json", [])


def save_schedule(schedule: List[Dict[str, Any]]) -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "_schedule.json").write_text(json.dumps(schedule, ensure_ascii=False, indent=2), encoding="utf-8")


def get_login_status() -> Dict[str, Any]:
    """各平台登录态（outputs/_login/<platform>.json）。"""
    login_dir = OUTPUTS_DIR / "_login"
    states: Dict[str, Any] = {}
    if login_dir.is_dir():
        for f in sorted(login_dir.glob("*.json")):
            try:
                states[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
    return states


# ---------- 简单缓存 ----------

_cache_lock = __import__("threading").Lock()
_cache: Dict[str, Any] = {"items": [], "built_at": 0.0, "root_mtime": 0.0}


def _root_mtime() -> float:
    if not OUTPUTS_DIR.is_dir():
        return 0.0
    latest = OUTPUTS_DIR.stat().st_mtime
    try:
        for child in OUTPUTS_DIR.iterdir():
            try:
                latest = max(latest, child.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return latest


def get_outputs_cached() -> Dict[str, Any]:
    global _cache
    with _cache_lock:
        rm = _root_mtime()
        if not _cache["items"] or rm > _cache["root_mtime"]:
            items = _scan_all()
            _cache = {
                "items": items,
                "built_at": time.time(),
                "root_mtime": rm,
                "total": len(items),
                "total_files": sum(i.get("fileCount", 0) for i in items),
            }
    return _cache


def list_outputs_cached() -> Dict[str, Any]:
    c = get_outputs_cached()
    return {k: c[k] for k in ("total", "total_files", "items")} | {"source_dir": str(OUTPUTS_DIR)}
