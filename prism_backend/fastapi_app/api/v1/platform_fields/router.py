"""平台字段管理 API（Phase 1.1-1.5）

端点：
  GET /platform-fields/              列出所有平台配置
  GET /platform-fields/{platform}    获取指定平台字段配置
  GET /platform-fields/{platform}/category/{category}  按分类获取字段
  POST /platform-fields/{platform}/validate  验证发布载荷
  POST /platform-fields/declaration/normalize   归一化自主声明
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from prism_core.platform_fields import get_fields_by_category as _get_fields_by_category
from prism_core.platform_fields import (
    Platform,
    FieldCategory,
    FieldSpec,
    PlatformFieldsConfig,
    PlatformFieldsRegistry,
    platform_fields_registry,
    validate_publish_payload,
    normalize_declaration,
)

router = APIRouter()


class ValidateRequest(BaseModel):
    payload: Dict[str, Any]


class DeclarationNormalizeRequest(BaseModel):
    platform: Platform
    declaration: str


@router.get("/", response_model=list[PlatformFieldsConfig])
def list_all_platforms():
    return platform_fields_registry.list_all_platforms()


@router.get("/{platform}", response_model=PlatformFieldsConfig)
def get_platform_config(platform: str):
    try:
        p = Platform(platform)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"平台 '{platform}' 不支持")
    return platform_fields_registry.get_config(p)


@router.get("/{platform}/category/{category}", response_model=list[FieldSpec])
def _get_category_fields(platform: str, category: str):
    try:
        p = Platform(platform)
        c = FieldCategory(category)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"平台 '{platform}' 或分类 '{category}' 不支持")
    return _get_fields_by_category(p, c)


@router.post("/{platform}/validate")
def validate_payload(platform: str, body: ValidateRequest):
    try:
        p = Platform(platform)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"平台 '{platform}' 不支持")
    result = validate_publish_payload(p, body.payload)
    return result


@router.post("/declaration/normalize")
def normalize_decl(body: DeclarationNormalizeRequest):
    return {"normalized": normalize_declaration(body.platform, body.declaration)}
