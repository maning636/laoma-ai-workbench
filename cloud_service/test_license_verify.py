"""注册码验签 · 云端侧测试 + **跨模块常量一致性闸门**。

用途:
  1. 验证 `cloud_service/billing/license_verify.py` 的验签/解析逻辑;
  2. **钉死云端常量副本与桌面端的一致性** —— 云端为了让服务端保持轻量,
     刻意不复用 `prism_backend.fastapi_app.core.license_keys`(会拖进 Electron 依赖),
     所以两边各有一份常量副本。本测试用 AST 解析桌面端源文件(不 import,零副作用),
     任何一边改了而另一边忘了改,这里直接红。

用法:
    python cloud_service/test_license_verify.py
    # 或:python -m pytest cloud_service/test_license_verify.py -q
"""

from __future__ import annotations

import ast
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cloud_service.billing import license_verify as lv  # noqa: E402

_DESKTOP_KEYS_FILE = (
    _REPO_ROOT / "prism_backend" / "fastapi_app" / "core" / "license_keys.py"
)


# ──────────────────────────────────────────────────────────────
# AST 工具:从桌面端源文件里取常量(不 import,避免拉起 Electron 依赖)
# ──────────────────────────────────────────────────────────────


def _parse_module_constants(path: Path) -> dict[str, object]:
    """把一个模块里所有「顶层常量赋值」抽出来。

    只处理字面量与简单容器;遇到调用表达式(例如 `dict(...)`)返回原样节点,
    由调用方决定怎么处理。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: dict[str, object] = {}
    for node in tree.body:
        # `X = ...` 是 Assign;`X: T = ...`(带类型注解)是 AnnAssign,两者都要收
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            try:
                out[target.id] = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                out[target.id] = value
    return out


# ──────────────────────────────────────────────────────────────
# 测试
# ──────────────────────────────────────────────────────────────


def test_desktop_constants_mirror() -> None:
    """云端常量副本必须与桌面端逐项一致。"""
    desktop = _parse_module_constants(_DESKTOP_KEYS_FILE)

    assert desktop["PUBLIC_KEY_HEX"] == lv.PUBLIC_KEY_HEX, (
        "公钥不一致:云端与桌面端必须同步(公钥换了会导致所有已签发注册码失效)"
    )
    assert tuple(desktop["ENTITLEMENTS"]) == lv.ENTITLEMENTS, "授权条目清单不一致"
    assert desktop["FLAG_CAPACITY"] == lv.FLAG_CAPACITY, "flag 容量表不一致"
    assert desktop["FLAG_ENTITLEMENT"] == lv.FLAG_ENTITLEMENT, "flag→条目映射不一致"
    assert desktop["DEFAULT_GRACE_DAYS"] == lv.DEFAULT_GRACE_DAYS, "默认宽限天数不一致"
    assert desktop.get("DEFAULT_CREDITS", 0) == lv.DEFAULT_CREDITS, "默认积分额度不一致"


def _make_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return private_key, public_hex


def _issue(private_key, **overrides) -> str:
    payload = {
        "v": lv.PAYLOAD_VERSION,
        "lid": "LIC-TEST-000001",
        "ent": ["core", "ai_cloud"],
        "iat": "2026-01-01T00:00:00+00:00",
        "exp": "2027-01-01T00:00:00+00:00",
        "grace": 7,
        "cust": "测试客户",
        "note": "",
    }
    payload.update(overrides)
    body = lv.json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    body_b64 = lv._b64u_encode(body.encode("utf-8"))
    sig = private_key.sign(body_b64.encode("ascii"))
    return f"{lv.TOKEN_PREFIX}.{body_b64}.{lv._b64u_encode(sig)}"


def test_verify_token_success() -> None:
    private_key, public_hex = _make_keypair()
    token = _issue(private_key, cr=2000)

    claims = lv.verify_token(token, public_key_hex=public_hex)

    assert claims.license_id == "LIC-TEST-000001"
    assert claims.entitlements == frozenset({"core", "ai_cloud"})
    assert claims.credits == 2000
    assert claims.grace_days == 7
    assert claims.customer == "测试客户"
    # effective_until = exp + grace
    assert claims.effective_until == claims.expires_at + timedelta(days=7)


def test_verify_token_without_credits_is_zero() -> None:
    """老版本注册码(没有 cr 字段)必须照常验签,积分按 0 处理。"""
    private_key, public_hex = _make_keypair()
    token = _issue(private_key)

    claims = lv.verify_token(token, public_key_hex=public_hex)
    assert claims.credits == 0


def _tamper_signature(sig_b64: str) -> str:
    """把签名字节真的改掉（解码 → 翻一个 bit → 重新编码）。

    为什么不能直接用字符串替换（例：把 base64 末 2 个字符换成 "AA"）：
    base64 末位字符有 4 位是**无效位**（Python 的 urlsafe_b64decode 会直接丢弃），
    所以那种改法**并不保证**签名字节真的变了 —— 当原签名末字节恰好是 0 时，
    改前改后解码出的 64 字节完全一样，注册码照样验签通过。
    Ed25519 签名的末字节只可能取 [0, 0x0F]（S 标量 < L，高 4 位恒为 0），
    于是这种写法有 **1/16 ≈ 6.25% 的概率**变成"根本没篡改" -> 用例随机红。
    （2026-10-23 CI 上就是这么炸的：test_verify_token_rejects_tampered_signature。）
    """
    raw = lv._b64u_decode(sig_b64)
    return lv._b64u_encode(bytes([raw[0] ^ 0x01]) + raw[1:])


def test_verify_token_rejects_tampered_signature() -> None:
    private_key, public_hex = _make_keypair()
    token = _issue(private_key)
    head, body, sig = token.split(".")
    tampered_sig = _tamper_signature(sig)
    tampered = f"{head}.{body}.{tampered_sig}"

    # 前提自检：篡改必须真的改掉了字节，否则这个用例测的是"没篡改能不能过"
    assert lv._b64u_decode(tampered_sig) != lv._b64u_decode(sig)

    try:
        lv.verify_token(tampered, public_key_hex=public_hex)
    except lv.LicenseVerifyError as exc:
        assert "签名校验不通过" in str(exc)
    else:
        raise AssertionError("篡改后的注册码必须被拒绝")


def test_verify_token_rejects_tampered_payload() -> None:
    """篡改载荷（改客户名）也必须被拒绝 —— 签名是盖在载荷 base64 上的。

    这条攻击路径原来没被覆盖：签名用例只动了签名段，没动载荷段。
    """
    private_key, public_hex = _make_keypair()
    token = _issue(private_key)
    head, body, sig = token.split(".")

    payload = lv.json.loads(lv._b64u_decode(body))
    payload["cust"] = "攻击者"
    body2 = lv._b64u_encode(
        lv.json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    tampered = f"{head}.{body2}.{sig}"

    try:
        lv.verify_token(tampered, public_key_hex=public_hex)
    except lv.LicenseVerifyError as exc:
        assert "签名校验不通过" in str(exc)
    else:
        raise AssertionError("篡改载荷后的注册码必须被拒绝")


def test_verify_token_rejects_bad_format() -> None:
    for bad in ("", "not-a-token", "PRISM1.only-two", "WRONG.body.sig"):
        try:
            lv.verify_token(bad)
        except lv.LicenseVerifyError:
            pass
        else:
            raise AssertionError(f"非法注册码必须被拒绝: {bad!r}")


def test_verify_token_rejects_future_issued_at() -> None:
    private_key, public_hex = _make_keypair()
    future = datetime.now(timezone.utc) + timedelta(days=1)
    token = _issue(private_key, iat=future.isoformat(timespec="seconds"))

    try:
        lv.verify_token(token, public_key_hex=public_hex)
    except lv.LicenseVerifyError as exc:
        assert "尚未生效" in str(exc)
    else:
        raise AssertionError("未来签发的注册码必须被拒绝")


def test_verify_token_rejects_bad_credits() -> None:
    private_key, public_hex = _make_keypair()
    for bad in (-1, "abc"):
        token = _issue(private_key, cr=bad)
        try:
            lv.verify_token(token, public_key_hex=public_hex)
        except lv.LicenseVerifyError:
            pass
        else:
            raise AssertionError(f"非法 credits 必须被拒绝: {bad!r}")


def test_flags_for_entitlements_is_subset_scoped() -> None:
    """只带 core 条目时,不该给 ai_cloud / persona 这类 Pro 能力。"""
    flags = lv.flags_for_entitlements(frozenset({"core"}))

    assert flags["max_accounts"] == -1          # core 解锁
    assert flags["data_recovery"] is True        # core 解锁
    assert flags["ai_mode"] == "local_key"       # 无 ai_cloud → 不给云端能力
    assert flags["cloud_prompt"] is False
    assert flags["persona"] is False
    assert flags["max_platforms"] == 3          # 无 multi_platform → community 档


def test_flags_for_entitlements_full() -> None:
    flags = lv.flags_for_entitlements(
        frozenset({"core", "ai_cloud", "multi_platform", "persona", "agent", "campaign"})
    )
    assert flags["ai_mode"] == "cloud"
    assert flags["image_gen"] == "cloud"
    assert flags["max_platforms"] == 8
    assert flags["persona"] is True
    assert flags["stream_chat"] is True
    assert flags["agent_quota"] == 2
    assert flags["campaign_orchestration"] is True


def run() -> int:
    """cloud_service 的 pytest 适配层约定:自运行脚本风格,返回失败计数。

    (`cloud_service/conftest.py` 会把本文件当作**一个** pytest 用例,
    调用 `run()` 并断言返回 0。)
    """
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[FAIL] {name}: {exc}")
        else:
            print(f"[PASS] {name}")
    print()
    print("RESULT:", "PASS" if failures == 0 else f"FAIL ({failures})")
    return failures


if __name__ == "__main__":
    sys.exit(run())
