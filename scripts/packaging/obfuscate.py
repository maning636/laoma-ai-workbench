"""C18 客户端混淆工具(pyarmor 优先,缺失时降级跳过)。

背景(§6.2 / §7-R4):核心资产已下沉云端,客户端仅残留"订阅校验链路 + 关键处理逻辑"。
本工具对这些残留模块做混淆试点,提高逆向成本。

设计要点:
  * pyarmor 缺失 → 明确警告 + 退出 0,**降级跳过,不阻塞打包**
  * 混淆产物落到 `dist/obfuscate-out`(不覆盖源码)
  * 单独的 `inject` 子命令把混淆产物**就地**替换源码,以便 PyInstaller 打包时只看到混淆版本
  * 单独的 `backup` / `restore` 子命令由打包脚本配对调用,保证源码可回滚
  * 提供 `verify` 在隔离进程里 import 混淆产物,验证可用性

默认试点范围(最小,§6.2 决策):
  prism_backend/fusion_ai/cloud_gateway.py
    (TokenPair / TokenStore / CloudGateway / license 校验链路)

子命令:
  check                          检查 pyarmor 是否可用,输出 JSON
  backup   [--targets a,b]       备份源码到 dist/obfuscate-backup
  restore  [--targets a,b]       从备份还原源码
  obfuscate  [--out DIR]         pyarmor gen 到 dist/obfuscate-out
  inject   [--out DIR]           把混淆产物复制到源码路径(用于打包前)
  verify   [--out DIR]           隔离 import 检查混淆后可用性

调用顺序(由 build_services.ps1 编排):
  check → (若可用) backup → obfuscate → inject → [PyInstaller] → restore

环境变量:
  OBFUSCATE_TARGETS  逗号分隔的路径列表,覆盖默认
  OBFUSCATE_OUT      混淆输出目录,默认 dist/obfuscate-out
  OBFUSCATE_PYTHON   使用的 Python 解释器

退出码:
  0  成功,或"降级跳过"
  1  混淆本身失败,或参数错误
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "dist" / "obfuscate-out"
BACKUP_DIR = REPO_ROOT / "dist" / "obfuscate-backup"
DEFAULT_TARGETS = [
    "prism_backend/fusion_ai/cloud_gateway.py",
]
TAG = "[obfuscate]"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"{TAG} {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"{TAG} WARNING: {msg}", flush=True)


def die(msg: str) -> int:
    print(f"{TAG} ERROR: {msg}", file=sys.stderr, flush=True)
    return 1


def resolve_targets(raw: list[str] | None) -> list[Path]:
    """解析 --targets / OBFUSCATE_TARGETS / 默认列表,返回绝对路径。"""
    if raw:
        items = list(raw)
    else:
        env = os.environ.get("OBFUSCATE_TARGETS", "").strip()
        items = [x.strip() for x in env.split(",") if x.strip()] if env else list(DEFAULT_TARGETS)
    out: list[Path] = []
    for rel in items:
        p = Path(rel.replace("/", os.sep))
        out.append(p if p.is_absolute() else (REPO_ROOT / p))
    return out


def find_python() -> str:
    env = os.environ.get("OBFUSCATE_PYTHON", "").strip()
    return env if env else (sys.executable or "python")


def resolve_out_dir(cli_val: str | None) -> Path:
    raw = cli_val or os.environ.get("OBFUSCATE_OUT", str(DEFAULT_OUT))
    p = Path(raw)
    return p if p.is_absolute() else (REPO_ROOT / p)


def pyarmor_available(python: str) -> tuple[bool, str]:
    """通过 `python -m pyarmor.cli --version` 探测 pyarmor。"""
    try:
        proc = subprocess.run(
            [python, "-m", "pyarmor.cli", "--version"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"probe failed: {exc}"
    if proc.returncode == 0:
        return True, (proc.stdout or proc.stderr).strip()[:120]
    return False, (proc.stderr or proc.stdout).strip()[:200]


def _write_json(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def cmd_check(_args: argparse.Namespace) -> int:
    python = find_python()
    ok, detail = pyarmor_available(python)
    _write_json({
        "python": python,
        "pyarmor_available": ok,
        "detail": detail,
        "repo_root": str(REPO_ROOT),
        "default_targets": DEFAULT_TARGETS,
        "out_dir": str(DEFAULT_OUT),
    })
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for src in resolve_targets(args.targets):
        if not src.exists():
            warn(f"backup skipped (missing): {src}")
            continue
        rel = src.relative_to(REPO_ROOT)
        dest = BACKUP_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        log(f"backup: {rel}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    restored, missing = 0, []
    for src in resolve_targets(args.targets):
        rel = src.relative_to(REPO_ROOT) if src.is_absolute() else src
        bak = BACKUP_DIR / rel
        if not bak.exists():
            missing.append(str(bak))
            continue
        shutil.copy2(bak, src)
        restored += 1
        log(f"restore: {rel}")
    if missing:
        warn(f"no backup for: {missing}")
    if restored == 0 and not missing:
        warn("nothing to restore")
    return 0


def cmd_obfuscate(args: argparse.Namespace) -> int:
    python = find_python()
    ok, detail = pyarmor_available(python)
    if not ok:
        warn(f"pyarmor unavailable ({detail}); downgrade: skip obfuscation")
        warn("install with: pip install pyarmor   (or set OBFUSCATE_PYTHON)")
        return 0

    out_dir = resolve_out_dir(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 幂等:清旧产物,避免残留文件干扰下一次混淆
    for old in out_dir.rglob("*"):
        if old.is_file():
            try:
                old.unlink()
            except OSError:
                pass

    targets = resolve_targets(args.targets)
    existing = [t for t in targets if t.exists()]
    if not existing:
        warn("no target files exist; nothing to obfuscate")
        return 0

    # 先备份,便于注入后回滚
    if cmd_backup(argparse.Namespace(targets=args.targets)) != 0:
        return 1

    cmd = [
        python, "-m", "pyarmor.cli",
        "gen",
        "-O", str(out_dir),
        "--no-runtime",           # 无独立 runtime 二进制,仅生成加密 py + runtime 包
    ] + [str(t) for t in existing]

    log(f"running: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        warn("pyarmor gen timed out; downgrade: skip")
        return 0
    except Exception as exc:  # noqa: BLE001
        warn(f"pyarmor gen failed to launch: {exc}; downgrade: skip")
        return 0

    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)

    if proc.returncode != 0:
        warn(f"pyarmor gen exited {proc.returncode}; downgrade: skip obfuscation")
        warn("常见原因:未购买 license / trial 过期 / 文件被占用 / 语法错误。")
        return 0

    runtime_pkgs = sorted({d.name for d in out_dir.rglob("pyarmor_runtime_*") if d.is_dir()})
    if runtime_pkgs:
        log(f"pyarmor runtime packages: {runtime_pkgs}")
    produced = sum(1 for _ in out_dir.rglob("*") if _.is_file())
    log(f"obfuscation done -> {out_dir} ({produced} file(s))")
    return 0


def cmd_inject(args: argparse.Namespace) -> int:
    """把 dist/obfuscate-out 下的混淆产物就地注入源码树。

    映射规则:
      * targets 指定的每个 target(相对 repo_root 的路径)→ 直接覆盖对应源码文件
      * out_dir 中的 pyarmor_runtime_* 目录 → 复制到 prism_backend/ 下,便于
        PyInstaller 通过既有 --paths prism_backend 收集,同时 --collect-all 显式打包。

    这样:
      * 目标模块的混淆 .py 就地替换源码,PyInstaller 只看到混淆版本;
      * runtime 包位于 prism_backend/ 根,不污染源码树的其他位置;
      * 打包完成后调用 restore 恢复源码 + ps1 清理注入的 pyarmor_runtime_*。
    """
    out_dir = resolve_out_dir(args.out)
    if not out_dir.exists():
        warn(f"out dir not found: {out_dir}; run 'obfuscate' first")
        return 0

    # 幂等备份目标文件(仅备份用户显式指定的 targets,不备份 runtime 包)
    cmd_backup(argparse.Namespace(targets=args.targets))

    # 1) 复制每个 target 对应的混淆产物
    targets = resolve_targets(args.targets)
    for tgt in targets:
        if not tgt.exists():
            warn(f"inject skipped (target missing): {tgt}")
            continue
        rel = tgt.relative_to(REPO_ROOT)
        # pyarmor gen --no-runtime 会保持同名 .py(加密源码)
        src_file = out_dir / rel
        if not src_file.exists() and rel.suffix == ".py":
            # 兜底:某些 pyarmor 版本可能省略 .py 后缀
            alt = out_dir / rel.parent / (rel.stem + ".py")
            if alt.exists():
                src_file = alt
        if not src_file.exists():
            warn(f"no obfuscated output for {rel}; skip")
            continue
        shutil.copy2(src_file, tgt)
        log(f"inject: {rel}")

    # 2) 复制 pyarmor_runtime_* 到 prism_backend/ 根
    prism_backend = REPO_ROOT / "prism_backend"
    prism_backend.mkdir(parents=True, exist_ok=True)
    for rt_dir in out_dir.iterdir():
        if rt_dir.is_dir() and rt_dir.name.startswith("pyarmor_runtime_"):
            dest = prism_backend / rt_dir.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(rt_dir, dest)
            log(f"inject runtime: prism_backend/{rt_dir.name}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """在隔离子进程里 import 混淆后的模块,验证可用性。"""
    out_dir = resolve_out_dir(args.out)
    if not out_dir.exists():
        warn(f"out dir not found: {out_dir}; run 'obfuscate' first")
        return 0

    runtime_dirs = [d for d in out_dir.iterdir() if d.name.startswith("pyarmor_runtime_")]
    sys_path_extra = [str(out_dir)] + [str(d) for d in runtime_dirs]

    # 收集混淆产物中的顶层模块名(基于目录结构)
    modules: list[str] = []
    for py in out_dir.rglob("*.py"):
        rel = py.relative_to(out_dir)
        parts = list(rel.parts)
        if parts[-1].endswith(".py"):
            parts[-1] = parts[-1][:-3]
        elif parts[-1] == "__init__.py":
            parts = parts[:-1]
        if parts:
            modules.append("".join(parts[i] + ("." if i < len(parts) - 1 else "") for i in range(len(parts))))
    if not modules:
        warn("no modules to verify in out dir")
        return 0

    probe = """
