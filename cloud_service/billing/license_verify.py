"""云端侧注册码验签 —— 与桌面端同一套 Ed25519 公钥。

背景(线下人工充值模式)
------------------------
线上支付已下线,商业闭环改为:
  用户加产品方微信 → 人工收款 → 产品方签发注册码(含授权条目 / 期限 / 积分额度)
  → 用户把注册码填进客户端 → 客户端本地验签(离线可用)
  → 客户端把注册码同步到云端 → 云端验签 → 写订阅 + 注入积分额度

所以云端必须**独立具备验签能力**:它要确认「这个注册码确实是我们签发的、还没过期、
带哪些授权条目、含多少积分」,再据此给账户开通能力。

⚠️ 常量一致性
-------------
本模块的 `PUBLIC_KEY_HEX` / `ENTITLEMENTS` / `FLAG_CAPACITY` / `FLAG_ENTITLEMENT`
是桌面端 `prism_backend/fastapi_app/core/license_keys.py` 的**镜像副本**。

刻意不复用那边的模块:桌面端带一整套 Electron/浏览器依赖,云端服务要保持轻量,
跨模块 import 会把客户端依赖拖进云端运行时(且 PyInstaller 打包链要跟着改)。

漂移风险由 `cloud_service/test_license_verify.py` 断言钉死:
该测试在完整依赖环境里同时 import 两边,公钥/条目/容量表任一处不一致直接红。
**改一边必须改另一边。**
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 常量(镜像 prism_backend/fastapi_app/core/license_keys.py)
# ──────────────────────────────────────────────────────────────

#: Ed25519 公钥(32 字节 raw 的 hex)。私钥在签发端,绝不入库、不进安装包。
PUBLIC_KEY_HEX = "ddd48aab99201a7eb8a73168dff98b8f076393f6cfdfb7ae02bd5f2fbed28bba"

#: 注册码 token 前缀(格式版本)
TOKEN_PREFIX = "PRISM1"

#: payload 格式版本
PAYLOAD_VERSION = 1

#: 可组合的授权条目
ENTITLEMENTS: tuple[str, ...] = (
    "core",
    "ai_cloud",
    "agent",
    "persona",
    "campaign",
    "multi_platform",
)

#: flag 容量表:(类型, community 档, pro 档)
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

#: flag → 需要的注册码条目(1:1)
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

#: 默认宽限天数
DEFAULT_GRACE_DAYS = 7

#: 注册码默认积分额度
DEFAULT_CREDITS = 0


# ──────────────────────────────────────────────────────────────
# 数据结构与异常
# ──────────────────────────────────────────────────────────────


class LicenseVerifyError(ValueError):
    """注册码验签/解析失败(格式错、签名不通过、条目非法、已过期等)。"""


@dataclass(frozen=True)
class LicenseClaims:
    """验签通过的注册码声明。"""

    license_id: str
    entitlements: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    grace_days: int
    customer: str = ""
    note: str = ""
    credits: int = DEFAULT_CREDITS

    @property
    def effective_until(self) -> datetime:
        """能力实际失效时刻 = 到期日 + 宽限期。

        与桌面端只读切换点对齐:桌面端在 `expires_at + grace_days` 之后才转只读,
        云端订阅也必须活到这一刻,否则会出现「本地还能写、云端已降级」的不一致。
        """
        return self.expires_at + timedelta(days=self.grace_days)

    def to_dict(self) -> dict[str, Any]:
        return {
            "licenseId": self.license_id,
            "entitlements": sorted(self.entitlements),
            "issuedAt": self.issued_at.isoformat(timespec="seconds"),
            "expiresAt": self.expires_at.isoformat(timespec="seconds"),
            "graceDays": self.grace_days,
            "effectiveUntil": self.effective_until.isoformat(timespec="seconds"),
            "customer": self.customer,
            "note": self.note,
            "credits": self.credits,
        }


# ──────────────────────────────────────────────────────────────
# 编解码与验签
# ──────────────────────────────────────────────────────────────


def _b64u_decode(s: str) -> bytes:
    """base64url 解码(容忍缺省 padding)。"""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _parse_ts(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise LicenseVerifyError("时间字段缺失")
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise LicenseVerifyError(f"时间字段格式错:{exc}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def decode_payload(body_b64: str) -> LicenseClaims:
    """解出 payload 并做结构校验(**不验签**)。"""
    try:
        raw = json.loads(_b64u_decode(body_b64).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise LicenseVerifyError(f"payload 无法解析:{exc}") from exc
    if not isinstance(raw, dict):
        raise LicenseVerifyError("payload 不是对象")

    version = int(raw.get("v", 0))
    if version != PAYLOAD_VERSION:
        raise LicenseVerifyError(f"不支持的 payload 版本: {version}")

    ents_raw = raw.get("ent") or []
    if not isinstance(ents_raw, list):
        raise LicenseVerifyError("ent 必须是数组")
    unknown = [e for e in ents_raw if e not in ENTITLEMENTS]
    if unknown:
        raise LicenseVerifyError(f"未知授权条目: {unknown}")
    if not ents_raw:
        raise LicenseVerifyError("注册码未包含任何授权条目")

    try:
        grace = int(raw.get("grace", DEFAULT_GRACE_DAYS))
    except (TypeError, ValueError) as exc:
        raise LicenseVerifyError("grace 必须是整数") from exc
    if grace < 0:
        raise LicenseVerifyError("grace 不能为负")

    try:
        credits = int(raw.get("cr", DEFAULT_CREDITS))
    except (TypeError, ValueError) as exc:
        raise LicenseVerifyError("cr 必须是整数") from exc
    if credits < 0:
        raise LicenseVerifyError("cr 不能为负")

    return LicenseClaims(
        license_id=str(raw.get("lid") or ""),
        entitlements=frozenset(str(e) for e in ents_raw),
        issued_at=_parse_ts(raw.get("iat")),
        expires_at=_parse_ts(raw.get("exp")),
        grace_days=grace,
        customer=str(raw.get("cust") or ""),
        note=str(raw.get("note") or ""),
        credits=credits,
    )


def verify_token(
    token: str,
    *,
    public_key_hex: str = PUBLIC_KEY_HEX,
    now: Optional[datetime] = None,
) -> LicenseClaims:
    """验签并返回注册码声明。**失败一律抛 `LicenseVerifyError`**。

    与桌面端的差别:桌面端是「验签失败也不抛异常,返回状态对象」;
    云端这里是「调用方需要区分成功/失败并给用户明确提示」,所以用异常更顺手。
    """
    now = now or datetime.now(timezone.utc)
    token = (token or "").strip()
    if not token:
        raise LicenseVerifyError("注册码为空")

    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise LicenseVerifyError("注册码格式不正确(应以 PRISM1. 开头)")

    _, body_b64, sig_b64 = parts
    claims = decode_payload(body_b64)

    try:
        public_bytes = bytes.fromhex(public_key_hex)
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
        public_key.verify(_b64u_decode(sig_b64), body_b64.encode("ascii"))
    except InvalidSignature as exc:
        raise LicenseVerifyError(
            "注册码签名校验不通过(可能被篡改或不是本产品签发的)"
        ) from exc
    except (ValueError, binascii.Error) as exc:
        raise LicenseVerifyError(f"注册码签名数据损坏:{exc}") from exc

    if now < claims.issued_at:
        raise LicenseVerifyError("注册码尚未生效,请检查本机系统时间")

    return claims


# ──────────────────────────────────────────────────────────────
# 按授权条目算 flag 档位
# ──────────────────────────────────────────────────────────────


def license_cap(flag: str, entitlements: frozenset[str]) -> object:
    """该 flag 在本地被允许到的档位(有对应条目 → Pro 档,否则 Community 档)。"""
    spec = FLAG_CAPACITY.get(flag)
    if spec is None:
        return None
    _typ, community, pro = spec
    entry = FLAG_ENTITLEMENT.get(flag)
    if entry is None:
        return community
    return pro if entry in entitlements else community


def flags_for_entitlements(entitlements: frozenset[str]) -> dict[str, Any]:
    """按注册码授权条目算出云端应下发的 flag 快照。

    这是「按条目解锁」,不是整档 Pro —— 注册码只带 `core`,就不该给
    `persona` / `cloud_prompt` 这些 Pro 能力。
    """
    return {flag: license_cap(flag, entitlements) for flag in FLAG_CAPACITY}


__all__ = [
    "PUBLIC_KEY_HEX",
    "TOKEN_PREFIX",
    "PAYLOAD_VERSION",
    "ENTITLEMENTS",
    "FLAG_CAPACITY",
    "FLAG_ENTITLEMENT",
    "DEFAULT_GRACE_DAYS",
    "DEFAULT_CREDITS",
    "LicenseVerifyError",
    "LicenseClaims",
    "decode_payload",
    "verify_token",
    "license_cap",
    "flags_for_entitlements",
]
