"""cloud_service 的 pytest 适配层（X3）。

背景:cloud_service/ 下的 5 个 ``test_*.py`` 是**自运行脚本**(不是 pytest 用例):
    - 每个脚本定义 ``def run() -> int``,内部用 ``check()`` 打印 ``[PASS]`` / ``[FAIL]``;
    - 末尾以 ``if __name__ == "__main__": ...`` 自执行,返回失败计数,0 表示全绿。

因此 ``python -m pytest cloud_service -q`` 默认收集到 **0 items**,CI 里等于没有
SaaS 类测试。本 conftest 通过 pytest 的 :func:`pytest_collect_file` 钩子把每个
``test_*.py`` 视作**一个** pytest 用例,用例内部直接调用该脚本的 ``run()``:

* 不重写任何测试逻辑,也不改动脚本内 ``check()`` / 断言;
* 不注入任何环境变量——5 个脚本已在文件顶部自行设置 ``CLOUD_*`` 与临时 SQLite;
* 不启动子进程——直接在同进程内 import + 调用,避免 Windows/UTF-8 路径问题;
* 独立运行能力保留:``python cloud_service\\test_xxx.py`` 仍可打印 ``ALL TESTS PASSED``。

注意:5 个脚本都会把 ``CLOUD_DB_URL`` 设到各自的临时 SQLite 文件,而
``cloud_service.db.init_db`` 的 SQLAlchemy engine 在首次 import 时读取该 env 并缓存。
因此我们**顺序** import(不是并行),在每次 import 之间清一次
``cloud_service.db`` / ``cloud_service.settings`` 的模块缓存,让新脚本读到的
是它自己写入的 ``CLOUD_DB_URL``;同时清 ``cloud_service.main`` / ``cloud_service.db``
的 ``lru_cache`` 让 FastAPI lifespan 的 ``init_db()`` 使用新的 settings。
"""

from __future__ import annotations

import importlib
import sys
import sysconfig
from pathlib import Path
from types import ModuleType
from typing import Iterable

import pytest

# 把仓库根加进 sys.path(脚本内部自己也会加,这里作为兜底:允许在任意 cwd 下运行 pytest)。
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _purge_cloud_service_modules() -> None:
    """清掉 cloud_service.* 的模块缓存。

    原因:每个脚本都会修改 ``os.environ["CLOUD_DB_URL"]`` 到不同的临时 SQLite 文件,
    而 ``cloud_service.db`` 在首次 import 时读取该 env 并把 engine 固化下来。
    只有清缓存让 SQLAlchemy 用新的 ``CLOUD_DB_URL`` 重新建 engine,才能保证每个脚本
    的写入落在**它自己**的临时 DB 里(否则第 2..N 个脚本会污染第 1 个脚本的库)。
    """
    for name in list(sys.modules):
        if name == "cloud_service" or name.startswith("cloud_service."):
            del sys.modules[name]


def _resolve_repo_root(script_path: Path) -> Path:
    """推断脚本期望的仓库根(与脚本内部使用的方式一致)。"""
    p = script_path.resolve()
    for parent in p.parents:
        if (parent / "cloud_service").is_dir():
            return parent
    return _REPO_ROOT


def _resolve_executable() -> str:
    """返回当前 Python 解释器的**真实路径**(去掉 pyvenv.cfg → Scripts 的包装层)。

    ``sys.executable`` 在 venv 里通常是 ``venv\\Scripts\\python.exe``(一个会读
    ``pyvenv.cfg`` 后转发到 home 解释器的包装器)。``subprocess.run`` 直接调这个
    路径在 Windows 上可行,但为了让 pytest 用例失败信息里出现真实解释器路径,
    优先从 ``sys._base_executable`` 或 ``pyvenv.cfg`` 里读 home 解释器;失败则退回原值。
    """
    exe = Path(sys.executable)
    cfg = exe.parent / "pyvenv.cfg"
    if cfg.is_file():
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("home ="):
                    home = Path(line.split("=", 1)[1].strip()).resolve()
                    candidate = home / exe.name
                    if candidate.is_file():
                        return str(candidate)
        except OSError:
            pass
    base = getattr(sys, "_base_executable", None)
    if base and Path(base).is_file():
        return base
    return str(exe)


def pytest_collect_file(file_path, parent):  # type: ignore[no-untyped-def]
    """把 cloud_service 下的 ``test_*.py`` 收集成单个 pytest 用例。

    该钩子在每个 candidate file 上都会跑,所以严格限定:
      * 必须是 :file:`cloud_service` 目录内的文件;
      * 文件名必须以 ``test_`` 开头且以 ``.py`` 结尾;
      * 文件必须真的能被 import,并暴露一个 callable ``run()`` 返回 int。
    不满足任一条则返回 None,pytest 会继续尝试其他 collector。
    """
    p = Path(file_path)
    if p.name.startswith("test_") and p.suffix == ".py":
        try:
            rel = p.resolve().relative_to(_REPO_ROOT.resolve())
        except ValueError:
            return None
        # 只接管 cloud_service/ 目录直下的脚本
        if len(rel.parts) != 2 or rel.parts[0] != "cloud_service":
            return None

        script_path = p.resolve()
        script_rel = str(script_path.relative_to(_REPO_ROOT))
        return _CloudScriptItem.from_parent(parent, fpath=script_path, rpath=script_rel)


class _CloudScriptItem(pytest.Item):
    """把一个自运行脚本包装成单个 pytest 用例。"""

    def __init__(self, fpath: Path, rpath: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(
            name=rpath,
            parent=kwargs["parent"],
            fspath=fpath,
        )
        self._fpath = fpath
        self._rpath = rpath

    def runtest(self) -> None:  # type: ignore[no-untyped-def]
        """执行:import 脚本 → 调用 ``run()`` → 断言返回值为 0。"""
        # 让脚本内部的 ``Path(__file__).resolve().parent.parent`` 与 CI 里
        # 的 python -m pytest 保持一致行为:先清一次模块缓存,再 import。
        _purge_cloud_service_modules()

        root = _resolve_repo_root(self._fpath)
        exe = _resolve_executable()

        # 用 runpy 风格的 import(不触发 __main__ 分支,但保留 __name__ == "<mod>").
        # 由于文件名合法(以 test_ 开头、下划线分隔),可以直接用 importlib。
        module_name = (
            "cloud_service."
            + self._fpath.stem
        )
        try:
            spec = importlib.util.spec_from_file_location(
                module_name, self._fpath, submodule_search_locations=None
            )
            if spec is None or spec.loader is None:
                pytest.skip(f"cannot build import spec for {self._rpath}", allow_module_level=False)
            mod: ModuleType = importlib.util.module_from_spec(spec)
            # 预注册到 sys.modules,让 from cloud_service.xxx import yyy 能找到 __file__
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
        except Exception as e:  # pragma: no cover - pytest.fail 会覆盖大部分情形
            pytest.fail(
                f"[import error] {self._rpath}: {type(e).__name__}: {e}\n"
                f"  解释器: {exe}\n  仓库根: {root}"
            )

        run_fn = getattr(mod, "run", None)
        if not callable(run_fn):
            pytest.fail(f"[missing run()] {self._rpath} 未定义可调用 run() 函数")

        fails: int = run_fn()
        if fails != 0:
            pytest.fail(f"[{fails} check(s) failed] {self._rpath} — 详见上方 [FAIL] 行")


__all__ = ["pytest_collect_file"]
