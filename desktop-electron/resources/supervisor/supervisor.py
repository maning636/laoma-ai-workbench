#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Supervisor for packaged backend services.

Production mode prefers packaged service executables under resources/services.
Python script fallback is kept only for local/dev usage.
"""

from __future__ import annotations

import io
import glob
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

LOG_MAX_BYTES = 50 * 1024 * 1024
LOG_BACKUP_COUNT = 3

_SUPERVISOR_DIR = Path(__file__).resolve().parent
if str(_SUPERVISOR_DIR) not in sys.path:
    sys.path.insert(0, str(_SUPERVISOR_DIR))

# 日志目录：使用 supervisor.py 所在目录下的 logs/，而不是相对 cwd。
# 之前用相对路径 Path("logs") 会导致 PyInstaller 打包后 cwd 变化，日志写不进预期目录。
_SUPERVISOR_LOGS_DIR = Path(os.environ.get("LAOMA_SUPERVISOR_LOGS_DIR") or "").expanduser() \
    if os.environ.get("LAOMA_SUPERVISOR_LOGS_DIR") else _SUPERVISOR_DIR / "logs"
_SUPERVISOR_LOGS_DIR.mkdir(parents=True, exist_ok=True)
_LOGS_DIR = _SUPERVISOR_LOGS_DIR
_LOG_FORMATTER = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_LOG_FORMATTER)

_file_handler = RotatingFileHandler(
    _LOGS_DIR / "supervisor.log",
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
    errors="replace",
)
_file_handler.setFormatter(_LOG_FORMATTER)

logger = logging.getLogger("supervisor")
logger.setLevel(logging.INFO)
logger.handlers = [_stream_handler, _file_handler]
logger.propagate = False


PLATFORM_BROWSER_DEFAULTS: Dict[str, str] = {
    "douyin": "chromium",
    "kuaishou": "chromium",
    "xiaohongshu": "chromium",
    "channels": "chromium",
    "bilibili": "chromium",
}

# 大陆平台默认强制直连（不走本机 VPN/全局代理）。与前端 platformProxyPreferences 的 direct 一致。
PLATFORM_PROXY_DEFAULTS: Dict[str, str] = {
    "douyin": "direct",
    "kuaishou": "direct",
    "xiaohongshu": "direct",
    "channels": "direct",
    "bilibili": "direct",
}

# =============================================================================
# B7: SERVICE_REGISTRY —— 打包服务元数据集中描述
# ----------------------------------------------------------------------------
# 覆盖 supervisor 管理的所有服务(backend / automation-worker / celery-worker /
# hermes-dashboard / hermes-webui / hermes-gateway / redis)。
#
# 字段说明：
#   exe_paths        打包可执行相对路径(顺序即优先级);相对 self.services_dir 解析。
#                    redis/hermes-* 为脚本或独立 exe,不列入 service_executables。
#   host             HTTP/探针默认 host(None 表示无 HTTP 探针)。
#   port_default     默认监听端口(None=不监听 TCP)。
#   env_port_keys    端口环境变量候选(顺序即优先级)。
#   log_file         服务日志文件名。
#   start_order      启动顺序(数值升序)。
#   stop_order       停止顺序(数值升序)。
#   health_paths     就绪探针路径(元组);空元组=仅 TCP 连接,非 HTTP 服务走 _probe_redis。
#   status_extras    get_service_status 需要附加的命名 URL 字段(如 dashboard_url/webui_url)。
#   restart_policy   崩溃重启策略 {max_restarts, backoff, stable_after}。
#
# 说明:
#   - backend 默认监听 7000,与 prism_backend/fastapi_app/run.py 保持一致。
#   - redis 走 prism_backend/Redis/redis-server.exe,由 start_redis 独立处理,
#     registry 仅用于诊断/停止顺序/端口登记。
# =============================================================================
SERVICE_REGISTRY: Dict[str, Dict[str, object]] = {
    "redis": {
        "exe_paths": (),
        "host": "127.0.0.1",
        "port_default": 6379,
        "env_port_keys": (),
        "log_file": "redis.log",
        "start_order": 0,
        "stop_order": 9,
        "health_paths": (),
        "restart_policy": {"max_restarts": 0, "backoff": 5.0, "stable_after": 120.0},
        "status_extras": (),
    },
    "automation-worker": {
        "exe_paths": ("automation-worker/automation-worker.exe", "automation-worker.exe"),
        "host": "127.0.0.1",
        "port_default": 7001,
        "env_port_keys": ("AUTOMATION_WORKER_PORT", "LAOMA_AUTOMATION_WORKER_PORT"),
        "log_file": "automation-worker.log",
        "start_order": 1,
        "stop_order": 5,
        "health_paths": ("/health",),
        "restart_policy": {"max_restarts": 3, "backoff": 3.0, "stable_after": 60.0},
        "status_extras": (),
    },
    "backend": {
        "exe_paths": ("backend/backend.exe", "backend.exe"),
        "host": "127.0.0.1",
        "port_default": 7000,
        "env_port_keys": ("BACKEND_PORT", "LAOMA_BACKEND_PORT"),
        "log_file": "backend.log",
        "start_order": 2,
        "stop_order": 4,
        "health_paths": ("/health",),
        "restart_policy": {"max_restarts": 3, "backoff": 3.0, "stable_after": 60.0},
        "status_extras": (),
    },
    "celery-worker": {
        "exe_paths": ("celery-worker/celery-worker.exe", "celery-worker.exe"),
        "host": None,
        "port_default": None,
        "env_port_keys": (),
        "log_file": "celery-worker.log",
        "start_order": 3,
        "stop_order": 3,
        "health_paths": (),
        "restart_policy": {"max_restarts": 2, "backoff": 5.0, "stable_after": 90.0},
        "status_extras": (),
    },
    "hermes-dashboard": {
        "exe_paths": (),
        "host": "127.0.0.1",
        "port_default": 9119,
        "env_port_keys": ("LAOMA_HERMES_DASHBOARD_PORT",),
        "log_file": "hermes-dashboard.log",
        "start_order": 4,
        "stop_order": 2,
        "health_paths": ("/",),
        "restart_policy": {"max_restarts": 2, "backoff": 5.0, "stable_after": 90.0},
        "status_extras": ("dashboard_url",),
    },
    "hermes-webui": {
        "exe_paths": (),
        "host": "127.0.0.1",
        "port_default": 9131,
        "env_port_keys": ("LAOMA_HERMES_WEBUI_PORT",),
        "log_file": "hermes-webui.log",
        "start_order": 5,
        "stop_order": 1,
        "health_paths": ("/?prism_shell_health=1", "/static/boot.js?prism_shell_health=1"),
        "restart_policy": {"max_restarts": 2, "backoff": 5.0, "stable_after": 90.0},
        "status_extras": ("webui_url",),
    },
    "hermes-gateway": {
        "exe_paths": (),
        "host": None,
        "port_default": None,
        "env_port_keys": (),
        "log_file": "hermes-gateway.log",
        "start_order": 6,
        "stop_order": 0,
        "health_paths": (),
        "restart_policy": {"max_restarts": 1, "backoff": 8.0, "stable_after": 120.0},
        "status_extras": (),
    },
}

# =============================================================================
# 注册码能力门禁 —— 限制功能版不启动 Hermes sidecar
# =============================================================================
# 客户端合并成单一安装器后,同一个安装包要同时服务「完整版」和「限制功能版」。
# Hermes 三个进程(dashboard / webui / gateway)属于 **agent 能力**(Pro 档
# `agent_quota=2`,Community 档 `agent_quota=0`),限制功能版用户用不了它们 ——
# 白白占着内存与端口(9119 / 9131),体验上还会看到一堆用不了的入口。
#
# 判据:**本地注册码**是否带 `agent` 授权条目。
#   - 只看本地注册码、不看云端订阅:Hermes 是**本地**运行时,不需要联网;
#     云端不可达时也不该把付费用户降级(云端那一轨管的是 AI 额度,不是本地 agent)。
#   - 必须验签(Ed25519 公钥来自 prism_backend 的 license_keys.py):
#     否则用户改一下 license.json 就能白嫖 agent 能力。
#   - 逃生门:env `LAOMA_HERMES_SKIP_ENTITLEMENT_GATE=1` 可整体关闭门禁
#     (开发态由 Electron 主进程在 dev 分支自动设置,免得本地调试没码也起不了 Hermes)。
# =============================================================================

#: 受门禁管控的服务(全部是 Hermes sidecar)
HERMES_SERVICES = ("hermes-dashboard", "hermes-webui", "hermes-gateway")

#: 授权条目名:与 prism_backend/fastapi_app/core/license_keys.py 的 ENTITLEMENTS 一致
AGENT_ENTITLEMENT = "agent"

#: 注册码 token 前缀(与 core/license.py 的 TOKEN_PREFIX 一致)
LICENSE_TOKEN_PREFIX = "PRISM1"

#: 门禁总开关的逃生 env
HERMES_GATE_SKIP_ENV = "LAOMA_HERMES_SKIP_ENTITLEMENT_GATE"


def _b64u_decode(value: str) -> bytes:
    """base64url 解码(容忍缺省 padding)。"""
    import base64

    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def load_license_public_key(backend_dir: Path) -> Optional[str]:
    """从 prism_backend 的 license_keys.py 读 Ed25519 公钥(hex)。

    用 importlib **按文件路径**加载,不走 `import fastapi_app...` ——
    `fastapi_app/core/__init__.py` 会连带 import config/logger/exceptions,
    supervisor 只是引导进程,不该被这些副作用拖住。

    读不到返回 None(调用方按「没有授权」处理)。
    """
    module_path = backend_dir / "fastapi_app" / "core" / "license_keys.py"
    if not module_path.is_file():
        return None
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("_prism_license_keys", module_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        value = getattr(module, "PUBLIC_KEY_HEX", None)
        return str(value) if value else None
    except Exception as exc:  # noqa: BLE001 - 引导进程不能因读公钥失败而崩
        logger.warning("Failed to load license public key: %s", exc)
        return None


def verify_license_token(token: str, public_key_hex: str) -> Optional[frozenset]:
    """验签注册码并返回授权条目集合;验签失败/格式错/异常 → None。

    签名对象是 payload 的 base64url 文本(与 core/license.py::verify_license 一致),
    这里只取 `ent` 字段,不看有效期 —— 有效期判定归后端,supervisor 只管「有没有 agent 能力」。
    """
    parts = (token or "").strip().split(".")
    if len(parts) != 3 or parts[0] != LICENSE_TOKEN_PREFIX:
        return None
    _, body_b64, sig_b64 = parts
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ed25519

        public_key = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(public_key_hex)
        )
        public_key.verify(_b64u_decode(sig_b64), body_b64.encode("ascii"))
        raw = json.loads(_b64u_decode(body_b64).decode("utf-8"))
    except (InvalidSignature, ValueError, TypeError, KeyError):
        return None
    except Exception as exc:  # noqa: BLE001 - cryptography 缺失等一律按「无授权」
        logger.warning("License signature verification failed: %s", exc)
        return None
    if not isinstance(raw, dict):
        return None
    entitlements = raw.get("ent") or []
    if not isinstance(entitlements, list):
        return None
    return frozenset(str(item) for item in entitlements)


class ProcessManager:
    def __init__(self) -> None:
        self.processes: Dict[str, subprocess.Popen] = {}
        self.process_loggers: Dict[str, logging.Logger] = {}
        self.process_log_handlers: Dict[str, RotatingFileHandler] = {}
        self.log_threads: Dict[str, threading.Thread] = {}
        self.should_stop = False

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame) -> None:  # noqa: ANN001
        logger.info("Received signal %s, shutting down...", signum)
        self.should_stop = True
        self.stop_all()
        sys.exit(0)

    def _setup_process_logger(self, name: str) -> logging.Logger:
        proc_logger = logging.getLogger(f"process.{name}")
        proc_logger.setLevel(logging.INFO)
        proc_logger.propagate = False

        old_handler = self.process_log_handlers.pop(name, None)
        if old_handler:
            try:
                proc_logger.removeHandler(old_handler)
            except Exception:
                pass
            old_handler.close()

        logs_dir = _LOGS_DIR
        logs_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            logs_dir / f"{name}.log",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
            errors="replace",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        proc_logger.handlers = [handler]
        self.process_log_handlers[name] = handler
        self.process_loggers[name] = proc_logger
        return proc_logger

    def _cleanup_process_logger(self, name: str) -> None:
        handler = self.process_log_handlers.pop(name, None)
        proc_logger = self.process_loggers.pop(name, None)
        if handler:
            if proc_logger:
                try:
                    proc_logger.removeHandler(handler)
                except Exception:
                    pass
            handler.close()

    def _start_log_thread(self, name: str, proc: subprocess.Popen) -> None:
        if name in self.log_threads or not proc.stdout:
            return

        proc_logger = self._setup_process_logger(name)

        def _reader() -> None:
            try:
                for line in proc.stdout:
                    if line:
                        proc_logger.info(line.rstrip("\r\n"))
            except Exception as exc:
                logger.error("[%s] log stream error: %s", name, exc)
            finally:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

        thread = threading.Thread(target=_reader, name=f"{name}-logger", daemon=True)
        self.log_threads[name] = thread
        thread.start()

    def start_process(self, name: str, cmd: List[str], cwd: str, env: Dict[str, str]) -> bool:
        try:
            logger.info("Starting %s...", name)
            logger.info("  Command: %s", " ".join(cmd))
            logger.info("  Working dir: %s", cwd)

            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            self.processes[name] = proc
            self._start_log_thread(name, proc)
            logger.info("%s started successfully (PID: %s)", name, proc.pid)
            return True
        except Exception as exc:
            logger.error("%s failed to start: %s", name, exc)
            return False

    def is_running(self, name: str) -> bool:
        proc = self.processes.get(name)
        return proc is not None and proc.poll() is None

    def get_exit_code(self, name: str) -> Optional[int]:
        proc = self.processes.get(name)
        if proc is None:
            return None
        code = proc.poll()
        return code

    def tail_process_log(self, name: str, lines: int = 25) -> str:
        """读取最近一次进程日志文件的末尾若干行（失败根因上报用）。"""
        logs_dir = Path("logs")
        log_file = logs_dir / f"{name}.log"
        if not log_file.exists():
            return ""
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
            tail = text.splitlines()[-lines:]
            return "\n".join(tail)
        except Exception:
            return ""

    def stop_process(self, name: str, timeout: int = 4) -> None:
        proc = self.processes.get(name)
        if not proc:
            return

        logger.info("Stopping %s...", name)
        try:
            if sys.platform == "win32":
                # 参考 dsh-desktop：SIGTERM 式优雅退出，超时后强杀。
                # Windows 上没有 POSIX 信号，先尝试 taskkill 不带 /F（请求优雅退出），
                # 超时后再 /F 强杀整个进程树。
                subprocess.run(
                    ["taskkill", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=max(timeout + 5, 8),
                )
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    proc.wait(timeout=5)
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        except Exception as exc:
            logger.warning("Stop %s raised: %s; forcing kill", name, exc)
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            thread = self.log_threads.pop(name, None)
            if thread:
                thread.join(timeout=2)
            self._cleanup_process_logger(name)
            self.processes.pop(name, None)

    def stop_all(self) -> None:
        logger.info("Stopping all managed services...")
        # B7: 停止顺序读 SERVICE_REGISTRY[svc]["stop_order"](数值升序),
        # 未登记在 registry 中的进程(极端情况)兜底关闭。
        stop_order = sorted(
            SERVICE_REGISTRY.keys(),
            key=lambda name: int(SERVICE_REGISTRY[name]["stop_order"]),
        )
        for name in stop_order:
            if name in self.processes:
                self.stop_process(name)
        for name in list(self.processes.keys()):
            self.stop_process(name)


class Supervisor:
    def __init__(self) -> None:
        self.manager = ProcessManager()
        # B7: service_ports 从 SERVICE_REGISTRY 派生。
        # 仅登记 registry 中带 port_default 且 health_paths 非空或服务名==redis 的条目:
        #   - backend / automation-worker / hermes-dashboard / hermes-webui:HTTP 动态端口 + 就绪探测
        #   - redis:非 HTTP 但需被 can_start_service / get_service_status 探测 6379 冲突与外部实例
        #   - celery-worker / hermes-gateway:port_default=None,无需登记
        dynamic_or_probed = (
            "backend", "automation-worker", "hermes-dashboard", "hermes-webui", "redis",
        )
        self.service_ports: Dict[str, int] = {}
        for _name in dynamic_or_probed:
            _meta = SERVICE_REGISTRY[_name]
            _default_port = _meta.get("port_default")
            if _default_port is None:
                continue
            self.service_ports[_name] = self._read_env_port(
                tuple(_meta["env_port_keys"]),
                int(_default_port),
            )
        self.preferred_service_ports = dict(self.service_ports)
        self.external_services: Dict[str, bool] = {}
        self.kill_port_conflict = os.environ.get("SUPERVISOR_KILL_PORT_CONFLICT", "1") != "0"

        # ── 启动令牌与状态文件（供 Electron 主进程发现 API 端口/服务端口/归属校验）──
        self.launch_token = uuid.uuid4().hex
        self.state_path = Path(
            os.environ.get("LAOMA_SUPERVISOR_STATE_PATH")
            or str(Path.home() / ".prism-supervisor" / "state.json")
        )
        self.started_at = time.time()

        # ── 失败诊断与重启策略 ──
        # B7: restart_policy 从 SERVICE_REGISTRY 聚合;monitor_loop 使用 self.restart_policy。
        # 仅保留 max_restarts > 0 的服务(redis=0 表示不参与自动重启,保持旧行为)。
        self.failures: Dict[str, Dict[str, object]] = {}
        self.restart_policy: Dict[str, Dict[str, float]] = {
            name: dict(meta["restart_policy"])  # type: ignore[arg-type]
            for name, meta in SERVICE_REGISTRY.items()
            if meta.get("restart_policy")
            and int(meta["restart_policy"].get("max_restarts", 0)) > 0  # type: ignore[union-attr]
        }
        self._login_env_cache: Optional[Dict[str, str]] = None

        env_resources_path = os.environ.get("LAOMA_RESOURCES_PATH") or os.environ.get("LAOMA_APP_ROOT")
        if env_resources_path:
            self.resources_path = Path(env_resources_path)
            self.is_packaged = True
        elif getattr(sys, "frozen", False):
            self.is_packaged = True
            current = Path(sys.executable).parent
            self.resources_path = current.parent if current.name == "supervisor" else current.parent.parent
        else:
            self.is_packaged = False
            self.resources_path = Path(__file__).parent.parent.parent.parent

        if not (self.resources_path / "prism_backend").exists():
            for candidate in (self.resources_path.parent, self.resources_path.parent.parent):
                if len(candidate.parts) > 1 and (candidate / "prism_backend").exists():
                    self.resources_path = candidate
                    break

        self.backend_dir = self.resources_path / "prism_backend"
        self.hermes_dir = self.resources_path / "tools" / "hermes-agent"
        self.hermes_home_dir = Path(
            os.environ.get("PRISM_HERMES_HOME")
            or str(self.resources_path / "tools" / "hermes-home")
        )
        self.prismenv_dir = self.resources_path / "prismenv"
        self.prismenv_site_packages = self._resolve_prismenv_site_packages()
        self.browsers_dir = self.resources_path / "browsers"
        self.services_dir = self.resources_path / "services"
        self.python_exe = self._resolve_prismenv_python()

        # 打包可执行路径：从 SERVICE_REGISTRY 读取 exe_paths(顺序即优先级),相对 services_dir。
        # 仅登记 exe_paths 非空的 exe 类服务;hermes-*/redis 走脚本或独立启动路径。
        self.service_executables = {
            name: tuple(self.services_dir / rel for rel in SERVICE_REGISTRY[name]["exe_paths"])
            for name in SERVICE_REGISTRY
            if SERVICE_REGISTRY[name].get("exe_paths")
        }

        logger.info("Environment: %s", "packaged" if self.is_packaged else "dev")
        logger.info("Resources path: %s", self.resources_path)
        logger.info("Backend dir: %s (exists: %s)", self.backend_dir, self.backend_dir.exists())
        logger.info("Services dir: %s (exists: %s)", self.services_dir, self.services_dir.exists())
        logger.info("Browsers dir: %s (exists: %s)", self.browsers_dir, self.browsers_dir.exists())
        logger.info("Shared Python runtime: %s", self.python_exe or "not available")
        if self.prismenv_site_packages:
            logger.info("Packaged site-packages: %s", self.prismenv_site_packages)

    @staticmethod
    def _read_env_port(keys: Tuple[str, ...], default: int) -> int:
        for key in keys:
            raw_value = str(os.environ.get(key) or "").strip()
            if not raw_value:
                continue
            try:
                parsed = int(raw_value)
            except ValueError:
                continue
            if parsed > 0:
                return parsed
        return default

    # ────────────────────────────────────────────────────────────────
    # 完整 shell 环境注入：子进程环境 = 登录环境 + 当前环境 + PRISM 覆盖
    # ────────────────────────────────────────────────────────────────
    def _collect_login_env(self) -> Dict[str, str]:
        """收集用户登录会话的完整环境（PATH 等），参考 dsh-desktop 的 $SHELL -l -i -c env。

        Windows：从注册表读取用户级 + 机器级环境变量；
        macOS/Linux：通过登录 shell（-l -i）导出完整环境。
        结果缓存；失败时回退为 os.environ。
        """
        if self._login_env_cache is not None:
            return self._login_env_cache

        collected: Dict[str, str] = {}
        if sys.platform == "win32":
            collected = self._collect_windows_registry_env()
        else:
            collected = self._collect_login_shell_env()

        if collected:
            # 当前进程 env 覆盖登录环境（Electron 显式设置的变量优先）
            merged = {**collected, **os.environ}
        else:
            merged = os.environ.copy()
        self._login_env_cache = merged
        logger.info("Login environment collected: %d variables", len(merged))
        return merged

    def _collect_windows_registry_env(self) -> Dict[str, str]:
        """从 Windows 注册表（HKCU/HKLM Environment）读取用户/机器环境变量。"""
        ps_script = (
            "$ErrorActionPreference = 'SilentlyContinue'; "
            "$out = @{}; "
            "foreach ($scope in @('User','Machine')) { "
            "  $vars = [Environment]::GetEnvironmentVariables($scope); "
            "  foreach ($key in $vars.Keys) { "
            "    if (-not $out.ContainsKey($key)) { $out[$key] = [string]$vars[$key] } "
            "  } "
            "}; "
            "if ($out.Count -gt 0) { $out | ConvertTo-Json -Compress }"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if result.returncode != 0:
                logger.warning("Registry env collection failed: %s", result.stderr[:200])
                return {}
            raw = str(result.stdout or "").strip()
            if not raw:
                return {}
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return {}
            return {str(k): str(v) for k, v in parsed.items() if v is not None}
        except Exception as exc:
            logger.warning("Failed to collect registry env: %s", exc)
            return {}

    def _collect_login_shell_env(self) -> Dict[str, str]:
        """macOS/Linux：$SHELL -l -i -c env 收集登录 shell 环境。"""
        shell = os.environ.get("SHELL") or "/bin/sh"
        command = f"{shell} -l -i -c env"
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            if result.returncode != 0:
                logger.warning("Login shell env collection failed: %s", result.stderr[:200])
                return {}
            env: Dict[str, str] = {}
            for line in str(result.stdout or "").splitlines():
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key and key not in env:
                    env[key] = value
            return env
        except Exception as exc:
            logger.warning("Failed to collect login shell env: %s", exc)
            return {}

    # ────────────────────────────────────────────────────────────────
    # 失败诊断 / 启动令牌 / 状态文件
    # ────────────────────────────────────────────────────────────────
    def _record_failure(
        self,
        name: str,
        stage: str,
        detail: str,
        exit_code: Optional[int] = None,
    ) -> None:
        entry = self.failures.setdefault(
            name, {"count": 0, "restart_count": 0, "last_error_at": None}
        )
        entry["count"] = int(entry.get("count") or 0) + 1
        entry["stage"] = stage
        entry["detail"] = detail[:500]
        entry["last_error_at"] = time.time()
        if exit_code is not None:
            entry["exit_code"] = exit_code
        logger.error("[%s] failure recorded: %s — %s", name, stage, detail[:200])

    def _tail_log(self, name: str, lines: int = 25) -> str:
        return self.manager.tail_process_log(name, lines)

    def _is_pid_listening(self, pid: Optional[int], port: int, host: str = "127.0.0.1") -> bool:
        """校验监听端口的进程确实是本 supervisor 拉起的子进程（防止连到陈旧实例）。"""
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            import psutil
        except Exception:
            return True  # psutil 不可用时退化为仅 HTTP 探测
        try:
            for conn in psutil.net_connections(kind="inet"):
                if (
                    conn.laddr
                    and conn.laddr.ip == host
                    and conn.laddr.port == port
                    and conn.pid == pid
                ):
                    return True
        except Exception:
            return True
        return False

    def _write_state_file(self, api_port: Optional[int] = None) -> None:
        """把 supervisor 的发现信息写入状态文件，Electron 主进程据此连接。"""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "pid": os.getpid(),
                "startedAt": self.started_at,
                "launchToken": self.launch_token,
                "apiPort": api_port,
                "servicePorts": {
                    name: port for name, port in self.service_ports.items()
                },
            }
            tmp_path = self.state_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(self.state_path)
        except Exception as exc:
            logger.warning("Failed to write supervisor state file: %s", exc)

    def get_diagnostics(self) -> Dict[str, object]:
        """失败根因上报：服务状态 + 失败记录 + 环境摘要 + 日志路径。"""
        services: Dict[str, object] = {}
        # B7: 遍历 SERVICE_REGISTRY 全部已登记服务。
        for name in sorted(SERVICE_REGISTRY.keys()):
            status = self.get_service_status(name)
            failure = self.failures.get(name)
            if failure:
                status["failure"] = failure
                status["log_tail"] = self._tail_log(name)
            services[name.replace("-", "_")] = status

        return {
            "supervisor": {
                "pid": os.getpid(),
                "apiPort": getattr(self, "api_port", None),
                "launchToken": self.launch_token,
                "startedAt": self.started_at,
                "isPackaged": self.is_packaged,
            },
            "services": services,
            "environment": {
                "resourcesPath": str(self.resources_path),
                "backendDir": str(self.backend_dir),
                "python": str(self.python_exe) if self.python_exe else None,
                "prismenvSitePackages": str(self.prismenv_site_packages) if self.prismenv_site_packages else None,
                "servicePorts": {k: v for k, v in self.service_ports.items()},
            },
            "logPaths": {
                "supervisor": str(Path("logs") / "supervisor.log"),
                "backend": str(Path("logs") / SERVICE_REGISTRY["backend"]["log_file"]),
            },
        }

    def _get_gateway_state_path(self) -> Path:
        return self.hermes_home_dir / "gateway_state.json"

    def _get_hermes_webui_state_path(self) -> Path:
        return self.hermes_home_dir / "webui"

    def _get_hermes_workspace_root(self) -> Path:
        return self.resources_path

    def _is_pid_alive(self, pid: Optional[int]) -> bool:
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

    def _read_gateway_state(self) -> Dict[str, object]:
        gateway_state_path = self._get_gateway_state_path()
        if not gateway_state_path.exists():
            return {}
        try:
            payload = json.loads(gateway_state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            logger.warning("Failed to read Hermes gateway state: %s", exc)
            return {}

    def _get_gateway_platform_status(self) -> Dict[str, object]:
        if not self.hermes_dir.exists():
            return {
                "configured": False,
                "platforms": [],
                "reason": "Hermes runtime is not installed.",
            }

        try:
            if self.python_exe and Path(self.python_exe).exists():
                env = os.environ.copy()
                env["HERMES_HOME"] = str(self.hermes_home_dir)
                env["HERMES_CONFIG_PATH"] = str(self.hermes_home_dir / "config.yaml")
                env["PRISM_HERMES_HOME"] = str(self.hermes_home_dir)
                result = subprocess.run(
                    [
                        str(self.python_exe),
                        "-c",
                        (
                            "import json, sys; "
                            "sys.path.insert(0, sys.argv[1]); "
                            "from gateway.config import Platform, load_gateway_config; "
                            "config = load_gateway_config(); "
                            "platforms = sorted("
                            "platform.value "
                            "for platform, platform_config in (config.platforms or {}).items() "
                            "if getattr(platform_config, 'enabled', False) and platform != Platform.LOCAL"
                            "); "
                            "print(json.dumps({'platforms': platforms}, ensure_ascii=False))"
                        ),
                        str(self.hermes_dir),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(self.hermes_dir),
                    env=env,
                    check=True,
                )
                payload = json.loads((result.stdout or "").strip() or "{}")
                platforms = payload.get("platforms", [])
                if not isinstance(platforms, list):
                    raise ValueError("Invalid Hermes gateway platform payload")
            else:
                hermes_dir_str = str(self.hermes_dir)
                added_sys_path = False
                if hermes_dir_str not in sys.path:
                    sys.path.insert(0, hermes_dir_str)
                    added_sys_path = True
                try:
                    from gateway.config import Platform, load_gateway_config

                    config = load_gateway_config()
                    platforms = sorted(
                        platform.value
                        for platform, platform_config in (config.platforms or {}).items()
                        if getattr(platform_config, "enabled", False) and platform != Platform.LOCAL
                    )
                finally:
                    if added_sys_path:
                        try:
                            sys.path.remove(hermes_dir_str)
                        except ValueError:
                            pass
        except Exception as exc:
            logger.warning("Failed to inspect Hermes gateway configuration: %s", exc)
            return {
                "configured": False,
                "platforms": [],
                "reason": f"Failed to inspect Hermes gateway configuration: {exc}",
            }

        if platforms:
            return {
                "configured": True,
                "platforms": platforms,
                "reason": "",
            }

        return {
            "configured": False,
            "platforms": [],
            "reason": "No messaging platforms are configured for Hermes gateway.",
        }

    def _find_git_bash(self) -> Optional[str]:
        candidates = (
            self.resources_path / "tools" / "git" / "bin" / "bash.exe",
            self.resources_path / "tools" / "git" / "usr" / "bin" / "bash.exe",
            Path(os.getenv("ProgramFiles", "")) / "Git" / "bin" / "bash.exe",
            Path(os.getenv("ProgramFiles", "")) / "Git" / "usr" / "bin" / "bash.exe",
            Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Git" / "bin" / "bash.exe",
        )
        for candidate in candidates:
            if candidate and candidate.exists():
                return str(candidate)
        return None

    def _find_browser_executable(self, patterns: Iterable[str]) -> Optional[Path]:
        for pattern in patterns:
            matches = sorted(glob.glob(str(self.browsers_dir / pattern)))
            if matches:
                return Path(matches[-1])
        return None

    def _resolve_prismenv_python(self) -> Optional[Path]:
        candidates = (
            self.prismenv_dir / "Scripts" / "python.exe",
            self.prismenv_dir / "bin" / "python",
        )
        for candidate in candidates:
            if candidate.exists() and self._python_is_usable(candidate):
                return candidate
            if candidate.exists():
                logger.warning("Packaged Python exists but is not usable: %s", candidate)
        system_python = self._resolve_system_python()
        if system_python:
            logger.warning("Falling back to system Python for Hermes scripts: %s", system_python)
            return system_python
        return None

    def _resolve_system_python(self) -> Optional[Path]:
        for command in ("python", "python3"):
            try:
                result = subprocess.run(
                    [command, "-c", "import sys; print(sys.executable)"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    check=False,
                )
            except Exception:
                continue
            if result.returncode == 0:
                executable = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else command
                path = Path(executable)
                return path if path.exists() else Path(command)
        return None

    def _python_is_usable(self, python_path: Path) -> bool:
        try:
            result = subprocess.run(
                [str(python_path), "-c", "import sys; print(sys.version)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _resolve_prismenv_site_packages(self) -> Optional[Path]:
        candidates = (
            self.prismenv_dir / "Lib" / "site-packages",
            self.prismenv_dir / "lib" / "site-packages",
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _build_pythonpath(
        self,
        *preferred: object,
        base: Optional[str] = None,
        exclude: Optional[Iterable[object]] = None,
    ) -> str:
        entries: List[str] = []
        seen: set[str] = set()
        excluded: set[str] = set()

        for raw in exclude or ():
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                excluded.add(os.path.normcase(os.path.normpath(text)))

        def add(raw: object) -> None:
            if raw is None:
                return
            text = str(raw).strip()
            if not text:
                return
            normalized = os.path.normcase(os.path.normpath(text))
            if any(normalized == root or normalized.startswith(root + os.sep) for root in excluded):
                return
            if normalized in seen:
                return
            seen.add(normalized)
            entries.append(text)

        for item in preferred:
            add(item)

        for raw_entry in str(base or "").split(os.pathsep):
            add(raw_entry)

        return os.pathsep.join(entries)

    def _can_bind_port(self, port: int, host: str = "127.0.0.1") -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
            return True
        except OSError:
            return False
        except Exception:
            return False

    def _find_available_port(
        self,
        preferred_port: int,
        *,
        host: str = "127.0.0.1",
        max_attempts: int = 32,
        reserved_ports: Optional[set[int]] = None,
    ) -> int:
        candidate = max(int(preferred_port), 1)
        for _ in range(max_attempts):
            if reserved_ports and candidate in reserved_ports:
                candidate += 1
                continue
            if self._can_bind_port(candidate, host=host):
                return candidate
            candidate += 1
        raise RuntimeError(f"No available port found starting from {preferred_port}")

    def _resolve_dynamic_service_port(self, name: str, reserved_ports: Optional[set[int]] = None) -> int:
        preferred_port = self.preferred_service_ports.get(name, self.service_ports.get(name))
        if preferred_port is None:
            raise KeyError(f"Unknown service port mapping: {name}")
        current_port = self.service_ports.get(name, preferred_port)
        if (not reserved_ports or current_port not in reserved_ports) and self._can_bind_port(current_port):
            return current_port

        resolved_port = self._find_available_port(preferred_port, reserved_ports=reserved_ports)
        if resolved_port != current_port:
            logger.warning(
                "Port %s for %s is unavailable; reassigned to %s",
                current_port,
                name,
                resolved_port,
            )
        self.service_ports[name] = resolved_port
        return resolved_port

    def _refresh_dynamic_service_ports(self) -> None:
        # B7: 动态端口仅针对 registry 中带 port_default 且监听 HTTP 的服务(redis 由 start_redis 独立处理)。
        http_services = [
            name
            for name, meta in SERVICE_REGISTRY.items()
            if meta.get("port_default") is not None and name != "redis"
        ]
        reserved_ports: set[int] = set()
        for service_name in http_services:
            reserved_ports.add(self._resolve_dynamic_service_port(service_name, reserved_ports))

    def _get_reserved_dynamic_ports(self, current_name: str) -> set[int]:
        # B7: 冲突候选从 SERVICE_REGISTRY 派生(排除 redis)。
        reserved_ports: set[int] = set()
        for service_name, meta in SERVICE_REGISTRY.items():
            if service_name == current_name or service_name == "redis":
                continue
            if meta.get("port_default") is None:
                continue
            port = self.service_ports.get(service_name)
            if isinstance(port, int) and port > 0:
                reserved_ports.add(port)
        return reserved_ports

    def _build_hermes_cli_launch(self, *cli_args: str) -> List[str]:
        if not self.python_exe:
            raise FileNotFoundError("No shared python runtime available for Hermes CLI")
        source_path = str(self.hermes_dir)
        bootstrap = (
            "import runpy, sys; "
            f"sys.path.insert(0, {source_path!r}); "
            "runpy.run_module('hermes_cli.main', run_name='__main__')"
        )
        return [str(self.python_exe), "-c", bootstrap, *cli_args]

    def _build_run_path_launch(self, script_path: Path, *sys_paths: Path) -> List[str]:
        if not self.python_exe:
            raise FileNotFoundError("No shared python runtime available for scripted launch")
        inserts = "".join(
            f"sys.path.insert(0, {str(path)!r}); " for path in sys_paths if path
        )
        bootstrap = (
            "import runpy, sys; "
            f"{inserts}"
            f"runpy.run_path({str(script_path)!r}, run_name='__main__')"
        )
        return [str(self.python_exe), "-c", bootstrap]

    def _load_runtime_settings(self) -> Dict[str, object]:
        settings_path_raw = os.environ.get("PRISM_RUNTIME_SETTINGS_PATH")
        if not settings_path_raw:
            return {}

        settings_path = Path(settings_path_raw)
        if not settings_path.exists():
            return {}

        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception as exc:
            logger.warning("Failed to load runtime settings from %s: %s", settings_path, exc)
        return {}

    def _normalize_platform_browser_choice(self, value: object, fallback: str = "chromium") -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"auto", "chromium", "firefox"}:
            return normalized
        return fallback

    def _normalize_platform_browser_preferences(self, raw: object) -> Dict[str, str]:
        normalized = dict(PLATFORM_BROWSER_DEFAULTS)
        if not isinstance(raw, dict):
            return normalized

        for platform, default_choice in PLATFORM_BROWSER_DEFAULTS.items():
            direct_value = raw.get(platform)
            alias_value = raw.get("tencent") if platform == "channels" else None
            candidate = direct_value if direct_value is not None else alias_value
            normalized[platform] = self._normalize_platform_browser_choice(candidate, default_choice)

        return normalized

    def _normalize_platform_proxy_preferences(self, raw: object) -> Dict[str, str]:
        normalized = dict(PLATFORM_PROXY_DEFAULTS)
        if not isinstance(raw, dict):
            return normalized

        for platform, default_mode in PLATFORM_PROXY_DEFAULTS.items():
            direct_value = raw.get(platform)
            alias_value = raw.get("tencent") if platform == "channels" else None
            candidate = direct_value if direct_value is not None else alias_value
            normalized[platform] = self._normalize_platform_proxy_choice(candidate, default_mode)

        return normalized

    def _normalize_platform_proxy_choice(self, value: object, fallback: str = "direct") -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"direct", "inherit"}:
            return normalized
        return fallback

    def build_direct_connect_platforms(self, raw: object) -> List[str]:
        preferences = self._normalize_platform_proxy_preferences(raw)
        direct = []
        for platform, mode in preferences.items():
            if mode == "direct":
                direct.append("tencent" if platform == "channels" else platform)
        return direct

    def build_env(self) -> Dict[str, str]:
        # 完整环境：登录会话环境 + 当前进程环境（PRISM_* 显式覆盖）
        env = self._collect_login_env()
        runtime_settings = self._load_runtime_settings()
        browser_headless = runtime_settings.get("browserHeadless")
        automation_runtime = runtime_settings.get("automationRuntime")
        platform_browser_preferences = self._normalize_platform_browser_preferences(
            runtime_settings.get("platformBrowserPreferences")
        )
        settings_path_raw = os.environ.get("PRISM_RUNTIME_SETTINGS_PATH")

        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = self._build_pythonpath(
            self.backend_dir,
            self.prismenv_site_packages,
            base=env.get("PYTHONPATH"),
        )
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(self.browsers_dir)
        env["PLAYWRIGHT_AUTO_INSTALL"] = "0"
        env["PLAYWRIGHT_HEADLESS"] = (
            "true" if isinstance(browser_headless, bool) and browser_headless else
            "false" if isinstance(browser_headless, bool) else
            os.getenv("PLAYWRIGHT_HEADLESS", "true")
        )
        env["LAOMA_AUTOMATION_RUNTIME"] = "patchright"
        if settings_path_raw:
            env["PRISM_RUNTIME_SETTINGS_PATH"] = settings_path_raw
        env["PRISM_PLATFORM_BROWSER_PREFERENCES"] = json.dumps(platform_browser_preferences)
        for platform, choice in platform_browser_preferences.items():
            env[f"PRISM_PLATFORM_BROWSER_{platform.upper()}"] = choice
        env["PRISM_PLATFORM_BROWSER_TENCENT"] = platform_browser_preferences.get("channels", "chromium")
        env["LAOMA_DIRECT_PLATFORMS"] = ",".join(
            self.build_direct_connect_platforms(runtime_settings.get("platformProxyPreferences"))
        )
        env["BACKEND_PORT"] = str(self.service_ports["backend"])
        env["LAOMA_BACKEND_PORT"] = str(self.service_ports["backend"])
        env["AUTOMATION_WORKER_PORT"] = str(self.service_ports["automation-worker"])
        env["ENABLE_OCR_RESCUE"] = "1"
        env["ENABLE_SELENIUM_RESCUE"] = "1"
        env["ENABLE_SELENIUM_DEBUG"] = "1"
        env["FORKED_BY_MULTIPROCESSING"] = "1"
        env["HERMES_HOME"] = str(self.hermes_home_dir)
        env["HERMES_CONFIG_PATH"] = str(self.hermes_home_dir / "config.yaml")
        env["PRISM_HERMES_HOME"] = str(self.hermes_home_dir)
        env["LAOMA_SUPERVISOR_MANAGES_HERMES_UI"] = "1"
        env["LAOMA_HERMES_DASHBOARD_PORT"] = str(self.service_ports["hermes-dashboard"])
        env["LAOMA_HERMES_WEBUI_PORT"] = str(self.service_ports["hermes-webui"])
        # 启动令牌：子进程携带，供归属校验与未来 readiness 校验使用
        env["PRISM_LAUNCH_TOKEN"] = self.launch_token
        if self.python_exe:
            env["PRISM_HERMES_PYTHON"] = str(self.python_exe)

        git_bash = self._find_git_bash()
        if git_bash:
            env["HERMES_GIT_BASH_PATH"] = git_bash

        chrome_path = self._find_browser_executable(
            (
                "chromium/hibbiki-*/Chrome-bin/chrome.exe",
                "chromium/chromium-*/chrome-win64/chrome.exe",
                "chromium/chromium-*/chrome-win/chrome.exe",
                "chromium-*/chrome-win64/chrome.exe",
                "chromium-*/chrome-win/chrome.exe",
                "chrome-for-testing/chrome-*/chrome-win64/chrome.exe",
            )
        )
        if chrome_path:
            env["LOCAL_CHROME_PATH"] = str(chrome_path)

        headless_shell_path = self._find_browser_executable(
            ("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe",)
        )
        if headless_shell_path:
            env["LOCAL_CHROME_HEADLESS_SHELL_PATH"] = str(headless_shell_path)

        firefox_path = self._find_browser_executable(
            (
                "firefox-*/firefox/firefox.exe",
                "firefox/firefox-*/firefox/firefox.exe",
            )
        )
        if firefox_path and firefox_path.exists():
            env["LOCAL_FIREFOX_PATH"] = str(firefox_path)

        logger.info(
            "Runtime settings applied: PLAYWRIGHT_HEADLESS=%s LAOMA_AUTOMATION_RUNTIME=%s "
            "PRISM_PLATFORM_BROWSER_PREFERENCES=%s LAOMA_DIRECT_PLATFORMS=%s",
            env["PLAYWRIGHT_HEADLESS"],
            env["LAOMA_AUTOMATION_RUNTIME"],
            env.get("PRISM_PLATFORM_BROWSER_PREFERENCES", ""),
            env.get("LAOMA_DIRECT_PLATFORMS", ""),
        )

        return env

    def get_service_executable(self, name: str) -> Optional[Path]:
        candidates = self.service_executables.get(name) or ()
        for exe in candidates:
            if exe.exists():
                return exe
        return None

    def get_service_launch(self, name: str) -> Tuple[List[str], str]:
        service_exe = self.get_service_executable(name)
        if service_exe:
            return [str(service_exe)], str(self.backend_dir)

        if not self.python_exe:
            raise FileNotFoundError(f"No packaged executable or python runtime available for service: {name}")

        if name == "backend":
            script = self.backend_dir / "fastapi_app" / "run.py"
            if not script.exists():
                raise FileNotFoundError(f"Backend script not found: {script}")
            return [str(self.python_exe), str(script)], str(self.backend_dir)

        if name == "automation-worker":
            script = self.backend_dir / "automation_worker" / "worker.py"
            if not script.exists():
                raise FileNotFoundError(f"Worker script not found: {script}")
            return [str(self.python_exe), str(script)], str(self.backend_dir)

        if name == "celery-worker":
            return [
                str(self.python_exe),
                "-m",
                "celery",
                "-A",
                "fastapi_app.tasks.celery_app.celery_app",
                "worker",
                "--loglevel=info",
                "--pool=threads",
                "--concurrency=1000",
                "--hostname=prism-worker@supervisor",
            ], str(self.backend_dir)

        if name == "hermes-gateway":
            script = self.hermes_dir / "hermes_cli" / "main.py"
            if not script.exists():
                raise FileNotFoundError(f"Hermes gateway entry script not found: {script}")
            if not self.python_exe:
                raise FileNotFoundError("No Hermes python runtime available for hermes-gateway")
            return self._build_hermes_cli_launch(
                "gateway",
                "run",
                "--replace",
                "--accept-hooks",
            ), str(self.resources_path)

        if name == "hermes-dashboard":
            dashboard_port = str(self.service_ports["hermes-dashboard"])
            dashboard_dist = self.hermes_dir / "hermes_cli" / "web_dist" / "index.html"
            if not dashboard_dist.exists():
                raise FileNotFoundError(f"Hermes dashboard dist not found: {dashboard_dist}")
            if not self.python_exe:
                raise FileNotFoundError("No Hermes python runtime available for hermes-dashboard")
            return self._build_hermes_cli_launch(
                "dashboard",
                "--host",
                "127.0.0.1",
                "--port",
                dashboard_port,
                "--no-open",
                "--skip-build",
            ), str(self.hermes_dir)

        if name == "hermes-webui":
            script = self.resources_path / "tools" / "hermes-webui" / "server.py"
            index_html = self.resources_path / "tools" / "hermes-webui" / "static" / "index.html"
            if not script.exists() or not index_html.exists():
                raise FileNotFoundError(f"Hermes WebUI is not installed under: {script.parent}")
            if not self.python_exe:
                raise FileNotFoundError("No Hermes python runtime available for hermes-webui")
            return self._build_run_path_launch(
                script,
                script.parent,
                self.hermes_dir,
            ), str(script.parent)

        raise ValueError(f"Unsupported service: {name}")

    def get_service_env(self, name: str, base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        env = dict(base_env or self.build_env())
        if name in {"hermes-gateway", "hermes-dashboard", "hermes-webui"}:
            env["PYTHONPATH"] = self._build_pythonpath(
                self.hermes_dir,
                self.prismenv_site_packages,
                base=env.get("PYTHONPATH"),
                exclude=(self.backend_dir,),
            )
            env["HERMES_WEBUI_AGENT_DIR"] = str(self.hermes_dir)
            if self.python_exe:
                env["HERMES_WEBUI_PYTHON"] = str(self.python_exe)

        if name == "hermes-dashboard":
            env["HERMES_WEB_DIST"] = str(self.hermes_dir / "hermes_cli" / "web_dist")
        elif name == "hermes-webui":
            self._get_hermes_webui_state_path().mkdir(parents=True, exist_ok=True)
            self._get_hermes_workspace_root().mkdir(parents=True, exist_ok=True)
            env["HERMES_WEBUI_HOST"] = "127.0.0.1"
            env["HERMES_WEBUI_PORT"] = str(self.service_ports["hermes-webui"])
            env["HERMES_WEBUI_STATE_DIR"] = str(self._get_hermes_webui_state_path())
            env["HERMES_WEBUI_DEFAULT_WORKSPACE"] = str(self._get_hermes_workspace_root())
            env.setdefault("HERMES_SKIP_CHMOD", "1")
        return env

    def _http_ok(self, url: str, timeout: float = 2.0) -> bool:
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return 200 <= getattr(response, "status", 0) < 500
        except Exception:
            return False

    def _is_service_ready(self, name: str) -> bool:
        """通用就绪探针(B7 统一):按 SERVICE_REGISTRY[name] 派生。

        - 未在 registry 中:退化返回 False(防御,理论上不会走到这里)。
        - 未运行:False。
        - port_default 为 None(celery-worker / hermes-gateway):无 TCP 探测,直接返回 True。
        - health_paths 为空(redis):仅 TCP connect(端口在听且归属本进程)。
        - health_paths 非空(HTTP 服务):TCP + pid 校验 + 全部 HTTP path 通过。
        """
        if not self.manager.is_running(name):
            return False
        meta = SERVICE_REGISTRY.get(name)
        if meta is None:
            return False
        port_default = meta.get("port_default")
        if port_default is None:
            # 无监听端口的服务(celery-worker/hermes-gateway)视为就绪。
            return True

        port = self.service_ports.get(name)
        if port is None:
            return False
        proc = self.manager.processes.get(name)
        child_pid = proc.pid if proc is not None else None

        if not self.is_port_in_use(port):
            return False
        if not self._is_pid_listening(child_pid, int(port)):
            return False

        host = meta.get("host") or "127.0.0.1"
        for path in tuple(meta.get("health_paths") or ()):
            if not self._http_ok(f"http://{host}:{int(port)}{path}"):
                return False
        return True

    def wait_for_service_ready(self, name: str, timeout: float = 20.0, poll_interval: float = 0.5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            proc = self.manager.processes.get(name)
            if proc is not None and proc.poll() is not None:
                return False
            if self._is_service_ready(name):
                return True
            time.sleep(poll_interval)
        return self._is_service_ready(name)

    def start_named_service(self, name: str, env: Optional[Dict[str, str]] = None) -> bool:
        if not self.can_start_service(name):
            return False
        try:
            launch_cmd, cwd = self.get_service_launch(name)
            started = self.manager.start_process(name, launch_cmd, cwd, self.get_service_env(name, env))
            if not started:
                self._record_failure(name, "start", "进程启动失败（start_process 返回 False）")
                return False
            # B7: 仅对 registry 中声明了 port_default 且健康探针非空的 HTTP 服务做就绪探测;
            # redis/celery-worker/hermes-gateway 无 health_paths,依赖进程存活即视为就绪。
            meta = SERVICE_REGISTRY.get(name)
            if meta and meta.get("port_default") is not None and tuple(meta.get("health_paths") or ()):
                ready = self.wait_for_service_ready(name)
                if not ready:
                    probe_port = self.service_ports.get(name)
                    log_tail = self._tail_log(name)
                    self._record_failure(
                        name,
                        "readiness",
                        f"启动后未通过就绪探测（端口 {probe_port}）；日志尾部: {log_tail[-300:] or '无'}",
                    )
                    self.manager.stop_process(name)
                    return False
            return True
        except Exception as exc:
            logger.warning("Skipping %s startup: %s", name, exc)
            self._record_failure(name, "exception", str(exc))
            return False

    def is_port_in_use(self, port: int, host: str = "127.0.0.1") -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                return sock.connect_ex((host, port)) == 0
        except Exception:
            return False

    def _find_pids_by_port(self, port: int) -> List[int]:
        try:
            import psutil
        except Exception:
            return []

        pids = set()
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr and conn.laddr.port == port and conn.pid:
                    pids.add(conn.pid)
        except Exception:
            return []
        return sorted(pids)

    def _terminate_pid(self, pid: int) -> bool:
        if pid <= 0 or pid == os.getpid():
            return False
        if sys.platform == "win32":
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return result.returncode == 0
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except Exception:
            return False

    def _free_port(self, port: int, name: str) -> bool:
        pids = self._find_pids_by_port(port)
        for pid in pids:
            self._terminate_pid(pid)
        if pids:
            time.sleep(1)
        return not self.is_port_in_use(port)

    def mark_external_service(self, name: str, running: bool) -> None:
        if running:
            self.external_services[name] = True
        else:
            self.external_services.pop(name, None)

    def is_external_running(self, name: str) -> bool:
        return bool(self.external_services.get(name))

    def get_service_status(self, name: str) -> Dict[str, object]:
        gateway_platform_status = None
        if name == "hermes-gateway":
            gateway_platform_status = self._get_gateway_platform_status()

        proc = self.manager.processes.get(name)
        managed_running = self.manager.is_running(name)
        external_running = self.is_external_running(name)
        service_port = self.service_ports.get(name)

        if not managed_running and service_port:
            port_open = self.is_port_in_use(service_port)
            if port_open and not external_running:
                external_running = True
                self.mark_external_service(name, True)
            elif external_running and not port_open:
                external_running = False
                self.mark_external_service(name, False)

        pid = proc.pid if managed_running and proc else None

        if name == "hermes-gateway" and external_running and pid is None:
            gateway_state = self._read_gateway_state()
            gateway_pid = gateway_state.get("pid")
            if isinstance(gateway_pid, int):
                pid = gateway_pid

        source = "managed" if managed_running else "external" if external_running else "stopped"
        payload = {
            "running": bool(managed_running or external_running),
            "pid": pid,
            "external": external_running,
            "managed": managed_running,
            "source": source,
        }
        if gateway_platform_status is not None:
            payload["configured"] = bool(gateway_platform_status["configured"])
            payload["platforms"] = gateway_platform_status["platforms"]
            payload["reason"] = gateway_platform_status["reason"]
            if not gateway_platform_status["configured"]:
                payload["running"] = False
                payload["pid"] = None
                payload["external"] = False
                payload["managed"] = False
                payload["source"] = "disabled"
        # B7: 端口 / URL 附加字段统一由 SERVICE_REGISTRY 驱动。
        meta = SERVICE_REGISTRY.get(name)
        if meta and meta.get("port_default") is not None:
            svc_port = self.service_ports.get(name)
            host = meta.get("host") or "127.0.0.1"
            if svc_port is not None:
                base_url = f"http://{host}:{int(svc_port)}"
                payload["port"] = svc_port
                payload["url"] = base_url
                for extra_key in tuple(meta.get("status_extras") or ()):
                    payload[extra_key] = base_url
        return payload

    def _license_entitlements(self) -> Optional[frozenset]:
        """读取本地注册码的授权条目(已验签);没有注册码 / 验签失败 → None。

        注册码文件位置与后端一致:由 Electron 主进程注入 `LAOMA_DATA_DIR`,
        文件名固定 `license.json`(core/license.py::LICENSE_FILE_NAME)。
        """
        data_dir = (os.environ.get("LAOMA_DATA_DIR") or "").strip()
        if not data_dir:
            return None
        license_path = Path(data_dir) / "license.json"
        if not license_path.is_file():
            return None
        try:
            payload = json.loads(license_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 文件坏了按「无授权」
            logger.warning("Failed to read local license file: %s", exc)
            return None
        if not isinstance(payload, dict):
            return None
        public_key_hex = load_license_public_key(self.backend_dir)
        if not public_key_hex:
            logger.warning("License public key unavailable; agent capability disabled")
            return None
        return verify_license_token(str(payload.get("token") or ""), public_key_hex)

    def agent_capability_enabled(self) -> bool:
        """本地注册码是否带 `agent` 授权条目(决定要不要起 Hermes sidecar)。"""
        if (os.environ.get(HERMES_GATE_SKIP_ENV) or "").strip() in {"1", "true", "yes", "on"}:
            return True
        entitlements = self._license_entitlements()
        return bool(entitlements and AGENT_ENTITLEMENT in entitlements)

    def can_start_service(self, name: str) -> bool:
        if name in HERMES_SERVICES and not self.agent_capability_enabled():
            logger.info(
                "Skipping %s startup: local license has no '%s' entitlement "
                "(limited-feature edition)",
                name,
                AGENT_ENTITLEMENT,
            )
            return False
        if name == "hermes-gateway":
            gateway_platform_status = self._get_gateway_platform_status()
            if not gateway_platform_status["configured"]:
                self.mark_external_service(name, False)
                return False
            gateway_state = self._read_gateway_state()
            gateway_pid = gateway_state.get("pid")
            if self._is_pid_alive(gateway_pid if isinstance(gateway_pid, int) else None):
                if self.kill_port_conflict and isinstance(gateway_pid, int):
                    if self._terminate_pid(gateway_pid):
                        time.sleep(1)
                        self.mark_external_service(name, False)
                        return True
                self.mark_external_service(name, True)
                return False
            self.mark_external_service(name, False)
            return True

        if name in {"backend", "automation-worker", "hermes-dashboard", "hermes-webui"}:
            self._resolve_dynamic_service_port(name, self._get_reserved_dynamic_ports(name))
            self.mark_external_service(name, False)
            return True

        port = self.service_ports.get(name)
        if not port:
            return True
        if self.is_port_in_use(port):
            if self.kill_port_conflict and self._free_port(port, name):
                self.mark_external_service(name, False)
                return True
            self.mark_external_service(name, True)
            return False
        self.mark_external_service(name, False)
        return True

    def _kill_conflicting_processes(self) -> None:
        # B7: 冲突清理端口来自 SERVICE_REGISTRY(redis=6379),非硬编码元组。
        for name, meta in SERVICE_REGISTRY.items():
            port_default = meta.get("port_default")
            if not port_default or name in {"backend", "automation-worker", "hermes-dashboard", "hermes-webui"}:
                # HTTP 服务的动态端口冲突由 _resolve_dynamic_service_port / can_start_service 处理,
                # 这里只清理外部非 HTTP 服务(redis)可能占用的静态端口。
                continue
            port = self.service_ports.get(name, int(port_default))
            if self.is_port_in_use(int(port)) and self.kill_port_conflict:
                for pid in self._find_pids_by_port(int(port)):
                    self._terminate_pid(pid)
                time.sleep(0.5)

    def start_redis(self, env: Dict[str, str]) -> None:
        redis_candidates = (
            self.resources_path / "prism_backend" / "Redis",
            self.resources_path / "Redis",
            self.resources_path / "redis",
        )

        redis_dir = None
        redis_exe = None
        redis_conf = None
        for candidate in redis_candidates:
            potential_exe = candidate / "redis-server.exe"
            if potential_exe.exists():
                redis_dir = candidate
                redis_exe = potential_exe
                redis_conf = candidate / "redis.windows.conf"
                break

        if not redis_exe:
            logger.warning("Redis executable not found in packaged resources.")
            return

        redis_in_use = self.is_port_in_use(6379)
        if redis_in_use and self.kill_port_conflict:
            redis_in_use = not self._free_port(6379, "redis")

        if redis_in_use:
            self.mark_external_service("redis", True)
            return

        redis_cmd = [str(redis_exe)]
        if redis_conf and redis_conf.exists():
            redis_cmd.append(str(redis_conf))
        self.manager.start_process("redis", redis_cmd, str(redis_dir), env)
        time.sleep(2)

    def start_services(self) -> None:
        logger.info("=" * 60)
        logger.info("   老马AI工作台 Supervisor Start")
        logger.info("=" * 60)

        self._kill_conflicting_processes()
        self._refresh_dynamic_service_ports()
        env = self.build_env()
        self.external_services = {}

        # B7: 启动顺序按 SERVICE_REGISTRY[svc]["start_order"] 数值升序。
        # - redis(start_order=0):由 start_redis 独立启动(exe+conf 探测),不在 start_named_service 里跑。
        # - celery-worker/hermes-gateway(start_order>=3 且 port_default=None):进程拉起即视为就绪,
        #   _is_service_ready 内部对无端口的服务直接返回 True,不会走 HTTP 探测。
        # - hermes-gateway 依赖 gateway 配置:若未配置则跳过(由 start_named_service -> can_start_service 处理)。
        # - backend 与 automation-worker 启动后等待其就绪(2s/3s)以确保 worker 后续能连到 backend。
        self.start_redis(env)

        start_order = sorted(
            SERVICE_REGISTRY.keys(),
            key=lambda name: int(SERVICE_REGISTRY[name]["start_order"]),
        )
        startup_delays = {"automation-worker": 2, "backend": 3}  # 保持与旧实现一致的启动延迟
        for name in start_order:
            if name == "redis":
                continue  # 已在上面处理
            if name == "hermes-gateway":
                gateway_platform_status = self._get_gateway_platform_status()
                if not gateway_platform_status["configured"]:
                    logger.info(
                        "Skipping hermes-gateway startup: %s",
                        gateway_platform_status["reason"],
                    )
                    continue
            self.start_named_service(name, env)
            delay = startup_delays.get(name)
            if delay:
                time.sleep(delay)

        logger.info("=" * 60)
        logger.info("All services started")
        logger.info("=" * 60)

    def _maybe_start_hermes_when_entitled(self, env: Dict[str, str]) -> None:
        """运行中拿到 agent 授权后补起 Hermes sidecar(每 15 秒检查一次)。

        场景:用户在设置页输入注册码 → 后端落盘 `license.json` →
        supervisor 下一轮检查发现多了 `agent` 条目 → 把启动时被门禁拦下的
        Hermes 三个进程补起来,不用重启客户端。
        """
        now = time.time()
        last_check = getattr(self, "_last_hermes_gate_check", 0.0)
        if now - last_check < 15.0:
            return
        self._last_hermes_gate_check = now
        if not self.agent_capability_enabled():
            return
        for name in HERMES_SERVICES:
            if name in self.manager.processes:
                continue
            if self.start_named_service(name, env):
                logger.info("Hermes %s started after license upgrade", name)

    def monitor_loop(self) -> None:
        logger.info("Starting supervisor monitor loop...")
        env = self.build_env()
        restart_counts: Dict[str, int] = {}
        last_alive_at: Dict[str, float] = {}
        restart_in_flight: set[str] = set()

        def _restart(name: str, proc: subprocess.Popen) -> None:
            policy = self.restart_policy.get(name) or {}
            max_restarts = int(policy.get("max_restarts", 0))
            backoff = float(policy.get("backoff", 5.0))
            count = restart_counts.get(name, 0)
            try:
                if count >= max_restarts:
                    self._record_failure(
                        name, "crash-limit", f"已达最大重启次数 {max_restarts}，停止自动重启"
                    )
                    return
                restart_counts[name] = count + 1
                self._record_failure(
                    name, "crash", f"进程退出，准备第 {count + 1} 次重启",
                    exit_code=proc.returncode,
                )
                time.sleep(backoff)
                if self.manager.should_stop:
                    return
                logger.info("Restarting %s (attempt %d/%d)...", name, count + 1, max_restarts)
                self.start_named_service(name, env)
                self._write_state_file(getattr(self, "api_port", None))
            finally:
                restart_in_flight.discard(name)

        try:
            while not self.manager.should_stop:
                time.sleep(3)
                now = time.time()
                # 动态解锁:用户在运行中输入了带 agent 条目的注册码 → 补起 Hermes
                self._maybe_start_hermes_when_entitled(env)
                for name, proc in list(self.manager.processes.items()):
                    if proc.poll() is None:
                        last_alive_at[name] = now
                        continue
                    if name in restart_in_flight:
                        continue
                    policy = self.restart_policy.get(name) or {}
                    stable_after = float(policy.get("stable_after", 60.0))
                    if restart_counts.get(name, 0) > 0 and (now - last_alive_at.get(name, 0.0)) >= stable_after:
                        restart_counts[name] = 0
                        logger.info("%s 稳定运行，重启计数已重置", name)
                    logger.warning("%s exited with code %s", name, proc.returncode)
                    if name in self.restart_policy:
                        restart_in_flight.add(name)
                        threading.Thread(
                            target=_restart, args=(name, proc), daemon=True, name=f"restart-{name}"
                        ).start()
        except KeyboardInterrupt:
            logger.info("Supervisor interrupted.")
        finally:
            self.manager.stop_all()

    def _resolve_api_port(self) -> int:
        """解析 supervisor HTTP API 端口：env 显式 → 7002 → 递增找可用端口。"""
        env_port = self._read_env_port(("PRISM_SUPERVISOR_PORT", "SUPERVISOR_API_PORT"), 0)
        if env_port and self._can_bind_port(env_port):
            return env_port
        if self._can_bind_port(7002):
            return 7002
        return self._find_available_port(7002)

    def start_all(self) -> None:
        self.start_services()

    def run(self) -> None:
        try:
            from api_server import SupervisorHTTPServer

            self.api_port = self._resolve_api_port()
            self.api_server = SupervisorHTTPServer(self, port=self.api_port)
            if not self.api_server.start():
                raise RuntimeError(f"Supervisor API 启动失败（端口 {self.api_port}）")
            self.api_port = self.api_server.port  # 动态分配时回读实际绑定端口
            self._write_state_file(self.api_port)
            self.start_services()
            self._write_state_file(self.api_port)  # 服务端口确定后再写一次
            self.monitor_loop()
        except Exception as exc:
            logger.error("Supervisor runtime error: %s", exc, exc_info=True)
            self._record_failure("supervisor", "runtime", str(exc))
        finally:
            if hasattr(self, "api_server"):
                self.api_server.stop()
            self.manager.stop_all()


def main() -> None:
    supervisor = Supervisor()
    supervisor.run()


if __name__ == "__main__":
    main()
