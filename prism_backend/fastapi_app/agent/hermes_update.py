"""Hermes Agent upstream update management.

Update preferences and state live under HERMES_HOME.  That directory is deliberately
outside ``tools/hermes-agent`` and is never passed to git, so model, gateway, MCP and
WebUI state survive source refreshes.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .hermes_config import (
    get_hermes_home_path,
    get_hermes_python_path,
    get_hermes_runtime_stamp_path,
    get_hermes_source_path,
    get_repo_root,
)
from ..utils.subprocess_safe import safe_run


logger = logging.getLogger(__name__)


DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": True,
    "interval_hours": 24,
    "branch": "main",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _settings_path() -> Path:
    return get_hermes_home_path() / "update-settings.json"


def _state_path() -> Path:
    return get_hermes_home_path() / "update-state.json"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def get_update_settings() -> Dict[str, Any]:
    stored = _read_json(_settings_path())
    settings = {**DEFAULT_SETTINGS, **stored}
    settings["enabled"] = bool(settings["enabled"])
    settings["interval_hours"] = max(1, min(168, int(settings["interval_hours"])))
    settings["branch"] = str(settings["branch"] or "main").strip() or "main"
    return settings


def save_update_settings(*, enabled: bool, interval_hours: int, branch: str) -> Dict[str, Any]:
    normalized_branch = str(branch or "main").strip() or "main"
    if normalized_branch.startswith("-") or ".." in normalized_branch:
        raise ValueError("Invalid Hermes upstream branch")
    settings = {
        "enabled": bool(enabled),
        "interval_hours": max(1, min(168, int(interval_hours))),
        "branch": normalized_branch,
    }
    _write_json(_settings_path(), settings)
    return settings


def _git(*args: str, check: bool = True) -> str:
    source = get_hermes_source_path()
    result = safe_run(
        ["git", "-C", str(source), *args],
        timeout=120,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git failed").strip())
    return (result.stdout or "").strip()


def _revision(ref: str) -> Optional[str]:
    value = _git("rev-parse", ref, check=False).strip()
    return value if len(value) == 40 else None


def check_for_updates() -> Dict[str, Any]:
    settings = get_update_settings()
    state = _read_json(_state_path())
    source = get_hermes_source_path()
    if not (source / ".git").exists():
        result = {"installed": False, "update_available": False, "error": "Hermes Agent 尚未安装。"}
    else:
        try:
            branch = settings["branch"]
            _git("fetch", "--depth", "1", "origin", branch)
            local_revision = _revision("HEAD")
            remote_revision = _revision("FETCH_HEAD")
            result = {
                "installed": True,
                "update_available": bool(local_revision and remote_revision and local_revision != remote_revision),
                "local_revision": local_revision,
                "remote_revision": remote_revision,
                "error": None,
            }
        except Exception as exc:
            result = {"installed": True, "update_available": False, "error": str(exc)}
    state.update(result)
    state["last_checked_at"] = _now()
    _write_json(_state_path(), state)
    return get_update_status()


def _powershell() -> Optional[str]:
    return shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")


def _resolve_deps_with(python_exe: Path) -> list[str]:
    """Resolve Hermes deps (base + web) using a Python >=3.11 interpreter."""
    code = (
        "import json, pathlib, tomllib; "
        "d = tomllib.loads(pathlib.Path('pyproject.toml').read_text()); "
        "p = d.get('project', {}); "
        "deps = list(p.get('dependencies', [])); "
        "deps.extend((p.get('optional-dependencies') or {}).get('web', [])); "
        "print(json.dumps(deps))"
    )
    result = safe_run(
        [str(python_exe), "-c", code],
        cwd=str(get_hermes_source_path()),
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Failed to resolve Hermes dependencies from pyproject.toml")
    return [d for d in json.loads(result.stdout) if isinstance(d, str)]


def apply_update() -> Dict[str, Any]:
    """Run the full update so dependencies and source stay aligned.

    Windows uses the existing PowerShell installer; macOS/Linux do the same job
    with Python (git pull + pip reinstall into prismenv) so no PowerShell is
    required.
    """
    settings = get_update_settings()
    state = _read_json(_state_path())
    branch = settings["branch"]
    source = get_hermes_source_path()
    python_exe = get_hermes_python_path()
    stamp = get_hermes_runtime_stamp_path()

    state.update({"updating": True, "last_error": None})
    _write_json(_state_path(), state)
    try:
        # ------------------------------------------------------------------
        # Layer 1 (code) -- snapshot HEAD before we touch the working tree.
        # This gives rollback_update a concrete SHA to reset to.
        # ------------------------------------------------------------------
        old_sha = _git("rev-parse", "HEAD")
        state["pre_update_sha"] = old_sha
        _write_json(_state_path(), state)

        if sys.platform == "win32":
            shell = _powershell()
            script = get_repo_root() / "scripts" / "hermes" / "setup-local-hermes.ps1"
            if not shell or not script.exists():
                raise RuntimeError("找不到 PowerShell 或 Hermes 安装脚本，无法执行完整更新。")
            result = safe_run(
                [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                 "-Branch", branch, "-Force"],
                timeout=1800, check=False,
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "Hermes 更新失败").strip()[-4000:])
        else:
            # 拉取/重置 Hermes 源码到目标分支
            if not (source / ".git").exists():
                _git("clone", "--depth", "1", "--branch", branch,
                     "https://github.com/NousResearch/hermes-agent.git", str(source))
            else:
                _git("fetch", "--depth", "1", "origin", branch)
                _git("reset", "--hard", f"origin/{branch}")
                _git("clean", "-fd")

            # 确保 prismenv 存在
            if not python_exe.exists():
                from .hermes_config import get_prismenv_root
                base = sys.executable
                safe_run([base, "-m", "venv", str(get_prismenv_root())], check=True, timeout=300)

            # 升级 pip 基础组件
            safe_run([str(python_exe), "-m", "pip", "install", "--upgrade",
                      "pip", "wheel", "setuptools"],
                     timeout=300, check=True)
            safe_run([str(python_exe), "-m", "pip", "uninstall", "-y",
                      "openmanus", "browser-use", "langchain-openai"],
                     timeout=120)

            # 安装 Hermes 依赖（base + web）
            deps = _resolve_deps_with(python_exe)
            safe_run([str(python_exe), "-m", "pip", "install", *deps],
                     timeout=1200, check=True)

            # 打上就绪标记
            version = safe_run([str(python_exe), "--version"], timeout=30).stdout.strip()
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(f"{version}\n", encoding="utf-8")
    except Exception as exc:
        logger.warning("Hermes apply_update failed, triggering rollback: %s", exc)
        try:
            rollback_result = rollback_update()
        except Exception as rb_exc:
            logger.warning("Hermes rollback_update raised: %s", rb_exc)
            rollback_result = {"ok": False, "error": str(rb_exc)}
        state.update({
            "updating": False,
            "last_error": str(exc),
            "rollback_result": rollback_result,
        })
        _write_json(_state_path(), state)
        raise

    state.update({
        "updating": False,
        "update_available": False,
        "local_revision": _revision("HEAD"),
        "remote_revision": _revision("HEAD"),
        "last_updated_at": _now(),
        "last_error": None,
    })
    _write_json(_state_path(), state)
    return get_update_status()


def _restore_code(pre_update_sha: str) -> Dict[str, Any]:
    """Layer 1 (code): reset Hermes source back to ``pre_update_sha``.

    Hermes ships as a shallow clone (``git clone --depth 1`` in the
    ``setup-local-hermes.ps1`` installer), so ``pre_update_sha`` may already
    be gone from local object storage if a later fetch truncated it.  Probe
    with ``git cat-file -t`` first; if missing, fetch it with ``--depth 50``
    before the hard reset.  Errors are captured in the returned dict and never
    re-raised here -- the caller wraps us in its own try/except.
    """
    result: Dict[str, Any] = {"code_restored": False, "sha": pre_update_sha}
    if not pre_update_sha:
        return result

    # Probe for the object locally; if absent (shallow truncate), fetch it.
    probe = _git("cat-file", "-t", pre_update_sha, check=False).strip()
    if not probe:
        try:
            _git("fetch", "--depth", "50", "origin", pre_update_sha)
        except Exception as exc:
            result["fetch_error"] = str(exc)[:500]
            return result

    _git("reset", "--hard", pre_update_sha)
    _git("clean", "-fd")
    result["code_restored"] = True
    return result


def _rerun_setup_script(branch: str) -> Dict[str, Any]:
    """Layer 2 (env): re-run setup-local-hermes.ps1 (Win) or the pip flow
    (non-Win) so the venv matches the reset source tree. Mirrors the block
    inside ``apply_update``."""
    result: Dict[str, Any] = {"attempted": True}
    source = get_hermes_source_path()
    python_exe = get_hermes_python_path()
    try:
        if sys.platform == "win32":
            shell = _powershell()
            script = get_repo_root() / "scripts" / "hermes" / "setup-local-hermes.ps1"
            if not shell or not script.exists():
                result["error"] = "找不到 PowerShell 或 Hermes 安装脚本，无法执行回滚。"
                return result
            res = safe_run(
                [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                 "-Branch", branch, "-Force"],
                timeout=1800, check=False,
            )
            if res.returncode != 0:
                result["error"] = (res.stderr or res.stdout or "Hermes 回滚失败").strip()[-4000:]
                return result
            result["ok"] = True
        else:
            # Non-Windows: replicate the tail end of apply_update so pip tracks
            # the reset tree. This is defensive -- apply_update on Linux already
            # ran setup, so if that fails, at least env is refreshed.
            if not (source / ".git").exists():
                result["error"] = f"Hermes 源码缺失: {source}"
                return result
            _git("reset", "--hard", f"origin/{branch}")
            _git("clean", "-fd")
            if not python_exe.exists():
                result["error"] = f"Python 环境缺失: {python_exe}"
                return result
            safe_run([str(python_exe), "-m", "pip", "install", "--upgrade",
                      "pip", "wheel", "setuptools"],
                     timeout=300, check=True)
            deps = _resolve_deps_with(python_exe)
            safe_run([str(python_exe), "-m", "pip", "install", *deps],
                     timeout=1200, check=True)
            stamp = get_hermes_runtime_stamp_path()
            version = safe_run([str(python_exe), "--version"],
                               timeout=30).stdout.strip()
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(f"{version}\n", encoding="utf-8")
            result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)[:1000]
    return result


def rollback_update() -> Dict[str, Any]:
    """Two-layer rollback for Hermes.

    * Layer 1 (code): ``git reset --hard <pre_update_sha>`` + ``git clean -fd``,
      with a shallow-clone fallback (``cat-file -t`` probe + ``fetch --depth 50``).
    * Layer 2 (env): re-run ``setup-local-hermes.ps1`` so the prismenv / WebUI
      assets track the restored source tree.

    Every step is wrapped in try/except; failures are recorded in the returned
    dict and never re-raised here.  If ``state["pre_update_sha"]`` is missing
    (very old state file or apply crashed before the snapshot was written), the
    function degrades to Layer 2 only.
    """
    state = _read_json(_state_path())
    result: Dict[str, Any] = {"ok": True}

    settings = get_update_settings()
    branch = settings["branch"]
    pre_update_sha = state.get("pre_update_sha")

    # ------------------------------------------------------------------
    # Layer 1 (code).
    # ------------------------------------------------------------------
    layer1: Dict[str, Any] = {"attempted": False}
    if pre_update_sha:
        layer1["attempted"] = True
        try:
            layer1["result"] = _restore_code(pre_update_sha)
        except Exception as exc:
            layer1["error"] = str(exc)[:1000]
            result["ok"] = False
    else:
        layer1["skipped"] = "no pre_update_sha in state"
    result["layer1"] = layer1

    # ------------------------------------------------------------------
    # Layer 2 (env): re-run the installer so the venv matches source.
    # ------------------------------------------------------------------
    layer2: Dict[str, Any] = {"attempted": False}
    try:
        layer2["result"] = _rerun_setup_script(branch)
        layer2["attempted"] = True
        if not layer2["result"].get("ok"):
            layer2["error"] = layer2["result"].get("error")
            result["ok"] = False
    except Exception as exc:
        layer2["error"] = str(exc)[:1000]
        result["ok"] = False
    result["layer2"] = layer2

    # ------------------------------------------------------------------
    # Persist rollback bookkeeping.  Never raise while writing state.
    # ------------------------------------------------------------------
    state.update({
        "updating": False,
        "last_rollback_at": _now(),
        "last_rollback_result": result,
        "last_error": None if result.get("ok") else (state.get("last_error") or "rollback partially failed"),
    })
    try:
        _write_json(_state_path(), state)
    except Exception as exc:
        result["state_write_error"] = str(exc)

    return result


def get_update_status() -> Dict[str, Any]:
    settings = get_update_settings()
    state = _read_json(_state_path())
    source = get_hermes_source_path()
    return {
        "settings": settings,
        "installed": (source / ".git").exists(),
        "local_revision": state.get("local_revision") or (_revision("HEAD") if (source / ".git").exists() else None),
        "remote_revision": state.get("remote_revision"),
        "update_available": bool(state.get("update_available")),
        "updating": bool(state.get("updating")),
        "last_checked_at": state.get("last_checked_at"),
        "last_updated_at": state.get("last_updated_at"),
        "last_error": state.get("last_error") or state.get("error"),
        # 三层回滚可观测字段（P3-2 引入）：有则透传，无则 None，前端/调度器可判断是否可回滚。
        "pre_update_sha": state.get("pre_update_sha"),
        "last_rollback_at": state.get("last_rollback_at"),
        "last_rollback_result": state.get("last_rollback_result"),
        "preserved_home_path": str(get_hermes_home_path()),
    }


class HermesUpdateScheduler:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while True:
            settings = get_update_settings()
            if settings["enabled"]:
                status = get_update_status()
                last = status.get("last_checked_at")
                due = True
                if last:
                    try:
                        due = datetime.now(timezone.utc) >= datetime.fromisoformat(last) + timedelta(hours=settings["interval_hours"])
                    except ValueError:
                        pass
                if due:
                    try:
                        checked = await asyncio.to_thread(check_for_updates)
                        if checked["update_available"]:
                            # Updating in-use Python/UI files is unsafe on Windows.
                            from .hermes_agent import reset_hermes_agent, stop_hermes_dashboard

                            await stop_hermes_dashboard()
                            await reset_hermes_agent()
                            await asyncio.to_thread(apply_update)
                    except Exception as exc:
                        logger.warning("Scheduled Hermes update failed: %s", exc)
            await asyncio.sleep(900)


_scheduler = HermesUpdateScheduler()


async def start_hermes_update_scheduler() -> None:
    await _scheduler.start()


async def stop_hermes_update_scheduler() -> None:
    await _scheduler.stop()
