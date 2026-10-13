"""平台登录态检查 API（Phase 1.6）

端点：
  POST /login-check/          检查单个账号登录态
  POST /login-check/batch     批量检查账号登录态
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from prism_core.platform_login_checker import (
    LoginCheckResult,
    platform_login_checker,
)

router = APIRouter()


class LoginCheckRequest(BaseModel):
    account_id: str = ""
    platform: int = 0
    platform_name: str = ""
    cookie_file: str = ""


class LoginCheckBatchRequest(BaseModel):
    accounts: list[dict] = Field(default_factory=list)


class LoginCheckBatchResponse(BaseModel):
    total: int
    results: list[LoginCheckResult]


@router.post("/", response_model=LoginCheckResult)
def check_login(body: LoginCheckRequest):
    return platform_login_checker.check_login(
        body.account_id, body.platform, body.platform_name, body.cookie_file
    )


@router.post("/batch", response_model=LoginCheckBatchResponse)
def check_all(body: LoginCheckBatchRequest):
    results = platform_login_checker.check_all_accounts(body.accounts)
    return LoginCheckBatchResponse(total=len(results), results=results)
