"""注册码(license)本地校验 —— **离线可用**,Ed25519 签名。

设计要点
--------
1. **本地验签**:注册码由签发端用 Ed25519 私钥签名,客户端用**公钥**验签。
   验签不联网,所以断网也能用(满足"离线宽限"的前提)。
2. **固定期限(D3)**:payload 里带 `expires_at`;到期后进入 `grace_days` 宽限期;
   宽限期满 → `expired` → **只读**(D4:能看不能新增)。
3. **双轨判定(D1=C)**:`allowed(功能) = 注册码授权条目 ∩ 订阅配额`。
   注册码决定**本地**能用什么(条目 → flag 档位),云端订阅决定**云端**给多少配额,
   两者取更严格的那个。实现在 `effective_flags()`。
4. **默认不绑机器(R1=A)**:payload 不含设备指纹,一码通用。

安全边界
--------
- 本模块**只验签**,不签发。私钥不在仓库里。
- 明文 token 存本地(license 本来就要粘贴给用户,不是秘密);
  完整性由签名保证,保密性不保证。
- 时钟回拨防护:记录 `last_seen_at`,本机时间比上次倒退超过阈值 → 判为回拨,license 失效。
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

from .license_keys import (
    DEFAULT_CREDITS,
    DEFAULT_GRACE_DAYS,
    ENTITLEMENTS,
    FLAG_CAPACITY,
    FLAG_ENTITLEMENT,
    PUBLIC_KEY_HEX,
)

logger = logging.getLogger(__name__)

#: license token 前缀(格式版本)
TOKEN_PREFIX = "PRISM1"

#: payload 格式版本
PAYLOAD_VERSION = 1

#: 时钟回拨判定容差(小时)。本机时间比上次成功校验倒退超过这个量 → 判为回拨
CLOCK_ROLLBACK_TOLERANCE_HOURS = 24

#: license 状态
STATUS_MISSING = "missing"            # 从未输入注册码
STATUS_ACTIVE = "active"              # 有效期内
STATUS_GRACE = "grace"                # 已到期,在宽限期内(仍可写)
STATUS_EXPIRED = "expired"            # 已到期且宽限期满 → 只读
STATUS_INVALID = "invalid"            # 格式错 / 签名不通过 / 条目非法
STATUS_NOT_YET_VALID = "not_yet_valid"  # iat 在未来(时钟问题或伪造)

#: license 本地存储文件名(落在数据目录,与 paths.json 同级)
LICENSE_FILE_NAME = "license.json"


# ──────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LicensePayload:
    """注册码里签名的载荷。"""

    version: int
    license_id: str
    entitlements: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    grace_days: int
    customer: str = ""
    note: str = ""
    credits: int = DEFAULT_CREDITS

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.version,
            "lid": self.license_id,
            "ent": sorted(self.entitlements),
            "iat": self.issued_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "exp": self.expires_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "grace": self.grace_days,
            "cust": self.customer,
            "note": self.note,
            "cr": self.credits,
        }


@dataclass(frozen=True)
class LicenseState:
    """注册码的当前状态(客户端判定与 UI 展示都用它)。"""

    status: str
    valid: bool = False                      # 签名有效(不代表未过期)
    entitlements: frozenset[str] = field(default_factory=frozenset)
    expires_at: Optional[datetime] = None
    grace_days: int = DEFAULT_GRACE_DAYS
    read_only: bool = False                  # True → 只读(能看不能新增)
    license_id: str = ""
    customer: str = ""
    message: str = ""
    has_token: bool = False
    credits: int = DEFAULT_CREDITS

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE

    @property
    def is_grace(self) -> bool:
        return self.status == STATUS_GRACE

    @property
    def is_expired(self) -> bool:
        return self.status == STATUS_EXPIRED

    @property
    def has_any(self) -> bool:
        """是否曾经有过一个注册码(哪怕已过期)—— 只读判定用。"""
        return self.has_token and self.valid

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "valid": self.valid,
            "entitlements": sorted(self.entitlements),
            "expiresAt": (
                self.expires_at.astimezone(timezone.utc).isoformat(timespec="seconds")
                if self.expires_at else None
            ),
            "graceDays": self.grace_days,
            "readOnly": self.read_only,
            "licenseId": self.license_id,
            "customer": self.customer,
            "message": self.message,
            "hasToken": self.has_token,
            "credits": self.credits,
        }


# ──────────────────────────────────────────────────────────────
# 编解码
# ──────────────────────────────────────────────────────────────

def _b64u_decode(s: str) -> bytes:
    """base64url 解码(容忍缺省 padding)。"""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def encode_license(payload: dict[str, Any], private_key: ed25519.Ed25519PrivateKey) -> str:
    """把 payload 签成 license token。

    ⚠️ **签发端专用**,私钥绝不能进仓库。客户端不需要这个函数。
    签名对象是 payload 的 base64url 文本(而不是 JSON 字节),避免序列化歧义。
    """
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    body_b64 = _b64u_encode(body.encode("utf-8"))
    sig = private_key.sign(body_b64.encode("ascii"))
    return f"{TOKEN_PREFIX}.{body_b64}.{_b64u_encode(sig)}"


def _parse_ts(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("时间字段缺失")
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def decode_payload(body_b64: str) -> LicensePayload:
    """解出 payload 并做结构校验(不验签)。"""
    raw = json.loads(_b64u_decode(body_b64).decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("payload 不是对象")
    version = int(raw.get("v", 0))
    if version != PAYLOAD_VERSION:
        raise ValueError(f"不支持的 payload 版本: {version}")
    ents_raw = raw.get("ent") or []
    if not isinstance(ents_raw, list):
        raise ValueError("ent 必须是数组")
    unknown = [e for e in ents_raw if e not in ENTITLEMENTS]
    if unknown:
        raise ValueError(f"未知授权条目: {unknown}")
    if not ents_raw:
        raise ValueError("注册码未包含任何授权条目")
    grace = int(raw.get("grace", DEFAULT_GRACE_DAYS))
    if grace < 0:
        raise ValueError("grace 不能为负")
    # 积分额度:老版本注册码没有 `cr` 字段 → 按 0 处理(向后兼容)
    try:
        credits = int(raw.get("cr", DEFAULT_CREDITS))
    except (TypeError, ValueError):
        raise ValueError("cr 必须是整数")
    if credits < 0:
        raise ValueError("cr 不能为负")
    return LicensePayload(
        version=version,
        license_id=str(raw.get("lid") or ""),
        entitlements=frozenset(str(e) for e in ents_raw),
        issued_at=_parse_ts(raw.get("iat")),
        expires_at=_parse_ts(raw.get("exp")),
        grace_days=grace,
        customer=str(raw.get("cust") or ""),
        note=str(raw.get("note") or ""),
        credits=credits,
    )


# ──────────────────────────────────────────────────────────────
# 验签与状态判定
# ──────────────────────────────────────────────────────────────

def verify_license(
    token: str,
    *,
    public_key_hex: str = PUBLIC_KEY_HEX,
    now: Optional[datetime] = None,
) -> LicenseState:
    """验签并算出当前状态。**不抛异常**,失败一律返回对应状态。"""
    now = now or datetime.now(timezone.utc)
    token = (token or "").strip()

    if not token:
        return LicenseState(status=STATUS_MISSING, message="尚未输入注册码")

    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        return LicenseState(
            status=STATUS_INVALID, has_token=True,
            message="注册码格式不正确(应以 PRISM1. 开头)",
        )

    _, body_b64, sig_b64 = parts

    try:
        payload = decode_payload(body_b64)
    except Exception as exc:  # noqa: BLE001
        return LicenseState(
            status=STATUS_INVALID, has_token=True,
            message=f"注册码内容无法解析:{exc}",
        )

    try:
        public_bytes = bytes.fromhex(public_key_hex)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_bytes)
        public_key.verify(_b64u_decode(sig_b64), body_b64.encode("ascii"))
    except InvalidSignature:
        return LicenseState(
            status=STATUS_INVALID, has_token=True,
            message="注册码签名校验不通过(可能被篡改或不是本产品签发的)",
        )
    except (ValueError, binascii.Error) as exc:
        return LicenseState(
            status=STATUS_INVALID, has_token=True,
            message=f"注册码签名数据损坏:{exc}",
        )

    # ── 签名有效,接下来只看时间 ──────────────────────────────
    if now < payload.issued_at:
        return LicenseState(
            status=STATUS_NOT_YET_VALID, valid=True,
            entitlements=payload.entitlements, expires_at=payload.expires_at,
            grace_days=payload.grace_days, license_id=payload.license_id,
            customer=payload.customer, has_token=True, credits=payload.credits,
            message="注册码尚未生效,请检查本机系统时间",
        )

    grace_end = payload.expires_at + timedelta(days=payload.grace_days)
    if now < payload.expires_at:
        return LicenseState(
            status=STATUS_ACTIVE, valid=True,
            entitlements=payload.entitlements, expires_at=payload.expires_at,
            grace_days=payload.grace_days, license_id=payload.license_id,
            customer=payload.customer, has_token=True, credits=payload.credits,
            message=f"注册码有效,到期时间 {payload.expires_at.date().isoformat()}",
        )

    if now < grace_end:
        days_left = (grace_end - now).days
        return LicenseState(
            status=STATUS_GRACE, valid=True,
            entitlements=payload.entitlements, expires_at=payload.expires_at,
            grace_days=payload.grace_days, license_id=payload.license_id,
            customer=payload.customer, has_token=True, credits=payload.credits,
            message=f"注册码已到期,宽限期内还可继续使用(剩余约 {days_left} 天)",
        )

    return LicenseState(
        status=STATUS_EXPIRED, valid=True, read_only=True,
        entitlements=payload.entitlements, expires_at=payload.expires_at,
        grace_days=payload.grace_days, license_id=payload.license_id,
        customer=payload.customer, has_token=True, credits=payload.credits,
        message="注册码已过期,当前为只读模式(可查看,不能新增)",
    )


# ──────────────────────────────────────────────────────────────
# 本地存储
# ──────────────────────────────────────────────────────────────

def _data_dir() -> Path:
    """license 的存放目录(与 paths.json 同级)。"""
    try:
        from .paths import get_data_dir

        return Path(get_data_dir())
    except Exception:  # noqa: BLE001 - paths 不可用时退回环境变量/临时目录
        env = (os.getenv("LAOMA_DATA_DIR") or "").strip()
        if env:
            return Path(env)
        return Path(tempfile.gettempdir()) / "prism-fusion"


def license_file_path() -> Path:
    return _data_dir() / LICENSE_FILE_NAME


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """原子写(与 paths.json 同一套路):临时文件 + os.replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_license(
    token: str,
    *,
    public_key_hex: str = PUBLIC_KEY_HEX,
    now: Optional[datetime] = None,
) -> LicenseState:
    """保存注册码(会先验签;验签不过**不落盘**)。

    `public_key_hex` 可注入,便于测试用临时密钥对;生产路径一律用默认公钥。
    """
    state = verify_license(token, public_key_hex=public_key_hex, now=now)
    if not state.valid:
        return state
    path = license_file_path()
    payload = {
        "token": token.strip(),
        "savedAt": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "lastSeenAt": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(
            timespec="seconds"
        ),
    }
    try:
        _atomic_write_json(path, payload)
    except OSError as exc:
        logger.warning("[license] 写入失败:%s", exc)
        return LicenseState(
            status=STATUS_INVALID, valid=True, message=f"注册码保存失败:{exc}"
        )
    return state


