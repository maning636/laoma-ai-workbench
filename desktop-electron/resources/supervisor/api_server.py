#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Supervisor HTTP API - control endpoints for Electron.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import sys
import threading
import time

# B-A: 服务清单统一从 supervisor.SERVICE_REGISTRY 派生,避免 api_server.py 与 supervisor.py
# 各自维护一份硬编码列表。同目录导入,与 supervisor.py 打包时总是并存。
_SUPERVISOR_DIR = os.path.dirname(os.path.abspath(__file__))
if _SUPERVISOR_DIR not in sys.path:
    sys.path.insert(0, _SUPERVISOR_DIR)

from supervisor import SERVICE_REGISTRY  # noqa: E402

logger = logging.getLogger(__name__)

# /api/status 与 /api/restart 对外暴露的"用户可见"服务。
#
# 注意:
# - 顺序**不能**改成 registry 的 start_order 顺序 —— 那样会破坏历史 /api/status 返回
#   字典的字段顺序契约(旧实现固定为 backend / automation-worker / celery-worker /
#   hermes-gateway / hermes-dashboard / hermes-webui)。
# - redis 在 registry 中存在但历史 API 从未返回它,这里同样排除,保持外部行为不变。
#
# 这里只做"成员校验",不做"顺序推导":显式列出 6 个服务名,启动时若 registry 中缺失
# 立刻 raise,保证 registry 与 api_server.py 契约同步演进,而不是静默分叉。
_LEGACY_API_SERVICES: tuple = (
    "backend",
    "automation-worker",
    "celery-worker",
    "hermes-gateway",
    "hermes-dashboard",
    "hermes-webui",
)
_missing = [n for n in _LEGACY_API_SERVICES if n not in SERVICE_REGISTRY]
if _missing:
    raise RuntimeError(
        f"api_server.py: SERVICE_REGISTRY 缺失 legacy API 服务条目: {_missing}"
    )
STATUS_SERVICES: tuple = _LEGACY_API_SERVICES


class SupervisorAPIHandler(BaseHTTPRequestHandler):
    supervisor = None
    restart_lock = threading.Lock()
    restart_in_progress = False

    def log_message(self, format, *args):  # noqa: A003, ANN001
        return

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path == "/api/status":
            status = {}
            for name in STATUS_SERVICES:
                service_status = self.supervisor.get_service_status(name)
                failure = self.supervisor.failures.get(name)
                if failure:
                    service_status["failure"] = failure
                    service_status["log_tail"] = self.supervisor._tail_log(name)
                status[name.replace("-", "_")] = service_status
            self._send_json({"status": "success", "data": status})
            return

        if self.path == "/api/restart-status":
            self._send_json(
                {
                    "status": "success",
                    "data": {
                        "restart_in_progress": bool(self.__class__.restart_in_progress),
                    },
                }
            )
            return

        if self.path == "/api/health":
            # 归属校验：Electron 对比 launchToken 与状态文件中的令牌，确认连的是本 supervisor
            self._send_json(
                {
                    "status": "ok",
                    "message": "Supervisor is running",
                    "pid": os.getpid(),
                    "launchToken": getattr(self.supervisor, "launch_token", None),
                    "apiPort": getattr(self.supervisor, "api_port", None),
                }
            )
            return

        if self.path == "/api/diagnostics":
            self._send_json(
                {
                    "status": "success",
                    "data": self.supervisor.get_diagnostics(),
                }
            )
            return

        self._send_json({"status": "error", "message": "Not Found"}, 404)

    def do_POST(self):
        if self.path == "/api/start":
            return self._run_action(self.supervisor.start_all, "All services started")

        if self.path == "/api/stop":
            return self._run_action(self.supervisor.manager.stop_all, "All services stopped")

        if self.path == "/api/restart":
            with self.__class__.restart_lock:
                if self.__class__.restart_in_progress:
                    self._send_json({"status": "accepted", "message": "Restart already in progress"})
                    return
                self.__class__.restart_in_progress = True

            def _restart_all_async():
                try:
                    self.supervisor.manager.stop_all()
                    self.supervisor.start_all()
                    logger.info("All services restarted successfully")
                except Exception as exc:
                    logger.error("Restart all services failed: %s", exc, exc_info=True)
                finally:
                    with self.__class__.restart_lock:
                        self.__class__.restart_in_progress = False

            threading.Thread(target=_restart_all_async, name="supervisor-restart-all", daemon=True).start()
            self._send_json({"status": "accepted", "message": "Restart scheduled"})
            return

        if self.path.startswith("/api/restart/"):
            service = self.path.split("/")[-1]
            if service not in STATUS_SERVICES:
                valid_services = list(STATUS_SERVICES)
                self._send_json(
                    {
                        "status": "error",
                        "message": f"Invalid service: {service}. Use: {', '.join(valid_services)}",
                    },
                    400,
                )
                return

            try:
                if service == "hermes-gateway":
                    gateway_platform_status = self.supervisor._get_gateway_platform_status()
                    if not gateway_platform_status.get("configured"):
                        self._send_json(
                            {
                                "status": "error",
                                "message": str(gateway_platform_status.get("reason") or "Hermes gateway is not configured."),
                            },
                            409,
                        )
                        return

                if self.supervisor.manager.is_running(service):
                    self.supervisor.manager.stop_process(service)
                    time.sleep(1)

                started = self.supervisor.start_named_service(service)
                service_status = self.supervisor.get_service_status(service)
                if not started and not service_status.get("running"):
                    self._send_json(
                        {
                            "status": "error",
                            "message": f"{service} failed to restart",
                            "data": service_status,
                        },
                        500,
                    )
                    return
                message = f"{service} restarted" if started else f"{service} already running"
                self._send_json({"status": "success", "message": message, "data": service_status})
            except Exception as exc:
                logger.error("Restart service %s failed: %s", service, exc)
                self._send_json({"status": "error", "message": str(exc)}, 500)
            return

        self._send_json({"status": "error", "message": "Not Found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _run_action(self, fn, message):
        try:
            fn()
            self._send_json({"status": "success", "message": message})
        except Exception as exc:
            self._send_json({"status": "error", "message": str(exc)}, 500)


class SupervisorHTTPServer:
    def __init__(self, supervisor, host="127.0.0.1", port=7002):
        self.supervisor = supervisor
        self.host = host
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        try:
            SupervisorAPIHandler.supervisor = self.supervisor
            self.server = ThreadingHTTPServer((self.host, self.port), SupervisorAPIHandler)
            # 动态端口（port=0 或绑定后被内核调整）时回读实际监听端口
            self.port = self.server.server_address[1]
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            logger.info("Supervisor API started: http://%s:%s", self.host, self.port)
            return True
        except Exception as exc:
            logger.error("Supervisor API start failed: %s", exc)
            return False

    def stop(self):
        if self.server:
            self.server.shutdown()
            logger.info("Supervisor API stopped")
