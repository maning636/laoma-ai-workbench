"""模型供应商注册表 API —— CRUD / 测试连接 / 拉模型 / 应用到通道。

端点前缀：/api/v1/ai/providers  （由本模块的 prefix="/ai/providers" 提供）

设计要点：
- 数据表：model_providers（sa_models.py 中的 model_providers 定义，schema.py 建表）
- 存储风格：沿用 ai/router.py 的双写模式（mysql_enabled → sa_connection；否则 sqlite3）
- API Key 存储与 ai_model_configs 保持一致（明文 Text），输出时统一打码 sk-****尾4位
- 通用拉模型函数 fetch_models_from_url 从 ccswitch_bridge 复用
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fastapi_app.core.config import settings
from fastapi_app.db.runtime import mysql_enabled, sa_connection
from sqlalchemy import text


router = APIRouter(prefix="/ai/providers", tags=["AI 模型供应商注册表"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, description="供应商名称（唯一）")
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    enabled: bool = True
    remark: Optional[str] = None


class ProviderUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    enabled: Optional[bool] = None
    remark: Optional[str] = None


class ApplyToRequest(BaseModel):
    model_name: str = Field(default="", description="要应用到通道的模型名（非空）")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _mask_key(api_key: Optional[str]) -> Optional[str]:
    """api_key 输出打码：sk-****尾4位。空值 / 空串保持原样。"""
    if not api_key:
        return api_key
    s = str(api_key)
    if len(s) <= 4:
        return "sk-****" + s[-len(s):] if s else "sk-****"
    return "sk-****" + s[-4:]


def _row_to_provider(row: Dict[str, Any]) -> Dict[str, Any]:
    """把数据库行转成输出 dict：enabled int→bool，api_key 打码，available_models JSON→list。"""
    out = dict(row)
    if "enabled" in out:
        out["enabled"] = bool(int(out.get("enabled") or 0))
    if "api_key" in out:
        out["api_key"] = _mask_key(out.get("api_key"))
    if out.get("available_models"):
        try:
            parsed = json.loads(out["available_models"])
            out["available_models"] = parsed if isinstance(parsed, list) else None
        except Exception:
            out["available_models"] = None
    else:
        out["available_models"] = None
    return out


# ---------------------------------------------------------------------------
# DB helpers（沿用 ai/router.py 双写风格）
# ---------------------------------------------------------------------------

def _db_query(sql_sa: str, params: Dict[str, Any], sql_sq: str, params_sq: tuple) -> List[Dict[str, Any]]:
    if mysql_enabled():
        with sa_connection() as conn:
            rows = conn.execute(text(sql_sa), params).mappings().all()
            return [dict(r) for r in rows]
    import sqlite3
    conn = sqlite3.connect(settings.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql_sq, params_sq)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _db_query_one(sql_sa: str, params: Dict[str, Any], sql_sq: str, params_sq: tuple) -> Optional[Dict[str, Any]]:
    rows = _db_query(sql_sa, params, sql_sq, params_sq)
    return rows[0] if rows else None


def _db_exec(sql_sa: str, params: Dict[str, Any], sql_sq: str, params_sq: tuple) -> int:
    """执行写操作，返回受影响行数。"""
    if mysql_enabled():
        with sa_connection() as conn:
            res = conn.execute(text(sql_sa), params)
            return getattr(res, "rowcount", 0) or 0
    import sqlite3
    conn = sqlite3.connect(settings.DATABASE_PATH)
    cur = conn.cursor()
    cur.execute(sql_sq, params_sq)
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected


def _db_exec_ins(sql_sa: str, params: Dict[str, Any], sql_sq: str, params_sq: tuple) -> int:
    """执行写操作并返回最后插入 id。"""
    if mysql_enabled():
        with sa_connection() as conn:
            res = conn.execute(text(sql_sa), params)
            last_id = getattr(res, "lastrowid", None)
            return int(last_id) if last_id is not None else 0
    import sqlite3
    conn = sqlite3.connect(settings.DATABASE_PATH)
    cur = conn.cursor()
    cur.execute(sql_sq, params_sq)
    last_id = cur.lastrowid or 0
    conn.commit()
    conn.close()
    return last_id


# ---------------------------------------------------------------------------
# CRUD 端点
# ---------------------------------------------------------------------------

@router.get("", summary="列出所有模型供应商")
async def list_providers():
    try:
        rows = _db_query(
            sql_sa="SELECT * FROM model_providers ORDER BY id",
            params={},
            sql_sq="SELECT * FROM model_providers ORDER BY id",
            params_sq=(),
        )
        return {"status": "success", "data": [_row_to_provider(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取供应商列表失败: {str(e)}")


@router.post("", summary="新建模型供应商")
async def create_provider(req: ProviderCreate):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    try:
        existing = _db_query_one(
            sql_sa="SELECT id FROM model_providers WHERE name = :n",
            params={"n": name},
            sql_sq="SELECT id FROM model_providers WHERE name = ?",
            params_sq=(name,),
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"供应商名称「{name}」已存在")

        row_id = _db_exec_ins(
            sql_sa=(
                "INSERT INTO model_providers (name, base_url, api_key, enabled, remark) "
                "VALUES (:name, :base_url, :api_key, :enabled, :remark)"
            ),
            params={
                "name": name,
                "base_url": req.base_url,
                "api_key": req.api_key,
                "enabled": 1 if req.enabled else 0,
                "remark": req.remark,
            },
            sql_sq=(
                "INSERT INTO model_providers (name, base_url, api_key, enabled, remark) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            params_sq=(name, req.base_url, req.api_key, 1 if req.enabled else 0, req.remark),
        )
        row = _db_query_one(
            sql_sa="SELECT * FROM model_providers WHERE id = :i",
            params={"i": row_id},
            sql_sq="SELECT * FROM model_providers WHERE id = ?",
            params_sq=(row_id,),
        )
        return {"status": "success", "data": _row_to_provider(row)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建供应商失败: {str(e)}")


@router.put("/{provider_id}", summary="更新模型供应商")
async def update_provider(provider_id: int, req: ProviderUpdate):
    # 先取原记录
    orig = _db_query_one(
        sql_sa="SELECT * FROM model_providers WHERE id = :i",
        params={"i": provider_id},
        sql_sq="SELECT * FROM model_providers WHERE id = ?",
        params_sq=(provider_id,),
    )
    if not orig:
        raise HTTPException(status_code=404, detail="供应商不存在")

    # 用请求字段覆盖（None 表示未提供，保留原值）
    new_name = req.name if req.name is not None else orig.get("name")
    new_base_url = req.base_url if req.base_url is not None else orig.get("base_url")
    new_api_key = req.api_key if req.api_key is not None else orig.get("api_key")
    new_enabled = req.enabled if req.enabled is not None else bool(int(orig.get("enabled") or 0))
    new_remark = req.remark if req.remark is not None else orig.get("remark")

    if new_name and new_name != orig.get("name"):
        dup = _db_query_one(
            sql_sa="SELECT id FROM model_providers WHERE name = :n AND id != :i",
            params={"n": new_name, "i": provider_id},
            sql_sq="SELECT id FROM model_providers WHERE name = ? AND id != ?",
            params_sq=(new_name, provider_id),
        )
        if dup:
            raise HTTPException(status_code=409, detail=f"供应商名称「{new_name}」已存在")

    try:
        affected = _db_exec(
            sql_sa=(
                "UPDATE model_providers "
                "SET name=:name, base_url=:base_url, api_key=:api_key, enabled=:enabled, "
                "remark=:remark, updated_at=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            params={
                "id": provider_id,
                "name": new_name,
                "base_url": new_base_url,
                "api_key": new_api_key,
                "enabled": 1 if new_enabled else 0,
                "remark": new_remark,
            },
            sql_sq=(
                "UPDATE model_providers "
                "SET name=?, base_url=?, api_key=?, enabled=?, remark=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?"
            ),
            params_sq=(new_name, new_base_url, new_api_key, 1 if new_enabled else 0, new_remark, provider_id),
        )
        if affected == 0:
            raise HTTPException(status_code=404, detail="供应商不存在")
        row = _db_query_one(
            sql_sa="SELECT * FROM model_providers WHERE id = :i",
            params={"i": provider_id},
            sql_sq="SELECT * FROM model_providers WHERE id = ?",
            params_sq=(provider_id,),
        )
        return {"status": "success", "data": _row_to_provider(row)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新供应商失败: {str(e)}")


@router.delete("/{provider_id}", summary="删除模型供应商")
async def delete_provider(provider_id: int):
    row = _db_query_one(
        sql_sa="SELECT * FROM model_providers WHERE id = :i",
        params={"i": provider_id},
        sql_sq="SELECT * FROM model_providers WHERE id = ?",
        params_sq=(provider_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="供应商不存在")

    # 检查是否被 ai_model_configs 引用（三元组匹配）
    refs = _find_references(row)
    if refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"供应商「{row['name']}」正被以下通道引用，请先解绑或删除对应配置",
                "references": refs,
            },
        )

    affected = _db_exec(
        sql_sa="DELETE FROM model_providers WHERE id = :i",
        params={"i": provider_id},
        sql_sq="DELETE FROM model_providers WHERE id = ?",
        params_sq=(provider_id,),
    )
    return {"status": "success", "message": "供应商已删除", "affected": affected}


def _find_references(provider_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """找出 ai_model_configs 中引用该供应商的通道（name+base_url+api_key 三者全匹配）。"""
    name = provider_row.get("name") or ""
    base_url = provider_row.get("base_url") or ""
    api_key = provider_row.get("api_key") or ""
    rows = _db_query(
        sql_sa=(
            "SELECT service_type, id, provider, base_url, api_key, model_name "
            "FROM ai_model_configs WHERE provider = :n"
        ),
        params={"n": name},
        sql_sq=(
            "SELECT service_type, id, provider, base_url, api_key, model_name "
            "FROM ai_model_configs WHERE provider = ?"
        ),
        params_sq=(name,),
    )
    refs = []
    for r in rows:
        r_base = (r.get("base_url") or "") or ""
        r_key = (r.get("api_key") or "") or ""
        if r_base == base_url and r_key == api_key:
            refs.append({
                "config_id": r.get("id"),
                "service_type": r.get("service_type"),
                "provider": r.get("provider"),
                "base_url": r.get("base_url"),
                "model_name": r.get("model_name"),
            })
    return refs


# ---------------------------------------------------------------------------
# 测试连接 / 拉模型 / 应用到通道
# ---------------------------------------------------------------------------

@router.post("/{provider_id}/test-connection", summary="测试供应商连接")
async def test_provider_connection(provider_id: int):
    """复用 ccswitch_bridge.fetch_models_from_url 的 /v1/models 校验逻辑。

    返回：{status, data: {ok, latency_ms, model_count, error?}}
    """
    import httpx

    row = _db_query_one(
        sql_sa="SELECT * FROM model_providers WHERE id = :i",
        params={"i": provider_id},
        sql_sq="SELECT * FROM model_providers WHERE id = ?",
        params_sq=(provider_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="供应商不存在")

    base_url = (row.get("base_url") or "").strip()
    api_key = (row.get("api_key") or "").strip()
    if not base_url:
        return {"status": "success", "data": {
            "ok": False, "error": "供应商未配置 base_url", "latency_ms": 0, "model_count": 0
        }}

    # 抽出候选 URL 并逐个尝试（复用 ccswitch_bridge 的逻辑）
    from fastapi_app.agent.ccswitch_bridge import _models_url_candidates

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    start = time.monotonic()
    last_error = ""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for url in _models_url_candidates(base_url):
                try:
                    resp = await client.get(url, headers=headers)
                except httpx.TimeoutException:
                    last_error = f"请求超时：{url}"
                    continue
                except httpx.HTTPError as exc:
                    last_error = f"请求失败：{exc}"
                    continue

                if resp.status_code in (401, 403):
                    return {"status": "success", "data": {
                        "ok": False,
                        "error": f"鉴权失败（HTTP {resp.status_code}），请检查 api_key",
                        "latency_ms": int((time.monotonic() - start) * 1000),
                        "model_count": 0,
                    }}
                if resp.status_code >= 400:
                    last_error = f"{url} 返回 HTTP {resp.status_code}"
                    continue
                try:
                    data = resp.json()
                except Exception:
                    last_error = f"{url} 返回非 JSON"
                    continue
                items = data.get("data") or data.get("models") or []
                model_count = len([m for m in items if isinstance(m, dict) and m.get("id")])
                return {"status": "success", "data": {
                    "ok": True,
                    "latency_ms": int((time.monotonic() - start) * 1000),
                    "model_count": model_count,
                }}
        return {"status": "success", "data": {
            "ok": False,
            "error": f"连接失败：{last_error or '未知错误'}",
            "latency_ms": int((time.monotonic() - start) * 1000),
            "model_count": 0,
        }}
    except Exception as e:
        return {"status": "success", "data": {
            "ok": False,
            "error": f"测试异常：{str(e)}",
            "latency_ms": int((time.monotonic() - start) * 1000),
            "model_count": 0,
        }}


@router.get("/{provider_id}/models", summary="抓取供应商可用模型")
async def get_provider_models(provider_id: int):
    """调用 {base_url}/v1/models 抓取模型列表，并写入 available_models 缓存。"""
    row = _db_query_one(
        sql_sa="SELECT * FROM model_providers WHERE id = :i",
        params={"i": provider_id},
        sql_sq="SELECT * FROM model_providers WHERE id = ?",
        params_sq=(provider_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="供应商不存在")

    base_url = (row.get("base_url") or "").strip()
    api_key = (row.get("api_key") or "").strip()
    if not base_url:
        return {"status": "success", "data": {"provider_id": provider_id, "models": [], "error": "供应商未配置 base_url"}}

    from fastapi_app.agent.ccswitch_bridge import fetch_models_from_url

    try:
        result = await fetch_models_from_url(base_url, api_key, provider_label=row.get("name") or base_url)
    except ValueError as exc:
        return {"status": "success", "data": {
            "provider_id": provider_id, "models": [], "error": str(exc)
        }}
    except Exception as exc:
        return {"status": "success", "data": {
            "provider_id": provider_id, "models": [], "error": f"抓取模型异常：{str(exc)}"
        }}

    models = result.get("models", [])
    # 写缓存
    try:
        _db_exec(
            sql_sa=(
                "UPDATE model_providers SET available_models = :m, updated_at = CURRENT_TIMESTAMP WHERE id = :i"
            ),
            params={"m": json.dumps(models, ensure_ascii=False), "i": provider_id},
            sql_sq=(
                "UPDATE model_providers SET available_models = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
            ),
            params_sq=(json.dumps(models, ensure_ascii=False), provider_id),
        )
    except Exception:
        pass

    return {"status": "success", "data": {
        "provider_id": provider_id, "models": models, "count": len(models)
    }}


@router.post("/{provider_id}/apply-to/{service_type}", summary="把供应商应用到通道")
async def apply_to_channel(provider_id: int, service_type: str, req: ApplyToRequest):
    """把供应商的 base_url/api_key 写入 ai_model_configs 对应记录。

    - model 参数由请求体提供，必须非空
    - provider 字段写供应商 name（软关联）
    """
    model_name = (req.model_name or "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="model_name 不能为空")

    row = _db_query_one(
        sql_sa="SELECT * FROM model_providers WHERE id = :i",
        params={"i": provider_id},
        sql_sq="SELECT * FROM model_providers WHERE id = ?",
        params_sq=(provider_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="供应商不存在")

    name = row.get("name")
    base_url = row.get("base_url")
    api_key = row.get("api_key")

    # upsert ai_model_configs（复用 ai/router.py 的 upsert 语义）
    existing = _db_query_one(
        sql_sa="SELECT id FROM ai_model_configs WHERE service_type = :t",
        params={"t": service_type},
        sql_sq="SELECT id FROM ai_model_configs WHERE service_type = ?",
        params_sq=(service_type,),
    )
    if existing:
        _db_exec(
            sql_sa=(
                "UPDATE ai_model_configs "
                "SET provider=:provider, api_key=:api_key, base_url=:base_url, model_name=:model_name, "
                "is_active=1, updated_at=CURRENT_TIMESTAMP WHERE service_type=:service_type"
            ),
            params={
                "service_type": service_type,
                "provider": name,
                "api_key": api_key,
                "base_url": base_url,
                "model_name": model_name,
            },
            sql_sq=(
                "UPDATE ai_model_configs "
                "SET provider=?, api_key=?, base_url=?, model_name=?, is_active=1, updated_at=CURRENT_TIMESTAMP "
                "WHERE service_type=?"
            ),
            params_sq=(name, api_key, base_url, model_name, service_type),
        )
        action = "updated"
    else:
        _db_exec_ins(
            sql_sa=(
                "INSERT INTO ai_model_configs "
                "(service_type, provider, api_key, base_url, model_name, is_active) "
                "VALUES (:service_type, :provider, :api_key, :base_url, :model_name, 1)"
            ),
            params={
                "service_type": service_type,
                "provider": name,
                "api_key": api_key,
                "base_url": base_url,
                "model_name": model_name,
            },
            sql_sq=(
                "INSERT INTO ai_model_configs "
                "(service_type, provider, api_key, base_url, model_name, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)"
            ),
            params_sq=(service_type, name, api_key, base_url, model_name),
        )
        action = "created"

    return {"status": "success", "message": f"已把供应商「{name}」应用到通道 {service_type}",
            "action": action, "service_type": service_type, "provider_id": provider_id,
            "model_name": model_name}


# ---------------------------------------------------------------------------
# 通道 → 供应商软关联端点（挂载在 ai/model-configs 前缀下）
# ---------------------------------------------------------------------------

model_configs_link_router = APIRouter(prefix="/ai/model-configs", tags=["AI 模型供应商注册表"])


@model_configs_link_router.get("/{service_type}/provider-link", summary="查询通道绑定的供应商")
async def get_model_config_provider_link(service_type: str):
    """返回该通道绑定的模型供应商。

    软关联规则：ai_model_configs 中的 provider/base_url/api_key 三者与某供应商全匹配时视为绑定，
    否则返回 null。不做数据迁移，也不写入外键。
    """
    cfg = _db_query_one(
        sql_sa="SELECT * FROM ai_model_configs WHERE service_type = :t",
        params={"t": service_type},
        sql_sq="SELECT * FROM ai_model_configs WHERE service_type = ?",
        params_sq=(service_type,),
    )
    if not cfg:
        return {"status": "success", "data": None}

    name = (cfg.get("provider") or "")
    base_url = (cfg.get("base_url") or "") or ""
    api_key = (cfg.get("api_key") or "") or ""
    if not name:
        return {"status": "success", "data": None}

    providers = _db_query(
        sql_sa="SELECT * FROM model_providers WHERE name = :n",
        params={"n": name},
        sql_sq="SELECT * FROM model_providers WHERE name = ?",
        params_sq=(name,),
    )
    matched = None
    for p in providers:
        p_base = (p.get("base_url") or "") or ""
        p_key = (p.get("api_key") or "") or ""
        if p_base == base_url and p_key == api_key:
            matched = p
            break
    return {"status": "success", "data": _row_to_provider(matched) if matched else None}