def clear_license() -> bool:
    """清除本地注册码。"""
    path = license_file_path()
    try:
        if path.exists():
            path.unlink()
            return True
    except OSError as exc:
        logger.warning("[license] 删除失败:%s", exc)
    return False


def load_license_token() -> str:
    """读取本地保存的注册码**原文**(token)。

    ⚠️ 只供**后端内部**使用 —— 例如把注册码同步到云端开通能力。
    原文**不要**出现在任何 HTTP 响应里:注册码本身就是发给用户的凭据,
    但没必要到处传。前端只拿 `LicenseState.to_dict()` 里的脱敏字段。
    """
    path = license_file_path()
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[license] 读取 token 失败:%s", exc)
        return ""
    return str(data.get("token") or "").strip()


def load_license(
    *,
    public_key_hex: str = PUBLIC_KEY_HEX,
    now: Optional[datetime] = None,
    touch: bool = True,
) -> LicenseState:
    """读取本地注册码并验签。带**时钟回拨**防护。

    `public_key_hex` 可注入,便于测试用临时密钥对;生产路径一律用默认公钥。
    `touch=False` 表示**只读不改**:不刷新 `lastSeenAt`(只读守卫每次拦截都
    调本函数,回写磁盘没意义,还会白白多一次写)。
    """
    path = license_file_path()
    if not path.is_file():
        return LicenseState(status=STATUS_MISSING, message="尚未输入注册码")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[license] 读取失败:%s", exc)
        return LicenseState(status=STATUS_INVALID, has_token=True, message=f"本地注册码文件损坏:{exc}")

    token = str(data.get("token") or "")
    state = verify_license(token, public_key_hex=public_key_hex, now=now)
    if not state.has_token:
        state = LicenseState(
            status=STATUS_INVALID, valid=state.valid, has_token=True,
            entitlements=state.entitlements, expires_at=state.expires_at,
            grace_days=state.grace_days, license_id=state.license_id,
            customer=state.customer, message=state.message,
            credits=state.credits,
        )

    # ── 时钟回拨防护 ────────────────────────────────────────
    last_seen_raw = str(data.get("lastSeenAt") or "")
    if last_seen_raw and state.valid:
        try:
            last_seen = _parse_ts(last_seen_raw)
            current = now or datetime.now(timezone.utc)
            if current < last_seen - timedelta(hours=CLOCK_ROLLBACK_TOLERANCE_HOURS):
                return LicenseState(
                    status=STATUS_INVALID, valid=True, has_token=True,
                    entitlements=state.entitlements, expires_at=state.expires_at,
                    grace_days=state.grace_days, license_id=state.license_id,
                    customer=state.customer, credits=state.credits,
                    message="检测到系统时间被回拨,注册码已暂停使用,请校正系统时间",
                )
        except Exception:  # noqa: BLE001 - lastSeenAt 坏了不算回拨
            pass

    # 刷新 lastSeenAt(成功读到即视为"设备在正常时间线上")
    if state.valid and touch:
        try:
            data["lastSeenAt"] = (now or datetime.now(timezone.utc)).astimezone(
                timezone.utc
            ).isoformat(timespec="seconds")
            _atomic_write_json(path, data)
        except OSError:
            pass

    return state


