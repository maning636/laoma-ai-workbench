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
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

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


# ---------------------------------------------------------------------------
# 新增：Redis 硬连通性 & redis-py 版本硬约束（消灭假阳性）
# ---------------------------------------------------------------------------
# 背景：preflight 的 `_check_redis` 只做 socket.connect_ex（TCP），不经过 redis-py。
# 结果：即使打包产物里装了 redis-py 8.x（pin 应是 <5），preflight 也会返回
# reachable=True，烟测通过；但 Celery 一旦连 broker 就会因 RESP3 HELLO 不兼容炸掉。
# 下面这三个测试把这些"看不见"的失败模式全部变成硬失败。


def _extract_redis_url(payload: dict) -> str:
    """从 preflight payload 里抽出 redis 组件的 url；拿不到时返回默认值。"""
    try:
        v = payload.get("redis")
        if isinstance(v, dict):
            u = (v.get("url") or "").strip()
            if u:
                return u
    except Exception:
        pass
    return os.environ.get("LAOMA_REDIS_URL") or "redis://localhost:6379/0"


def test_preflight_redis_reachable_hard():
    """硬断言：preflight.redis.reachable 必须为 True。

    只收紧 redis 组件 —— 其他组件（如 persona_api / hermes）允许 False，
    因为打包机可能没装/没启动它们；但 redis 是打包必备（内置一份）。
    """
    status, payload = _get_json_async("/api/v1/system/preflight")
    assert status == 200, f"preflight HTTP {status}"
    assert isinstance(payload, dict), f"preflight payload not dict: {type(payload)}"

    redis_comp = payload.get("redis")
    assert isinstance(redis_comp, dict), (
        f"preflight.redis must be dict; got {type(redis_comp).__name__}: {redis_comp!r}"
    )
    reachable = redis_comp.get("reachable")
    url = redis_comp.get("url") or "(unset)"
    reason = redis_comp.get("reason") or ""
    assert reachable is True, (
        "HARD FAIL: preflight.redis.reachable != True. "
        f"url={url!r} reachable={reachable!r} reason={reason!r}. "
        "打包产物必须内置一份可达的 Redis。"
    )

    # 顺手对 celery broker 也做一次同一断言（同一个 broker，问题同源）
    celery_comp = payload.get("celery")
    if isinstance(celery_comp, dict) and celery_comp.get("broker"):
        assert celery_comp.get("reachable") is True, (
            "HARD FAIL: preflight.celery.reachable != True. "
            f"broker={celery_comp.get('broker')!r} "
            f"reason={celery_comp.get('reason')!r}"
        )


def _redis_py_version_from_env(env_python: str) -> str:
    """用给定的 python.exe 读取它自带的 redis 包版本号。"""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    code = "import redis, sys; sys.stdout.write(redis.__version__); sys.stdout.flush()"
    cp = subprocess.run(
        [env_python, "-c", code],
        capture_output=True, text=True, timeout=15, env=env,
    )
    if cp.returncode != 0:
        pytest.fail(
            f"can't read redis.__version__ via {env_python}: "
            f"rc={cp.returncode}\nstderr={cp.stderr.strip()}"
        )
    return cp.stdout.strip()


def _pick_package_python() -> Path | None:
    """定位打包产物内 python.exe；找不到时返回 None。"""
    pkg = os.environ.get("LAOMA_PACKAGE_PATH", "").strip()
    if pkg:
        cand = Path(pkg) / "prismenv" / "Scripts" / "python.exe"
        if cand.exists():
            return cand
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "prismenv" / "Scripts" / "python.exe"
        if cand.exists():
            return cand
    return None


def test_packaged_redis_py_version_pinned():
    """硬断言：打包产物内 redis-py 主版本号必须 < 5。

    打包机若装了 8.x，会与内置 Redis 5 在 RESP3/HELLO 上冲突，
    表现是 Celery 永远连不上 broker —— 但 preflight TCP ping 是抓不到的。
    """
    py_exe = _pick_package_python()
    if py_exe is None:
        pytest.skip(
            "no packaged python.exe found (set LAOMA_PACKAGE_PATH to the "
            "win-unpacked root to enforce this check)"
        )

    ver_str = _redis_py_version_from_env(str(py_exe))
    try:
        major = int(re.match(r"\d+", ver_str or "?").group())
    except Exception:
        major = -1
    assert major < 5, (
        f"HARD FAIL: packaged redis-py major={major} (>=5, likely RESP3). "
        "It will send 'HELLO' to the bundled Redis 5, causing "
        "'unknown command HELLO' and Celery will never connect to the broker. "
        f"python={py_exe} redis.__version__={ver_str!r}"
    )


def test_redis_e2e_ping_via_packaged_redis_py():
    """端到端：用产物自带的 redis-py 对产物使用的那台 Redis 发一次 PING → True。

    这是**根因级**检查：直接验证"产物里的 redis-py 能不能连上"，
    与 preflight 的 TCP-only 探测完全不同。任何 RESP 层/HELLO 不兼容
    都会在这里以 ConnectionError 形式硬失败。
    """
    status, payload = _get_json_async("/api/v1/system/preflight")
    assert status == 200, f"preflight HTTP {status}"
    assert isinstance(payload, dict), f"preflight payload not dict"
    redis_url = _extract_redis_url(payload)

    py_exe = _pick_package_python()
    if py_exe is None:
        pytest.skip(
            "no packaged python.exe found (set LAOMA_PACKAGE_PATH to run "
            "the end-to-end ping test)"
        )

    ping_url = os.environ.get("LAOMA_REDIS_PING_URL") or redis_url
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["LAOMA_REDIS_PING_URL"] = ping_url

    code = (
        "import os, sys, redis as r; "
        "from urllib.parse import urlparse; "
        "u = os.environ.get('LAOMA_REDIS_PING_URL') or 'redis://localhost:6379/0'; "
        "p = urlparse(u); "
        "c = r.Redis(host=p.hostname or 'localhost', "
        "port=p.port or 6379, db=(p.path or '/0').lstrip('/') or '0', "
        "socket_connect_timeout=3, socket_timeout=3); "
        "try: "
        "    ok = bool(c.ping()); "
        "    v = (c.info('server').get('redis_version') or '?'); "
        "    print('PING_OK redis_version=' + str(v)); "
        "except Exception as e: "
        "    sys.stdout.write('PING_FAIL ' + type(e).__name__ + ': ' + str(e)); "
        "    sys.exit(2)"
    )
    cp = subprocess.run(
        [str(py_exe), "-c", code],
        capture_output=True, text=True, timeout=15, env=env,
    )
    out = (cp.stdout or "").strip()
    err = (cp.stderr or "").strip()
    assert cp.returncode == 0, (
        f"HARD FAIL: redis-py PING failed against {ping_url!r} using "
        f"python={py_exe}\n"
        f"stdout={out!r}\nstderr={err!r}\n"
        f"diag: 若 stdout/stderr 里出现 'unknown command HELLO' 或 'unknown command 'HELLO''，"
        f"即 redis-py >= 5 与内置 Redis 5 的 RESP3 握手不兼容 → Celery 无法连 broker。"
        f"修复：把 requirements.txt 里的 redis 版本 pin 到 <5（例如 redis==4.6.0）后重打包。"
    )
    assert out.startswith("PING_OK"), (
        f"unexpected PING output: {out!r}"
    )


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
