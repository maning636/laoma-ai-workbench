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
        # ── 订单超时任务(P4)───────────────────────────
        # 只影响 `status='created'` 的订单;不影响 paid / refunded / closed。
        # 多 worker 部署下每个 worker 都会跑一份,注意幂等性(按 id 列表关闭)。
        "order_timeout": {
            "enabled": _get_str("CLOUD_ORDER_TIMEOUT_ENABLED", "true").lower()
            in {"1", "true", "yes"},
            "interval_seconds": _get_int("CLOUD_ORDER_TIMEOUT_INTERVAL_SECONDS", 3600),
            "hours": _get_int("CLOUD_ORDER_TIMEOUT_HOURS", 24),
        },
        # ── 日终对账调度(P6)───────────────────────────────
        # 默认 **关闭**:因为 `reconcile_day(platform_bills=None)` 会遍历已注册
        # adapter 调 `adapter.fetch_bill()`,一旦接入真实商户 adapter 就是外部调用。
        # 生产上线前必须显式确认开关,并配合日志告警;真实 adapter 上线时务必
        # 检查 fetch_bill 的限流与重试策略,避免每天全量拉账单触发商户配额。
        "reconcile": {
            "enabled": _get_str("CLOUD_RECONCILE_ENABLED", "false").lower()
            in {"1", "true", "yes"},
            "interval_seconds": _get_int("CLOUD_RECONCILE_INTERVAL_SECONDS", 86400),
            # 起始窗口(相对本次执行时间往前多少小时):默认 24h,覆盖"昨日"日切。
            "lookback_hours": _get_int("CLOUD_RECONCILE_LOOKBACK_HOURS", 24),
            # C-E: 单次 fetch_bill 的 wall-clock 超时。超时后本轮该 adapter 视为
            # 失败,不影响其它 adapter 与下一轮。默认 30s。
            "fetch_timeout_seconds": _get_float(
                "CLOUD_RECONCILE_FETCH_TIMEOUT_SECONDS", 30.0,
            ),
            # C-E: 指数退避(base 秒)。第 n 次失败后等 base * (2 ** (n-1)),
            # 封顶 max。默认 300s(5min),封顶 3600s(1h)。
            "backoff_base_seconds": _get_float(
                "CLOUD_RECONCILE_BACKOFF_BASE_SECONDS", 300.0,
            ),
            "backoff_max_seconds": _get_float(
                "CLOUD_RECONCILE_BACKOFF_MAX_SECONDS", 3600.0,
            ),
            # C-E: 每日调用次数上限(所有 worker 累计)。0 = 关闭限流;
            # 默认 10(约每小时 1 次);超限后本轮跳过并 warn。
            "daily_limit": _get_int("CLOUD_RECONCILE_DAILY_LIMIT", 10),
            # C-E: 每日限流 key 前缀(不同环境可隔离)
            "daily_limit_base_key": _get_str(
                "CLOUD_RECONCILE_DAILY_LIMIT_KEY",
                "cloud:payment:reconcile",
            ),
        },
        # ── 后台任务分布式锁(C-D)────────────────────────
        # `uvicorn --workers > 1` 时每个 worker 都会跑一份 lifespan;
        # 该开关控制是否用 Redis SET NX PX 抢锁,只有抢到锁的 worker 才执行
        # 本轮任务,避免:1) 重复调用商户 fetch_bill;2) 日志重复。
        #
        # 默认 **true**:Redis 挂时自动降级为"无锁模式"(打 warning 但照常
        # 执行),既不会因 Redis 抖动停摆,也在正常路径下避免重复外部调用。
        # 单 worker 部署(开发)可关闭以避免一次 RTT。
        "task_lock": {
            "enabled": _get_str("CLOUD_TASK_LOCK_ENABLED", "true").lower()
            in {"1", "true", "yes"},
            # 锁 TTL 秒;0 = 按 2 * 任务间隔 自动推导。默认 0 让调用方按任务间隔
            # 动态算 TTL,通常 > 单轮任务最长执行时间,防止死锁。
            "ttl_seconds": _get_int("CLOUD_TASK_LOCK_TTL_SECONDS", 0),
        },
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
