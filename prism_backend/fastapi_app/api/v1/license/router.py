"""注册码(license)本地管理 API。

端点(前缀 `/api/v1/license`):
  - `GET    /status`           当前注册码状态 + 本地维度的 flag 档位
  - `POST   /activate`         输入/更换注册码(验签通过才落盘)
  - `POST   /sync-cloud`       把本地注册码同步到云端(开通订阅 + 注入积分额度)
  - `DELETE /`                 清除本地注册码
  - `GET    /effective-flags`  **双轨交集**后的最终 flag(注册码 ∩ 云端订阅)

设计:
  - 注册码是**本地**的,不依赖云端;云端只管订阅配额。
  - `/effective-flags` 会尽力拉云端 flag;拉不到就按 Community 兜底(离线可用)。
  - 所有响应都带 `readOnly`,前端据此禁用"新建"类操作(D4:能看不能新增)。
  - 线上支付已下线(2026-10-22):云端订阅改由**注册码**开通 —— `/sync-cloud`
    把本地注册码同步给云端,云端验签后开通订阅并注入注册码携带的积分额度。
    注册码原文只在本机与云端之间流转,不返回给前端。
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from fastapi_app.core.license import (
    STATUS_INVALID,
    LicenseState,
    clear_license,
    effective_flags,
    license_cap,
    load_license,
    load_license_token,
    save_license,
)
from fastapi_app.core.license_keys import FLAG_CAPACITY

router = APIRouter(tags=["注册码"])


class LicenseActivateRequest(BaseModel):
    """激活注册码请求体。"""

    code: str = Field(..., min_length=8, max_length=4096, description="注册码(PRISM1.…)")


def _license_flags(state: LicenseState) -> dict[str, Any]:
    """注册码**本地维度**的 flag 档位(不掺云端)。"""
    return {flag: license_cap(flag, state.entitlements) for flag in FLAG_CAPACITY}


def _extract_user_id(request: Request) -> str:
    """从 Authorization Bearer 里取 user_id(best-effort,不解 JWT 也能用)。

    取不到就用 "anonymous" —— billing_client 会回落 Community 默认 flag,
    语义上等价于"未登录即社区版"。
    """
    auth = (
        request.headers.get("authorization")
        or request.headers.get("Authorization")
        or ""
    )
    token = auth.replace("Bearer ", "").replace("bearer ", "").strip()
    if not token:
        return "anonymous"
    try:
        segment = token.split(".")[1]
        segment += "=" * (-len(segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment).decode("utf-8"))
        sub = payload.get("sub")
        if isinstance(sub, (str, int)) and str(sub).strip():
            return str(sub).strip()
    except (ValueError, KeyError, IndexError, binascii.Error, UnicodeDecodeError):
        pass
    return "anonymous"


def _cloud_flags(request: Request) -> dict[str, Any]:
    """尽力拉云端 feature flags;拉不到就空 dict(按 Community 兜底)。"""
    try:
        from fastapi_app.api import billing_client as _bc

        auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        token = auth.replace("Bearer ", "").replace("bearer ", "").strip()
        snapshot = _bc.get_feature_flags(_extract_user_id(request), token)
        flags = snapshot.get("flags") or {}
        return dict(flags) if isinstance(flags, dict) else {}
    except Exception:  # noqa: BLE001 - 云端不可达不该阻断本地判定
        return {}


@router.get("/status")
def license_status() -> dict[str, Any]:
    """当前注册码状态(纯本地,不联网)。"""
    state = load_license()
    return {
        "license": state.to_dict(),
        "licenseFlags": _license_flags(state),
        "readOnly": state.read_only,
    }


@router.post("/activate")
def license_activate(payload: LicenseActivateRequest) -> dict[str, Any]:
    """输入/更换注册码。验签不通过 → 400 且**不落盘**。"""
    state = save_license(payload.code)
    if not state.valid:
        raise HTTPException(status_code=400, detail=state.message or "注册码无效")
    return {
        "ok": True,
        "license": state.to_dict(),
        "licenseFlags": _license_flags(state),
        "readOnly": state.read_only,
    }


@router.delete("/")
def license_clear() -> dict[str, Any]:
    """清除本地注册码(回到社区版)。"""
    cleared = clear_license()
    state = load_license()
    return {
        "ok": True,
        "cleared": cleared,
        "license": state.to_dict(),
        "licenseFlags": _license_flags(state),
        "readOnly": state.read_only,
    }


@router.get("/effective-flags")
def license_effective_flags(request: Request) -> dict[str, Any]:
    """双轨交集后的最终 flag:注册码授权条目 ∩ 云端订阅配额。

    云端不可达时按 Community 兜底(离线也能跑)。
    """
    state = load_license()
    cloud = _cloud_flags(request)
    final = effective_flags(state, cloud)
    return {
        "flags": final,
        "license": state.to_dict(),
        "readOnly": state.read_only,
        "cloudAvailable": bool(cloud),
    }


@router.post("/sync-cloud")
def license_sync_cloud(request: Request) -> dict[str, Any]:
    """把本地注册码**同步到云端**:云端验签后开通订阅并注入积分额度。

    线下人工充值模式(线上支付已下线)下的关键一步 —— 没有它,云端不认识这份注册码,
    D1=C 双轨交集会把云端侧压回 community 档,用户就享受不到云端 AI / 云端生图。

    设计要点:
      - **注册码原文不出本机**:token 由后端从本地 `license.json` 读取,
        只在服务端内部转发给云端,不返回给前端、不写日志;
      - 需要带云端登录态(`Authorization: Bearer <cloud access token>`),
        否则云端认不出是哪个账户要开通;
      - 同步成功后会清掉本地缓存的 feature flags 快照,让新开通的能力立刻生效。

    失败:
      - 本地没有注册码 → 400
      - 云端不可达 / 云端拒绝 → 502(detail 是可直接展示的中文文案)
    """
    token = load_license_token()
    if not token:
        raise HTTPException(status_code=400, detail="尚未输入注册码,无法同步到云端")

    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    cloud_token = auth.replace("Bearer ", "").replace("bearer ", "").strip()

    try:
        from fastapi_app.api import billing_client as _bc

        client = _bc.get_default_client()
        result = client.activate_license(token, cloud_token)
    except RuntimeError as exc:
        # 云端明确拒绝(注册码无效 / 未登录 / 已过期等)——文案已由云端给出
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 网络异常统一转 502
        raise HTTPException(status_code=502, detail=f"云端不可达:{exc}") from exc

    # 订阅状态变了 → 缓存里的 flag 快照已过期,清掉让下一次读取拿到新值
    try:
        from fastapi_app.api import billing_client as _bc

        uid = _extract_user_id(request)
        if uid and uid != "anonymous":
            _bc.get_default_client().clear_cache(uid)
    except Exception:  # noqa: BLE001 - 清缓存失败不该让同步失败
        pass

    return {"ok": True, "result": result}


__all__ = ["router", "LicenseActivateRequest"]
