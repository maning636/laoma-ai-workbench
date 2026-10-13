"""
integration_test.py — 打包产物的 API 集成烟测（B5）

定位：
    不启动服务、不做前端渲染。只针对「后端已起好的地址」打四个关键端点：
        - GET /api/v1/system/preflight       —— 11 个组件 key 全部存在
        - GET /api/v1/agent/easel/status     —— data 非空
        - GET /api/v1/agent/easel/update/status —— data.state / data.settings 存在
        - GET /api/v1/system/health-check    —— preflight 字段存在

后端地址来源（优先级从高到低）：
    1. env BACKEND_URL          —— 完整 base URL，例如 http://127.0.0.1:7000
    2. env LAOMA_BACKEND_PORT   —— 只给端口，默认 host 127.0.0.1
    3. 默认 http://127.0.0.1:7000  （与打包 supervisor 默认端口一致）

运行：
    $py -m pytest scripts/tests/integration_test.py -q
    # 或者由 e2e_packaged_test.ps1 拉起打包产物后：
    BACKEND_URL=http://127.0.0.1:7000 $py -m pytest scripts/tests/integration_test.py -q

说明：
    每个 test_* 用 asyncio.run(...) 自启动 event loop，不依赖 pytest-asyncio，
    这样在没有安装 pytest-asyncio 的干净 CI 环境也能直接跑。
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# preflight 期望返回的 11 个组件 key（对齐 fastapi_app/api/v1/system/preflight.py 的 tasks）
EXPECTED_PREFLIGHT_KEYS: tuple[str, ...] = (
    "python",
    "redis",
    "celery",
    "easel",
    "hermes",
    "persona_api",
    "playwright",
    "disk_space",
    "skills_dir_exists",
    "third_party_tools",
    "template_lib",
)


def _resolve_base_url() -> str:
    """从环境变量解析 base URL。"""
    base = os.environ.get("BACKEND_URL")
    if base:
        return base.rstrip("/")
    port = os.environ.get("LAOMA_BACKEND_PORT", "7000").strip() or "7000"
    host = os.environ.get("LAOMA_BACKEND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    return f"http://{host}:{port}"


BASE_URL: str = _resolve_base_url()
TIMEOUT: float = float(os.environ.get("BACKEND_TIMEOUT", "8.0"))


def _get_json_async(path: str) -> tuple[int, object]:
    """同步入口：在临时 event loop 里发一次 GET，返回 (status_code, json)。"""

    async def _run():
        async with httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(TIMEOUT, connect=3.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(path)
            try:
                return resp.status_code, resp.json()
            except Exception:
                return resp.status_code, resp.text

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


def test_preflight():
    """GET /api/v1/system/preflight 必须 200 且包含 11 个组件 key。"""
    status, payload = _get_json_async("/api/v1/system/preflight")
    assert status == 200, (
        f"preflight HTTP {status}: {payload if not isinstance(payload, dict) else 'see body'}"
    )
    assert isinstance(payload, dict), f"preflight payload not dict: {type(payload)}"

    missing = [k for k in EXPECTED_PREFLIGHT_KEYS if k not in payload]
    assert not missing, (
        f"preflight missing keys: {missing}; got top-level: {sorted(payload.keys())}"
    )

    # 允许组件内部 reachable=False（比如打包机未装 redis），但键本身必须存在。
    for k in EXPECTED_PREFLIGHT_KEYS:
        v = payload[k]
        assert v is not None, f"preflight.{k} is null"


def test_easel_status():
    """GET /api/v1/agent/easel/status 必须 200 且 data 是 dict。"""
    status, payload = _get_json_async("/api/v1/agent/easel/status")
    assert status == 200, f"easel/status HTTP {status}"
    assert isinstance(payload, dict), f"payload not dict: {type(payload)}"
    assert "data" in payload, f"missing 'data' key in response: {payload}"
    data = payload["data"]
    # 端点约定：成功时 data 是 Easel 状态 dict；异常时 data = {'error': ...}，仍是 dict
    assert isinstance(data, dict), f"data is not dict: {type(data)}"


def test_easel_update_status():
    """GET /api/v1/agent/easel/update/status 必须 200 且含 data.state / data.settings。"""
    status, payload = _get_json_async("/api/v1/agent/easel/update/status")
    assert status == 200, f"update/status HTTP {status}"
    assert isinstance(payload, dict), f"payload not dict: {type(payload)}"
    assert "data" in payload, f"missing 'data' key: {payload}"
    data = payload["data"]
    assert isinstance(data, dict), f"data not dict: {type(data)}"
    # 状态/配置在文件不存在时会退化为 {}，但键必须存在
    assert "state" in data, f"missing data.state: {data}"
    assert "settings" in data, f"missing data.settings: {data}"


def test_health_check():
    """GET /api/v1/system/health-check 必须 200 且含 preflight 字段。"""
    status, payload = _get_json_async("/api/v1/system/health-check")
    assert status == 200, f"health-check HTTP {status}"
    assert isinstance(payload, dict), f"payload not dict: {type(payload)}"

    # 顶层结构：{ status, components, preflight, timestamp }
    assert "preflight" in payload, f"missing 'preflight': {list(payload.keys())}"
    # preflight 可能是 dict（正常）或 error 字符串（run_preflight_check 抛异常时的兜底）
    assert isinstance(payload["preflight"], (dict, str)), (
        f"preflight must be dict or error string: {type(payload['preflight'])}"
    )
    # components 字段可选，但存在时必须是 dict
    if "components" in payload:
        assert isinstance(payload["components"], dict), (
            f"components not dict: {type(payload['components'])}"
        )


# ---------------------------------------------------------------------------
# 占位：前端视觉验证
# ---------------------------------------------------------------------------


def test_settings_page_easel_card_placeholder():
    """前端 Easel 卡片视觉验证占位。

    本测试故意 skip：真正验证需要 Playwright + 浏览器会话，超出 API 集成测试范畴。
    打包环境下的浏览器渲染建议由 scripts/tests/e2e_packaged_test.ps1 触发，
    或后续在 CI 中拆独立 job 覆盖。
    """
    pytest.skip(
        "requires Playwright + graphical session; run via e2e_packaged_test.ps1"
    )
