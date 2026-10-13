"""统一 subprocess 封装:自动注入 CREATE_NO_WINDOW/UTF8/超时/encoding。

所有 subprocess 调用走这里,避免 53 处各自处理。
Windows 下 GUI 场景默认不闪控制台窗口,同时统一 UTF-8 编码避免中文乱码。

用法:
    from fastapi_app.utils.subprocess_safe import safe_run, safe_popen

    r = safe_run(["git", "status"], timeout=30)
    if r.returncode == 0:
        ...

    proc = safe_popen(["python", "long_task.py"])
    ...
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Union

__all__ = ["safe_run", "safe_popen"]


Command = Union[str, Sequence[str]]


def _build_env(env_extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """构造子进程环境:强制 UTF-8、无缓冲,并叠加调用方额外变量。"""
    env: Dict[str, str] = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if env_extra:
        env.update(env_extra)
    return env


def _creationflags(shell: bool) -> int:
    """Windows GUI 场景隐藏控制台窗口;shell=True 时禁用以避免冲突。"""
    if sys.platform == "win32" and not shell:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


def _validate_cwd(cwd: Optional[Union[str, os.PathLike]]) -> Optional[str]:
    """校验 cwd 存在,返回规范化字符串或 None。"""
    if cwd is None:
        return None
    path = Path(cwd)
    if not path.exists():
        raise ValueError(f"cwd 不存在: {cwd}")
    if not path.is_dir():
        raise ValueError(f"cwd 不是目录: {cwd}")
    return str(path)


def safe_run(
    cmd: Command,
    *,
    timeout: Optional[float] = 120,
    cwd: Optional[Union[str, os.PathLike]] = None,
    env_extra: Optional[Mapping[str, str]] = None,
    encoding: str = "utf-8",
    errors: str = "replace",
    shell: bool = False,
    capture_output: bool = True,
    check: bool = False,
    input_data: Optional[Union[bytes, str]] = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """统一 subprocess.run:自动注入 UTF8/no_window/cwd 校验。

    Args:
        cmd: 命令(字符串或序列)。
        timeout: 秒级超时,超时抛 subprocess.TimeoutExpired。
        cwd: 工作目录;存在性在本函数内校验,缺失抛 ValueError。
        env_extra: 需要注入的额外环境变量,会叠加在 os.environ 之上。
        encoding: 输入输出编码,默认 utf-8。
        errors: 解码错误处理,默认 replace(不中断,保留可诊断性)。
        shell: 是否走 shell;Windows 下为 True 时不加 CREATE_NO_WINDOW。
        capture_output: 是否捕获 stdout/stderr,默认 True。
        check: True 时非零退出码抛 subprocess.CalledProcessError。
        input_data: 传给子进程的 stdin 内容。
        **kwargs: 透传给 subprocess.run 的其他参数(如 stdout/stderr 重定向)。

    Returns:
        subprocess.CompletedProcess,含 returncode/stdout/stderr。
    """
    resolved_cwd = _validate_cwd(cwd)
    env = _build_env(env_extra)
    return subprocess.run(  # type: ignore[arg-type]
        cmd,
        timeout=timeout,
        cwd=resolved_cwd,
        env=env,
        encoding=encoding,
        errors=errors,
        shell=shell,
        capture_output=capture_output,
        check=check,
        input=input_data,
        text=True,
        creationflags=_creationflags(shell),
        **kwargs,
    )


def safe_popen(
    cmd: Command,
    *,
    cwd: Optional[Union[str, os.PathLike]] = None,
    env_extra: Optional[Mapping[str, str]] = None,
    shell: bool = False,
    **kwargs: Any,
) -> subprocess.Popen:
    """统一 subprocess.Popen(长时进程):同 safe_run 注入 UTF8/no_window/cwd 校验。

    注意:Popen 的 stdout/stderr 若使用 PIPE,配合 text=True/encoding/errors
    可获得 UTF-8 文本流;调用方可通过 kwargs 传入 stdout/stderr/stdin。
    对 Popen 默认不设置 encoding(避免与调用方 text 处理冲突),但强制注入
    环境变量让子进程自身使用 UTF-8。
    """
    resolved_cwd = _validate_cwd(cwd)
    env = _build_env(env_extra)
    return subprocess.Popen(  # type: ignore[arg-type]
        cmd,
        cwd=resolved_cwd,
        env=env,
        shell=shell,
        creationflags=_creationflags(shell),
        **kwargs,
    )
