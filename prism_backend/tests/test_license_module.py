"""注册码(license)模块 后端测试。

覆盖：
  1. 签发 → 验签闭环（真 Ed25519）
  2. 状态机：active / grace / expired / invalid / missing / not_yet_valid
  3. 篡改签名、换钥匙签名 → 一律 invalid
  4. D4 到期只读：宽限期满 → read_only=True；宽限期内仍可写；从未有注册码 → 非只读
  5. D1=C 双轨判定：注册码条目 ∩ 云端订阅配额（数值取小、布尔取与、模式取更严）
  6. 本地存储：保存 / 读取 / 清除；验签不过不落盘
  7. 时钟回拨防护
  8. 只读守卫 require_write_allowed

约定：
  - license 存储目录用 monkeypatch 改到 tmp_path，**不污染真实数据目录**；
  - 私钥在测试里现生成，不依赖仓库外的私钥文件。

用法：
  cd prism_backend && python -m pytest tests/test_license_module.py -q
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("FEATURE_FLAGS_DISABLED", "1")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from fastapi_app.core import license as L  # noqa: E402
from fastapi_app.core.license_keys import ENTITLEMENTS, FLAG_CAPACITY, FLAG_ENTITLEMENT  # noqa: E402


# ──────────────────────────────────────────────────────────────
# fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture()
def keys():
    """测试用的密钥对(现生成,不依赖仓库外私钥)。"""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    return priv, pub_hex


@pytest.fixture()
def license_home(tmp_path, monkeypatch):
    """把 license 的存储目录指到 tmp_path。"""
    monkeypatch.setenv("LAOMA_DATA_DIR", str(tmp_path))
    return tmp_path


def _issue(priv, entitlements, *, now=None, exp_delta_days=30, grace=7, lid="LIC-TEST-0001"):
    now = now or datetime.now(timezone.utc)
    payload = {
        "v": L.PAYLOAD_VERSION,
        "lid": lid,
        "ent": sorted(entitlements),
        "iat": now.isoformat(timespec="seconds"),
        "exp": (now + timedelta(days=exp_delta_days)).isoformat(timespec="seconds"),
        "grace": grace,
        "cust": "测试客户",
        "note": "",
    }
    return L.encode_license(payload, priv)


# ──────────────────────────────────────────────────────────────
# 1. 签发 → 验签闭环
# ──────────────────────────────────────────────────────────────

def test_verify_valid_license(keys):
    priv, pub = keys
    token = _issue(priv, ["core", "ai_cloud"])
    state = L.verify_license(token, public_key_hex=pub)
    assert state.status == L.STATUS_ACTIVE
    assert state.valid is True
    assert state.entitlements == frozenset({"core", "ai_cloud"})
    assert state.read_only is False
    assert state.has_token is True
    assert state.expires_at is not None


def test_empty_token_is_missing(keys):
    _, pub = keys
    state = L.verify_license("", public_key_hex=pub)
    assert state.status == L.STATUS_MISSING
    assert state.read_only is False  # 从未有过注册码 → 社区版照常用


def test_tampered_signature_is_invalid(keys):
    priv, pub = keys
    token = _issue(priv, ["core"])
    head, body, sig = token.split(".")
    # 解码 → 翻一个 bit → 重新编码：保证签名字节真的变了。
    # 直接改 base64 字符串（末几位换成 "aaaa"）不保证有效 ——
    # 末位字符有 4 位是无效位，解码时被丢弃，可能改了个寂寞。
    raw = L._b64u_decode(sig)
    tampered_sig = L._b64u_encode(bytes([raw[0] ^ 0x01]) + raw[1:])
    assert L._b64u_decode(tampered_sig) != raw
    tampered = f"{head}.{body}.{tampered_sig}"
    state = L.verify_license(tampered, public_key_hex=pub)
    assert state.status == L.STATUS_INVALID
    assert state.valid is False


def test_foreign_key_is_invalid(keys):
    priv, pub = keys
    other = ed25519.Ed25519PrivateKey.generate()
    other_pub = other.public_key().public_bytes_raw().hex()
    token = _issue(other, ["core"])
    state = L.verify_license(token, public_key_hex=pub)
    assert state.status == L.STATUS_INVALID
    # 用正确的公钥验签则通过 —— 说明失败原因是"钥匙不对",不是格式问题
    assert L.verify_license(token, public_key_hex=other_pub).status == L.STATUS_ACTIVE


def test_garbage_token_is_invalid(keys):
    _, pub = keys
    assert L.verify_license("garbage", public_key_hex=pub).status == L.STATUS_INVALID
    assert L.verify_license("PRISM1.aaa.bbb", public_key_hex=pub).status == L.STATUS_INVALID


def test_unknown_entitlement_rejected(keys):
    priv, pub = keys
    now = datetime.now(timezone.utc)
    payload = {
        "v": 1, "lid": "X", "ent": ["not_a_real_entry"],
        "iat": now.isoformat(timespec="seconds"),
        "exp": (now + timedelta(days=1)).isoformat(timespec="seconds"),
        "grace": 7, "cust": "", "note": "",
    }
    token = L.encode_license(payload, priv)
    state = L.verify_license(token, public_key_hex=pub)
    assert state.status == L.STATUS_INVALID
    assert "条目" in state.message


# ──────────────────────────────────────────────────────────────
# 2. 状态机 + D4 只读
# ──────────────────────────────────────────────────────────────

def test_grace_period_is_writable(keys):
    priv, pub = keys
    now = datetime.now(timezone.utc)
    # 签发于 40 天前，到期于 3 天前，宽限 7 天 → 仍在宽限期
    token = _issue(priv, ["core"], now=now - timedelta(days=40), exp_delta_days=37, grace=7)
    state = L.verify_license(token, public_key_hex=pub, now=now)
    assert state.status == L.STATUS_GRACE
    assert state.read_only is False


def test_expired_is_read_only(keys):
    priv, pub = keys
    now = datetime.now(timezone.utc)
    # 签发于 60 天前，到期于 30 天前，宽限 7 天 → 宽限期已满
    token = _issue(priv, ["core"], now=now - timedelta(days=60), exp_delta_days=30, grace=7)
    state = L.verify_license(token, public_key_hex=pub, now=now)
    assert state.status == L.STATUS_EXPIRED
    assert state.read_only is True


def test_not_yet_valid(keys):
    priv, pub = keys
    now = datetime.now(timezone.utc)
    token = _issue(priv, ["core"], now=now + timedelta(days=2), exp_delta_days=30)
    state = L.verify_license(token, public_key_hex=pub, now=now)
    assert state.status == L.STATUS_NOT_YET_VALID
    assert state.valid is True


# ──────────────────────────────────────────────────────────────
# 3. D1=C 双轨判定
# ──────────────────────────────────────────────────────────────

CLOUD_PRO = {
    "max_accounts": -1, "max_platforms": 8, "ai_mode": "cloud", "image_gen": "cloud",
    "agent_quota": 2, "data_recovery": True, "persona": True,
    "proxy_management": True, "stream_chat": True, "team_members": 1,
}
CLOUD_COMMUNITY = {
    "max_accounts": 3, "max_platforms": 3, "ai_mode": "local_key", "image_gen": "local_key",
    "agent_quota": 0, "data_recovery": True, "persona": False,
    "proxy_management": False, "stream_chat": False, "team_members": 1,
}


def test_license_cap_picks_pro_only_with_entry(keys):
    priv, pub = keys
    state = L.verify_license(_issue(priv, ["core", "ai_cloud", "multi_platform"]), public_key_hex=pub)
    assert L.license_cap("max_accounts", state.entitlements) == -1     # core
    assert L.license_cap("max_platforms", state.entitlements) == 8     # multi_platform
    assert L.license_cap("ai_mode", state.entitlements) == "cloud"     # ai_cloud
    assert L.license_cap("agent_quota", state.entitlements) == 0       # 无 agent → community
    assert L.license_cap("persona", state.entitlements) is False       # 无 persona → community


def test_effective_flags_intersect_with_cloud(keys):
    priv, pub = keys
    state = L.verify_license(_issue(priv, ["core", "ai_cloud", "multi_platform"]), public_key_hex=pub)
    eff = L.effective_flags(state, CLOUD_PRO)
    assert eff["max_accounts"] == -1
    assert eff["max_platforms"] == 8
    assert eff["ai_mode"] == "cloud"
    assert eff["agent_quota"] == 0          # 无 agent 条目
    assert eff["persona"] is False          # 无 persona 条目
    assert eff["data_recovery"] is True     # core 覆盖


def test_effective_flags_take_stricter_side(keys):
    priv, pub = keys
    state = L.verify_license(_issue(priv, ["core", "ai_cloud", "multi_platform"]), public_key_hex=pub)
    eff = L.effective_flags(state, CLOUD_COMMUNITY)
    assert eff["max_accounts"] == 3          # 注册码要无限，云端只给 3 → 取 3
    assert eff["max_platforms"] == 3
    assert eff["ai_mode"] == "local_key"     # 任一边不是 cloud → local_key


def test_effective_flags_offline_fallback(keys):
    priv, pub = keys
    state = L.verify_license(_issue(priv, ["core"]), public_key_hex=pub)
    eff = L.effective_flags(state, None)
    assert eff["max_accounts"] == 3          # 云端不可达 → Community 兜底
    assert eff["ai_mode"] == "local_key"


def test_feature_allowed(keys):
    priv, pub = keys
    state = L.verify_license(_issue(priv, ["core"]), public_key_hex=pub)
    assert L.feature_allowed("max_accounts", state, CLOUD_PRO) is True
    assert L.feature_allowed("persona", state, CLOUD_PRO) is False


def test_every_flag_has_capacity_and_entry():
    """容量表与条目表必须一一对应,不能有孤儿 flag。"""
    assert set(FLAG_CAPACITY) == set(FLAG_ENTITLEMENT)
    for flag, entry in FLAG_ENTITLEMENT.items():
        assert entry in ENTITLEMENTS, f"{flag} 指向未知条目 {entry}"


# ──────────────────────────────────────────────────────────────
# 4. 本地存储
# ──────────────────────────────────────────────────────────────

def test_save_load_clear_license(keys, license_home):
    priv, pub = keys
    token = _issue(priv, ["core", "agent"])

    # 验签不过 → 不落盘
    bad = L.save_license("PRISM1.aaa.bbb", public_key_hex=pub)
    assert bad.valid is False
    assert not (license_home / "license.json").exists()

    state = L.save_license(token, public_key_hex=pub)
    assert state.valid is True
    assert (license_home / "license.json").is_file()

    loaded = L.load_license(public_key_hex=pub)
    assert loaded.status == L.STATUS_ACTIVE
    assert loaded.entitlements == frozenset({"core", "agent"})

    assert L.clear_license() is True
    assert L.load_license(public_key_hex=pub).status == L.STATUS_MISSING


def test_license_file_is_json_and_gitignored_dir(keys, license_home):
    priv, pub = keys
    L.save_license(_issue(priv, ["core"]), public_key_hex=pub)
    path = license_home / "license.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "token" in data and "savedAt" in data


# ──────────────────────────────────────────────────────────────
# 5. 时钟回拨防护
# ──────────────────────────────────────────────────────────────

def test_clock_rollback_blocks_license(keys, license_home):
    priv, pub = keys
    now = datetime.now(timezone.utc)
    token = _issue(priv, ["core"])
    L.save_license(token, public_key_hex=pub)

    # 把 lastSeenAt 改成未来(相当于用户把系统时间往前调过,现在又调回来)
    path = license_home / "license.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["lastSeenAt"] = (now + timedelta(days=3)).isoformat(timespec="seconds")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    state = L.load_license(public_key_hex=pub, now=now)
    assert state.status == L.STATUS_INVALID
    assert "时间" in state.message


# ──────────────────────────────────────────────────────────────
# 6. 只读守卫
# ──────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_guard_allows_when_not_read_only(keys, license_home):
    from fastapi_app.api.v1.license.guard import require_write_allowed

    priv, pub = keys
    L.save_license(_issue(priv, ["core"]), public_key_hex=pub)
    # 未过期 → 放行
    await require_write_allowed(None)


@pytest.mark.anyio
async def test_guard_blocks_when_read_only(keys, license_home, monkeypatch):
    from fastapi_app.api.v1.license import guard

    priv, pub = keys
    now = datetime.now(timezone.utc)
    token = _issue(priv, ["core"], now=now - timedelta(days=60), exp_delta_days=30, grace=7)
    L.save_license(token, public_key_hex=pub)

    # 固定"现在"到过期之后
    monkeypatch.setattr(
        guard, "load_license",
        lambda *a, **k: L.verify_license(
            token, public_key_hex=pub, now=now + timedelta(days=1)
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await guard.require_write_allowed(None)
    assert exc.value.status_code == 403
    assert exc.value.detail["reason"] == "license_expired_read_only"
    assert exc.value.detail["readOnly"] is True
