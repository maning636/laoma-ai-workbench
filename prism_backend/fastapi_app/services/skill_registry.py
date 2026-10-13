"""
技能库注册中心（老马AI工作台 × Easel 融合）。

直接扫描 Easel 本地技能目录（skills/openclaw/*/SKILL.md，Anthropic Agent Skills
标准格式），提供目录/详情/刷新接口 —— 这是"实时更新 skills"商业接口的地基：
技能更新 = 磁盘重新扫描（Easel git pull 后无需重启老马AI工作台即可生效）。

数据不落库：以 mtime 缓存为主，磁盘即真相源（skills 目录是唯一事实源）。
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi_app.core.logger import logger
from fastapi_app.services.easel_workbench import EASEL_DIR

SKILLS_DIR = EASEL_DIR / "skills" / "openclaw"
SHARED_SCRIPTS_DIR = EASEL_DIR / "skills" / "shared" / "scripts"

# 分层中文名
LAYER_LABELS: Dict[str, str] = {
    "discover": "发现",
    "plan": "策划",
    "produce": "创作",
    "publish": "发布",
    "attribute": "归因",
    "general": "通用",
}

_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {"items": [], "built_at": 0.0, "source_mtime": 0.0}


def _skills_root_mtime() -> float:
    """技能根目录最近修改时间（含子目录一层，廉价判断是否有更新）。"""
    root = SKILLS_DIR
    if not root.is_dir():
        return 0.0
    latest = root.stat().st_mtime
    try:
        for child in root.iterdir():
            try:
                latest = max(latest, child.stat().st_mtime)
                skill_md = child / "SKILL.md"
                if skill_md.is_file():
                    latest = max(latest, skill_md.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return latest


def _parse_frontmatter(raw: str) -> Dict[str, str]:
    fm = re.match(r"(?s)^---\r?\n(.*?)\r?\n---", raw)
    if not fm:
        return {}
    text = fm.group(1)
    out: Dict[str, str] = {}
    for key in ("name", "description", "layer", "version", "author"):
        m = re.search(rf"(?m)^{key}:\s*(.+?)\s*$", text)
        if m:
            out[key] = m.group(1).strip().strip('"').strip("'")
    return out


def _count_scripts(dir_path: Path) -> int:
    count = 0
    for ext in ("*.py", "*.js", "*.mjs", "*.sh", "*.cjs"):
        count += sum(1 for _ in dir_path.rglob(ext))
    return count


def _scan_one(skill_dir: Path) -> Optional[Dict[str, Any]]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        raw = skill_md.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        logger.warning(f"[SkillRegistry] 读取失败 {skill_md}: {e}")
        return None
    fm = _parse_frontmatter(raw)
    n_scripts = _count_scripts(skill_dir)
    rel_files = []
    for p in sorted(skill_dir.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            rel_files.append(str(p.relative_to(skill_dir)))
    body = re.sub(r"(?s)^---\r?\n.*?\r?\n---\r?\n?", "", raw, count=1)
    return {
        "name": fm.get("name") or skill_dir.name,
        "dir": skill_dir.name,
        "description": fm.get("description", ""),
        "layer": fm.get("layer", "general"),
        "layer_label": LAYER_LABELS.get(fm.get("layer", ""), "通用"),
        "version": fm.get("version", ""),
        "author": fm.get("author", ""),
        "scripts": n_scripts,
        "files": len(rel_files),
        "mtime": int(skill_md.stat().st_mtime),
        "body": body,
    }


def _scan_all() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not SKILLS_DIR.is_dir():
        return items
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith((".", "_")):
            continue
        item = _scan_one(skill_dir)
        if item:
            items.append(item)
    items.sort(key=lambda x: x["name"])
    return items


def _get_catalog(force: bool = False) -> Dict[str, Any]:
    global _cache
    with _cache_lock:
        src_mtime = _skills_root_mtime()
        if force or not _cache["items"] or src_mtime > _cache["source_mtime"]:
            _cache["items"] = _scan_all()
            _cache["built_at"] = time.time()
            _cache["source_mtime"] = src_mtime
            logger.info(f"[SkillRegistry] 技能目录已刷新: {len(_cache['items'])} 个技能")
    return _cache


def list_skills(layer: Optional[str] = None, keyword: Optional[str] = None) -> Dict[str, Any]:
    """技能目录（不含正文 body，列表轻量化）。"""
    cat = _get_catalog()
    items = cat["items"]
    if layer:
        items = [i for i in items if i["layer"] == layer]
    if keyword:
        kw = keyword.lower()
        items = [
            i for i in items
            if kw in i["name"].lower() or kw in i["description"].lower()
        ]
    return {
        "total": len(items),
        "total_all": len(cat["items"]),
        "layers": {k: sum(1 for i in cat["items"] if i["layer"] == k) for k in LAYER_LABELS},
        "items": [{k: v for k, v in i.items() if k != "body"} for i in items],
        "updated_at": int(cat["built_at"]),
        "source_dir": str(SKILLS_DIR),
    }


def get_skill(name: str) -> Dict[str, Any]:
    cat = _get_catalog()
    for item in cat["items"]:
        if item["name"] == name or item["dir"] == name:
            return item
    raise LookupError(f"技能不存在: {name}")


def refresh_skills() -> Dict[str, Any]:
    """强制重扫磁盘（对外"实时更新 skills"接口的实现基础）。"""
    global _cache
    with _cache_lock:
        _cache = {"items": [], "built_at": 0.0, "source_mtime": 0.0}
    cat = _get_catalog(force=True)
    return {"total": len(cat["items"]), "built_at": int(cat["built_at"])}


def shared_scripts() -> List[Dict[str, Any]]:
    """Easel shared/scripts 的 47 个公共脚本工具（创作工坊执行层用）。"""
    out: List[Dict[str, Any]] = []
    if not SHARED_SCRIPTS_DIR.is_dir():
        return out
    for p in sorted(SHARED_SCRIPTS_DIR.glob("*.py")):
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")[:400]
        except OSError:
            head = ""
        m = re.search(r'(?m)"""(.{5,200}?)"""', head)
        out.append({
            "name": p.stem,
            "file": p.name,
            "size": p.stat().st_size,
            "doc": (m.group(1).strip() if m else ""),
        })
    return out
