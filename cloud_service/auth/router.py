"""Auth 端点(C12)。

前缀:`/cloud/auth`(在 `main.py` 中挂载)。
端点:
  POST /cloud/auth/register  { username, email, password } → 201 + user
  POST /cloud/auth/login     { username, password }        → { access_token, refresh_token, expires_in, token_type }
  POST /cloud/auth/refresh   { refresh_token }             → { access_token, expires_in, token_type }
  GET  /cloud/auth/me        (Bearer JWT)                  → user
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jwt import ExpiredSignatureError, InvalidTokenError

from ..db import get_db
from ..settings import get_settings
from . import security
from .models import User

router = APIRouter()

# Bearer token 解析(在 /me 上以 Depends 形式挂;无效/缺失 → 401)
_bearer = HTTPBearer(auto_error=False)

# 基础字段校验(与 FastAPI 自动 422 兼容)
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\.]{2,32}$")
_PASSWORD_MIN = 8
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ──────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32, description="2-32 字符,字母数字 _-.")
    email: str = Field(..., description="有效邮箱")
    password: str = Field(..., min_length=_PASSWORD_MIN, max_length=128)

    @field_validator("username")
    @classmethod
    def _username_pattern(cls, v: str) -> str:
        if not _USERNAME_RE.match(v):
            raise ValueError("username 只能包含字母、数字、下划线、连字符、点号")
        return v

    @field_validator("email")
    @classmethod
    def _email_pattern(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("email 格式不正确")
        return v

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if len(v) < _PASSWORD_MIN:
            raise ValueError(f"password 至少 {_PASSWORD_MIN} 位")
        return v


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒

    model_config = {"extra": "forbid"}


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

    model_config = {"extra": "forbid"}


class UserResponse(BaseModel):
    id: int
    username: str
    email: str | None = None
    is_active: bool
    created_at: str | None = None

    model_config = {"extra": "forbid"}


class ErrorResponse(BaseModel):
    detail: str

    model_config = {"extra": "forbid"}


# ──────────────────────────────────────────────────────────────
# Auth 依赖
# ──────────────────────────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = security.decode_token(credentials.credentials)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    try:
        user = db.get(User, int(user_id))
    except (TypeError, ValueError):
        user = None
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")

    return user


def _access_ttl_seconds() -> int:
    return int(get_settings()["access_token_expire_minutes"]) * 60


def _token_pair_for(user: User) -> TokenPair:
    access = security.create_access_token(user.id)
    refresh = security.create_refresh_token(user.id)
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=_access_ttl_seconds(),
    )


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────

@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserResponse:
    """创建用户。username / email 任一重复 → 409。"""
    existing = db.execute(
        select(User).where(
            (User.username == payload.username) | (User.email == payload.email)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username or email already registered",
        )

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=security.hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username or email already registered",
        )
    db.refresh(user)
    return UserResponse(**user.to_dict())


@router.post(
    "/login",
    response_model=TokenPair,
    responses={401: {"model": ErrorResponse}},
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    """用户名密码登录。密码错或用户不存在都返回同一 401(避免用户枚举)。"""
    user = db.execute(
        select(User).where(User.username == payload.username)
    ).scalar_one_or_none()
    if user is None or not security.verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")
    return _token_pair_for(user)


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    responses={401: {"model": ErrorResponse}},
)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> RefreshResponse:
    """用 refresh token 换取新的 access token。"""
    if not security.is_refresh_token(payload.refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    try:
        claims = security.decode_token(payload.refresh_token)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = claims.get("sub")
    user = db.get(User, int(user_id)) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is inactive")

    access = security.create_access_token(user.id)
    return RefreshResponse(
        access_token=access,
        expires_in=_access_ttl_seconds(),
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """返回当前 JWT 对应的用户信息。"""
    return UserResponse(**current_user.to_dict())


__all__ = ["router", "get_current_user"]
