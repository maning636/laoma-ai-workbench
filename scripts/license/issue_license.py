"""注册码签发端 —— 用 Ed25519 私钥签发 license token。

⚠️ **私钥绝不入库**。本脚本读取仓库外的私钥文件,签发后只输出 token。

用法:
    # 年卡,含 core + ai_cloud + multi_platform
    python scripts/license/issue_license.py \
        --key "D:\\Prism-Fusion-Backup\\license-keys\\prism_license_ed25519.pem" \
        --plan year --entitlements core,ai_cloud,multi_platform \
        --customer "马哥" --note "年卡"

    # 季卡 + 月卡
    python scripts/license/issue_license.py --key <私钥> --plan quarter --entitlements core,agent
    python scripts/license/issue_license.py --key <私钥> --plan month  --entitlements core

    # 指定到期日 + 自定义宽限
    python scripts/license/issue_license.py --key <私钥> --expires 2027-01-31 --grace 14 \
        --entitlements core,ai_cloud

    # 写到文件(不打印到 stdout)
    python scripts/license/issue_license.py --key <私钥> --plan year --entitlements core --out D:\\lic.txt

期限(D3):年卡 / 季卡 / 月卡,也可用 --expires 指定具体日期。
宽限:到期后仍可继续使用的天数,默认 7 天(见 license_keys.DEFAULT_GRACE_DAYS)。

私钥位置可用环境变量 `PRISM_LICENSE_KEY` 指定,省得每次敲长路径。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cryptography.hazmat.primitives import serialization  # noqa: E402

from prism_backend.fastapi_app.core.license import (  # noqa: E402
    PAYLOAD_VERSION,
    encode_license,
)
from prism_backend.fastapi_app.core.license_keys import (  # noqa: E402
    DEFAULT_GRACE_DAYS,
    ENTITLEMENTS,
)

#: D3 固定期限
PLAN_DAYS = {"year": 365, "quarter": 90, "month": 30}

#: 私钥文件默认位置(仓库外)
DEFAULT_KEY = Path(r"D:\Prism-Fusion-Backup\license-keys\prism_license_ed25519.pem")


def load_private_key(path: Path):
    raw = path.read_bytes()
    key = serialization.load_pem_private_key(raw, password=None)
    return key


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="签发 Prism-Fusion 注册码")
    ap.add_argument(
        "--key",
        default=os.getenv("PRISM_LICENSE_KEY") or str(DEFAULT_KEY),
        help="Ed25519 私钥 PEM 路径(默认读环境变量 PRISM_LICENSE_KEY)",
    )
    ap.add_argument(
        "--entitlements",
        required=True,
        help="授权条目,逗号分隔。可选:" + ",".join(ENTITLEMENTS),
    )
    ap.add_argument("--plan", choices=sorted(PLAN_DAYS), help="固定期限:year/quarter/month")
    ap.add_argument("--expires", help="指定到期日 YYYY-MM-DD(与 --plan 二选一)")
    ap.add_argument(
        "--grace", type=int, default=DEFAULT_GRACE_DAYS,
        help=f"到期后宽限天数(默认 {DEFAULT_GRACE_DAYS})",
    )
    ap.add_argument("--customer", default="", help="客户标识(可选)")
    ap.add_argument("--note", default="", help="备注(可选)")
    ap.add_argument("--license-id", default="", help="注册码 ID(默认自动生成)")
    ap.add_argument("--out", help="把 token 写到文件而不是 stdout")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出签发结果")
    args = ap.parse_args(argv)

    # ── 校验参数 ────────────────────────────────────────────
    ents = [e.strip() for e in args.entitlements.split(",") if e.strip()]
    unknown = [e for e in ents if e not in ENTITLEMENTS]
    if unknown:
        print(f"ERROR: unknown entitlements {unknown}; allowed = {list(ENTITLEMENTS)}")
        return 1
    if not ents:
        print("ERROR: --entitlements 不能为空")
        return 1
    if args.plan and args.expires:
        print("ERROR: --plan 与 --expires 二选一")
        return 1
    if not args.plan and not args.expires:
        print("ERROR: 必须给 --plan 或 --expires")
        return 1
    if args.grace < 0:
        print("ERROR: --grace 不能为负")
        return 1

    now = datetime.now(timezone.utc)
    if args.plan:
        expires_at = now + timedelta(days=PLAN_DAYS[args.plan])
    else:
        try:
            expires_at = datetime.fromisoformat(args.expires).replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"ERROR: --expires 不是合法日期: {args.expires}")
            return 1
        if expires_at <= now:
            print("ERROR: --expires 必须在未来")
            return 1

    key_path = Path(args.key)
    if not key_path.is_file():
        print(f"ERROR: private key not found: {key_path}")
        print("  生成密钥对:python scripts/license/keygen.py")
        return 1
    try:
        private_key = load_private_key(key_path)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: 无法读取私钥: {exc}")
        return 1

    # ── 签发 ────────────────────────────────────────────────
    payload = {
        "v": PAYLOAD_VERSION,
        "lid": args.license_id or f"LIC-{now.strftime('%Y%m%d')}-{os.urandom(3).hex().upper()}",
        "ent": sorted(set(ents)),
        "iat": now.isoformat(timespec="seconds"),
        "exp": expires_at.isoformat(timespec="seconds"),
        "grace": args.grace,
        "cust": args.customer,
        "note": args.note,
    }
    token = encode_license(payload, private_key)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(token + "\n", encoding="utf-8")
        print(f"token written: {out_path}  ({len(token)} chars)")
    elif args.json:
        import json

        print(json.dumps(
            {"token": token, "payload": payload}, ensure_ascii=False, indent=2
        ))
    else:
        print(token)
        print()
        print(f"# license_id   = {payload['lid']}")
        print(f"# entitlements = {', '.join(payload['ent'])}")
        print(f"# issued_at    = {payload['iat']}")
        print(f"# expires_at   = {payload['exp']}")
        print(f"# grace_days   = {payload['grace']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
