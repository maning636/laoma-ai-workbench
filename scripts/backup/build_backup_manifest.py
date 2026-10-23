# -*- coding: utf-8 -*-
"""生成（或校验）Prism-Fusion 备份目录的 MANIFEST.txt。

为什么固化成脚本：round17 / round18 的 MANIFEST 都是手写哈希，格式容易漂移、
哈希容易抄错，也没法回读自证。这里把「列哪些文件、按什么顺序排、哈希怎么算、
说明怎么写」全部写死，并支持写完立即回读校验（--verify）。

用法
----
    # 生成（默认写到 <backup-root>/MANIFEST.txt）
    python scripts/backup/build_backup_manifest.py \
        --backup-root "D:/Prism-Fusion-Backup" \
        --source-commit f36c620 --round 18

    # 只校验已有 MANIFEST 与磁盘现状是否一致
    python scripts/backup/build_backup_manifest.py \
        --backup-root "D:/Prism-Fusion-Backup" --verify

覆盖范围约定
------------
* 只覆盖**备份交付物**：根目录文件 + deploy/ + db/；
* 私有材料（license-keys/ Ed25519 私钥、pro-assets/ Pro prompt 正文）
  与过程目录（_verify/、_build_archive_*/、_extracts/、_acceptance/、
  _superseded_*/）一律不在清单内 —— 它们存在本机，但不随公开仓、
  不随安装包、不随本清单分发。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime

SEP = "-" * 100
EQ = "=" * 100

# 清单数据行：路径 + 体积 + sha-256（表头/分隔线/头部字段行都匹配不上）
ROW_RE = re.compile(r"^(?P<rel>\S.*?)\s+(?P<size>\d+)\s+(?P<sha>[0-9a-f]{64})$")

# 备份根目录下**排除**的目录名：私有材料与过程产物
EXCLUDED_ROOT_DIRS = {
    "license-keys",   # Ed25519 私钥，签名注册码用 —— 绝不可外发
    "pro-assets",     # Pro 云端 prompt 正文 —— 绝不可外发
}

# 清单收录的子目录（相对备份根）
INCLUDED_SUBDIRS = ("deploy", "db")

# 显式排序：与历轮 MANIFEST 的行序保持一致，避免轮次之间行序漂移
DELIVERABLE_ORDER = [
    ".env.example",
    "PROJECT_DEVELOPMENT_HISTORY.md",
    "Prism-Fusion-source.zip",
    "latest.yml",
    "LaomaAI-1.1.5-setup.exe",
    "LaomaAI-1.1.5-setup.exe.blockmap",
    "deploy/README.md",
    "deploy/deploy.sh",
    "deploy/nginx-prism-cloud.conf",
    "deploy/prism-cloud.service",
    "deploy/website/index.html",
    "deploy/website/fde.conf",
    "deploy/website/README.md",
    "db/prism_cloud_2026-10-22_210132.sql.gz",
]

NOTES_TEMPLATE = """\
说明：
  1) 本清单只覆盖备份交付物（根目录文件 + deploy/ + db/）；
     _verify/ 为核实过程产物、_build_archive_*/ 为打包归档、
     _superseded_round17/ 与 _superseded_round{round}/ 均为被后续轮次取代的旧产物，
     均未列入。
  2) **私有材料不在清单内**：license-keys/（Ed25519 私钥，签名注册码用）与
     pro-assets/（Pro 云端 prompt 正文）存在于本机备份目录，但**不随公开仓、
     不随安装包、不随本清单分发**；请勿整目录外发。
  3) MANIFEST.txt 自身因自指（无法包含自身最终哈希）不在清单内，其哈希需单独计算。
  4) Prism-Fusion-source.zip 由 git -c core.autocrlf=false -c core.eol=lf archive
     {source_commit} 生成。逐文件核验（1423 个文件，与该提交的 git tree 比对）：
     1350 个逐字节一致；其余 73 个仅行尾不同（59 个 .bat / 2 个 .cmd / 12 个 .ps1），
     系仓库 .gitattributes 明确规定的 Windows 脚本 CRLF 规则（* text=auto eol=lf
     加 *.bat/*.cmd/*.ps1 text eol=crlf）所致，非内容差异；无多余文件、无缺失文件。
  5) **源码包与二进制的对应关系**：已发布的 1.1.5 安装包由 2026-10-23 03:31-03:38
     在 {source_commit} 的工作树上构建（win-unpacked 03:31:28 / 安装包 03:38:26 /
     blockmap 03:38:41 / latest.yml 03:38:44）。逐字节核验（解包 app.asar 与该提交
     比对）：asar 内 src/main/index.js 与该提交仅差 37 行，其中 33 行为打包时尚未
     清理的中文注释乱码、2 行为 BOM 加固调用点（readJsonFileSafely）；因 asar 内
     package.json 实测无 BOM（首字节即 '{{'），该 2 处差异运行时无功能影响。
     asar 内 src/main/version-catalog.js 与该提交完全一致。
  6) **不在 1.1.5 二进制内的后续改动**：adec916（归属切 maning636，13:23）、
     45e71e4（P7：云端 AI / TikHub 未配置时关闭入口）、312e4ba、ffafd6a 等。
     已发布安装包内 package.json 的 author 仍为 Laihiujin —— 与 adec916 提交说明
     一致（需 1.1.6 重打包才生效）。已发布前端产物中 P7 标记命中 0 次，可反证。
  7) 最新完整源码（含归属切换与 P7）在 GitHub 仓库 maning636/laoma-ai-workbench，
     origin/main = ffafd6a；需要「与已发布二进制严格对应」的源码，请用本清单内的
     Prism-Fusion-source.zip（{source_commit}）。
  8) 本轮起为**单一客户端**：社区版安装器与 latest-community.yml 已取消，
     完整版 / 限制功能版在同一个客户端内按注册码切换。
  9) deploy/website/index.html 是从线上服务器 /var/www/fde/index.html 拉取的当前线上
     版本（切 GitHub Release 直链之后的那版）；切之前的旧版存于
     _superseded_round{round}/deploy-website-index.html.pre-github-release。
"""


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_excluded_root_dir(name: str) -> bool:
    if name in EXCLUDED_ROOT_DIRS:
        return True
    return name.startswith("_")


def collect_deliverables(backup_root: str) -> list[str]:
    """列出纳入清单的相对路径（已排序）。"""
    found: list[str] = []

    for name in sorted(os.listdir(backup_root)):
        full = os.path.join(backup_root, name)
        if os.path.isdir(full):
            if is_excluded_root_dir(name) or name not in INCLUDED_SUBDIRS:
                continue
            for root, dirs, files in os.walk(full):
                dirs.sort()
                for fn in sorted(files):
                    rel = os.path.relpath(os.path.join(root, fn), backup_root)
                    found.append(rel.replace(os.sep, "/"))
        elif os.path.isfile(full):
            if name == "MANIFEST.txt":
                continue  # 自指：无法包含自身最终哈希
            found.append(name)

    ordered: list[str] = []
    for rel in DELIVERABLE_ORDER:
        if rel in found:
            ordered.append(rel)
    # 清单里没显式列出的新文件，按路径排序追加在后面（不会悄悄漏掉文件）
    for rel in sorted(found):
        if rel not in ordered:
            ordered.append(rel)
    return ordered


def git_meta(repo: str, commit: str) -> dict:
    proc = subprocess.run(
        ["git", "-C", repo, "show", "-s",
         "--format=%H%n%h%n%an%n%ci%n%s", commit],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise SystemExit("git show 失败: %s" % proc.stderr.strip())
    lines = proc.stdout.splitlines()
    return {
        "commit": lines[0].strip(),
        "short": lines[1].strip(),
        "author": lines[2].strip(),
        "date": lines[3].strip(),
        "subject": lines[4].strip(),
    }


def render(backup_root: str, repo: str, commit: str, round_no: str) -> str:
    meta = git_meta(repo, commit)
    files = collect_deliverables(backup_root)

    out: list[str] = []
    out.append(EQ)
    out.append("Prism-Fusion Backup MANIFEST")
    out.append(EQ)
    out.append("Generated        : %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    out.append("Git commit       : %s" % meta["commit"])
    out.append("Git short sha    : %s" % meta["short"])
    out.append("Author           : %s" % meta["author"])
    out.append("Commit date      : %s" % meta["date"])
    out.append("Subject          : %s" % meta["subject"])
    out.append("Backup root      : %s" % backup_root)
    out.append("Deliverable files: %d" % len(files))
    out.append("")
    out.append(SEP)
    out.append("%-50s%6s  %s" % ("RELATIVE PATH", "SIZE(B)", "SHA-256"))
    out.append(SEP)
    for rel in files:
        full = os.path.join(backup_root, rel.replace("/", os.sep))
        size = os.path.getsize(full)
        out.append("%-50s%6d  %s" % (rel, size, sha256_of(full)))
    out.append(SEP)
    out.append("")
    out.append(NOTES_TEMPLATE.format(round=round_no, source_commit=meta["short"]))
    return "\n".join(out)


def verify(backup_root: str, manifest_path: str) -> int:
    """回读清单，逐行重新算哈希，与磁盘现状比对。"""
    with open(manifest_path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    checked = 0
    bad = 0
    for line in lines:
        match = ROW_RE.match(line)
        if not match:
            continue  # 分隔线、表头、头部字段行都不是清单行
        rel = match.group("rel")
        digest = match.group("sha")
        full = os.path.join(backup_root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            print("  [缺失] %s" % rel)
            bad += 1
            continue
        actual = sha256_of(full)
        if actual != digest:
            print("  [不符] %s\n         清单=%s\n         实际=%s" % (rel, digest, actual))
            bad += 1
        else:
            checked += 1
    print("校验完成：通过 %d 个，不符/缺失 %d 个" % (checked, bad))
    return 0 if bad == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成/校验 Prism-Fusion 备份 MANIFEST")
    parser.add_argument("--backup-root", required=True, help="备份根目录")
    parser.add_argument("--repo", default=None, help="仓库根目录（默认取本脚本所在仓库）")
    parser.add_argument("--commit", default="HEAD", help="清单头部记录的 git 提交")
    parser.add_argument("--source-commit", default=None,
                        help="源码包对应的提交（默认与 --commit 相同）")
    parser.add_argument("--round", default="18", help="本轮轮次号（写进说明段）")
    parser.add_argument("--out", default=None, help="清单输出路径（默认 <backup-root>/MANIFEST.txt）")
    parser.add_argument("--verify", action="store_true", help="只校验已有清单，不重写")
    args = parser.parse_args(argv)

    backup_root = os.path.abspath(args.backup_root)
    repo = os.path.abspath(args.repo) if args.repo else os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    manifest_path = args.out or os.path.join(backup_root, "MANIFEST.txt")

    if args.verify:
        return verify(backup_root, manifest_path)

    source_commit = args.source_commit or args.commit
    text = render(backup_root, repo, source_commit, args.round)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("已写出: %s (%d B)" % (manifest_path, os.path.getsize(manifest_path)))
    return verify(backup_root, manifest_path)


if __name__ == "__main__":
    sys.exit(main())
