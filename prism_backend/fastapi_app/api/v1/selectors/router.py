"""选择器版本化配置管理 API（Phase 2.1）

端点：
  GET    /selectors/versions/{platform}            获取版本列表
  GET    /selectors/{platform}                     获取当前版本配置
  GET    /selectors/{platform}/{version}           获取指定版本配置
  GET    /selectors/{platform}/key/{selector_name} 获取单个选择器值
  POST   /selectors/                               保存新版本配置
  POST   /selectors/rollback/{platform}/{version}   回滚到指定版本
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from prism_core.selectors import (
    SelectorConfig,
    load_selectors,
    save_selectors,
    list_selector_versions,
    rollback_selectors,
    get_selector,
)

router = APIRouter()


class SelectorConfigSave(BaseModel):
    platform: str = ""
    version: str = ""
    selectors: dict = {}
    fallback_selectors: dict = {}
    description: str = ""


@router.get("/versions/{platform}", response_model=list[str])
def list_versions(platform: str):
    return list_selector_versions(platform)


@router.get("/{platform}", response_model=SelectorConfig)
def get_current(platform: str, version: Optional[str] = None):
    config = load_selectors(platform, version)
    if not config:
        raise HTTPException(status_code=404, detail=f"平台 '{platform}' 无选择器配置")
    return config


@router.get("/{platform}/key/{selector_name}", response_model=dict)
def get_single_selector(platform: str, selector_name: str, version: Optional[str] = None):
    value = get_selector(platform, selector_name, version)
    if value is None:
        raise HTTPException(status_code=404, detail=f"选择器 '{selector_name}' 不存在")
    return {"platform": platform, "selector_name": selector_name, "value": value}


@router.post("/", response_model=SelectorConfig)
def save_config(body: SelectorConfigSave):
    config = SelectorConfig(**body.model_dump())
    version = save_selectors(config)
    return config


@router.post("/rollback/{platform}/{version}")
def rollback(platform: str, version: str):
    ok = rollback_selectors(platform, version)
    if not ok:
        raise HTTPException(status_code=404, detail=f"版本 '{version}' 不存在")
    return {"ok": True, "platform": platform, "rolled_back_to": version}
