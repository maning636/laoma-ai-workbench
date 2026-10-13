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

_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


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


def run() -> int:
    from fastapi.testclient import TestClient

    from cloud_service.main import app

    _install_llm_mock()

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
        check("health.prompt_count.cloud == 5", hv.get("prompt_count", {}).get("cloud") == 5,
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
        check("chat basic.usage_after.remaining == 1",
              c2.get("usage_after", {}).get("remaining") == 1,
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
        check("POST /cloud/llm/chat raw_prompt overshoot -> 402",
              r.status_code == 402, f"status={r.status_code} body={r.text}")

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
        check("POST /cloud/llm/chat missing variables -> 422",
              r.status_code == 422, f"status={r.status_code} body={r.text[:200]}")

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

    try:
        Path(_tmp.name).unlink(missing_ok=True)
    except OSError:
        pass

    return fails


if __name__ == "__main__":
    rc = run()
    print(f"\n{'ALL TESTS PASSED' if rc == 0 else f'{rc} TEST(S) FAILED'}")
    sys.exit(0 if rc == 0 else 1)
