"""注册码(license)的**公开**常量:公钥、授权条目、flag 容量表。

⚠️ 本文件**只含公钥**。私钥是签发端的私产,不入库、不进安装包。
公钥公开是安全的 —— 它只能验签,不能签发。

为什么单独一个文件:
  - 公钥是"发布配置",客户端验签要用;
  - 容量表是 D1=C 双轨判定的**数值真源**,与云端
    `cloud_service/billing/feature_gate.py` 的 `COMMUNITY_FLAGS` / `PRO_FLAGS` 对齐;
  - 改一处要同步另一处,所以这里在注释里写明对照关系。
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────
# 验签公钥(Ed25519,32 字节 raw 的 hex)
# ──────────────────────────────────────────────────────────────
# 私钥位置:**不入库、不进安装包**,由签发方自行保管(默认落在仓库外的备份目录)。
# 生成/轮换:python scripts/license/keygen.py --out <仓库外路径>.pem
#
# ⚠️ 轮换公钥会让所有已签发的注册码失效 —— 必须与私钥一起换,
#    并在换版说明里写明。老公钥可以保留一段时间做"双公钥验签"过渡。
PUBLIC_KEY_HEX = "ddd48aab99201a7eb8a73168dff98b8f076393f6cfdfb7ae02bd5f2fbed28bba"

# ──────────────────────────────────────────────────────────────
# 授权条目(可组合的授权包)
# ──────────────────────────────────────────────────────────────
# 与 docs/feature-gate-matrix.md §2 一致。
ENTITLEMENTS: tuple[str, ...] = (
    "core",            # 基础包:账号数、团队席位、数据回收
    "ai_cloud",        # 云端 AI:云端 prompt / 云端生图 / 云端模型
    "agent",           # Agent 配额:Hermes Agent 与流式对话
    "persona",         # Persona 与代理:指纹 / 代理管理 / 代理网关
    "campaign",        # 营销活动编排
    "multi_platform",  # 多平台发布(超出社区版 3 平台的配额)
)

# ──────────────────────────────────────────────────────────────
# flag 容量表 —— 与云端 COMMUNITY_FLAGS / PRO_FLAGS 对齐
# ──────────────────────────────────────────────────────────────
# 类型:
#   ("numeric", community, pro)   数值配额,-1 表示无限
#   ("bool",    community, pro)   开关
#   ("mode",    community, pro)   模式字符串
#
# 对照:cloud_service/billing/feature_gate.py 的 COMMUNITY_FLAGS / PRO_FLAGS
#       prism_backend/fastapi_app/api/billing_client.py 的同名常量
#       prism_frontend/src/lib/plan-flags.ts 的 DEFAULT_COMMUNITY_FLAGS
FLAG_CAPACITY: dict[str, tuple[str, object, object]] = {
    "max_accounts": ("numeric", 3, -1),
    "max_platforms": ("numeric", 3, 8),
    "ai_mode": ("mode", "local_key", "cloud"),
    "image_gen": ("mode", "local_key", "cloud"),
    "agent_quota": ("numeric", 0, 2),
    "data_recovery": ("bool", True, True),
    "persona": ("bool", False, True),
    "proxy_management": ("bool", False, True),
    "stream_chat": ("bool", False, True),
    "team_members": ("numeric", 1, 1),
    "cloud_prompt": ("bool", False, True),
    "campaign_orchestration": ("bool", False, True),
}

# ──────────────────────────────────────────────────────────────
# flag → 需要的注册码条目(1:1,与矩阵 §1「Flag 真源表」一致)
# ──────────────────────────────────────────────────────────────
# 口径说明:矩阵 §2 的 `core` 行历史上把 `max_platforms` 也列了进去,
# 与 §1「max_platforms → multi_platform」冲突。本模块以 **§1 为准**:
# `max_platforms` 的 Pro 档配额(8)由 `multi_platform` 条目解锁;
# `core` 只覆盖 `max_accounts` / `data_recovery` / `team_members`。
FLAG_ENTITLEMENT: dict[str, str] = {
    "max_accounts": "core",
    "max_platforms": "multi_platform",
    "ai_mode": "ai_cloud",
    "image_gen": "ai_cloud",
    "agent_quota": "agent",
    "data_recovery": "core",
    "persona": "persona",
    "proxy_management": "persona",
    "stream_chat": "agent",
    "team_members": "core",
    "cloud_prompt": "ai_cloud",
    "campaign_orchestration": "campaign",
}

#: 默认宽限天数(license 到期后仍可继续写的天数)
DEFAULT_GRACE_DAYS = 7


__all__ = [
    "PUBLIC_KEY_HEX",
    "ENTITLEMENTS",
    "FLAG_CAPACITY",
    "FLAG_ENTITLEMENT",
    "DEFAULT_GRACE_DAYS",
]
