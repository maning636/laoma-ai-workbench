"""Open Core · Feature Gate (Community vs Pro 功能分层).

设计参考:
  - `docs/dev-reports/2026-10-16-open-core-strategy.md` §2 §3
  - `docs/dev-reports/2026-10-16-module-replication-plan.md`

本模块提供:
  1. **Feature Flags 常量**: `COMMUNITY_FLAGS` / `PRO_FLAGS` 明确定义
     两档套餐的功能边界,便于:
       - 客户端拉取后按 flag 渲染 UI(隐藏 Pro 功能入口)
       - 服务端 API 在关键路径调用 `check_feature` / `require_feature`
         做 403 拦截
  2. **`check_feature(user_id, feature_name)`**: 检查某用户是否具备某功能。
     - 优先查云端订阅(通过 SQLAlchemy);
     - 若无 DB session 或订阅记录,回落为 Community 默认值(不阻断客户端离线使用);
     - 不修改订阅状态,只做只读查询。
  3. **`require_feature(user, feature_name)`**: FastAPI 依赖,
     未授权时抛 `HTTPException(403)` 且返回结构化 upgrade 提示。
  4. **`get_user_feature_flags(user_id)`**: 返回该用户当前所有 flag,
     客户端订阅后缓存,避免每次请求都打云端。

设计原则:
  - **不破坏现有功能**: Community 的限制是"新增检查",不是"删除功能";
    现有 C13 billing 的 `quota`(月度 LLM 调用额度)仍然生效,
    本模块叠加在其之上,两者是**AND**关系。
  - **无云端也能跑**: 客户端未联网 / 云端 5xx / 未登录 时,
    回落 Community 默认 flag(允许基本体验,不阻断)。
  - **单一来源**: `is_pro` 判定复用 C13 billing 的 Subscription 表
    (`plan == "pro" and status == "active" and not expired`),
    避免多套订阅口径打架。

Feature Flags 完整列表 (对齐 `open-core-strategy.md` §3.1/§3.2):

  max_accounts       矩阵发布账号上限       Community=3       Pro=-1(无限)
  max_platforms      可用平台数上限         Community=3       Pro=8
  ai_mode            AI 调用模式            Community=local   Pro=cloud
  image_gen          文生图(M1)            Community=local   Pro=cloud
  agent_quota        Hermes Agent 可用数    Community=0       Pro=2
  data_recovery      数据回收能力           Community=true    Pro=true（D7 社区版即可用）
  persona            Persona 指纹增强       Community=false   Pro=true
  proxy_management   代理管理/IP 池         Community=false   Pro=true
  stream_chat        SSE 流式 AI 对话       Community=false   Pro=true
  team_members       团队座位数             Community=1       Pro=1(暂同;Team 档另行)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 常量:两档套餐的 feature flags
# ──────────────────────────────────────────────────────────────

Plan = Literal["community", "pro", "free"]

# 说明:
#   - `community` / `free`: 语义等价,C13 里 plan='free' 是"永久免费订阅",
#     这里我们统一看作 Community 边界(策略文档 §3.1)。
#   - `pro`: 付费订阅(需 active 且未过期)。
#
# 数值约定:
#   - `max_accounts` / `max_platforms`: -1 表示无限,0 表示禁用
#   - `agent_quota`: 可用 agent 数量(0 = 完全禁用,2 = Pro 默认)
#   - `*_mode` 字段: "cloud" 走云端代理(不暴露 prompt / key),
#     "local_key" 走客户端自配 key(离线模式)

COMMUNITY_FLAGS: dict[str, Any] = {
    "max_accounts": 3,
    "max_platforms": 3,
    "ai_mode": "local_key",
    "image_gen": "local_key",
    "agent_quota": 0,
    "data_recovery": True,       # D7：数据回收不收进 Pro，社区版即可用
    "persona": False,
    "proxy_management": False,
    "stream_chat": False,
    "team_members": 1,
}

PRO_FLAGS: dict[str, Any] = {
    "max_accounts": -1,          # 无限
    "max_platforms": 8,          # 抖音/快手/小红书/视频号/B站/TikTok/YouTube/X
    "ai_mode": "cloud",
    "image_gen": "cloud",
    "agent_quota": 2,
    "data_recovery": True,
    "persona": True,
    "proxy_management": True,
    "stream_chat": True,
    "team_members": 1,          # Team 档位后续扩展
}


def _env_override_int(name: str, default: int) -> int:
    """读 env int;非法/空字符串 → 返回 default。"""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_override_bool(name: str, default: bool) -> bool:
    """读 env bool('1'/'true'/'yes' 视为 True);非法/空字符串 → 返回 default。"""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_override_str(name: str, default: str) -> str:
    """读 env str;空字符串 → 返回 default。"""
    raw = (os.getenv(name) or "").strip()
    return raw or default


def _build_flags(base: dict[str, Any]) -> dict[str, Any]:
    """根据 env 覆盖基础 flags。

    覆盖规则(生产可覆盖,开发者可跳过限制做本地测试):
      - CLOUD_MAX_ACCOUNTS        : Community=3 / Pro=-1
      - CLOUD_MAX_PLATFORMS       : Community=3 / Pro=8
      - CLOUD_AI_MODE             : 'local_key' | 'cloud'
      - CLOUD_IMAGE_GEN           : 'local_key' | 'cloud'
      - CLOUD_AGENT_QUOTA         : Community=0 / Pro=2
      - CLOUD_DATA_RECOVERY       : Community=false / Pro=true
      - CLOUD_PERSONA             : Community=false / Pro=true
      - CLOUD_PROXY_MANAGEMENT    : Community=false / Pro=true
      - CLOUD_STREAM_CHAT         : Community=false / Pro=true

    仅在 `CLOUD_FEATURE_GATE_DISABLED=true` 时,所有数值型强制为 -1、
    布尔型强制为 true(供开发者完全绕过 feature gate 做本地测试)。
    """
    flags = dict(base)

    if _env_override_bool("CLOUD_FEATURE_GATE_DISABLED", False):
        # 完全绕过:数值型全部无限,布尔型全部打开(仅供本地开发)
        for key in ("max_accounts", "max_platforms", "agent_quota", "team_members"):
            if key in flags:
                flags[key] = -1
        for key in ("data_recovery", "persona", "proxy_management", "stream_chat"):
            if key in flags:
                flags[key] = True
        flags["ai_mode"] = "cloud"
        flags["image_gen"] = "cloud"
        return flags

    # 单项覆盖
    flags["max_accounts"] = _env_override_int("CLOUD_MAX_ACCOUNTS", flags["max_accounts"])
    flags["max_platforms"] = _env_override_int("CLOUD_MAX_PLATFORMS", flags["max_platforms"])
    flags["agent_quota"] = _env_override_int("CLOUD_AGENT_QUOTA", flags["agent_quota"])
    flags["ai_mode"] = _env_override_str("CLOUD_AI_MODE", flags["ai_mode"])
    flags["image_gen"] = _env_override_str("CLOUD_IMAGE_GEN", flags["image_gen"])
    flags["data_recovery"] = _env_override_bool("CLOUD_DATA_RECOVERY", flags["data_recovery"])
    flags["persona"] = _env_override_bool("CLOUD_PERSONA", flags["persona"])
    flags["proxy_management"] = _env_override_bool(
        "CLOUD_PROXY_MANAGEMENT", flags["proxy_management"]
    )
    flags["stream_chat"] = _env_override_bool("CLOUD_STREAM_CHAT", flags["stream_chat"])
    return flags

# 所有支持的 feature 名(供客户端 UI / 服务端校验统一枚举)
FEATURE_NAMES: tuple[str, ...] = tuple(sorted(set(COMMUNITY_FLAGS) | set(PRO_FLAGS)))

# 需要"升级 Pro"提示的 feature 名(客户端 403 后可高亮引导)
UPGRADE_FEATURES: frozenset[str] = frozenset({
    "max_accounts", "max_platforms", "data_recovery", "persona",
    "proxy_management", "stream_chat",
})


# ──────────────────────────────────────────────────────────────
# 结果对象
# ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FeatureCheckResult:
    """`check_feature` 的返回值。

    Attributes:
      allowed: 是否允许访问该功能
      plan:    当前用户所属档位("community" | "pro")
      limit:   该 feature 对应的上限值(如 3 / -1),或 None(布尔型)
      reason:  机器可读的原因码,便于客户端本地化文案
    """
    allowed: bool
    plan: str
    limit: Optional[Any] = None
    reason: str = "ok"


# ──────────────────────────────────────────────────────────────
# 内部:从 DB 判定 plan
# ──────────────────────────────────────────────────────────────

def _resolve_plan(
    db: Optional[Session],
    user_id: Optional[int],
) -> str:
    """根据 DB 中的 Subscription 判定 plan。

    判定规则(与 C13 `_serialize_subscription` 保持一致):
      - db is None 或 user_id is None → "community"
      - 无 Subscription 记录         → "community"
      - status != 'active'          → "community"
      - is_expired()                → "community"
      - plan == 'pro'               → "pro"
      - 其他                        → "community"

    只有**真正的 DB 故障**(`SQLAlchemyError`)才回落 "community"(避免云端抖动阻断客户端)。

    ⚠️ 不要把这里改回 `except Exception`:
    历史上正因为 `except Exception` 把 `NameError`(漏 import `select`)伪装成
    "回落 community",结果**付费 Pro 用户被静默降级成 Community**,
    全部 Pro 权限(persona / proxy_management / stream_chat / 无限账号 /
    云端 AI 模式)失效,且没有任何报错。编程错误必须向上抛,让测试能抓到。
    """
    if db is None or user_id is None:
        return "community"
    try:
        from .models import Subscription  # 延迟导入避免循环
        sub = db.execute(select(Subscription).where(Subscription.user_id == user_id)).scalar_one_or_none()
        if sub is None:
            return "community"
        if sub.is_expired():
            return "community"
        if sub.status != "active":
            return "community"
        return "pro" if sub.plan == "pro" else "community"
    except SQLAlchemyError:
        # 云端 DB 故障 → 回落 Community(不阻断离线体验)
        logger.warning("[feature_gate] 订阅查询失败,回落 community", exc_info=True)
        return "community"


# ──────────────────────────────────────────────────────────────
# 公开 API:check_feature / get_user_feature_flags / require_feature
# ──────────────────────────────────────────────────────────────

def get_flags_for_plan(plan: str) -> dict[str, Any]:
    """按 plan 名返回该档位的 flag 快照(拷贝,应用 env 覆盖)。

    每次调用都会重新读 env,支持开发环境动态调整 feature gate 而无需重启。
    """
    base = PRO_FLAGS if plan == "pro" else COMMUNITY_FLAGS
    return _build_flags(base)


def get_user_feature_flags(
    user_id: Optional[int],
    db: Optional[Session] = None,
) -> dict[str, Any]:
    """返回指定用户当前的完整 flag 快照 + plan。

    客户端心跳或订阅状态变化后调用;返回结构:
      {
        "plan": "community" | "pro",
        "flags": { ... 各 feature 的实际值 ... },
      }
    """
    plan = _resolve_plan(db, user_id)
    flags = get_flags_for_plan(plan)
    return {
        "plan": plan,
        "flags": flags,
    }


def check_feature(
    user_id: Optional[int],
    feature_name: str,
    db: Optional[Session] = None,
) -> FeatureCheckResult:
    """检查用户是否有某 feature 权限。

    Args:
      user_id: 用户主键;None 或找不到订阅 → 视为 Community
      feature_name: 见 `FEATURE_NAMES` 中的任一字段
      db: SQLAlchemy session;None 时直接使用 Community 默认值

    Returns:
      `FeatureCheckResult(allowed, plan, limit, reason)`

    语义约定:
      - **布尔型 flag** (`data_recovery` / `persona` / `proxy_management` / `stream_chat`):
        `allowed = (flag is True)`, `limit=None`
      - **数值型 flag** (`max_accounts` / `max_platforms` / `agent_quota` / `team_members`):
        `allowed = (limit != 0)`, `limit=flag 值`
          - 0 表示明确禁用(不允许新增/创建);
          - -1 表示无限(始终允许);
          - >0 表示允许但不超上限(具体超限检查由业务 API 做)
      - **模式型 flag** (`ai_mode` / `image_gen`):
        `allowed = True`(总是可用),`limit=flag 值`("local_key" | "cloud")
          - 客户端按值切换本地/云端路径;服务端不阻拦本地模式。
      - **未知 feature**: 抛 `ValueError`(编程错误,不静默通过)
    """
    if feature_name not in FEATURE_NAMES:
        raise ValueError(
            f"unknown feature: {feature_name!r}; "
            f"supported: {sorted(FEATURE_NAMES)}"
        )

    plan = _resolve_plan(db, user_id)
    flags = get_flags_for_plan(plan)
    value = flags[feature_name]

    if feature_name in {"data_recovery", "persona", "proxy_management", "stream_chat"}:
        # 布尔型
        return FeatureCheckResult(
            allowed=bool(value),
            plan=plan,
            limit=None,
            reason="ok" if value else "upgrade_required",
        )

    if feature_name in {"ai_mode", "image_gen"}:
        # 模式型:总是可用,limit 是模式字符串
        return FeatureCheckResult(
            allowed=True,
            plan=plan,
            limit=value,
            reason="ok",
        )

    if feature_name in {"max_accounts", "max_platforms", "agent_quota", "team_members"}:
        # 数值型:0 = 明确禁用,-1 或 >0 = 允许
        allowed = value != 0
        return FeatureCheckResult(
            allowed=allowed,
            plan=plan,
            limit=value,
            reason="ok" if allowed else "upgrade_required",
        )

    # 兜底(理论上不会到这里,已覆盖 FEATURE_NAMES 全部分支)
    return FeatureCheckResult(
        allowed=bool(value),
        plan=plan,
        limit=value,
        reason="ok" if value else "upgrade_required",
    )


def require_feature(
    user: Any,
    feature_name: str,
    db: Optional[Session] = None,
    *,
    message: Optional[str] = None,
) -> FeatureCheckResult:
    """FastAPI 端点内的 gate helper:未授权时抛 403。

    用法::

        @router.post("/api/v1/accounts")
        def create_account(
            payload: CreateAccountRequest,
            current_user: User = Depends(get_current_user),
            db: Session = Depends(get_db),
        ):
            require_feature(current_user, "max_accounts", db)
            # ... 后续再做"当前账号数是否超过上限"的业务检查
            ...

    与 `check_feature` 的差别:本函数会**主动 raise HTTPException**;
    适合在服务端关键路径做 fail-fast 拦截。
    """
    result = check_feature(
        user_id=getattr(user, "id", None),
        feature_name=feature_name,
        db=db,
    )
    if result.allowed:
        return result

    detail: dict[str, Any] = {
        "feature": feature_name,
        "plan": result.plan,
        "reason": result.reason,
        "upgrade_required": feature_name in UPGRADE_FEATURES,
        "message": message or (
            f"Feature '{feature_name}' requires Pro plan. "
            f"Current plan: {result.plan}."
        ),
    }
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


# ──────────────────────────────────────────────────────────────
# 内部工具:账号/平台超上限检查(供业务 API 复用)
# ──────────────────────────────────────────────────────────────

def check_quota_or_raise(
    user: Any,
    feature_name: str,
    current_count: int,
    db: Optional[Session] = None,
    *,
    increment: int = 1,
) -> None:
    """检查"当前数量 + increment"是否超过 flag 上限,超过抛 403。

    用途:业务 API 在**创建**账号 / 平台绑定前调用,判断是否会
    超上限。示例:

      # 创建账号前
      existing = db.query(Account).filter(Account.user_id == current_user.id).count()
      check_quota_or_raise(current_user, "max_accounts", existing, db)
      # 通过 → 创建账号

    约定:
      - `max_accounts = -1`(Pro): 永远通过
      - `max_accounts = 0`: 抛 403(Community 已用满或禁用)
      - `max_accounts = 3`(Community): 若 existing + increment > 3 抛 403
      - 仅对数值型 feature 生效;布尔型 / 模式型 抛 `ValueError`
    """
    if feature_name not in {"max_accounts", "max_platforms", "agent_quota", "team_members"}:
        raise ValueError(
            f"check_quota_or_raise only supports numeric quota features; got {feature_name!r}"
        )

    result = check_feature(getattr(user, "id", None), feature_name, db=db)
    limit = result.limit

    if not isinstance(limit, int):
        raise ValueError(f"feature {feature_name!r} has non-numeric limit: {limit!r}")

    if limit == -1:
        # 无限,直接通过
        return

    if current_count < 0:
        raise ValueError(f"current_count must be >= 0, got {current_count}")

    new_count = current_count + increment
    if new_count > limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "feature": feature_name,
                "plan": result.plan,
                "reason": "quota_exceeded",
                "limit": limit,
                "current": current_count,
                "requested": increment,
                "upgrade_required": True,
                "message": (
                    f"Community plan allows up to {limit} "
                    f"{feature_name.replace('max_', '')}. "
                    f"Upgrade to Pro for unlimited access."
                ),
            },
        )


__all__ = [
    "COMMUNITY_FLAGS",
    "PRO_FLAGS",
    "FEATURE_NAMES",
    "UPGRADE_FEATURES",
    "Plan",
    "FeatureCheckResult",
    "get_flags_for_plan",
    "get_user_feature_flags",
    "check_feature",
    "require_feature",
    "check_quota_or_raise",
]