import sys, json
paths = json.loads(r'''{paths_json}''')
for p in paths:
    sys.path.insert(0, p)
modules = json.loads(r'''{mods_json}''')
results = {{}}
for m in modules:
    try:
        mod = __import__(m)
        results[m] = {{\"ok\": True, \"file\": getattr(mod, \"__file__\", \"<unknown>\")}}
    except Exception as exc:
        results[m] = {{\"ok\": False, \"error\": f\"{{type(exc).__name__}}: {{exc}}\"}}
print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
""".format(paths_json=json.dumps(sys_path_extra), mods_json=json.dumps(modules))

    python = find_python()
    log(f"verifying {len(modules)} module(s) via {python}")
    try:
        proc = subprocess.run([python, "-c", probe], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        warn("verify timed out")
        return 0
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)
    log("verify finished (see report above)")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="检查 pyarmor 可用性,输出 JSON")

    b = sub.add_parser("backup", help="备份源码到 dist/obfuscate-backup")
    b.add_argument("--targets", nargs="*", help="逗号或空格分隔的模块路径列表")

    r = sub.add_parser("restore", help="从备份还原源码")
    r.add_argument("--targets", nargs="*")

    o = sub.add_parser("obfuscate", help="pyarmor gen 混淆到 dist/obfuscate-out")
    o.add_argument("--targets", nargs="*")
    o.add_argument("--out", help="输出目录,默认 dist/obfuscate-out")

    j = sub.add_parser("inject", help="把混淆产物就地覆盖到源码路径(用于打包前)")
    j.add_argument("--targets", nargs="*")
    j.add_argument("--out", help="读取哪个混淆产物目录")

    v = sub.add_parser("verify", help="在隔离进程里 import 混淆产物")
    v.add_argument("--targets", nargs="*")
    v.add_argument("--out")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "check":
            return cmd_check(args)
        if args.cmd == "backup":
            return cmd_backup(args)
        if args.cmd == "restore":
            return cmd_restore(args)
        if args.cmd == "obfuscate":
            return cmd_obfuscate(args)
        if args.cmd == "inject":
            return cmd_inject(args)
        if args.cmd == "verify":
            return cmd_verify(args)
    except FileNotFoundError as exc:
        return die(f"file not found: {exc}")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return die(f"unexpected: {exc}")
    return die(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