# ──────────────────────────────────────────────────────────────
# D1=C 双轨判定
# ──────────────────────────────────────────────────────────────

def _restrict_numeric(a: object, b: object) -> object:
    """数值配额取交集(-1 = 无限,与任何具体值取那个具体值)。"""
    try:
        ai = int(a)  # type: ignore[arg-type]
        bi = int(b)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return a
    if ai == -1:
        return bi
    if bi == -1:
        return ai
    return min(ai, bi)


def _restrict_bool(a: object, b: object) -> object:
    return bool(a) and bool(b)


def _restrict_mode(a: object, b: object) -> object:
    """模式取更严格者。

    `local_key` = 本地模式(自配 key,不需要云端),`cloud` = 云端能力(需付费)。
    只要**任一边**没给云端能力,结果就是 local_key。
    """
    if a == "cloud" and b == "cloud":
        return "cloud"
    return "local_key"


_RESTRICTORS = {
    "numeric": _restrict_numeric,
    "bool": _restrict_bool,
    "mode": _restrict_mode,
}


def license_cap(flag: str, entitlements: frozenset[str]) -> object:
    """注册码维度:该 flag 在本地被允许到的档位。

    有对应条目 → 取 Pro 档;没有(或条目不存在)→ 取 Community 档。
    """
    spec = FLAG_CAPACITY.get(flag)
    if spec is None:
        return None
    typ, community, pro = spec
    entry = FLAG_ENTITLEMENT.get(flag)
    if entry is None:
        return community
    return pro if entry in entitlements else community


