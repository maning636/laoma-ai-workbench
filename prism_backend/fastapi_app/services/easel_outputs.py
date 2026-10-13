"""
Easel outputs 原生直读服务 —— 磁盘即真相源，不经 Easel 服务器。

直接扫描 Easel 的 outputs 目录（.easel.json 元数据 + 文件树），
为老马AI工作台原生「内容库」「工作台」提供数据。Easel 退役后此模块继续工作
（outputs 目录约定保留，或迁到 老马AI工作台 自己的数据目录——路径可通过环境变量改）。
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi_app.core.logger import logger
from fastapi_app.services.easel_workbench import EASEL_DIR

# 参照 Easel v0.2.1 tools/easel-ref/app.py:320, 502-506 的占位符判定规则：
# 常见占位符（replace_me / your-api-key / xxx / ... / <...>）视为"未配置"，
# 避免 .env.example 抄过来直接生效导致路径/密钥误配。
_PLACEHOLDER_RE = re.compile(r"replace_me|your[-_]?api[-_]?key|xxx|^\.{3}$|^<.*>$", re.I)


def is_configured(val: Optional[str]) -> bool:
    """非空且非占位符才算真正配置了。参照 Easel _is_set。"""
    if val is None or not str(val).strip():
        return False
    return not _PLACEHOLDER_RE.search(str(val).strip())


def _env(path_key: str, fallback: Path) -> Path:
    """读取路径型环境变量；占位符视为未配置，回落到 fallback。"""
    raw = os.getenv(path_key)
    if is_configured(raw):
        return Path(raw).expanduser().resolve()
    return fallback


OUTPUTS_DIR = _env("LAOMA_OUTPUTS_DIR", EASEL_DIR / "outputs")
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


# ---------- HTML 预览（含 base64 内联本地图，防止公众号回源抓本地地址导致裂图） ----------

_IMAGE_EXTS_SET = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico"}
_AUDIO_EXTS_SET = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
_VIDEO_EXTS_SET = {".mp4", ".mov", ".webm", ".m4v"}

_MIME_BY_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".bmp": "image/bmp",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".aac": "audio/aac", ".flac": "audio/flac", ".ogg": "audio/ogg",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".m4v": "video/mp4",
}

_MEDIA_RE = re.compile(
    r"""(?ix)
    (?:src|href|poster)\s*=\s*
    (?:["'])(?P<q1>[^"']+)(?:["'])
    |
    (?:src|href|poster)\s*=\s*
    (?P<q2>[A-Za-z0-9_./\-:%?&=~+,]+)
    """
)


def _encode_data_uri(local: Path, url: str) -> Optional[str]:
    """把 outputs/ 内的本地资源转成 data: URI；跨出 outputs/ 或太大/未知类型返回 None。"""
    # 只处理同根下的相对路径引用；外链一律保留
    if url.startswith(("http://", "https://", "data:", "blob:", "#", "//")):
        return None
    # 去掉 query/fragment
    url_path = url.split("?", 1)[0].split("#", 1)[0]
    if not url_path:
        return None
    # 允许 ./../ 写法；但必须仍落在 OUTPUTS_DIR 内
    candidate = (OUTPUTS_DIR / url_path).resolve()
    root = OUTPUTS_DIR.resolve()
    if candidate != root and root not in candidate.parents:
        return None
    if not candidate.is_file():
        return None
    ext = candidate.suffix.lower()
    mime = _MIME_BY_EXT.get(ext)
    if not mime:
        return None
    size = candidate.stat().st_size
    if size > 32 * 1024 * 1024:  # 32MB 上限，防止 HTML 体积爆炸
        return None
    try:
        b64 = base64.b64encode(candidate.read_bytes()).decode("ascii")
    except OSError:
        return None
    return f"data:{mime};base64,{b64}"


def preview_html(rel: str) -> Dict[str, Any]:
    """对 outputs/ 下 HTML 产物做本地图 base64 内联，返回渲染后的 HTML。

    - 同目录或 outputs/ 内的相对图片/音视频/HTML 引用 → 转成 data: URI
    - http(s)/data:/blob:/协议相对等外链 → 保留
    - 超出 32MB / 非白名单 MIME → 保留原样（避免体积失控）
    """
    full = _safe_output_path(rel)
    ext = full.suffix.lower()
    if ext not in (".html", ".htm"):
        raise FileNotFoundError("只支持 .html / .htm 预览")
    raw = full.read_text(encoding="utf-8", errors="ignore")

    inline_count = 0
    kept_remote: List[str] = []

    def _sub(m: "re.Match") -> str:
        nonlocal inline_count
        attr = m.group(0)
        if m.group("q1") is not None:
            quote = '"' if '"' in attr else "'"
            start, end = m.start("q1"), m.end("q1")
            url = m.group("q1")
        else:
            quote = ""
            start, end = m.start("q2"), m.end("q2")
            url = m.group("q2") or ""
        data = _encode_data_uri(full.parent, url)
        if data:
            inline_count += 1
            return attr[:start] + data + attr[end:]
        kept_remote.append(url)
        return attr

    html = _MEDIA_RE.sub(_sub, raw)
    return {
        "path": rel,
        "html": html,
        "inline_count": inline_count,
        "kept_remote": kept_remote[:50],  # 只返回前 50 条，防止响应过大
    }


def list_outputs_cached() -> Dict[str, Any]:
    c = get_outputs_cached()
    return {k: c[k] for k in ("total", "total_files", "items")} | {"source_dir": str(OUTPUTS_DIR)}
