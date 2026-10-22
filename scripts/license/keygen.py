"""生成 Prism-Fusion 注册码签名密钥对(Ed25519)。

⚠️ **私钥绝不入库**。本脚本只负责生成,不负责保管。

用法:
    # 生成到指定路径(建议放在仓库外的 D 盘目录)
    python scripts/license/keygen.py --out "D:\\Prism-Fusion-Backup\\license-keys\\prism_license_ed25519.pem"

    # 只打印公钥(用于填进 prism_backend/fastapi_app/core/license_keys.py)
    python scripts/license/keygen.py --out <私钥路径> --print-public

产物:
  - 私钥 PEM(带 0600 权限语义说明):**只放本机**,同步到受控的私钥库
  - 公钥 hex:**可以公开**,入库到客户端用于验签

设计上私钥与仓库分离,这样:
  - 开源仓里只有公钥 → 任何人 clone 都无法伪造注册码
  - 签发能力靠"谁掌握私钥"控制,而不是靠"谁有源码"控制
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

#: 私钥文件的建议存放目录(仓库外)
DEFAULT_KEY_DIR = Path(r"D:\Prism-Fusion-Backup\license-keys")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成注册码 Ed25519 签名密钥对")
    ap.add_argument(
        "--out",
        help=f"私钥输出路径(.pem)。默认目录 {DEFAULT_KEY_DIR}",
        default=str(DEFAULT_KEY_DIR / "prism_license_ed25519.pem"),
    )
    ap.add_argument("--print-public", action="store_true", help="额外打印公钥 hex")
    ap.add_argument(
        "--force", action="store_true", help="目标文件已存在时覆盖(默认拒绝)"
    )
    args = ap.parse_args(argv)

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"REFUSE: {out} already exists (use --force to overwrite)")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)

    private = ed25519.Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    out.write_bytes(pem)

    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_hex = public_bytes.hex()

    print(f"private key written: {out}  ({len(pem)} bytes)")
    print("  !! 私钥不要提交到 git,不要放进安装包,不要贴进聊天窗口 !!")
    if args.print_public:
        print()
        print("public key (hex, 32 bytes):")
        print(public_hex)
        print()
        print("填进: prism_backend/fastapi_app/core/license_keys.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