def effective_flags(
    license_state: LicenseState,
    cloud_flags: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """D1=C 双轨交集:注册码授权条目 ∩ 云端订阅配额。

    参数:
      license_state: 本地注册码状态
      cloud_flags:  云端下发的 flag 快照(取不到时按 Community 兜底)

    返回:每个 flag 的最终生效值。
    """
    cloud_flags = cloud_flags or {}
    out: dict[str, Any] = {}
    for flag, (typ, community, _pro) in FLAG_CAPACITY.items():
        lic_val = license_cap(flag, license_state.entitlements)
        cloud_val = cloud_flags.get(flag, community)
        out[flag] = _RESTRICTORS[typ](lic_val, cloud_val)
    return out


def feature_allowed(
    flag: str,
    license_state: LicenseState,
    cloud_flags: Optional[dict[str, Any]] = None,
) -> bool:
    """某个 flag 当前是否可用(按最终生效值判定)。"""
    final = effective_flags(license_state, cloud_flags)
    value = final.get(flag)
    spec = FLAG_CAPACITY.get(flag)
    if spec is None:
        return False
    typ = spec[0]
    if typ == "numeric":
        try:
            return int(value) != 0  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    if typ == "bool":
        return bool(value)
    return bool(value)


__all__ = [
    "TOKEN_PREFIX",
    "PAYLOAD_VERSION",
    "STATUS_MISSING",
    "STATUS_ACTIVE",
    "STATUS_GRACE",
    "STATUS_EXPIRED",
    "STATUS_INVALID",
    "STATUS_NOT_YET_VALID",
    "LicensePayload",
    "LicenseState",
    "encode_license",
    "decode_payload",
    "verify_license",
    "save_license",
    "clear_license",
    "load_license",
    "load_license_token",
    "license_file_path",
    "license_cap",
    "effective_flags",
    "feature_allowed",
]
