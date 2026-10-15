"""Easel upstream update management with three-layer rollback.

Mirrors :mod:`hermes_update` (dual JSON files under EASEL_DIR, atomic writes,
scheduled apply on interval), and adds three reversible layers on top of Easel
itself:

* **Layer 1 (code)** -- ``git reset --hard <pre_update_sha>`` after a snapshot
  of ``HEAD``.
* **Layer 2 (env)**  -- ``pip freeze`` of the Easel venv, plus the resolved
  ``openclaw`` CLI version (``npm list -g openclaw --depth=0``).
* **Layer 3 (data)** -- copies of ``EASEL_DIR/.env`` and the user's
  ``~/.openclaw-easel/openclaw.json`` (both optional).

Design notes:

* Easel ships as a **shallow clone** (single commit). We only ``--unshallow``
  on the first real apply, because ``git fetch --depth 1 origin main`` on a
  shallow clone happily works for read-only comparison and avoids a large
  transfer when the user just wants ``check_for_updates``.
* ``apply_update`` and ``rollback_update`` both run the ``setup.ps1`` /
  ``setup.sh`` installer to align the venv with the reset source tree.
* Every mutation is guarded by a global ``updating`` flag in
  ``update-state.json``. If any step of apply raises, ``rollback_update`` is
  invoked automatically; rollback itself is fully try/except and only records
  failure state, never raises a second exception.
* This module is **not** wired to ``main.py`` in this commit. It is exposed
  programmatically and can be toggled by a follow-up task.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.subprocess_safe import safe_run, safe_popen


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_BACKEND_ROOT = Path(__file__).resolve().parents[2]          # .../prism_backend
_REPO_ROOT = _BACKEND_ROOT.parent

_DEFAULT_EASEL_DIR = Path(os.getenv("LAOMA_EASEL_DIR") or (_REPO_ROOT.parent / "Easel"))

# Mirrors EASEL_PORT default in easel_workbench (LAOMA_EASEL_PORT > 7860).
EASEL_DIR = Path(os.getenv("LAOMA_EASEL_DIR") or _DEFAULT_EASEL_DIR)
EASEL_PORT = int(os.getenv("LAOMA_EASEL_PORT") or 7860)
# Mirrors GATEWAY_PORT in easel_workbench. Env override priority matches
# workbench: OPENCLAW_GATEWAY_PORT > EASEL_GATEWAY_PORT > profile=easel hash default 37289.
GATEWAY_PORT = int(
    os.getenv("OPENCLAW_GATEWAY_PORT")
    or os.getenv("EASEL_GATEWAY_PORT")
    or 37289
)

OPENCLAW_USER_DIR = Path(os.getenv("LAOMA_OPENCLAW_DIR") or (Path.home() / ".openclaw-easel"))
OPENCLAW_CONFIG = OPENCLAW_USER_DIR / "openclaw.json"

# Upper bound for a single apply/rollback run (1800s matches hermes_update).
_SETUP_TIMEOUT_S = 1800
_GIT_TIMEOUT_S = 180
_CHECK_TIMEOUT_S = 120

DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": False,              # opt-in: this is a fresh module
    "interval_hours": 24,
    "branch": "main",
    "agent_commit": None,          # optional pin; None = follow origin/branch
    "auto_apply": False,           # scheduler only auto-applies if explicitly True
}

DEFAULT_STATE: Dict[str, Any] = {
    "updating": False,
    "pre_update_sha": None,
    "env_snapshot": {},
    "backups_path": None,
    "last_checked_at": None,
    "last_updated_at": None,
    "last_error": None,
    "local_revision": None,
    "remote_revision": None,
    "update_available": False,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _settings_path() -> Path:
    return EASEL_DIR / "update-settings.json"


def _state_path() -> Path:
    return EASEL_DIR / "update-state.json"


def _backups_root() -> Path:
    return EASEL_DIR / "backups"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    """Atomic write: temp file in the same directory, then os.replace()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    with temporary.open("w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(str(temporary), str(path))


def get_update_settings() -> Dict[str, Any]:
    stored = _read_json(_settings_path())
    settings = {**DEFAULT_SETTINGS, **stored}
    settings["enabled"] = bool(settings["enabled"])
    try:
        settings["interval_hours"] = max(1, min(168, int(settings["interval_hours"])))
    except (TypeError, ValueError):
        settings["interval_hours"] = 24
    settings["branch"] = str(settings["branch"] or "main").strip() or "main"
    # Optional pin: if provided, must look like a commit SHA (short or full).
    agent_commit = settings.get("agent_commit")
    if isinstance(agent_commit, str):
        agent_commit = agent_commit.strip() or None
    settings["agent_commit"] = agent_commit
    return settings


def save_update_settings(
    *,
    enabled: bool,
    interval_hours: int,
    branch: str,
    agent_commit: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_branch = str(branch or "main").strip() or "main"
    if normalized_branch.startswith("-") or ".." in normalized_branch:
        raise ValueError("Invalid Easel upstream branch")
    if agent_commit is not None:
        agent_commit = str(agent_commit).strip()
        if not agent_commit or len(agent_commit) < 7:
            raise ValueError("Invalid Easel agent_commit (need >= 7 hex chars)")
    settings = {
        "enabled": bool(enabled),
        "interval_hours": max(1, min(168, int(interval_hours))),
        "branch": normalized_branch,
        "agent_commit": agent_commit,
    }
    _write_json(_settings_path(), settings)
    return settings


def get_update_status() -> Dict[str, Any]:
    settings = get_update_settings()
    state = _read_json(_state_path())
    installed = (EASEL_DIR / ".git").exists()
    return {
        "settings": settings,
        "installed": installed,
        "local_revision": state.get("local_revision") or (_revision("HEAD") if installed else None),
        "remote_revision": state.get("remote_revision"),
        "update_available": bool(state.get("update_available")),
        "updating": bool(state.get("updating")),
        "pre_update_sha": state.get("pre_update_sha"),
        "backups_path": state.get("backups_path"),
        "env_snapshot": state.get("env_snapshot") or {},
        "last_checked_at": state.get("last_checked_at"),
        "last_updated_at": state.get("last_updated_at"),
        "last_error": state.get("last_error") or state.get("error"),
        "easel_dir": str(EASEL_DIR),
    }


# ---------------------------------------------------------------------------
# git / subprocess wrappers
# ---------------------------------------------------------------------------

def _git(*args: str, check: bool = True, timeout: int = _GIT_TIMEOUT_S) -> str:
    """Run git in EASEL_DIR, return stdout. Raises on non-zero when check=True."""
    if not (EASEL_DIR / ".git").exists():
        raise RuntimeError(f"Easel 不是 git 仓库或缺少 .git: {EASEL_DIR}")
    result = safe_run(
        ["git", "-C", str(EASEL_DIR), *args],
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git failed").strip())
    return (result.stdout or "").strip()


def _revision(ref: str) -> Optional[str]:
    value = _git("rev-parse", ref, check=False).strip()
    return value if len(value) in (40, 7, 8, 12) and _is_hex(value) else None


def _is_hex(value: str) -> bool:
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


def _powershell() -> Optional[str]:
    return shutil.which("pwsh") or shutil.which("powershell") or shutil.which("powershell.exe")


def _pip_freeze_cmd() -> List[str]:
    venv = EASEL_DIR / ".venv"
    if sys.platform == "win32":
        exe = venv / "Scripts" / "python.exe"
    else:
        exe = venv / "bin" / "python"
    if exe.exists():
        return [str(exe), "-m", "pip", "freeze"]
    return [sys.executable, "-m", "pip", "freeze"]


# ---------------------------------------------------------------------------
# Layer 3: data backup/restore
# ---------------------------------------------------------------------------

def _backup_data_dir() -> Path:
    """Create EASEL_DIR/backups/<ts>/ and snapshot:
      - EASEL_DIR/.env (single file, if present)
      - OPENCLAW_USER_DIR/** (whole directory, if present)

    目录级备份原因（D 类 review 修订）：
      openclaw.json 只是 ~/.openclaw-easel/ 的顶层索引文件。
      同一目录下还有 agents/*/sessions/*.jsonl（会话历史）、sessions.json、
      skills/*（用户装过的 skills）、profiles/*、credentials/ 等 —— 只做单文件
      备份会导致 openclaw 升级后丢失会话历史与本地 skill 配置，回滚时无法完整
      恢复。故整体目录复制（shutil.copytree,dirs_exist_ok=False 首次安全）。
    """
    ts = _ts_slug()
    dest = _backups_root() / ts
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "manifest.json").write_text(
        json.dumps({"created_at": _now(), "timestamp": ts, "schema_version": 2},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # .env 仍是单文件
    env_src = EASEL_DIR / ".env"
    if env_src.is_file():
        shutil.copy2(str(env_src), str(dest / ".env"))

    # openclaw 用户目录整体复制 —— 目录级备份
    if OPENCLAW_USER_DIR.is_dir():
        # 记录目标路径，便于 _restore_data_dir 恢复原路径
        openclaw_dest = dest / "openclaw"
        # dirs_exist_ok=False 但 dest 目录是新建的，不会冲突
        shutil.copytree(
            str(OPENCLAW_USER_DIR),
            str(openclaw_dest),
            symlinks=True,
            # dirs_exist_ok=False (default); dest 是全新目录
        )
        logger.info(
            "Backed up openclaw user dir (directory): %s -> %s",
            OPENCLAW_USER_DIR, openclaw_dest,
        )

    return dest


def _restore_data_dir(backup_dir: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    env_copy = backup_dir / ".env"
    if env_copy.is_file():
        shutil.copy2(str(env_copy), str(EASEL_DIR / ".env"))
        result[".env"] = True
    else:
        result[".env"] = False

    # 目录级恢复：优先从 backup/openclaw/ 恢复整个目录，保留 openclaw.json 语义
    openclaw_backup_dir = backup_dir / "openclaw"
    if openclaw_backup_dir.is_dir():
        try:
            # 备份路径可能与当前 OPENCLAW_USER_DIR 不同（用户改了 env / 换机器），
            # 这里以当前 env 指向为准；目录内文件覆盖式合并，避免误删用户新加文件。
            OPENCLAW_USER_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                str(openclaw_backup_dir),
                str(OPENCLAW_USER_DIR),
                dirs_exist_ok=True,  # 合并而非替换；已存在同名单文件则覆盖
                symlinks=True,
            )
            result["openclaw_dir"] = True
            # 兼容旧调用方读取 openclaw.json 字段（顶层索引文件是否恢复）
            result["openclaw.json"] = (OPENCLAW_USER_DIR / "openclaw.json").is_file()
        except Exception as exc:
            result["openclaw_dir"] = False
            result["openclaw_dir_error"] = str(exc)[:500]
    else:
        # 旧备份格式兜底：单文件
        cfg_copy = backup_dir / "openclaw.json"
        if cfg_copy.is_file():
            OPENCLAW_USER_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(cfg_copy), str(OPENCLAW_CONFIG))
            result["openclaw.json"] = True
            result["openclaw_dir"] = False
        else:
            result["openclaw.json"] = False
            result["openclaw_dir"] = False
    return result


# ---------------------------------------------------------------------------
# Layer 2: env (pip + npm openclaw) snapshot/restore
# ---------------------------------------------------------------------------

def _snapshot_env(backup_dir: Path) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {}

    # pip freeze -> backup_dir/pip-freeze.txt
    pip_out_path = backup_dir / "pip-freeze.txt"
    try:
        res = safe_run(
            _pip_freeze_cmd(),
            timeout=180,
            check=False,
            cwd=str(EASEL_DIR),
        )
        text = res.stdout or ""
        pip_out_path.write_text(text, encoding="utf-8")
        snapshot["pip_freeze_path"] = str(pip_out_path)
        snapshot["pip_freeze_ok"] = res.returncode == 0
        if res.returncode != 0:
            snapshot["pip_freeze_error"] = (res.stderr or "").strip()[:1000]
    except Exception as exc:  # pragma: no cover
        snapshot["pip_freeze_ok"] = False
        snapshot["pip_freeze_error"] = str(exc)[:1000]

    # openclaw --version (from whichever CLI is on PATH)
    openclaw_bin = shutil.which("openclaw")
    if openclaw_bin:
        try:
            res = safe_run(
                [openclaw_bin, "--version"],
                timeout=30,
                check=False,
            )
            version = (res.stdout or res.stderr or "").strip().splitlines()[-1] if (res.stdout or res.stderr).strip() else ""
            snapshot["openclaw_bin"] = openclaw_bin
            snapshot["openclaw_version"] = version or None
        except Exception as exc:
            snapshot["openclaw_version_error"] = str(exc)[:500]
    else:
        snapshot["openclaw_bin"] = None
        snapshot["openclaw_version"] = None
    return snapshot


def _restore_env(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"pip_restored": False, "npm_restored": False}
    if not isinstance(snapshot, dict):
        return result

    freeze_path = snapshot.get("pip_freeze_path")
    if freeze_path:
        freeze_file = Path(freeze_path)
        if freeze_file.is_file():
            try:
                venv = EASEL_DIR / ".venv"
                if sys.platform == "win32":
                    pip_exe = venv / "Scripts" / "python.exe"
                else:
                    pip_exe = venv / "bin" / "python"
                if pip_exe.exists():
                    res = safe_run(
                        [str(pip_exe), "-m", "pip", "install", "-r", str(freeze_file)],
                        timeout=_SETUP_TIMEOUT_S, check=False,
                    )
                    result["pip_restored"] = res.returncode == 0
                    if res.returncode != 0:
                        result["pip_error"] = (res.stderr or "").strip()[:1000]
            except Exception as exc:
                result["pip_error"] = str(exc)[:500]

    version = snapshot.get("openclaw_version")
    if version and version not in ("unknown", ""):
        # Best effort: pin openclaw to the recorded version string.
        try:
            res = safe_run(
                ["npm", "install", "-g", f"openclaw@{version}"],
                timeout=_SETUP_TIMEOUT_S, check=False,
            )
            result["npm_restored"] = res.returncode == 0
            if res.returncode != 0:
                result["npm_error"] = (res.stderr or res.stdout or "").strip()[:1000]
        except Exception as exc:
            result["npm_error"] = str(exc)[:500]
    return result


# ---------------------------------------------------------------------------
# Layer 1: code snapshot/restore
# ---------------------------------------------------------------------------

def _snapshot_code() -> str:
    return _git("rev-parse", "HEAD")


def _restore_code(pre_update_sha: Optional[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"code_restored": False, "sha": pre_update_sha}
    if not pre_update_sha:
        return result

    # If the target object is not local (e.g. shallow clone truncated), fetch it.
    probe = _git("cat-file", "-t", pre_update_sha, check=False)
    if not probe.strip():
        try:
            _git("fetch", "--depth", "50", "origin", pre_update_sha)
        except Exception as exc:
            result["fetch_error"] = str(exc)[:500]
            return result

    _git("reset", "--hard", pre_update_sha)
    _git("clean", "-fd")
    result["code_restored"] = True
    return result


# ---------------------------------------------------------------------------
# Shallow-clone handling
# ---------------------------------------------------------------------------

def _unshallow_if_needed() -> None:
    """Grow the shallow clone once, so a later ``reset --hard pre_update_sha``
    has real history to fall back to. Prefer ``--unshallow``; if the remote
    rejects it (or history is not yet available), fall back to ``--depth=50``."""
    shallow_marker = EASEL_DIR / ".git" / "shallow"
    if not shallow_marker.exists():
        return
    try:
        _git("fetch", "--unshallow", "origin", check=True)
        return
    except Exception:
        try:
            _git("fetch", "--depth=50", "origin", check=True)
        except Exception as exc:
            logger.warning("Easel unshallow failed: %s", exc)


# ---------------------------------------------------------------------------
# Gateway process control (Easel Web + openclaw gateway)
# ---------------------------------------------------------------------------

def _pid_on_port(port: int) -> Optional[int]:
    """Find the PID listening on ``port`` (best-effort, psutil optional)."""
    try:
        import psutil  # type: ignore
    except Exception:
        return None
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and getattr(conn.laddr, "port", 0) == port and conn.status == psutil.CONN_LISTEN:
                return conn.pid
    except Exception:
        return None
    return None


def _kill_pid(pid: Optional[int], timeout_s: float = 8.0) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        import psutil  # type: ignore
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=timeout_s)
        except psutil.TimeoutExpired:
            p.kill()
            return True
        return True
    except Exception:
        # Fallback to raw os.kill for graceful stop.
        try:
            os.kill(pid, 15)
            return True
        except Exception:
            return False


def stop_easel_gateway() -> Dict[str, Any]:
    """Stop both the Easel Web process and the openclaw gateway if listening.

    自实现说明（review ⑱）：
    - easel_workbench 目前仅提供 Easel Web 的进程管理（start_easel / stop_easel /
      _easel_process），没有独立的 openclaw gateway 管理函数；gateway 的启停实际
      依赖 easel web 或 setup.* 拉起。
    - 且 easel_workbench 的接口是 async（依赖 _easel_process 全局句柄 + asyncio），
      本模块 apply_update / rollback_update 是同步流程（subprocess.run + _git），
      无法直接复用。
    - 因此这里保留按端口找 PID 的兜底实现；三层回滚逻辑不依赖 easel_workbench 的
      句柄。风险：会杀掉任何监听 EASEL_PORT/GATEWAY_PORT 的进程，包括用户手动启的
      实例——这是已知的 trade-off。未来若 easel_workbench 抽出 sync stop/start +
      gateway 管理，可以整体迁移过来。
    """
    result: Dict[str, Any] = {"easel_web": False, "gateway": False}
    web_pid = _pid_on_port(EASEL_PORT)
    if web_pid:
        result["easel_web"] = _kill_pid(web_pid)
        result["easel_web_pid"] = web_pid
    gw_pid = _pid_on_port(GATEWAY_PORT)
    if gw_pid:
        result["gateway"] = _kill_pid(gw_pid)
        result["gateway_pid"] = gw_pid
    return result


def start_easel_gateway() -> Dict[str, Any]:
    """Best-effort restart of ``easel web``.  The openclaw gateway is normally
    restarted by ``easel web`` (or ``setup.*``) itself; we do not try to
    spawn it here to avoid orphaned state.

    与 stop_easel_gateway 同理：本函数是同步的，无法直接调 easel_workbench 的
    async ``start_easel``。当前实现即"复用"了 easel_workbench 的意图（拉起
    ``easel web --port EASEL_PORT``，gateway 由 easel web 拉起），只是不复用其
    代码路径。未来若引入 sync start/stop 或统一由 easel_workbench 承担，可
    整体切换。
    """
    exe_dir = EASEL_DIR / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    exe = exe_dir / ("easel.exe" if sys.platform == "win32" else "easel")
    if not exe.exists():
        return {"started": False, "error": f"Easel 未安装: {exe}"}

    env_extra = {
        "EASEL_PORT": str(EASEL_PORT),
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    try:
        proc = safe_popen(
            [str(exe), "web", "--port", str(EASEL_PORT)],
            cwd=str(EASEL_DIR),
            env_extra=env_extra,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"started": True, "pid": proc.pid}
    except Exception as exc:
        return {"started": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# check_for_updates (read-only)
# ---------------------------------------------------------------------------

def check_for_updates() -> Dict[str, Any]:
    """Read-only remote comparison. Fetches one depth, does not mutate local.

    Never unshallows and never resets.
    """
    settings = get_update_settings()
    state = _read_json(_state_path())
    result: Dict[str, Any] = {"installed": False, "update_available": False, "error": None}

    if not (EASEL_DIR / ".git").exists():
        result["error"] = f"Easel 未安装或不是 git 仓库: {EASEL_DIR}"
    else:
        try:
            target = settings.get("agent_commit") or f"origin/{settings['branch']}"
            _git("fetch", "--depth", "1", "origin", settings["branch"],
                 timeout=_CHECK_TIMEOUT_S)
            local_revision = _revision("HEAD")
            # FETCH_HEAD always points at the head we just fetched.
            remote_revision = _revision("FETCH_HEAD")
            result = {
                "installed": True,
                "update_available": bool(local_revision and remote_revision and local_revision != remote_revision),
                "local_revision": local_revision,
                "remote_revision": remote_revision,
                "branch": settings["branch"],
                "target": target,
                "error": None,
            }
        except Exception as exc:
            result = {"installed": True, "update_available": False, "error": str(exc)}

    state.update(result)
    state["last_checked_at"] = _now()
    _write_json(_state_path(), state)
    return get_update_status()


# ---------------------------------------------------------------------------
# apply_update
# ---------------------------------------------------------------------------

def _run_setup_script(branch: str) -> None:
    """Invoke the repository's own installer (``setup.ps1`` / ``setup.sh``)."""
    if sys.platform == "win32":
        shell = _powershell()
        script = EASEL_DIR / "setup.ps1"
        if not shell or not script.exists():
            raise RuntimeError("找不到 PowerShell 或 Easel setup.ps1，无法执行完整更新。")
        cmd = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Force"]
    else:
        script = EASEL_DIR / "setup.sh"
        if not script.exists():
            raise RuntimeError("缺少 setup.sh，无法执行完整更新。")
        cmd = ["bash", str(script), "--force"]

    result = safe_run(
        cmd,
        cwd=str(EASEL_DIR),
        timeout=_SETUP_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout or "Easel setup 失败").strip()[-4000:]
        )


def apply_update() -> Dict[str, Any]:
    """Three-layer apply.  Any failure inside the ``try`` triggers rollback.

    Never called from this commit -- wired to a scheduler but the scheduler
    does not auto-apply until someone re-enables it in settings.
    """
    settings = get_update_settings()
    state = _read_json(_state_path())

    if state.get("updating"):
        return {"ok": False, "error": "上一次更新仍在进行中"}

    state.update({"updating": True, "last_error": None, "updating_since": _now()})
    _write_json(_state_path(), state)

    ts: Optional[str] = None
    try:
        # -----------------------------------------------------------------
        # Layer 3 (data) -- back up .env and user openclaw config first.
        # -----------------------------------------------------------------
        backup_dir = _backup_data_dir()
        ts = backup_dir.name
        state["backups_path"] = str(backup_dir)
        _write_json(_state_path(), state)

        # -----------------------------------------------------------------
        # Layer 2 (env) -- capture pip freeze + openclaw CLI version.
        # -----------------------------------------------------------------
        snapshot = _snapshot_env(backup_dir)
        state["env_snapshot"] = snapshot
        _write_json(_state_path(), state)

        # -----------------------------------------------------------------
        # Layer 1 (code) -- snapshot HEAD before we touch anything.
        # -----------------------------------------------------------------
        old_sha = _snapshot_code()
        state["pre_update_sha"] = old_sha
        _write_json(_state_path(), state)

        # -----------------------------------------------------------------
        # Grow the shallow clone so a later reset has real history to fall
        # back to. This is the ONLY point where we touch remote history.
        # -----------------------------------------------------------------
        _unshallow_if_needed()

        # -----------------------------------------------------------------
        # Stop Easel Web + openclaw gateway so no process holds the files.
        # -----------------------------------------------------------------
        stop_result = stop_easel_gateway()
        state["last_stop"] = stop_result
        _write_json(_state_path(), state)

        # -----------------------------------------------------------------
        # Reset to the requested branch/commit.
        # -----------------------------------------------------------------
        branch = settings["branch"]
        if settings.get("agent_commit"):
            target_ref = settings["agent_commit"]
        else:
            _git("fetch", "origin", branch)
            target_ref = f"origin/{branch}"
        _git("reset", "--hard", target_ref)
        _git("clean", "-fd")

        # -----------------------------------------------------------------
        # Re-run the installer so the venv / junctions / openclaw track the
        # reset tree. This is where most of the time is spent.
        # -----------------------------------------------------------------
        _run_setup_script(branch)

        # -----------------------------------------------------------------
        # Bring the gateway back up.
        # -----------------------------------------------------------------
        start_result = start_easel_gateway()
        state["last_start"] = start_result

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

    except Exception as exc:
        logger.warning("Easel apply_update failed, triggering rollback: %s", exc)
        try:
            rollback_result = rollback_update()
        except Exception as rb_exc:
            logger.warning("Easel rollback_update raised: %s", rb_exc)
            rollback_result = {"ok": False, "error": str(rb_exc)}
        state = _read_json(_state_path())
        state.update({
            "updating": False,
            "last_error": str(exc),
            "rollback_result": rollback_result,
        })
        _write_json(_state_path(), state)
        return {
            "ok": False,
            "error": str(exc),
            "rollback": rollback_result,
            "backups_path": state.get("backups_path"),
        }


# ---------------------------------------------------------------------------
# rollback_update
# ---------------------------------------------------------------------------

def rollback_update() -> Dict[str, Any]:
    """Three-layer rollback.  Every layer is guarded; failure is recorded, not raised."""
    state = _read_json(_state_path())
    result: Dict[str, Any] = {"ok": True}

    # Best-effort: stop the gateway so the reset has a quiet file system.
    try:
        result["stop"] = stop_easel_gateway()
    except Exception as exc:
        result["stop_error"] = str(exc)

    backups_path = state.get("backups_path")
    snapshot = state.get("env_snapshot") or {}
    pre_update_sha = state.get("pre_update_sha")

    # ------------------------------------------------------------------
    # Layer 3: data (files).
    # ------------------------------------------------------------------
    layer3: Dict[str, Any] = {"attempted": False}
    if backups_path:
        bdir = Path(backups_path)
        if bdir.is_dir():
            layer3["attempted"] = True
            layer3["path"] = str(bdir)
            try:
                layer3["result"] = _restore_data_dir(bdir)
            except Exception as exc:
                layer3["error"] = str(exc)[:1000]
                result["ok"] = False
    result["layer3"] = layer3

    # ------------------------------------------------------------------
    # Layer 2: env (pip freeze + npm openclaw version).
    # ------------------------------------------------------------------
    layer2: Dict[str, Any] = {"attempted": False}
    if snapshot:
        layer2["attempted"] = True
        try:
            layer2["result"] = _restore_env(snapshot)
        except Exception as exc:
            layer2["error"] = str(exc)[:1000]
            result["ok"] = False
    result["layer2"] = layer2

    # ------------------------------------------------------------------
    # Layer 1: code (git reset to pre_update_sha).
    # ------------------------------------------------------------------
    layer1: Dict[str, Any] = {"attempted": False}
    if pre_update_sha:
        layer1["attempted"] = True
        try:
            layer1["result"] = _restore_code(pre_update_sha)
        except Exception as exc:
            layer1["error"] = str(exc)[:1000]
            result["ok"] = False
    result["layer1"] = layer1

    # ------------------------------------------------------------------
    # Restart gateway.
    # ------------------------------------------------------------------
    try:
        result["start"] = start_easel_gateway()
    except Exception as exc:
        result["start_error"] = str(exc)

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


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class EaselUpdateScheduler:
    """Mirror of HermesUpdateScheduler: check every 900s, apply on interval."""

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
            try:
                settings = get_update_settings()
                if settings["enabled"]:
                    status = get_update_status()
                    last = status.get("last_checked_at")
                    due = True
                    if last:
                        try:
                            due = datetime.now(timezone.utc) >= datetime.fromisoformat(last) + timedelta(
                                hours=settings["interval_hours"]
                            )
                        except ValueError:
                            pass
                    if due:
                        try:
                            checked = await asyncio.to_thread(check_for_updates)
                            if checked.get("update_available"):
                                # Auto-apply is intentionally gated behind
                                # settings["enabled"] and only runs if the
                                # user has also set auto_apply=True.
                                if settings.get("auto_apply"):
                                    await asyncio.to_thread(apply_update)
                        except Exception as exc:
                            logger.warning("Scheduled Easel update failed: %s", exc)
            except Exception as exc:
                logger.warning("EaselUpdateScheduler loop error: %s", exc)
            await asyncio.sleep(900)


_scheduler = EaselUpdateScheduler()


async def start_easel_update_scheduler() -> None:
    await _scheduler.start()


async def stop_easel_update_scheduler() -> None:
    await _scheduler.stop()
