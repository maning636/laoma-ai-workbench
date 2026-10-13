"""系统预检（Preflight Check）

一次性聚合所有依赖组件状态，供前端设置页 / 启动自检使用。

设计原则：
- 每项独立 try/except，失败时返回 reachable=False + reason，绝不抛
- 所有网络探测超时 ≤ 2 秒（socket.connect_ex / httpx.timeout / asyncio.wait_for）
- 使用 asyncio 并发调度，整体调用应远小于总超时之和

调用：
    await run_preflight_check()  ->  dict
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any, Optional

# 硬编码总超时（防个别环节极端卡顿）
_TIMEOUT = 2.0


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _safe_str(v: Any) -> str:
    try:
        return str(v)
    except Exception:
        return "<unserializable>"


def _reason_from_exc(e: BaseException) -> str:
    name = type(e).__name__
    msg = str(e)
    return f"{name}: {msg}" if msg else name


async def _tcp_ping(url: str, timeout: float = _TIMEOUT) -> tuple[bool, str]:
    """通过解析 redis-style URL 后 socket 连接测试 TCP 可达性。

    返回 (reachable, reason)。失败时 reason 描述失败原因，成功时 reason=""。
    """
    host, port = _parse_redis_url(url)
    if not host or not port:
        return False, "invalid_url"
    loop = asyncio.get_running_loop()

    def _do() -> tuple[bool, str]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                s.connect_ex((host, port))  # 非 0 => 不可达
                return True, ""
            finally:
                try:
                    s.close()
                except Exception:
                    pass
        except Exception as e:
            return False, _reason_from_exc(e)

    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _do), timeout=timeout + 0.5
        )
    except asyncio.TimeoutError:
        return False, f"timeout>{timeout}s"
    except Exception as e:
        return False, _reason_from_exc(e)


def _parse_redis_url(url: str) -> tuple[Optional[str], Optional[int]]:
    """解析 redis://host:port 或 redis://host 形式的 URL。

    失败时返回 (None, None)。仅支持最常用的 host:port / 默认 6379。
    """
    try:
        from urllib.parse import urlparse
        u = (url or "").strip()
        if not u:
            return None, None
        if "://" not in u:
            # 裸 host:port
            if ":" in u:
                h, p = u.split(":", 1)
                try:
                    return h, int(p)
                except Exception:
                    return None, None
            return None, None
        parsed = urlparse(u)
        host = parsed.hostname
        port = parsed.port or 6379
        return host, int(port)
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# 各组件探测函数
# ---------------------------------------------------------------------------

async def _check_python() -> dict:
    try:
        return {
            "path": sys.executable,
            "version": sys.version,
            "prismenv_ready": "prismenv" in (sys.executable or ""),
        }
    except Exception as e:
        return {"reachable": False, "reason": _reason_from_exc(e)}


async def _check_redis() -> dict:
    try:
        from fastapi_app.core.config import settings
    except Exception as e:
        return {"url": "", "reachable": False, "reason": _reason_from_exc(e)}
    url = (getattr(settings, "REDIS_URL", "") or "").strip() or "redis://localhost:6379/0"
    try:
        reachable, reason = await _tcp_ping(url)
    except Exception as e:
        return {"url": url, "reachable": False, "reason": _reason_from_exc(e)}
    return {"url": url, "reachable": reachable, "reason": reason}


async def _check_celery() -> dict:
    try:
        from fastapi_app.core.config import settings
    except Exception as e:
        return {
            "broker": "", "result_backend": "", "reachable": False,
            "reason": _reason_from_exc(e),
        }
    broker = (getattr(settings, "CELERY_BROKER_URL", "") or "").strip() \
             or (getattr(settings, "REDIS_URL", "") or "").strip() \
             or "redis://localhost:6379/0"
    result_backend = (getattr(settings, "CELERY_RESULT_BACKEND", "") or "").strip() \
                     or (getattr(settings, "REDIS_URL", "") or "").strip() \
                     or broker
    try:
        reachable, reason = await _tcp_ping(broker)
    except Exception as e:
        return {
            "broker": broker,
            "result_backend": result_backend,
            "reachable": False,
            "reason": _reason_from_exc(e),
        }
    return {
        "broker": broker,
        "result_backend": result_backend,
        "reachable": reachable,
        "reason": reason,
    }


async def _check_easel() -> dict:
    try:
        from fastapi_app.services import easel_workbench as _ew
        easel_dir = Path(str(getattr(_ew, "EASEL_DIR", ""))) if getattr(_ew, "EASEL_DIR", None) else None
    except Exception as e:
        return {"dir": "", "installed": False, "ready": False, "reason": _reason_from_exc(e)}
    if easel_dir is None or not str(easel_dir):
        return {"dir": "", "installed": False, "ready": False, "reason": "EASEL_DIR unresolved"}
    try:
        installed = easel_dir.exists()
        return {
            "dir": str(easel_dir),
            "installed": bool(installed),
            "ready": bool(installed),
            "reason": "" if installed else "directory missing",
        }
    except Exception as e:
        return {"dir": str(easel_dir), "installed": False, "ready": False,
                "reason": _reason_from_exc(e)}


async def _check_hermes() -> dict:
    try:
        from fastapi_app.agent.hermes_config import get_hermes_home_path
        home = Path(str(get_hermes_home_path()))
    except Exception as e:
        return {
            "home": "", "installed": False, "ready": False,
            "dashboard_port": 9119, "reason": _reason_from_exc(e),
        }
    try:
        installed = home.exists()
        return {
            "home": str(home),
            "installed": bool(installed),
            "ready": bool(installed),
            "dashboard_port": 9119,
            "reason": "" if installed else "home missing",
        }
    except Exception as e:
        return {
            "home": str(home), "installed": False, "ready": False,
            "dashboard_port": 9119, "reason": _reason_from_exc(e),
        }


async def _check_persona_api() -> dict:
    url = "http://127.0.0.1:8787"
    try:
        import httpx
    except Exception as e:
        return {"url": url, "reachable": False, "reason": f"httpx_missing: {_reason_from_exc(e)}"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT, connect=_TIMEOUT)) as client:
            resp = await client.get(url)
            # 只要能收到 HTTP 响应就算可达
            return {
                "url": url,
                "reachable": True,
                "status_code": int(resp.status_code),
                "reason": "",
            }
    except Exception as e:
        return {"url": url, "reachable": False, "reason": _reason_from_exc(e)}


async def _check_playwright() -> dict:
    """尝试 import patchright 并探测 chromium 是否已安装（不做实际启动）。"""
    try:
        import patchright  # type: ignore  # noqa: F401
    except Exception as e:
        return {"patchright_chromium_installed": False,
                "reason": f"patchright_import_failed: {_reason_from_exc(e)}"}

    # 探测 registry 目录：patchright/playwright 通用位置
    # Windows: %LOCALAPPDATA%\\ms-playwright\\chromium-xxxx\\chrome-win\\chrome.exe
    # Linux/mac: ~/.cache/ms-playwright/chromium-xxxx/chrome-linux/chrome
    candidates = []
    env_local = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    if env_local:
        candidates.append(Path(env_local) / "ms-playwright")
    home = Path.home()
    candidates.append(home / ".cache" / "ms-playwright")
    env_home = os.environ.get("MS_PLAYWRIGHT_BROWSERS_PATH")
    if env_home:
        candidates.append(Path(env_home).expanduser())

    for root in candidates:
        try:
            if not root.exists():
                continue
            # 只要有一个 chromium-* 子目录就视为已安装
            for sub in root.iterdir():
                if sub.is_dir() and sub.name.startswith("chromium"):
                    return {
                        "patchright_chromium_installed": True,
                        "registry_dir": str(root),
                        "revision_dir": sub.name,
                        "reason": "",
                    }
        except Exception:
            continue

    return {
        "patchright_chromium_installed": False,
        "reason": "no chromium-* dir under ms-playwright registry",
    }


async def _check_disk_space() -> dict:
    try:
        from fastapi_app.core.paths import get_data_dir
        data_dir = Path(str(get_data_dir()))
    except Exception:
        data_dir = Path(os.environ.get("APPDATA") or Path.home())
    try:
        target = data_dir if data_dir.exists() else data_dir.parent
        while target and not target.exists() and target != target.parent:
            target = target.parent
        if not target or not target.exists():
            target = Path.home()
        total, _used, free = shutil.disk_usage(str(target))
        total_gb = round(total / (1024 ** 3), 2)
        free_gb = round(free / (1024 ** 3), 2)
        return {
            "path": str(target),
            "total_gb": total_gb,
            "free_gb": free_gb,
            "warning": free_gb < 10,
        }
    except Exception as e:
        return {
            "path": str(data_dir),
            "total_gb": 0, "free_gb": 0,
            "warning": True,
            "reason": _reason_from_exc(e),
        }


async def _check_skills_dir() -> bool:
    try:
        from fastapi_app.core.paths import get_skills_dir
        return bool(Path(str(get_skills_dir())).exists())
    except Exception:
        return False


async def _check_third_party_tools() -> dict:
    result = {}
    try:
        from fastapi_app.core import paths as _paths
    except Exception as e:
        for key in ("openmontage", "moneyprinter"):
            result[key] = {
                "dir": "", "installed": False, "reason": _reason_from_exc(e),
            }
        return result
    for key, getter in (
        ("openmontage", "get_openmontage_dir"),
        ("moneyprinter", "get_moneyprinter_dir"),
    ):
        try:
            fn = getattr(_paths, getter, None)
            if fn is None:
                result[key] = {"dir": "", "installed": False,
                               "reason": f"{getter} missing"}
                continue
            d = Path(str(fn()))
            installed = d.exists()
            result[key] = {
                "dir": str(d),
                "installed": bool(installed),
            }
        except Exception as e:
            result[key] = {
                "dir": "", "installed": False, "reason": _reason_from_exc(e),
            }
    return result


async def _check_template_lib() -> dict:
    try:
        from fastapi_app.core.paths import get_template_lib_dir
        d = Path(str(get_template_lib_dir()))
    except Exception as e:
        return {"dir": "", "exists": False, "reason": _reason_from_exc(e)}
    try:
        exists = d.exists()
        return {
            "dir": str(d),
            "exists": bool(exists),
            "reason": "" if exists else "directory missing",
        }
    except Exception as e:
        return {"dir": str(d), "exists": False, "reason": _reason_from_exc(e)}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def run_preflight_check() -> dict:
    """聚合所有依赖组件状态。永不抛、永不阻塞超过约 2 秒（并发）。"""
    start = time.time()
    tasks = {
        "python": _check_python(),
        "redis": _check_redis(),
        "celery": _check_celery(),
        "easel": _check_easel(),
        "hermes": _check_hermes(),
        "persona_api": _check_persona_api(),
        "playwright": _check_playwright(),
        "disk_space": _check_disk_space(),
        "skills_dir_exists": _check_skills_dir(),
        "third_party_tools": _check_third_party_tools(),
        "template_lib": _check_template_lib(),
    }
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks.values(), return_exceptions=True),
            timeout=8.0,  # 全局兜底，防止极端异常
        )
    except Exception as e:
        # 极端异常兜底：所有键填最小占位
        results = [
            {"error": _reason_from_exc(e)} for _ in tasks
        ]

    out: dict[str, Any] = {}
    for name, res in zip(tasks.keys(), results):
        if isinstance(res, BaseException):
            out[name] = {"error": _reason_from_exc(res)}
        elif isinstance(res, dict):
            out[name] = res
        else:
            # 允许标量值（例如 skills_dir_exists 直接是 bool）
            out[name] = res
    out["_meta"] = {
        "elapsed_ms": int((time.time() - start) * 1000),
        "hostname": os.uname().nodename if hasattr(os, "uname") else (
            os.environ.get("COMPUTERNAME", "") or "unknown"
        ),
    }
    return out
