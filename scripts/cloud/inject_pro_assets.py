"""把 Pro 私有资产注入到目标代码树(开源仓不含这些资产)。

背景(D6):云端 prompt 模板正文是核心资产,开源仓只留 stub。
本脚本负责把私有资产目录同步到目标仓库的 `_pro_assets/` 位置,
并提供 `--check` 模式做一致性校验(不写盘)。

用法:
    # 注入(目标目录不存在时创建;已存在且内容不同则拒绝,除非 --force)
    python scripts/cloud/inject_pro_assets.py --source <私有资产目录> --target <仓库根>

    # 只校验不写盘
    python scripts/cloud/inject_pro_assets.py --source <私有资产目录> --target <仓库根> --check

    # 列出私有资产目录里的文件与 sha256
    python scripts/cloud/inject_pro_assets.py --source <私有资产目录> --list

约定:
    - 私有资产目录里直接放资产文件(例如 `prompts_cloud.py`),
      注入后落到 `<target>/cloud_service/llm_proxy/_pro_assets/`。
    - 目标目录已被 `.gitignore` 排除,注入不会污染开源仓的 git 状态。
    - 全程不打印文件内容,只打印路径、字节数、sha256。
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

#: 私有资产在目标树里的落位(相对仓库根)
ASSET_SUBDIR = Path("cloud_service") / "llm_proxy" / "_pro_assets"

#: 允许注入的文件类型 —— 只放 .py,防止把私钥之类的东西顺手带进代码树
ALLOWED_SUFFIXES = {".py", ".json", ".txt"}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_assets(source: Path) -> list[Path]:
    """列出私有资产目录里待注入的普通文件(跳过 `__pycache__` 与隐藏文件)。"""
    if not source.is_dir():
        raise SystemExit(f"source directory not found: {source}")
    out: list[Path] = []
    for p in sorted(source.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(source)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        if p.suffix.lower() not in ALLOWED_SUFFIXES:
            raise SystemExit(
                f"refuse to inject unsupported file type: {rel} "
                f"(allowed: {sorted(ALLOWED_SUFFIXES)})"
            )
        out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="注入 Pro 私有资产到目标代码树(或只做一致性校验)"
    )
    ap.add_argument("--source", help="私有资产目录(内含 prompts_cloud.py 等)")
    ap.add_argument("--target", help="目标仓库根目录")
    ap.add_argument("--check", action="store_true", help="只校验不写盘")
    ap.add_argument("--force", action="store_true", help="覆盖已存在且内容不同的文件")
    ap.add_argument("--list", action="store_true", help="只列出源目录文件与 sha256")
    args = ap.parse_args(argv)

    if args.list:
        if not args.source:
            raise SystemExit("--list requires --source")
        for p in collect_assets(Path(args.source)):
            print(f"{sha256_of(p)}  {p.relative_to(Path(args.source))}  ({p.stat().st_size} bytes)")
        return 0

    if not args.source or not args.target:
        raise SystemExit("--source and --target are required")

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    dest_dir = target / ASSET_SUBDIR

    assets = collect_assets(source)
    if not assets:
        raise SystemExit(f"no assets found in {source}")

    changed: list[Path] = []
    missing: list[Path] = []
    same: list[Path] = []

    for src in assets:
        rel = src.relative_to(source)
        dst = dest_dir / rel
        if not dst.exists():
            missing.append((src, dst))
            continue
        if sha256_of(src) != sha256_of(dst):
            changed.append((src, dst))
        else:
            same.append((src, dst))

    for src, dst in same:
        print(f"[same ] {dst.relative_to(target)}  ({dst.stat().st_size} bytes)")
    for src, dst in missing:
        print(f"[new  ] {dst.relative_to(target)}  ({src.stat().st_size} bytes)")
    for src, dst in changed:
        print(f"[diff ] {dst.relative_to(target)}  sha256 {sha256_of(src)[:12]} != {sha256_of(dst)[:12]}")

    if args.check:
        print(f"CHECK: new={len(missing)} diff={len(changed)} same={len(same)}")
        return 1 if changed else 0

    if changed and not args.force:
        print("REFUSE: target differs from source (use --force to overwrite)")
        return 1

    dest_dir.mkdir(parents=True, exist_ok=True)
    for src, dst in missing + (changed if args.force else []):
        shutil.copy2(src, dst)
        print(f"[write] {dst.relative_to(target)}")

    print(
        f"DONE: wrote={len(missing) + (len(changed) if args.force else 0)} "
        f"same={len(same)} dest={dest_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
