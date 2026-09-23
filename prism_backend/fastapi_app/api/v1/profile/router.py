"""
账号画像 API（Prism 原生，简化版 Easel /api/profile/build）。

- POST /api/v1/content-library/profile/build   存基线（不做后台 AI 增强，秒可用）
- GET  /api/v1/content-library/profile          列出所有画像
- GET  /api/v1/content-library/profile/{name}   取单个画像

存储：{DATA_DIR}/profiles/{name}/profile.json
     含 {name, form, baseline, created_at, updated_at}
     baseline 是从 form 提炼的六维摘要（name/定位/受众/风格/目标平台/调性），仅确定性抽取，
     不调 AI——与 Easel 的后台 agent 增强不同，本端点只做基线，立即返回。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger

router = APIRouter(prefix="/content-library/profile", tags=["账号画像"])

_PROFILES_DIR = Path(settings.DATA_DIR) / "profiles"
# 名字安全规则（与前端提示一致）
_NAME_BAD_CHARS = re.compile(r"[/\\]")
_NAME_BAD_START = re.compile(r"^[\._-]")


def _profile_path(name: str) -> Path:
    return _PROFILES_DIR / name / "profile.json"


def _validate_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        raise HTTPException(status_code=400, detail="画像名称不能为空")
    if len(n) > 64:
        raise HTTPException(status_code=400, detail="画像名称过长（<= 64 字）")
    if _NAME_BAD_CHARS.search(n):
        raise HTTPException(status_code=400, detail="画像名称不能包含 / 或 \\")
    if _NAME_BAD_START.search(n):
        raise HTTPException(status_code=400, detail="画像名称不能以 . _ - 开头")
    if os.sep in n or os.altsep and os.altsep in n:
        raise HTTPException(status_code=400, detail="画像名称含非法路径字符")
    return n


def _list_names() -> List[str]:
    if not _PROFILES_DIR.is_dir():
        return []
    return sorted(
        p.name for p in _PROFILES_DIR.iterdir()
        if p.is_dir() and _profile_path(p.name).is_file()
    )


def _load(name: str) -> Optional[Dict[str, Any]]:
    p = _profile_path(name)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"[Profile] 读取 {p} 失败: {e}")
        return None


def _save(name: str, data: Dict[str, Any]) -> None:
    _profile_path(name).parent.mkdir(parents=True, exist_ok=True)
    _profile_path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _s(x: Any) -> str:
    return (str(x) if x is not None else "").strip()


def _lst(x: Any) -> List[str]:
    if isinstance(x, list):
        return [str(i).strip() for i in x if str(i).strip()]
    if isinstance(x, str) and x.strip():
        return [p.strip() for p in re.split(r"[,、/]", x) if p.strip()]
    return []


def _build_baseline(name: str, form: Dict[str, Any]) -> Dict[str, str]:
    """六维摘要：name / 定位 / 受众 / 风格 / 目标平台 / 调性。确定性抽取，不调 AI。"""
    platforms = _lst(form.get("platforms"))
    formats = _lst(form.get("formats"))
    links = form.get("links") or {}
    links = links if isinstance(links, dict) else {}

    direction = _s(form.get("direction")) or "（未填）"
    reason = _s(form.get("reason"))
    goal = _s(form.get("goal"))
    tone = _s(form.get("tone"))
    avoid = _s(form.get("avoid"))
    likes = _s(form.get("likes"))
    stage = _s(form.get("accountStage"))

    # 定位 = 方向 + 起号状态 + 优势（前 60 字）
    positioning_parts = [direction if direction != "（未填）" else ""]
    if stage:
        positioning_parts.append(f"当前{stage}")
    if reason:
        positioning_parts.append(reason[:40])
    positioning = " · ".join(p for p in positioning_parts if p) or "（未填）"

    # 受众 = 从 goal 里抽取粉量目标/受众描述（保守截取）
    audience = goal[:60] if goal else "（未填）"

    # 风格 = tone + formats
    style_parts = []
    if tone:
        style_parts.append(f"调性：{tone}")
    if formats:
        style_parts.append("形式：" + "、".join(formats))
    style = "；".join(style_parts) or "（未填）"

    # 目标平台 = platforms + 主链接计数
    platform_part = "、".join(platforms) if platforms else "（未填）"
    link_part = f"（已登记 {sum(1 for v in links.values() if str(v).strip())} 个主页）" if links else ""
    target_platform = platform_part + link_part

    # 调性 = tone + 红线/对标
    tone_parts = []
    if tone:
        tone_parts.append(tone)
    if avoid:
        tone_parts.append(f"红线：{avoid}")
    if likes:
        tone_parts.append(f"对标/兴趣：{likes[:40]}")
    tonality = "；".join(tone_parts) or "（未填）"

    return {
        "name": name,
        "定位": positioning,
        "受众": audience,
        "风格": style,
        "目标平台": target_platform,
        "调性": tonality,
    }


def _filled_dims(form: Dict[str, Any]) -> int:
    """12 维完整度（与前端进度条口径一致）。"""
    n = 0
    if _s(form.get("accountStage")): n += 1
    if _s(form.get("direction")): n += 1
    if _s(form.get("reason")): n += 1
    if _s(form.get("goal")): n += 1
    if _lst(form.get("platforms")): n += 1
    if _lst(form.get("formats")): n += 1
    if _s(form.get("likes")): n += 1
    if _s(form.get("tone")): n += 1
    if _s(form.get("avoid")): n += 1
    links = form.get("links") or {}
    if isinstance(links, dict):
        for v in links.values():
            if str(v or "").strip():
                n += 1
    return n


@router.post("/build")
async def build_profile(payload: Dict[str, Any] = Body(...)):
    """存基线画像。入参 {name, form}；form 是画像表单 12 维。不做后台 AI 增强。"""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")
    name = _validate_name(str(payload.get("name") or ""))
    form = payload.get("form") or {}
    if not isinstance(form, dict):
        raise HTTPException(status_code=400, detail="form 必须是 JSON 对象")
    if _list_names() and name in _list_names():
        raise HTTPException(status_code=409, detail=f"画像「{name}」已存在")

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    baseline = _build_baseline(name, form)
    record = {
        "name": name,
        "form": form,
        "baseline": baseline,
        "created_at": now_iso,
        "updated_at": now_iso,
        "filled_dims": _filled_dims(form),
        "total_dims": 12,
        "engine": "prism-native-baseline",  # 与 Easel 后台 agent 增强区分
    }
    try:
        _save(name, record)
    except Exception as e:
        logger.error(f"[Profile] 写入失败: {e}")
        raise HTTPException(status_code=500, detail=f"画像写入失败：{e}")

    return {
        "status": "success",
        "result": {
            "created": True,
            "name": name,
            "baseline": baseline,
            "filled_dims": record["filled_dims"],
            "total_dims": record["total_dims"],
            "path": str(_profile_path(name)),
        },
    }


@router.get("")
async def list_profiles():
    """列出所有画像（含六维摘要，供前端列表/详情使用）。"""
    items: List[Dict[str, Any]] = []
    for name in _list_names():
        rec = _load(name) or {}
        items.append({
            "name": name,
            "baseline": rec.get("baseline") or {},
            "created_at": rec.get("created_at"),
            "updated_at": rec.get("updated_at"),
            "filled_dims": rec.get("filled_dims"),
            "total_dims": rec.get("total_dims", 12),
        })
    return {"status": "success", "result": {"profiles": items, "count": len(items)}}


@router.get("/{name}")
async def get_profile(name: str):
    """取单个画像完整记录（含 form + baseline）。"""
    rec = _load(name)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"画像「{name}」不存在")
    return {"status": "success", "result": rec}
