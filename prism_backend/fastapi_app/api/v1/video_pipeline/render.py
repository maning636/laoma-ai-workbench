"""HyperFrames 渲染 subprocess 封装（供 POST /render 和 orchestrator.py 复用）"""
import json
import subprocess
import sys
import time
from pathlib import Path

from fastapi_app.core.logger import logger
from fastapi_app.core import paths as core_paths
from fastapi_app.utils.subprocess_safe import safe_run

_RENDER_TIMEOUT_SECONDS = 600
_PROXY = "http://127.0.0.1:7997"


def _build_env() -> dict:
    import os
    env = os.environ.copy()
    env["HTTPS_PROXY"] = _PROXY
    env["HTTP_PROXY"] = _PROXY
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["NODE_NO_WARNINGS"] = "1"
    node_dir = str(core_paths.get_nodejs_dir())
    path_sep = ";" if sys.platform == "win32" else ":"
    cur_path = env.get("PATH", "")
    if node_dir not in cur_path.split(path_sep):
        env["PATH"] = node_dir + path_sep + cur_path
    return env


def _resolve_npx() -> str:
    import shutil
    found = shutil.which("npx")
    if found:
        return found
    for cand in (Path(core_paths.get_nodejs_dir()) / "npx.cmd",
                 Path(core_paths.get_nodejs_dir()) / "npx.exe",
                 Path(str(Path.home() / "AppData/Roaming/nvm"))):
        if cand.exists():
            return str(cand)
    return "npx"


def probe_hyperframes() -> dict:
    try:
        proc = safe_run(
            [_resolve_npx(), "hyperframes", "--version"],
            timeout=30,
            env_extra=_build_env(),
            capture_output=True,
        )
        out = (proc.stdout or b"").decode("utf-8", errors="ignore").strip()
        err = (proc.stderr or b"").decode("utf-8", errors="ignore").strip()
        version = (out or err).splitlines()[0] if (out or err) else ""
        return {"installed": proc.returncode == 0, "version": version}
    except Exception as e:
        return {"installed": False, "version": "", "error": str(e)}


def run_hyperframes_render(composition_dir: Path, quality: str, fps: int, variables: dict | None = None, output_path: str | None = None) -> dict:
    """渲染 HyperFrames composition → MP4。

    variables: 传给模板的变量（merge 到 data-composition-variables 默认值），通过
    `--variables '{"title":"xxx"}'` flag 注入，模板内 window.__hyperframes.getVariables() 读取。
    output_path: 指定输出 MP4 路径（-o），否则默认 renders/<name>.mp4 在 composition_dir 下。
    """
    for check in ("lint", "validate"):
        try:
            safe_run(
                [_resolve_npx(), "hyperframes", check],
                cwd=str(composition_dir),
                capture_output=True,
                timeout=60,
                env_extra=_build_env(),
            )
        except Exception as e:
            logger.warning(f"[VideoPipeline] hyperframes {check} 跳过: {e}")

    cmd = [_resolve_npx(), "hyperframes", "render", "--quality", quality, "--fps", str(fps)]
    if output_path:
        cmd += ["-o", str(output_path)]
    if variables:
        # subprocess list 形式传参，无需 shell 转义；JSON 对象 merge 到模板默认值
        cmd += [f"--variables={json.dumps(variables, ensure_ascii=False)}"]
    logger.info(f"[VideoPipeline] render cwd={composition_dir} variables={'yes' if variables else 'no'} cmd={' '.join(cmd)}")
    started = time.time()
    proc = safe_run(
        cmd,
        cwd=str(composition_dir),
        capture_output=True,
        timeout=_RENDER_TIMEOUT_SECONDS,
        env_extra=_build_env(),
    )
    elapsed = round(time.time() - started, 1)
    stdout = (proc.stdout or b"").decode("utf-8", errors="ignore")
    stderr = (proc.stderr or b"").decode("utf-8", errors="ignore")
    if proc.returncode != 0:
        tail = (stderr or stdout)[-1200:]
        raise RuntimeError(f"hyperframes render 失败（rc={proc.returncode}）: {tail}")

    outputs = [
        str(p) for p in sorted(composition_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() == ".mp4"
    ]
    if not outputs:
        raise RuntimeError(
            f"渲染完成但未找到 MP4 产物（检查 composition 是否正确）。stdout 尾: {stdout[-400:]}"
        )
    return {"outputs": outputs, "elapsed_seconds": elapsed, "stdout": stdout, "stderr": stderr}