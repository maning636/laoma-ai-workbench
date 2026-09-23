"""
Easel 稿件桥服务：把 Easel outputs/ 内容库桥接进 Prism 素材与发布链路。

职责:
- 读取 Easel Web API 的产物树（/api/outputs），筛选带 .easel.json 元数据的"稿件"项目
- 代理 Easel 媒体文件（/api/media/{path}）供前端预览
- 导入稿件: 下载 deliverables → 写入 Prism 素材库（files/upload-save 语义）→ 返回 material_ids
- 导入映射持久化到 db/easel_imports.json，避免重复导入

对 Easel 的依赖仅为 3 个 HTTP 端点（outputs / media），Easel 升级不影响桥。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from fastapi_app.services.easel_workbench import EASEL_DIR, EASEL_HOST, EASEL_PORT, _easel_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # fastapi_app/../.. = prism_backend
IMPORTS_FILE = BACKEND_ROOT / "db" / "easel_imports.json"

# 允许导入的成品扩展名（对齐 Prism 素材库能力：视频/图片/音频/文本）
IMPORTABLE_EXTS = {
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".mp3", ".wav", ".m4a", ".aac",
    ".md", ".txt",
}
MAX_IMPORT_FILE_MB = 160


def _easel_base_url() -> str:
    return _easel_url()


async def _fetch_outputs_tree(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    resp = await client.get(f"{_easel_base_url()}/api/outputs", timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _load_imports() -> Dict[str, Any]:
    if not IMPORTS_FILE.is_file():
        return {}
    try:
        return json.loads(IMPORTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[EaselBridge] 读取导入映射失败: {e}")
        return {}


def _save_imports(data: Dict[str, Any]) -> None:
    IMPORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    IMPORTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def list_drafts() -> Dict[str, Any]:
    """Easel 稿件列表: outputs/ 中带 .easel.json 元数据的项目目录。"""
    async with httpx.AsyncClient() as client:
        try:
            tree = await _fetch_outputs_tree(client)
        except httpx.HTTPError as e:
            raise RuntimeError(f"Easel Web API 不可达（{_easel_base_url()}）: {e}")

    drafts: List[Dict[str, Any]] = []
    for node in tree:
        meta = node.get("meta") or {}
        if not meta:
            continue
        deliverables = meta.get("deliverablePaths") or []
        importable = [
            p for p in deliverables
            if Path(p).suffix.lower() in IMPORTABLE_EXTS
        ]
        drafts.append({
            "project": node.get("name"),
            "path": node.get("path"),
            "title": meta.get("title") or node.get("name"),
            "summary": meta.get("summary") or "",
            "platform": meta.get("platform") or "",
            "kind": meta.get("kind") or "",
            "status": meta.get("status") or "",
            "tags": meta.get("tags") or [],
            "cover": meta.get("cover") or "",
            "deliverables": deliverables,
            "importable_deliverables": importable,
            "mtime": node.get("mtime", 0),
            "imported": node.get("name") in _load_imports(),
        })
    drafts.sort(key=lambda d: d.get("mtime", 0), reverse=True)
    return {"drafts": drafts, "total": len(drafts)}


async def get_draft_detail(project: str) -> Dict[str, Any]:
    """单个稿件详情（含每个 deliverable 的代理预览 URL）。"""
    async with httpx.AsyncClient() as client:
        try:
            tree = await _fetch_outputs_tree(client)
        except httpx.HTTPError as e:
            raise RuntimeError(f"Easel Web API 不可达: {e}")

    for node in tree:
        if node.get("name") != project:
            continue
        meta = node.get("meta") or {}
        deliverables = meta.get("deliverablePaths") or []
        detail_items = []
        for p in deliverables:
            ext = Path(p).suffix.lower()
            detail_items.append({
                "path": p,
                "name": Path(p).name,
                "media_url": f"/api/v1/easel/media/{p}",
                "importable": ext in IMPORTABLE_EXTS,
            })
        imports = _load_imports().get(project, {})
        return {
            "project": project,
            "meta": meta,
            "items": detail_items,
            "imported": imports or None,
        }
    raise LookupError(f"Easel 稿件不存在: {project}")


async def get_media_stream(path: str):
    """流式代理 Easel 媒体文件。返回 (status, headers, byte_iterator)。"""
    if path.startswith("/") or ".." in path:
        raise LookupError("非法路径")
    url = f"{_easel_base_url()}/api/media/{path}"
    client = httpx.AsyncClient(timeout=None)
    try:
        req = client.build_request("GET", url)
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        raise RuntimeError(f"获取 Easel 媒体失败: {e}")

    headers = {}
    if resp.headers.get("content-type"):
        headers["content-type"] = resp.headers["content-type"]
    if resp.headers.get("content-length"):
        headers["content-length"] = resp.headers["content-length"]

    async def iterator():
        try:
            async for chunk in resp.aiter_bytes(64 * 1024):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return resp.status_code, headers, iterator()


async def import_draft(
    project: str,
    upload_file_func,
    platform_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    导入稿件 deliverables 到 Prism 素材库。

    upload_file_func: 异步回调 (filename: str, content: bytes, display_name: str,
                      group: str, note: str) -> dict  （files service 的 upload-save 封装，
                      返回含 file_id 的 data 字典）

    platform_map: Easel platform 名 → Prism 平台码映射（可覆盖默认）
    """
    detail = await get_draft_detail(project)
    meta = detail.get("meta") or {}
    deliverables = [i for i in detail.get("items", []) if i.get("importable")]
    if not deliverables:
        raise ValueError(f"稿件 {project} 没有可导入的成品文件")

    imports = _load_imports()
    if project in imports:
        existing = imports[project]
        return {
            "already_imported": True,
            "project": project,
            "material_ids": existing.get("material_ids", []),
            "imported_at": existing.get("imported_at"),
        }

    client = httpx.AsyncClient(timeout=None)
    material_ids: List[int] = []
    imported_files: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    try:
        for item in deliverables:
            rel = item["path"]
            resp = await client.get(f"{_easel_base_url()}/api/media/{rel}")
            if resp.status_code != 200:
                skipped.append({"path": rel, "reason": f"HTTP {resp.status_code}"})
                continue
            content = resp.content
            size_mb = len(content) / (1024 * 1024)
            if size_mb > MAX_IMPORT_FILE_MB:
                skipped.append({"path": rel, "reason": f"文件 {size_mb:.0f}MB 超过 {MAX_IMPORT_FILE_MB}MB 上限"})
                continue
            display_name = f"[easel:{project}] {item['name']}"
            note = json.dumps(
                {"easel_project": project, "easel_path": rel, "title": meta.get("title", "")},
                ensure_ascii=False,
            )
            result = await upload_file_func(
                filename=item["name"],
                content=content,
                display_name=display_name,
                group=f"easel:{project}",
                note=note,
            )
            file_id = result.get("file_id") or result.get("id")
            if file_id is not None:
                material_ids.append(int(file_id))
                imported_files.append({"path": rel, "file_id": int(file_id)})
            else:
                skipped.append({"path": rel, "reason": "上传成功但未返回 file_id"})
    finally:
        await client.aclose()

    record = {
        "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "title": meta.get("title", ""),
        "platform": meta.get("platform", ""),
        "material_ids": material_ids,
        "files": imported_files,
        "skipped": skipped,
    }
    imports[project] = record
    _save_imports(imports)

    suggested_platforms = [meta.get("platform")] if meta.get("platform") else []
    if platform_map:
        suggested_platforms = [platform_map.get(p, p) for p in suggested_platforms]

    return {
        "already_imported": False,
        "project": project,
        "material_ids": material_ids,
        "files": imported_files,
        "skipped": skipped,
        "suggested_platforms": suggested_platforms,
        "campaign_prefill": {
            "name": meta.get("title") or project,
            "remark": meta.get("summary") or "",
            "material_ids": material_ids,
        },
    }
