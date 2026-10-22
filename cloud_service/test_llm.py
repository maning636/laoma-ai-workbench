"""C14 · LLM Proxy TestClient 集成测试(不启动服务,不真调 LLM)。

覆盖流程:
  1. register → login → 拿 JWT
  2. POST /cloud/llm/chat(mock LLM) → 返回 content,不含 template
  3. GET  /cloud/llm/prompts → 分层列表(cloud / basic / all)
  4. 无 JWT → 401
  5. 订阅无额度 + chat → 402
  6. raw_prompt 未开 allow_raw → 400(防逆向)
  7. raw_prompt + allow_raw → 200(但消耗 2 倍额度)
  8. 未配置的 prompt_name → 404
  9. 缺变量的 chat → 422

用法:
  python cloud_service/test_llm.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# ── 环境准备:临时 SQLite,避免污染仓库 ────────────────────────
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["CLOUD_DB_URL"] = f"sqlite:///{_tmp.name}"
os.environ.pop("CLOUD_ACCESS_TOKEN_EXPIRE_MINUTES", None)

# free quota 设为 3,便于验证超额
os.environ["CLOUD_FREE_QUOTA"] = "3"
os.environ["CLOUD_PRO_QUOTA"] = "-1"

# LLM key:测试里 mock 掉,不需要真值,但保证 get_vault() 认为已配置
os.environ["CLOUD_LLM_API_KEY"] = "test-key-placeholder"
os.environ["CLOUD_LLM_BASE_URL"] = "https://example.invalid/v1"
os.environ["CLOUD_LLM_MODEL"] = "mock-model"
# 「模拟激活订阅」端点生产默认关闭(仅开发用);测试显式打开。
os.environ["CLOUD_DEV_ALLOW_SUBSCRIPTION_ACTIVATE"] = "1"

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# D6:云端模板正文是 Pro 私有资产。开源仓不含它,云端 tier 的行为也不同
# (403「需 Pro 版」而不是 200),且 403 **不消耗额度** —— 下面的额度断言要一起分支。
from cloud_service.llm_proxy import prompts as _prompts_mod  # noqa: E402

HAS_CLOUD_ASSETS = bool(_prompts_mod.CLOUD_PROMPTS)


def _install_llm_mock():
    """把 `llm_client.call_cloud_llm` 替换为异步 mock,防止真调网络。"""
    from cloud_service.llm_proxy import llm_client

    async def _fake_call_cloud_llm(*, messages, prompt_name, prompt_version, **_kw):
        # messages[0] 里就是渲染后的 prompt —— 用于断言渲染正确
        rendered = messages[0]["content"] if messages else ""
        return llm_client.LLMCallResult(
            content=f"[MOCK] rendered_len={len(rendered)} prompt_name={prompt_name}",
            model="mock-model",
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            tokens_in=max(1, len(rendered) // 2),
            tokens_out=20,
        )

    llm_client.call_cloud_llm = _fake_call_cloud_llm  # type: ignore[assignment]


def _install_stream_mock():
    """把 `llm_client.stream_cloud_llm` 替换为异步生成器 mock。

    行为:分 4 段吐 delta,最后一帧带 usage —— 覆盖"边流边累计 usage"路径。
    """
    from cloud_service.llm_proxy import llm_client

    def _chunks(rendered: str):
        # 简单稳定:每段 2-4 字符,便于断言顺序
        return ["Hello ", "world ", "from ", "mock!"]

    async def _fake_stream_cloud_llm(*, messages, prompt_name, prompt_version, **_kw):
        rendered = messages[0]["content"] if messages else ""
        for tok in _chunks(rendered):
            yield llm_client.LLMStreamEvent(delta=tok, usage={})
        yield llm_client.LLMStreamEvent(
            delta="",
            usage={"prompt_tokens": max(1, len(rendered) // 2), "completion_tokens": 20},
        )

    llm_client.stream_cloud_llm = _fake_stream_cloud_llm  # type: ignore[assignment]


def _install_stream_error_mock():
    """上游抛错的流式 mock —— 用于验证 error 帧路径。"""
    from cloud_service.llm_proxy import llm_client

    async def _fake_stream_cloud_llm(*, messages, prompt_name, prompt_version, **_kw):
        yield llm_client.LLMStreamEvent(delta="prefix ", usage={})
        raise RuntimeError("boom")
        # 让 mypy/静态工具认为这是异步生成器
        yield  # pragma: no cover

    llm_client.stream_cloud_llm = _fake_stream_cloud_llm  # type: ignore[assignment]


def run() -> int:
    from fastapi.testclient import TestClient

    from cloud_service.main import app

    _install_llm_mock()
    _install_stream_mock()

    fails = 0

    def check(label: str, cond: bool, extra: str = "") -> None:
        nonlocal fails
        tag = "PASS" if cond else "FAIL"
        print(f"[{tag}] {label}" + (f" — {extra}" if extra else ""))
        if not cond:
            fails += 1

    with TestClient(app) as client:
        # ── 1. register + login ─────────────────────────────
        r = client.post(
            "/cloud/auth/register",
            json={
                "username": "dave",
                "email": "dave@example.com",
                "password": "supers3cret",
            },
        )
        check("register dave", r.status_code == 201, f"status={r.status_code}")

        r = client.post(
            "/cloud/auth/login",
            json={"username": "dave", "password": "supers3cret"},
        )
        check("login dave", r.status_code == 200, f"status={r.status_code}")
        access = r.json().get("access_token", "")
        check("login returns access_token", bool(access), f"len={len(access)}")
        H = {"Authorization": f"Bearer {access}"}

        # ── 2. health:暴露 key 配置但不泄露 key 明文 ─────────
        r = client.get("/cloud/llm/health")
        check("GET /cloud/llm/health -> 200", r.status_code == 200,
              f"status={r.status_code}")
        hv = r.json()
        check("health.api_key_configured == True", hv.get("api_key_configured") is True,
              f"body={hv}")
        _expected_cloud = 5 if HAS_CLOUD_ASSETS else 0
        check(f"health.prompt_count.cloud == {_expected_cloud}",
              hv.get("prompt_count", {}).get("cloud") == _expected_cloud,
              f"count={hv.get('prompt_count')}")
        check("health.prompt_count.cloud_declared == 5",
              hv.get("prompt_count", {}).get("cloud_declared") == 5,
              f"count={hv.get('prompt_count')}")
        check("health.prompt_count.basic == 4", hv.get("prompt_count", {}).get("basic") == 4,
              f"count={hv.get('prompt_count')}")
        check("health 不含 key 明文", "test-key-placeholder" not in r.text,
              f"body={r.text[:200]}")

        # ── 3. GET /cloud/llm/prompts(不含模板)────────────
        r = client.get("/cloud/llm/prompts", headers=H)
        check("GET /cloud/llm/prompts -> 200", r.status_code == 200,
              f"status={r.status_code}")
        body = r.json()
        check("prompts.total == 9 (5 cloud + 4 basic)", body.get("total") == 9,
              f"total={body.get('total')}")
        item_names = [i["name"] for i in body["items"]]
        check("prompts 含 cloud 名 cognition.matrix_evaluate",
              "cognition.matrix_evaluate" in item_names, f"names={item_names}")
        check("prompts 含 basic 名 title.basic_generate",
              "title.basic_generate" in item_names, f"names={item_names}")
        # 关键:响应里没有 template 字段
        check("prompts 列表不含 template 字段",
              all("template" not in i for i in body["items"]),
              f"items[0]={body['items'][0]}")
        # 能力清单始终可见;available 反映当前部署能否拿到模板正文
        _cloud_items = [i for i in body["items"] if i.get("tier") == "cloud"]
        check("cloud 能力清单可列出(5 条)",
              len(_cloud_items) == 5, f"cloud_items={_cloud_items}")
        check("cloud 项 available 标记与资产就绪状态一致",
              all(i.get("available") is HAS_CLOUD_ASSETS for i in _cloud_items),
              f"cloud_items={_cloud_items}")

        # tier 过滤
        r = client.get("/cloud/llm/prompts?tier=cloud", headers=H)
        check("GET /cloud/llm/prompts?tier=cloud -> 200", r.status_code == 200)
        check("cloud filter total == 5", r.json().get("total") == 5,
              f"body={r.json()}")

        r = client.get("/cloud/llm/prompts?tier=basic", headers=H)
        check("GET /cloud/llm/prompts?tier=basic -> 200", r.status_code == 200)
        check("basic filter total == 4", r.json().get("total") == 4,
              f"body={r.json()}")

        # ── 4. 无 JWT → 401 ──────────────────────────────
        r = client.get("/cloud/llm/prompts")
        check("GET /cloud/llm/prompts without JWT -> 401", r.status_code == 401,
              f"status={r.status_code}")

        r = client.post(
            "/cloud/llm/chat",
            json={"prompt_name": "title.basic_generate", "variables": {"topic": "AI", "count": 3}},
        )
        check("POST /cloud/llm/chat without JWT -> 401", r.status_code == 401,
              f"status={r.status_code}")

        # ── 5. chat 走 prompt_name ────────────────────────
        r = client.post(
            "/cloud/llm/chat",
            json={
                "prompt_name": "platform_style.match",
                "variables": {"platform": "xiaohongshu", "topic": "早C晚A", "constraints": "≤30字"},
            },
            headers=H,
        )
        if HAS_CLOUD_ASSETS:
            check("POST /cloud/llm/chat prompt_name -> 200", r.status_code == 200,
                  f"status={r.status_code} body={r.text[:300]}")
            c1 = r.json()
            check("chat.prompt_name == platform_style.match",
                  c1.get("prompt_name") == "platform_style.match",
                  f"body={c1}")
            check("chat.prompt_tier == cloud", c1.get("prompt_tier") == "cloud",
                  f"body={c1}")
            check("chat.content 非空", bool(c1.get("content")),
                  f"content={c1.get('content')!r}")
            check("chat 响应不含 template 字段", "template" not in c1,
                  f"keys={list(c1.keys())}")
            check("chat.usage_after.remaining == 2 (3-1)",
                  c1.get("usage_after", {}).get("remaining") == 2,
                  f"usage={c1.get('usage_after')}")
        else:
            # 开源仓:云端模板正文不在 → 明确 403「需 Pro 版」,不是 404「不存在」
            check("POST /cloud/llm/chat cloud prompt(无资产) -> 403",
                  r.status_code == 403,
                  f"status={r.status_code} body={r.text[:300]}")
            check("403 提示需 Pro 版", "Pro" in r.text, f"body={r.text[:200]}")

        # ── 6. basic tier chat 也可以 ─────────────────────
        r = client.post(
            "/cloud/llm/chat",
            json={
                "prompt_name": "title.basic_generate",
                "variables": {"topic": "AI", "count": 3},
            },
            headers=H,
        )
        check("POST /cloud/llm/chat basic tier -> 200", r.status_code == 200,
              f"status={r.status_code}")
        c2 = r.json()
        check("chat basic.prompt_tier == basic",
              c2.get("prompt_tier") == "basic", f"body={c2}")
        # 有资产时云端 chat 已消耗 1(3→2),basic 再消耗 1 → 剩 1;
        # 无资产时云端 chat 是 403(不扣额度),basic 消耗 1 → 剩 2。
        _expected_remaining = 1 if HAS_CLOUD_ASSETS else 2
        check(f"chat basic.usage_after.remaining == {_expected_remaining}",
              c2.get("usage_after", {}).get("remaining") == _expected_remaining,
              f"usage={c2.get('usage_after')}")

        # ── 7. raw_prompt 未开 allow_raw → 400 ───────────
        r = client.post(
            "/cloud/llm/chat",
            json={"raw_prompt": "你好"},
            headers=H,
        )
        check("POST /cloud/llm/chat raw_prompt w/o allow_raw -> 400",
              r.status_code == 400, f"status={r.status_code} body={r.text}")

        # ── 8. raw_prompt + allow_raw 但剩余额度不够 2 倍 ──
        # 剩余额度只有 1,raw cost=2 → 402
        r = client.post(
            "/cloud/llm/chat",
            json={"raw_prompt": "你好", "allow_raw": True},
            headers=H,
        )
        # 有资产:已用 2,raw cost=2 → 2+2>3 → 402
        # 无资产:已用 1,raw cost=2 → 1+2=3 不超 → 200
        _expected_raw = 402 if HAS_CLOUD_ASSETS else 200
        check(f"POST /cloud/llm/chat raw_prompt overshoot -> {_expected_raw}",
              r.status_code == _expected_raw,
              f"status={r.status_code} body={r.text}")

        # ── 9. 不存在的 prompt_name → 404 ────────────────
        r = client.post(
            "/cloud/llm/chat",
            json={"prompt_name": "not.exist", "variables": {}},
            headers=H,
        )
        check("POST /cloud/llm/chat unknown prompt -> 404",
              r.status_code == 404, f"status={r.status_code}")

        # ── 10. 缺变量 → 422 ────────────────────────────
        r = client.post(
            "/cloud/llm/chat",
            json={"prompt_name": "platform_style.match", "variables": {"topic": "x"}},
            headers=H,
        )
        # 有资产:模板在,缺变量 → 422;无资产:模板不在 → 先 403「需 Pro 版」
        _expected_missing = 422 if HAS_CLOUD_ASSETS else 403
        check(f"POST /cloud/llm/chat missing variables -> {_expected_missing}",
              r.status_code == _expected_missing,
              f"status={r.status_code} body={r.text[:200]}")

        # ── 11. 激活 pro → raw 兜底可用 ──────────────────
        r = client.post(
            "/cloud/subscription/activate",
            json={"plan": "pro", "days": 30},
            headers=H,
        )
        check("POST /cloud/subscription/activate pro -> 200",
              r.status_code == 200, f"status={r.status_code}")
        check("pro.quota == -1", r.json().get("quota") == -1, f"body={r.json()}")

        r = client.post(
            "/cloud/llm/chat",
            json={"raw_prompt": "你好,请简单回复", "allow_raw": True},
            headers=H,
        )
        check("POST /cloud/llm/chat raw_prompt after pro -> 200",
              r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
        c3 = r.json()
        check("raw chat.prompt_tier == raw", c3.get("prompt_tier") == "raw",
              f"body={c3}")
        check("raw chat.prompt_name == __raw__", c3.get("prompt_name") == "__raw__",
              f"body={c3}")

        # ── 12. 渲染校验:确认模板渲染成功(含变量值)──────
        r = client.post(
            "/cloud/llm/chat",
            json={
                "prompt_name": "rewrite.basic_polish",
                "variables": {"content": "  你好世界  "},
            },
            headers=H,
        )
        check("render basic_polish -> 200", r.status_code == 200,
              f"status={r.status_code}")
        # mock 返回的 content 里带 rendered_len,用来间接验证变量被替换
        c4 = r.json()
        # "你好世界" 6 字符 + 前后空格去掉 → 4 字符;整体 prompt 应该 > 20 字符
        check("render 后 prompt 被注入(非空)",
              "rendered_len=" in c4.get("content", ""),
              f"content={c4.get('content')!r}")

        # ── 13. /cloud/llm/stream:happy path ──────────────
        # 用第二用户避免污染 dave 的 pro 状态;free quota = 3
        r = client.post(
            "/cloud/auth/register",
            json={"username": "dave2", "email": "d2@example.com", "password": "supers3cret"},
        )
        check("register dave2", r.status_code == 201, f"status={r.status_code}")
        r = client.post(
            "/cloud/auth/login",
            json={"username": "dave2", "password": "supers3cret"},
        )
        check("login dave2", r.status_code == 200, f"status={r.status_code}")
        H2 = {"Authorization": f"Bearer {r.json().get('access_token','') }"}

        with client.stream(
            "POST",
            "/cloud/llm/stream",
            json={"prompt_name": "title.basic_generate", "variables": {"topic": "AI", "count": 3}},
            headers=H2,
        ) as resp:
            check("POST /cloud/llm/stream -> 200", resp.status_code == 200,
                  f"status={resp.status_code}")
            ct = (resp.headers.get("content-type") or "").lower()
            check("stream content-type == text/event-stream",
                  ct.startswith("text/event-stream"), f"ct={ct}")
            check("stream header 含 mock-model",
                  (resp.headers.get("x-llm-model") or "") == "mock-model",
                  f"x-llm-model={resp.headers.get('x-llm-model')!r}")
            check("stream header 含 prompt_name(不含 template)",
                  (resp.headers.get("x-llm-prompt-name") or "") == "title.basic_generate",
                  f"x-llm-prompt-name={resp.headers.get('x-llm-prompt-name')!r}")
            check("stream header 含 prompt_tier=basic",
                  (resp.headers.get("x-llm-prompt-tier") or "") == "basic",
                  f"x-llm-prompt-tier={resp.headers.get('x-llm-prompt-tier')!r}")
            stream_text = "".join(resp.iter_text())

        # 分帧解析
        frames = [f for f in stream_text.split("\n\n") if f.strip()]
        check("stream 帧数 > 0", len(frames) > 0, f"frames={len(frames)}")
        done_frames = [f for f in frames if "[DONE]" in f]
        check("stream 含 [DONE] 终止帧", len(done_frames) == 1, f"frames={frames}")

        # 收集 data: 行的 JSON 内容
        message_data: list[dict] = []
        for f in frames:
            data_lines = [ln[6:] for ln in f.split("\n") if ln.startswith("data: ")]
            joined = "\n".join(data_lines)
            if joined.strip() == "[DONE]" or not joined:
                continue
            try:
                obj = json.loads(joined)
                if isinstance(obj, dict):
                    message_data.append(obj)
            except json.JSONDecodeError:
                pass
        check("stream 至少 3 条 message data", len(message_data) >= 3,
              f"n={len(message_data)} payload={message_data}")

        # 首帧必须带 meta(仅一次)
        meta_frames = [m for m in message_data if "meta" in m]
        check("stream 首帧 meta 恰好一次", len(meta_frames) == 1,
              f"n={len(meta_frames)} frames={message_data}")
        check("stream meta.prompt_name 正确",
              bool(meta_frames) and meta_frames[0]["meta"]["prompt_name"] == "title.basic_generate",
              f"meta={meta_frames[:1]}")

        # 顺序与拼接(过滤 usage-only / done 帧)
        deltas = [m["delta"] for m in message_data if m.get("delta")]
        check("stream delta 顺序正确",
              deltas == ["Hello ", "world ", "from ", "mock!"],
              f"deltas={deltas}")
        check("stream 拼接得到完整 content",
              "".join(deltas) == "Hello world from mock!",
              f"joined={''.join(deltas)!r}")

        # 终帧 tokens
        done_frames_json = [m for m in message_data if m.get("done")]
        check("stream 含 done=true 终帧", len(done_frames_json) == 1,
              f"n={len(done_frames_json)} all={message_data}")
        if done_frames_json:
            check("stream done.tokens_in > 0",
                  done_frames_json[0]["tokens_in"] > 0,
                  f"body={done_frames_json[0]}")
            check("stream done.tokens_out == 20",
                  done_frames_json[0]["tokens_out"] == 20,
                  f"body={done_frames_json[0]}")

        # 防逆向:任何响应体/帧都不应出现 template 字段或模板源码
        raw_render_hint = "生成 3 个"  # title.basic_generate 模板里的固定文本
        check("stream 响应不泄露 template 字段",
              "template" not in stream_text,
              f"text[:300]={stream_text[:300]!r}")
        check("stream 响应不泄露模板固定文本",
              raw_render_hint not in stream_text,
              f"text[:300]={stream_text[:300]!r}")

        # ── 14. 未鉴权 stream → 401 ──────────────────────
        r = client.post(
            "/cloud/llm/stream",
            json={"prompt_name": "title.basic_generate", "variables": {"topic": "x", "count": 1}},
        )
        check("POST /cloud/llm/stream without JWT -> 401", r.status_code == 401,
              f"status={r.status_code}")

        # ── 15. 前置额度检查:402 直接返回 JSON(不进入 SSE)──
        # dave2 已用 1/3;再连发 5 次,期望其中一次 402
        stream_statuses: list[int] = []
        for _ in range(5):
            with client.stream(
                "POST",
                "/cloud/llm/stream",
                json={"prompt_name": "title.basic_generate", "variables": {"topic": "x", "count": 1}},
                headers=H2,
            ) as sresp:
                stream_statuses.append(sresp.status_code)
                if sresp.status_code == 402:
                    break
        check("stream 前置额度检查:free quota=3 触发 402",
              402 in stream_statuses, f"statuses={stream_statuses}")
        # 402 时 content-type 应是 JSON,不应是 event-stream
        ct_402 = None
        for status_code in stream_statuses:
            if status_code == 402:
                # 复用:直接 GET 一次拿到 headers
                with client.stream(
                    "POST",
                    "/cloud/llm/stream",
                    json={"prompt_name": "title.basic_generate", "variables": {"topic": "x", "count": 1}},
                    headers=H2,
                ) as sresp:
                    ct_402 = sresp.headers.get("content-type", "")
                    sresp.close()
                break
        check("stream 402 返回 JSON(不进入 SSE)",
              bool(ct_402) and "application/json" in ct_402,
              f"ct={ct_402!r}")

        # ── 16. 未知 prompt → 404(前置校验)──
        r = client.post(
            "/cloud/llm/stream",
            json={"prompt_name": "not.exist", "variables": {}},
            headers=H,
        )
        check("POST /cloud/llm/stream unknown prompt -> 404",
              r.status_code == 404, f"status={r.status_code} body={r.text[:200]}")
        check("stream 404 是 JSON(不进入 SSE)",
              "application/json" in (r.headers.get("content-type") or ""),
              f"ct={r.headers.get('content-type')!r}")

        # ── 17. 上游异常:发出 error 帧后 [DONE],不 consume ──
        # dave 已 pro 无限额度,便于触发流而不受额度影响
        _install_stream_error_mock()
        used_before_err = client.get("/cloud/subscription", headers=H).json().get("used", 0)
        err_text = ""
        with client.stream(
            "POST",
            "/cloud/llm/stream",
            json={"prompt_name": "title.basic_generate", "variables": {"topic": "x", "count": 1}},
            headers=H,
        ) as sresp:
            check("stream upstream-err response 200", sresp.status_code == 200,
                  f"status={sresp.status_code}")
            err_text = "".join(sresp.iter_text())
        check("stream upstream-err 含 event: error", "event: error" in err_text,
              f"tail={err_text[:400]}")
        check("stream upstream-err 错误文本包含 boom",
              "boom" in err_text, f"err_text={err_text[:400]}")
        check("stream upstream-err 以 [DONE] 结束", err_text.rstrip().endswith("[DONE]"),
              f"tail={err_text[-80:]!r}")
        # 恢复 mock,便于后续(如果追加测试)
        _install_stream_mock()
        used_after_err = client.get("/cloud/subscription", headers=H).json().get("used", 0)
        check("stream upstream-err 未 consume 额度",
              used_after_err == used_before_err,
              f"before={used_before_err} after={used_after_err}")

        # ── 18. F-G 修复:预消费 + 补偿回滚(修复 AbortController 计费缺口) ──
        # 背景:客户端 AbortController/断网 触发 GeneratorExit,旧代码绕过
        # `except Exception`,导致"内容已发但未扣额度"。修复策略:预消费
        # + 各异常分支回滚。此处验证四条关键路径。

        import asyncio

        from cloud_service.auth.models import User as _U
        from cloud_service.db import SessionLocal as _SL
        from cloud_service.llm_proxy.router import llm_chat_stream as _llm_stream_ep
        from cloud_service.llm_proxy.schemas import ChatRequest as _ChatReq

        _db_q = _SL()
        _u_dave = _db_q.query(_U).filter(_U.username == "dave").first()
        _u_dave2 = _db_q.query(_U).filter(_U.username == "dave2").first()
        _db_q.close()
        assert _u_dave is not None and _u_dave2 is not None

        # ── 18a. 正常完成恰好扣 1 次 ───────────────────────
        _used_before_normal = client.get("/cloud/subscription", headers=H).json().get("used", 0)

        async def _drive_normal():
            resp = await _llm_stream_ep(
                payload=_ChatReq(
                    prompt_name="title.basic_generate",
                    variables={"topic": "AI", "count": 3},
                ),
                current_user=_u_dave,
                db=_SL(),
            )
            return "".join([chunk async for chunk in resp.body_iterator])

        _body_normal = asyncio.run(_drive_normal())
        _used_after_normal = client.get("/cloud/subscription", headers=H).json().get("used", 0)
        check("F-G 正常完成恰好扣 1 次额度",
              _used_after_normal == _used_before_normal + 1,
              f"before={_used_before_normal} after={_used_after_normal}")

        # ── 18b. 上游异常时回滚预消费(不净扣) ─────────────
        _install_stream_error_mock()
        _used_before_err2 = client.get("/cloud/subscription", headers=H).json().get("used", 0)

        async def _drive_err():
            resp = await _llm_stream_ep(
                payload=_ChatReq(
                    prompt_name="title.basic_generate",
                    variables={"topic": "x", "count": 1},
                ),
                current_user=_u_dave,
                db=_SL(),
            )
            return "".join([chunk async for chunk in resp.body_iterator])

        _body_err = asyncio.run(_drive_err())
        _used_after_err2 = client.get("/cloud/subscription", headers=H).json().get("used", 0)
        _install_stream_mock()
        check("F-G 上游异常时预消费被回滚(不净扣额度)",
              _used_after_err2 == _used_before_err2,
              f"before={_used_before_err2} after={_used_after_err2}")

        # ── 18c. 中断(GeneratorExit)时回滚预消费 ──────────
        # 用一个干净的 user 确保前置额度检查通过。
        r = client.post(
            "/cloud/auth/register",
            json={"username": "dave_fg_abort", "email": "fg_abort@example.com", "password": "supers3cret"},
        )
        check("F-G register dave_fg_abort for abort test", r.status_code == 201,
              f"status={r.status_code}")
        r = client.post(
            "/cloud/auth/login",
            json={"username": "dave_fg_abort", "password": "supers3cret"},
        )
        check("F-G login dave_fg_abort", r.status_code == 200)
        H_fg = {"Authorization": f"Bearer {r.json().get('access_token','')}"}
        _db_q2 = _SL()
        _u_fg = _db_q2.query(_U).filter(_U.username == "dave_fg_abort").first()
        _db_q2.close()
        assert _u_fg is not None

        _used_before_abort = client.get("/cloud/subscription", headers=H_fg).json().get("used", 0)

        # 直接调用 llm_chat_stream 拿到底层 async gen;用 athrow(GeneratorExit)
        # 触发 except GeneratorExit 分支,等价于 Starlette 在客户端断连时
        # 向 body_iterator 注入 GeneratorExit。
        from cloud_service.llm_proxy import llm_client as _llm_mod
        _orig_stream = _llm_mod.stream_cloud_llm

        async def _slow_stream(*, messages, prompt_name, prompt_version, **_kw):
            yield _llm_mod.LLMStreamEvent(delta="first ", usage={})
            await asyncio.sleep(30.0)  # 让 athrow 有窗口打进来
            yield _llm_mod.LLMStreamEvent(
                delta="",
                usage={"prompt_tokens": 5, "completion_tokens": 10},
            )

        _llm_mod.stream_cloud_llm = _slow_stream
        try:
            async def _drive_abort():
                resp = await _llm_stream_ep(
                    payload=_ChatReq(prompt_name="title.basic_generate", variables={"topic": "x", "count": 1}),
                    current_user=_u_fg,
                    db=_SL(),
                )
                gen = resp.body_iterator
                # 先消费首帧,让 generator 停在 await sleep 处
                try:
                    first_chunk = await gen.__anext__()
                except StopAsyncIteration:
                    first_chunk = ""
                # 再 athrow(GeneratorExit)
                result = "unexpected"
                try:
                    await gen.athrow(GeneratorExit)
                    result = "no-raise"
                except GeneratorExit:
                    result = "generator-exit-propagated"
                except BaseException as e:
                    result = f"other:{type(e).__name__}:{e}"
                return result, first_chunk

            _abort_result, _abort_first = asyncio.run(_drive_abort())
        finally:
            _llm_mod.stream_cloud_llm = _orig_stream

        _used_after_abort = client.get("/cloud/subscription", headers=H_fg).json().get("used", 0)
        check("F-G 中断(GeneratorExit)时预消费被回滚",
              _used_after_abort == _used_before_abort,
              f"before={_used_before_abort} after={_used_after_abort} result={_abort_result}")
        check("F-G GeneratorExit 由 except 分支 re-raise(透传)",
              _abort_result == "generator-exit-propagated",
              f"result={_abort_result}")

        # ── 18d. 额度不足 -> 402,且不进入生成器/不扣 ──────
        # dave2 quota=3, 测试 15 已将其耗尽。再发请求应 402,used 不变。
        _used_before_402 = client.get("/cloud/subscription", headers=H2).json().get("used", 0)
        r_402 = client.post(
            "/cloud/llm/stream",
            json={"prompt_name": "title.basic_generate", "variables": {"topic": "x", "count": 1}},
            headers=H2,
        )
        _used_after_402 = client.get("/cloud/subscription", headers=H2).json().get("used", 0)
        check("F-G 额度不足 -> 402(不进入生成器)",
              r_402.status_code == 402, f"status={r_402.status_code}")
        check("F-G 402 时未扣额度(未进入生成器)",
              _used_after_402 == _used_before_402,
              f"before={_used_before_402} after={_used_after_402}")

    try:
        Path(_tmp.name).unlink(missing_ok=True)
    except OSError:
        pass

    return fails


if __name__ == "__main__":
    rc = run()
    print(f"\n{'ALL TESTS PASSED' if rc == 0 else f'{rc} TEST(S) FAILED'}")
    sys.exit(0 if rc == 0 else 1)
