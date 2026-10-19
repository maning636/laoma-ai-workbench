"""Prism 后端 FastAPI 鉴权依赖。

M2 hardening 修复：之前 `fusion_ai/ai_agents.py` 把 Authorization Bearer token
字符串本身当作 user_id，跨用户"隔离"仅靠字符串不同，而非真正的 JWT 校验。
本模块提供**真正的 JWT 校验**依赖，供需要用户身份的接口使用。

设计要点
──────────
1. **JWT 校验**：使用 `cloud_service.auth.security` 的 `decode_token` /
   `create_access_token`，复用与云端 `/cloud/auth/*` 一致的 HS256 + secret 解析
   链路（`CLOUDJWT_SECRET` → `JWT_SECRET` → …）。
2. **严格 401**：Bearer token 缺失 / 非法 / 过期 / 载荷缺 `sub` / `type != "access"`
   → HTTP 401。不再降级到 `anonymous` 或裸 token 字符串。
3. **不做 DB 查用户**：`user_id` 直接取自 JWT 的 `sub` claim。生产环境若需
   `is_active` 之类的用户表校验，可在此处扩展（引入 `get_db` + `User` 查询）。
4. **测试友好**：`create_test_access_token(subject)` 允许测试注入合法 JWT，
   避免必须走完整的 register/login 流程。

契约
──────
  Depends(get_auth_user_id) -> str
    - Authorization: Bearer <JWT> 必填
    - JWT payload 必须包含 `sub`（用户唯一标识）与 `type == "access"`
    - 通过则返回 `sub`（字符串形式）
    - 失败抛 HTTPException(401)
"""

from __future__ import annotations

import jwt as pyjwt  # PyJWT
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


# ──────────────────────────────────────────────────────────────
# JWT 配置解析
# ──────────────────────────────────────────────────────────────

# 仅在测试/本地无 cloud_service 配置时兜底；生产必须显式设置 CLOUDJWT_SECRET 或 JWT_SECRET
# （此默认密钥仅用于本地开发，不作为生产 secret。）
_FALLBACK_TEST_SECRET = "prism-dev-only-test-secret"
_FALLBACK_ALGORITHM = "HS256"


def _jwt_config() -> tuple[str, str]:
    """返回 (secret, algorithm)。

    优先使用 cloud_service.settings（保证与 /cloud/auth 签发/校验的密钥一致）；
    失败时降级到 env 变量或测试默认值。
    """
    try:
        from cloud_service.settings import get_settings

        s = get_settings()
        secret = s.get("jwt_secret") or ""
        alg = s.get("jwt_algorithm") or _FALLBACK_ALGORITHM
        if secret:
            return secret, alg
    except Exception:
        pass
    import os

    secret = (
        os.getenv("CLOUDJWT_SECRET")
        or os.getenv("JWT_SECRET")
        or os.getenv("CLOUD_SECRET_KEY")
        or os.getenv("SECRET_KEY")
        or _FALLBACK_TEST_SECRET
    )
    return secret, _FALLBACK_ALGORITHM


# ──────────────────────────────────────────────────────────────
# Token 校验
# ──────────────────────────────────────────────────────────────


def _extract_bearer_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> str:
    """从 HTTPBearer 解析结果里取出 token；不合法直接 401。"""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = (credentials.credentials or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


def _resolve_user_id_from_token(token: str) -> str:
    """校验 JWT access token 并返回 `sub` 作为 user_id。

    - 签名错 / 过期 / 载荷非法 → 401
    - `type != "access"` → 401（避免用 refresh token 当 access token 用）
    - `sub` 缺失或空 → 401
    """
    secret, alg = _jwt_config()
    try:
        payload = pyjwt.decode(token, secret, algorithms=[alg])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except pyjwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sub = payload.get("sub")
    if sub is None or (isinstance(sub, str) and not sub.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload: missing sub",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return str(sub)


# ──────────────────────────────────────────────────────────────
# FastAPI Depends
# ──────────────────────────────────────────────────────────────


async def get_auth_user_id(
    credentials: HTTPAuthorizationCredentials | None = None,
    request: Request | None = None,
) -> str:
    """FastAPI 依赖：从 Authorization Bearer 头提取并校验 JWT，返回 user_id。

    用法：
        @router.get("/xxx")
        async def handler(uid: str = Depends(get_auth_user_id)):
            ...

    行为：
    - 无 Bearer token → 401 "Missing Bearer token"
    - 签名/过期/payload 非法 → 401
    - 通过 → 返回 JWT 的 `sub` 字符串

    支持两种调用方式：
      1. FastAPI 依赖注入（自动传入 credentials）
      2. 直接调用并传入 request（内部从 header 解析 credentials）

    ⚠️  不再降级 anonymous；query 参数 user_id 也不再覆盖（防绕过鉴权）。
    """
    if credentials is None and request is not None:
        raw = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        raw = raw.strip()
        if raw.lower().startswith("bearer "):
            token_str = raw[7:].strip()
            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=token_str,
            )
    token = _extract_bearer_token(credentials)
    return _resolve_user_id_from_token(token)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = None,
) -> dict:
    """返回用户信息 dict（当前仅含 `user_id`）。

    预留扩展点：未来接入 `cloud_service.auth.User` 表后可在此补充
    username / email / is_active 等字段，并保持现有 `user_id` 键不变。
    """
    uid = await get_auth_user_id(credentials=credentials)
    return {"user_id": uid}


# ──────────────────────────────────────────────────────────────
# 测试辅助
# ──────────────────────────────────────────────────────────────


def create_test_access_token(
    subject: str | int,
    *,
    expires_minutes: int = 60 * 24,
) -> str:
    """测试用：签发一个合法的 JWT access token（不走完整 auth 流程）。

    - `subject`：写入 `sub` claim，作为 user_id。
    - 使用与 `_jwt_config()` 一致的 secret + algorithm，保证 `_resolve_user_id_from_token`
      可以校验通过。
    """
    from datetime import datetime, timedelta, timezone

    import jwt as _jwt

    secret, alg = _jwt_config()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(subject),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    return _jwt.encode(claims, secret, algorithm=alg)


__all__ = [
    "get_auth_user_id",
    "get_current_user",
    "create_test_access_token",
]
