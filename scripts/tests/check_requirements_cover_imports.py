#!/usr/bin/env python3
"""检查「源码直接 import 的第三方包」是否都在 requirements*.txt 里声明了。

背景（真实事故）：
  prism_backend/fastapi_app/core/license.py 顶层 `from cryptography.exceptions
  import InvalidSignature`，而 cryptography 一直不在 requirements.txt 里。
  它在启动链路上（api/v1/router.py → license/router.py → core/license.py），
  于是「按 README 装依赖」的人装完根本起不来后端，CI 里 pytest 收集阶段
  直接 ModuleNotFoundError。

判定口径（刻意收窄，避免误报）：
  1. 只扫**可部署服务**的目录：prism_backend/fastapi_app/ 与 cloud_service/；
     scripts/、mcp_server.py、app_new/ 这些是独立工具脚本，不在启动链路上。
  2. 只看**模块级** import（函数体内的惰性 import 不算——它们是可选增强，
     缺了会降级而不是起不来）。这也顺带排除了 mediacrawler / json_repair
     这类按需加载的包。
  3. 本地模块按「仓库任意深度下存在同名目录（含 .py 文件）或 .py 文件」判定并跳过；
     但**只认源码树**，不认打包/缓存产物里的第三方包副本（见 SKIP_DIRS 注释）。
  4. 剩下的第三方包，必须能在 requirements.txt 或 requirements-dev.txt 里
     找到对应声明（按 PyPI 发行名匹配，差异见 ALIAS）。

另外做一次**影子检测**：如果某个第三方包名同时被本地目录占用（本地模块集合里
有它），检查会把它当成"自己人"跳过 —— 这就是漏判。所以只要这种名字同时也是
我们声明过的发行名，就直接判 FAIL。

用法：
  python scripts/tests/check_requirements_cover_imports.py            # 真检查
  python scripts/tests/check_requirements_cover_imports.py --self-test # 双向自测

退出码：0 = 通过；1 = 有问题。
"""

from __future__ import annotations

import ast
import io
import os
import re
import sys
import warnings

# Windows 控制台默认 GBK，输出里带非 ASCII 符号会直接抛 UnicodeEncodeError。
try:  # pragma: no cover - 只影响本地可读性
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 只扫可部署服务（启动链路）
SCAN_DIRS = (
    os.path.join("prism_backend", "fastapi_app"),
    "cloud_service",
)

# 目录名黑名单（在"判定本地模块"和"扫描 import"时都会剪掉）。
#
# 为什么必须黑名单而不是白名单：打包产物里会**整份拷贝**第三方包，例如
#   desktop-electron/dist-out/v5/**/_internal/cryptography/
#   desktop-electron/dist-community/**/_internal/cryptography/
#   _caches/uv/cache/**/cryptography/
#   _deploy_inputs/backups/dist-out-v1.1.0-old/**/_internal/cryptography/
# 这些目录里有 .py 文件，按"仓库任意深度下同名目录 = 本地模块"的朴素规则，
# cryptography 会被误判成"仓库自带模块" → 真正漏声明的包被跳过 →
# 闸门变成永远 OK 的假闸门（反向自测抓不到）。
SKIP_DIRS = {
    # --- 第三方包容器（pip / PyInstaller / vendored）---
    "site-packages", "_internal", "dist-info", "vendor", "wheels", "eggs",
    # --- 本仓库的构建产物 / 打包目录 ---
    "__pycache__", "node_modules", "prismenv", "dist-build", "dist-out",
    "dist-community", "win-unpacked", "dist", "build", "out", ".next",
    ".turbo", "coverage", "prism_publisher.egg-info",
    # --- 本机缓存 / 临时 / 备份 ---
    ".venv", ".venv-img", "venv", ".git", ".hg", ".svn", "hermes-agent",
    "tmp", ".tmp", "_caches", "_deploy_inputs", "artifacts", "browsers",
    "runtime-data", ".backups", ".dim-sandbox", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", "_plan_drafts_backup", "_appdata_electron",
    "_appdata_laoma_bid", "_backup_demo_20261015", "_electron_userdata",
    "_electron_userdata_packaged",
    # --- 运行期数据目录 ---
    "data", "logs", "uploads", "storage", "cookies", "profiles",
}

