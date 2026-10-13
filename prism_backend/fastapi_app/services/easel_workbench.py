"""
Easel Web 工作台托管服务（内嵌进 老马AI工作台前端）。

管理外部 Easel 项目（默认 D:\\工作台\\Easel）的 `easel web` 进程生命周期。
模式与 persona_dashboard.py 一致：单实例进程句柄 + 端口探测 + 幂等启动。

环境变量:
- LAOMA_EASEL_DIR:  Easel 仓库根目录（默认 ../Easel，与 LaomaAI-Fusion 同级）
- LAOMA_EASEL_PORT: Easel Web 端口（默认 7860，与 Easel web/app.py:4975 一致）
- OPENCLAW_GATEWAY_PORT / EASEL_GATEWAY_PORT: OpenClaw gateway 端口覆盖
  （优先级：OPENCLAW_GATEWAY_PORT > EASEL_GATEWAY_PORT > profile=easel 哈希默认 37289）
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from loguru import logger

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # fastapi_app/../.. = prism_backend
REPO_ROOT = BACKEND_ROOT.parent

EASEL_DIR = Path(os.getenv("LAOMA_EASEL_DIR") or (REPO_ROOT.parent / "Easel"))
EASEL_PORT = int(os.getenv("LAOMA_EASEL_PORT") or 7860)
EASEL_HOST = "127.0.0.1"
# OpenClaw gateway 默认端口：profile=easel 哈希 20000+fnv1a32("easel")%40000 = 37289
# env 覆盖优先级对齐 Easel gateway_endpoint.py: OPENCLAW_GATEWAY_PORT > EASEL_GATEWAY_PORT > profile 哈希
GATEWAY_PORT = int(
    os.getenv("OPENCLAW_GATEWAY_PORT")
    or os.getenv("EASEL_GATEWAY_PORT")
    or 37289
)

# 进程状态（单实例）
_easel_process: Optional[asyncio.subprocess.Process] = None
_log_task: Optional[asyncio.Task[None]] = None


def _easel_exe() -> Path:
    exe = EASEL_DIR / ".venv" / "Scripts" / ("easel.exe" if sys.platform == "win32" else "easel")
    return exe


def _easel_url() -> str:
    return f"http://{EASEL_HOST}:{EASEL_PORT}"


def _is_local_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((EASEL_HOST, port)) == 0


def _is_pid_alive(pid: Optional[int]) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False
    except Exception:
        return False


def _pid_listening_on_port(port: int) -> Optional[int]:
    """端口被监听但进程句柄丢失时，用 psutil 找到监听进程 PID（用于 stop）。"""
    try:
        import psutil

        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                return conn.pid
    except Exception:
        return None
    return None


async def _pump_logs(process: asyncio.subprocess.Process) -> None:
    """把 Easel 子进程 stdout 转发到老马AI工作台日志。"""
    assert process.stdout is not None
    while True:
        chunk = await process.stdout.readline()
        if not chunk:
            break
        line = chunk.decode("utf-8", errors="ignore").strip()
        if line:
            logger.info(f"[Easel] {line}")


async def _probe_web_api() -> bool:
    """探测 Easel Web API 是否可用（/api/outputs 返回 200 即在线）。"""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{_easel_url()}/api/outputs")
            return resp.status_code == 200
    except Exception:
        return False


async def _probe_gateway() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://{EASEL_HOST}:{GATEWAY_PORT}/")
            return resp.status_code < 500
    except Exception:
        return False


async def get_easel_status() -> Dict[str, Any]:
    """返回 Easel Web 运行状态（进程存活、端口监听、Web API 探测）。"""
    global _easel_process

    running = False
    pid: Optional[int] = None
    if _easel_process is not None and _easel_process.returncode is None:
        running = True
        pid = _easel_process.pid
    elif _is_local_port_open(EASEL_PORT):
        running = True
        pid = _pid_listening_on_port(EASEL_PORT)

    web_api_online = await _probe_web_api() if running else False
    gateway_online = await _probe_gateway()
    installed = (_easel_exe().is_file()) or (EASEL_DIR / "web" / "app.py").is_file()

    return {
        "running": running,
        "pid": pid if running and _is_pid_alive(pid) else None,
        "port": EASEL_PORT,
        "url": _easel_url(),
        "web_api_online": web_api_online,
        "gateway_online": gateway_online,
        "gateway_port": GATEWAY_PORT,
        "dir": str(EASEL_DIR),
        "installed": installed,
    }


async def start_easel() -> Dict[str, Any]:
    """拉起 `easel web --port <EASEL_PORT>` 子进程（幂等：已在运行则直接返回状态）。"""
    global _easel_process, _log_task

    status = await get_easel_status()
    if status["running"] and status["web_api_online"]:
        return status

    exe = _easel_exe()
    if not exe.is_file():
        raise RuntimeError(
            f"Easel 未安装或安装不完整: {EASEL_DIR}（缺少 {exe}）。请先运行 Easel 仓库的 setup.ps1"
        )

    env = os.environ.copy()
    env["EASEL_PORT"] = str(EASEL_PORT)
    env["PYTHONUNBUFFERED"] = "1"
    # Easel web 启动横幅包含 Unicode 字符（✦），GBK 控制台会直接崩溃
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    logger.info(f"[Easel] 启动工作台: {exe} web --port {EASEL_PORT} (cwd={EASEL_DIR})")
    _easel_process = await asyncio.create_subprocess_exec(
        str(exe),
        "web",
        "--port",
        str(EASEL_PORT),
        cwd=str(EASEL_DIR),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        creationflags=creationflags,
    )
    _log_task = asyncio.ensure_future(_pump_logs(_easel_process))

    # 冷启动轮询最多 60s（首次加载可能较慢）
    for _ in range(60):
        await asyncio.sleep(1)
        if _easel_process.returncode is not None:
            raise RuntimeError(f"Easel web 进程退出，退出码 {_easel_process.returncode}，详见老马AI工作台后端日志")
        if await _probe_web_api():
            break

    status = await get_easel_status()
    if not status["web_api_online"]:
        raise RuntimeError("Easel web 启动超时（60s 内 API 未就绪），详见老马AI工作台后端日志")
    return status


async def stop_easel() -> Dict[str, Any]:
    """停止 Easel Web 进程（优先停止本服务拉起的句柄，否则按端口找 PID）。"""
    global _easel_process, _log_task

    stopped_pid: Optional[int] = None
    if _easel_process is not None and _easel_process.returncode is None:
        stopped_pid = _easel_process.pid
        _easel_process.terminate()
        try:
            await asyncio.wait_for(_easel_process.wait(), timeout=8)
        except asyncio.TimeoutError:
            _easel_process.kill()
        _easel_process = None
        if _log_task is not None:
            _log_task.cancel()
            _log_task = None
    else:
        pid = _pid_listening_on_port(EASEL_PORT)
        if pid:
            stopped_pid = pid
            try:
                import psutil

                psutil.Process(pid).terminate()
                logger.info(f"[Easel] 已终止监听 {EASEL_PORT} 的进程 pid={pid}")
            except Exception as e:
                raise RuntimeError(f"停止 Easel 进程 pid={pid} 失败: {e}")

    return {"stopped_pid": stopped_pid, "running": _is_local_port_open(EASEL_PORT)}
