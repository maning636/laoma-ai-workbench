"""密码哈希(bcrypt)+ JWT(HS256)签发/校验。

依赖:`bcrypt` + `pyjwt`。

安全说明:
  - 密码:bcrypt(默认 cost=12),不存明文;比较走 bcrypt.checkpw(恒定时间)。
  - JWT:HS256 + `JWT_SECRET`(env 或进程内随机),access=30min / refresh=7d,可配。
  - Token 载荷里含 `sub`(user id)、`type`(access|refresh)、`exp`。
    刷新端点严格校验 `type == "refresh"`,避免用 access 换 refresh。
"""

from __future__ import annotations

import jwt  # PyJWT

import bcrypt as _bcrypt
from jwt import ExpiredSignatureError, InvalidTokenError

from ..settings import get_settings

_BCRYPT_ROUNDS = 12


# ──────────────────────────────────────────────────────────────
# 密码哈希
# ──────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """bcrypt 哈希。返回值是可安全入库的字符串。"""
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty str")
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode(
        "utf-8"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文与 bcrypt 哈希。恒定时间比较。"""
    if not password or not password_hash:
        return False
    try:
        return _bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ──────────────────────────────────────────────────────────────
# JWT
# ──────────────────────────────────────────────────────────────

def _jwt_cfg() -> tuple[str, str, int, int]:
    s = get_settings()
    return (
        s["jwt_secret"],
        s["jwt_algorithm"],
        int(s["access_token_expire_minutes"]),
        int(s["refresh_token_expire_days"]),
    )


def create_access_token(
    subject: str | int | dict,
    *,
    expires_minutes: int | None = None,
    extra_claims: dict | None = None,
) -> str:
    """签发 access token,`type="access"`。

    `subject` 支持三种形式:
      - `int` / `str`:作为 `sub` 写入
      - `dict`:整体作为 claims,其中的 `sub` 会被保留
    """
    secret, alg, default_minutes, _ = _jwt_cfg()
    minutes = expires_minutes if expires_minutes is not None else default_minutes
    return jwt.encode(
        _coerce_claims(
            subject=subject,
            token_type="access",
            lifetime_minutes=minutes,
            extra=extra_claims,
        ),
        secret,
        algorithm=alg,
    )


def create_refresh_token(
    subject: str | int | dict,
    *,
    expires_days: int | None = None,
    extra_claims: dict | None = None,
) -> str:
    """签发 refresh token,`type="refresh"`,默认 7 天。参数形态同 `create_access_token`。"""
    secret, alg, _, default_days = _jwt_cfg()
    days = expires_days if expires_days is not None else default_days
    return jwt.encode(
        _coerce_claims(
            subject=subject,
            token_type="refresh",
            lifetime_minutes=days * 24 * 60,
            extra=extra_claims,
        ),
        secret,
        algorithm=alg,
    )


def _coerce_claims(
    *,
    subject,
    token_type: str,
    lifetime_minutes: int,
    extra: dict | None = None,
) -> dict:
    """把 subject(dict / str / int) + extra 规整为最终 JWT claims。"""
    from datetime import datetime, timedelta, timezone

    if isinstance(subject, dict):
        base = dict(subject)
    else:
        base = {"sub": str(subject)}

    now = datetime.now(timezone.utc)
    claims: dict = {
        "sub": base.get("sub", base.get("subject", "")),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=lifetime_minutes)).timestamp()),
    }
    # 其它 base 里的键保留(如 role/email),但不要覆盖 sub/type/iat/exp
    for k, v in base.items():
        if k in claims or k == "subject":
            continue
        claims[k] = v
    if extra:
        for k, v in extra.items():
            if k in ("sub", "type", "iat", "exp"):
                continue
            claims[k] = v
    return claims


def decode_token(token: str) -> dict:
    """解码并校验签名/过期。失败抛 InvalidTokenError(ExpiredSignatureError 亦为其子类)。"""
    secret, alg, _, _ = _jwt_cfg()
    return jwt.decode(token, secret, algorithms=[alg])


def verify_token(token: str) -> bool:
    """布尔形式校验:不抛异常,签名错或过期返回 False。"""
    try:
        jwt.decode(token, _jwt_cfg()[0], algorithms=[_jwt_cfg()[1]])
        return True
    except InvalidTokenError:
        return False


def is_refresh_token(token: str) -> bool:
    """判断 token 是否 refresh 类型;过期 / 无效 / 签名错 → False。"""
    try:
        payload = decode_token(token)
    except InvalidTokenError:
        return False
    return payload.get("type") == "refresh"


__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "verify_token",
    "is_refresh_token",
    "ExpiredSignatureError",
]
