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


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
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
        # ── M3 · 积分制配置(2026-10-16) ─────────────────
        # 默认对齐澜途 `/points/recharge/options`:
        #   - 1 元 = 10 积分(1 积分 = ¥0.10)
        #   - 满 1000 积分赠 50%(3000 档赠 1000,5000 档赠 2000)
        #   - 5 档预设:100/500/1000/3000/5000
        #   - 支持自定义 1-10000 积分
        # env 覆盖示例:CLOUD_POINTS_PER_YUAN=20,CLOUD_POINTS_BONUS_RATE=0.3
        "points": {
            "enabled": _get_str("CLOUD_POINTS_ENABLED", "true").lower() in {"1", "true", "yes"},
            "points_per_yuan": _get_float("CLOUD_POINTS_PER_YUAN", 10.0),
            "bonus_threshold": _get_float("CLOUD_POINTS_BONUS_THRESHOLD", 1000.0),
            "bonus_rate": _get_float("CLOUD_POINTS_BONUS_RATE", 0.5),
            "min_points": _get_float("CLOUD_POINTS_MIN", 1.0),
            "max_points": _get_float("CLOUD_POINTS_MAX", 10000.0),
            "default_points": _get_float("CLOUD_POINTS_DEFAULT", 3000.0),
            "custom_enabled": _get_str("CLOUD_POINTS_CUSTOM_ENABLED", "true").lower()
                in {"1", "true", "yes"},
        },
        # ── 商业闭环:人工充值(2026-10-23 起取代线上支付)────────
        # **平台支付手段已彻底删除**(2026-10-23):
        #   - 删掉了整个 `cloud_service/payment/` 包(支付宝 / 微信支付 adapter、
        #     Order 表、create_order / callback / 订单查询 / 退款 4 个端点);
        #   - 删掉了 `POST /cloud/points/recharge`(创建充值订单);
        #   - 删掉了订单超时清理与日终对账两个后台任务;
        #   - 因此下面几段配置(`online_payment` / `order_timeout` /
        #     `reconcile` / `task_lock`)随之移除,对应的 env 也不再被读取。
        #
        # 现在的唯一收款路径(**不需要任何云端配置**):
        #   1. 用户在客户端「设置 → 联系我们」加产品方微信(二维码在包内);
        #   2. 微信转账并备注用户名;
        #   3. 产品方核对到账 → 人工签发注册码(含授权条目 / 期限 / 积分额度);
        #   4. 用户把注册码填进客户端 → `POST /cloud/license/activate` 开通。
        #
        # 积分的**入账**同理有两条,都不依赖支付通道:
        #   - `POST /cloud/license/activate`   —— 注册码激活时注入注册码携带的积分;
        #   - `POST /cloud/admin/points/adjust` —— 管理端人工增减账户积分。
        #
        # 客户端侧的人工充值入口见 `prism_frontend/src/lib/contact.ts`
        # 与 `components/settings/contact-card.tsx`(统一指向 `/settings#contact`)。
        # ── CORS(浏览器直连)───────────────────────────
        # 由 main.py 的 CORSMiddleware 使用;逗号分隔的 origin 列表。
        # 默认覆盖本地前端开发(3000 端口);生产通过 env 覆盖为真实前端域名。
        # 注意:**不要**把默认值写成 "*" 同时打开 allow_credentials —— 这是
        # 安全反模式。当前 cloud_service 不依赖 cookie 跨域(前端 client-
        # gateway 明确 credentials: "omit"),所以 allow_credentials=False。
        "cors_origins": _parse_cors_origins(
            _get_str(
                "CLOUD_CORS_ORIGINS",
                "http://127.0.0.1:3000,http://localhost:3000",
            )
        ),
    }


def _parse_cors_origins(raw: str) -> list[str]:
    """把逗号分隔的 origin 字符串解析为 list[str],忽略空段与纯空白段。"""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _detect_secret_source() -> str:
    for name in ("CLOUDJWT_SECRET", "JWT_SECRET", "CLOUD_SECRET_KEY", "SECRET_KEY"):
        if (os.getenv(name) or "").strip():
            return name
    return "random-in-memory"


def reset_settings_cache() -> None:
    """测试用:清掉 lru_cache 让下一次 get_settings() 重新读 env。"""
    get_settings.cache_clear()