# import 名 → PyPI 发行名（只在两者不同时才写）
ALIAS = {
    "jwt": "PyJWT",
    "dotenv": "python-dotenv",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "bs4": "beautifulsoup4",
    "docx": "python-docx",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "magic": "python-magic",
    "sklearn": "scikit-learn",
    "dateutil": "python-dateutil",
    "serial": "pyserial",
    "Crypto": "pycryptodome",
    "google": "google-api-python-client",
    "pkg_resources": "setuptools",
    "pptx": "python-pptx",
    "json_repair": "json-repair",
}

# 反向自测的候选：这些是"确实被模块级 import、且确实在 requirements 里声明"
# 的第三方包。自测时逐个把声明从集合里去掉，必须能被重新报出来。
SELF_TEST_CANDIDATES = (
    "cryptography", "fastapi", "sqlalchemy", "loguru", "httpx",
    "pydantic", "pydantic_settings", "uvicorn", "redis", "openai", "jwt",
)

# 扫描到的第三方 import 少于这个数 → 闸门多半是"扫空了"，判失败（防假闸门）
MIN_THIRD_PARTY_IMPORTS = 5


def _norm(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _dist_of(import_name: str) -> str:
    return ALIAS.get(import_name, import_name)


def _declared_names(path: str) -> set[str]:
    """从一个 requirements 风格的文件里取出声明的包名（已归一化）。"""
    out: set[str] = set()
    if not os.path.isfile(path):
        return out
    with io.open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#")[0].strip()
            if not line:
                continue
            m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
            if not m:
                continue
            pkg = m.group(1)
            out.add(_norm(pkg))
            out.add(_norm(ALIAS.get(pkg, pkg)))
    return out


def _local_module_names() -> set[str]:
    """仓库自带的模块名：任意深度下含 .py 的目录名 + .py 文件名。

    注意：目录**不要求**有 __init__.py —— 命名空间包（PEP 420）也算本地模块。
    例如 prism_backend/douyin_tiktok_api/crawlers/ 没有 __init__.py，是运行时
    由 api/v1/crawler/router.py 手动塞进 sys.path 后 import 的第三方风格代码，
    但它就躺在仓库里，算本地。

    关键：**只认源码树**。SKIP_DIRS 里的打包产物/缓存目录会被剪掉，否则它们
    内部整份拷贝的第三方包目录会被当成"仓库本地模块"，造成漏判。
    """
    names: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                names.add(os.path.splitext(fn)[0])
        # 目录里直接躺着 .py 文件 → 这个目录名可作为顶层模块被 import
        if any(fn.endswith(".py") for fn in filenames):
            names.add(os.path.basename(dirpath))
    # 两个服务本身就是包
    names.add("fastapi_app")
    names.add("cloud_service")
    names.add("prism_backend")
    return names


def _module_level_imports(path: str) -> list[str]:
    """取一个文件里**模块级**（不在函数体内）的顶层 import 名。"""
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return []
    try:
        with warnings.catch_warnings():
            # 仓库里有些文件带非法转义（如正则里的 \(），只解析不执行，
            # 解析期的 SyntaxWarning 与本检查无关，屏蔽掉免得刷屏。
            warnings.simplefilter("ignore")
            tree = ast.parse(src)
    except SyntaxError:
        return []

    out: list[str] = []
    # 逐个遍历「模块体」的直接子节点：函数/类内部的 import 一律跳过
    for node in tree.body:
        if isinstance(node, ast.Import):
            out.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # 相对导入
            if node.module:
                out.append(node.module.split(".")[0])
    return out


def _collect_imports() -> dict[str, list[str]]:
    """扫描 SCAN_DIRS，返回 {顶层 import 名: [文件相对路径, ...]}。

    注意这里**不**按 local/stdlib 过滤 —— 影子检测需要看到全部 import 名。
    """
    found: dict[str, list[str]] = {}
    for rel_dir in SCAN_DIRS:
        base = os.path.join(REPO_ROOT, rel_dir)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
                for top in _module_level_imports(path):
                    if top.startswith("_"):
                        continue
                    bucket = found.setdefault(top, [])
                    if rel not in bucket:
                        bucket.append(rel)
    return found


def _analyze(declared: set[str], local: set[str], imported: dict[str, list[str]]):
    """返回 (missing, shadowed)。

    missing  : 既不是本地模块、也没在 requirements 声明的第三方包
    shadowed : 名字既被本地目录占用、又是一个已声明的第三方发行名
               （这种名字会被当成"自己人"跳过 → 漏判，必须报出来）
    """
    stdlib = set(sys.stdlib_module_names)
    missing: dict[str, list[str]] = {}
    shadowed: dict[str, list[str]] = {}
    for top, files in imported.items():
        if top in stdlib:
            continue
        dist = _dist_of(top)
        if top in local:
            if _norm(dist) in declared or _norm(top) in declared:
                shadowed.setdefault(dist, []).extend(files)
            continue
        if _norm(dist) in declared or _norm(top) in declared:
            continue
        missing.setdefault(dist, []).extend(files)
    return missing, shadowed


def _print_missing(missing: dict[str, list[str]]) -> None:
    print("FAIL 以下第三方包被模块级 import，但 requirements*.txt 没有声明：")
    for dist in sorted(missing):
        print(f"\n* {dist}")
        for f in sorted(set(missing[dist]))[:8]:
            print(f"    {f}")
        if len(set(missing[dist])) > 8:
            print(f"    ... 共 {len(set(missing[dist]))} 个文件")
    print(
        "\n处理办法：把包加进 requirements.txt（若只用于测试则加 requirements-dev.txt）。"
        "\nimport 名与 PyPI 发行名不同的，同时在脚本顶部的 ALIAS 里补一条映射。"
    )


def _run_check(declared: set[str], local: set[str], imported: dict[str, list[str]]) -> int:
    missing, shadowed = _analyze(declared, local, imported)

    if shadowed:
        print("FAIL 影子检测：下列第三方包名被仓库本地目录占用，检查会把它当自己人跳过（漏判）：")
        for dist in sorted(shadowed):
            print(f"\n* {dist}")
            for f in sorted(set(shadowed[dist]))[:8]:
                print(f"    {f}")
        print(
            "\n处理办法：把占用该名字的目录移出源码树，或加进脚本顶部的 SKIP_DIRS。"
        )
        return 1

    if not missing:
        print("OK   可部署服务的模块级第三方 import 都在 requirements*.txt 里声明了")
        return 0

    _print_missing(missing)
    return 1


def _run_self_test(declared: set[str], local: set[str], imported: dict[str, list[str]]) -> int:
    """双向自测：证明这道闸门不是「永远 OK」的假闸门。

    正向：真实声明集合下必须没有 missing。
    反向：逐个把候选包的声明从集合里拿掉，必须能被重新报出来。
          （如果拿掉声明它仍然报不出来，说明这个名字被本地目录影子了 —— 闸门失灵）
    """
    stdlib = set(sys.stdlib_module_names)
    third_party = [n for n in imported if n not in stdlib and n not in local]
    if len(third_party) < MIN_THIRD_PARTY_IMPORTS:
        print(
            f"FAIL 自测前置条件不满足：只扫到 {len(third_party)} 个第三方模块级 import"
            f"（< {MIN_THIRD_PARTY_IMPORTS}），扫描范围可能失效，闸门形同虚设。"
        )
        return 1

    missing, _shadowed = _analyze(declared, local, imported)
    if missing:
        print("FAIL 自测前置条件不满足：真实声明集合下就有漏声明，先修声明再谈自测：")
        _print_missing(missing)
        return 1

    tested = 0
    for cand in SELF_TEST_CANDIDATES:
        if cand not in imported or cand in local or cand in stdlib:
            continue
        dist = _dist_of(cand)
        stripped = set(declared)
        stripped.discard(_norm(dist))
        stripped.discard(_norm(cand))
        m, _s = _analyze(stripped, local, imported)
        if dist in m:
            print(f"  OK   反向自测：去掉 {dist} 的声明后被正确报出（{len(set(m[dist]))} 个文件）")
            tested += 1
        else:
            print(f"  FAIL 反向自测：去掉 {dist} 的声明后**没有**被报出来 → 闸门失灵")
            print(f"        {dist} 可能被本地目录影子（local 命中: {cand in local}）")
            return 1

    if tested == 0:
        print("FAIL 自测没找到可用的候选包，无法验证闸门有效性")
        return 1

    print(f"OK   双向自测通过（{tested} 个候选包，删声明必被报出）")
    return 0


def main() -> int:
    declared = _declared_names(os.path.join(REPO_ROOT, "requirements.txt"))
    declared |= _declared_names(os.path.join(REPO_ROOT, "requirements-dev.txt"))
    local = _local_module_names()
    imported = _collect_imports()

    if "--self-test" in sys.argv[1:]:
        return _run_self_test(declared, local, imported)
    return _run_check(declared, local, imported)


if __name__ == "__main__":
    raise SystemExit(main())
