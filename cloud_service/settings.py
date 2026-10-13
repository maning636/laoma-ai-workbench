"""Cloud service 配置。

优先级(从高到低):
  1. 显式 env:`CLOUD_*` 前缀
  2. 兼容回退到仓库根 `.env` / 环境中的 `SECRET_KEY`(仅开发便利,生产必须显式配置)
  3. 默认值 / 随机生成

**安全约束**:
  - `JWT_SECRET` 未显式配置时,进程内随机生成——每次重启 access/refresh token 都会失效。
    这避免了硬编码默认密钥进入生产,同时也给了开发零配置的可用体验。
  - `DB_URL` 默认为 SQLite 单文件 `cloud.db`,生产建议 `mysql+pymysql://...`。
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

# cloud_service 目录(相对本文件定位,避免受 CWD 影响)
_CLOUD_DIR = Path(__file__).resolve().parent

_DEFAULT_DB_PATH = _CLOUD_DIR / "cloud.db"


def _get_str(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_jwt_secret() -> str:
    """解析 JWT 密钥。

    优先级:
      1. `CLOUDJWT_SECRET`(推荐)
      2. `JWT_SECRET`
      3. `CLOUD_SECRET_KEY`
      4. `SECRET_KEY`(与本地后端 config.py 的遗留字段同名;仅取 env 值,不 import 后端)
    未命中时,首次访问随机生成一次,进程内稳定。
    """
    for name in ("CLOUDJWT_SECRET", "JWT_SECRET", "CLOUD_SECRET_KEY", "SECRET_KEY"):
        val = (os.getenv(name) or "").strip()
        if val:
            return val

    # 首次生成一次,后续调用稳定
    if not getattr(_resolve_jwt_secret, "_cache", None):
        _resolve_jwt_secret._cache = secrets.token_urlsafe(48)  # type: ignore[attr-defined]
    return _resolve_jwt_secret._cache  # type: ignore[attr-defined]


def _resolve_db_url() -> str:
    url = _get_str("CLOUD_DB_URL") or _get_str("DB_URL")
    if url:
        return url
    return f"sqlite:///{_DEFAULT_DB_PATH.as_posix()}"


@lru_cache(maxsize=1)
def get_settings():
    """返回设置快照(单例,避免每次读 env)。"""
    return {
        "app_name": _get_str("CLOUD_APP_NAME", "Prism-Fusion Cloud"),
        "debug": _get_str("CLOUD_DEBUG", "").lower() in {"1", "true", "yes"},
        "jwt_secret": _resolve_jwt_secret(),
        "jwt_algorithm": _get_str("CLOUDJWT_ALGORITHM", "HS256"),
        "access_token_expire_minutes": _get_int("CLOUD_ACCESS_TOKEN_EXPIRE_MINUTES", 30),
        "refresh_token_expire_days": _get_int("CLOUD_REFRESH_TOKEN_EXPIRE_DAYS", 7),
        "db_url": _resolve_db_url(),
        "jwt_secret_source": _detect_secret_source(),
        "billing": {
            # free 用户月度额度(可 env 覆盖);0 = 明确禁用,-1 = 无限
            "free_quota": _get_int("CLOUD_FREE_QUOTA", 20),
            # pro 用户月度额度;-1 表示无限(默认)
            "pro_quota": _get_int("CLOUD_PRO_QUOTA", -1),
        },
    }


def _detect_secret_source() -> str:
    for name in ("CLOUDJWT_SECRET", "JWT_SECRET", "CLOUD_SECRET_KEY", "SECRET_KEY"):
        if (os.getenv(name) or "").strip():
            return name
    return "random-in-memory"


def reset_settings_cache() -> None:
    """测试用:清掉 lru_cache 让下一次 get_settings() 重新读 env。"""
    get_settings.cache_clear()
