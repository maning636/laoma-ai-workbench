"""M2 · AI 智能体风格训练后端测试（自运行，不启动服务）。

覆盖：
  1. AgentStore CRUD（add / list / get / remove / replace）
  2. 配额（默认 2 / 可配置 / 删除后释放 / 403 拒绝对超限创建）
  3. LLM 抽取器（注入 mock，验证 style_prompt 生成 + 长度收敛）
  4. 样例解析（str / list / dict 三形态 + 长度截断）
  5. 参数校验（缺 name / 缺 samples / 超长原则 / 超长名字）
  6. JWT 鉴权（M2 hardening 新增）：无 token / 无效 token / 过期 token / type=refresh → 401
  7. M1 集成（`_apply_agent_style` 注入 style_prompt；无效 id 原样返回）
  8. M1 ai_design.generate 端到端（mock provider + mock cloud points）：
       - 带 agent_id 时，实际发给 provider 的 prompt 头部含 "[风格指南"
       - 不带 agent_id 时行为完全一致
  9. 错误处理（LLM 失败 → 502；配额超限 → 403；未知 agent_id → 404）

约定：
  - **完全 mock LLM**：`set_llm_analyzer()` 注入一个同步函数。
  - **完全 mock 存储**：使用 tempfile 隔离 `AgentStore`，不污染真实磁盘。
  - **完全 mock provider**：`ai_design.set_generate_fn` 注入 fake。
  - **完全 mock cloud points**：`PointsClient(transport=MockCloud)`。
  - **JWT 校验**：使用 `fastapi_app.api.dependencies.create_test_access_token`
    签发合法 access token；测试用固定 subject 映射为 user_id。
  - 用例之间隔离：每个用例结束都 reset_store / reset_llm_analyzer。

用法：
  cd prism_backend && python tests/test_m2_agents.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ── sys.path 修正 ────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import jwt as _pyjwt  # PyJWT  # noqa: E402

from fusion_ai import ai_agents  # noqa: E402
from fusion_ai import ai_design  # noqa: E402
from fusion_ai.ai_design import router as ai_design_router  # noqa: E402
from fusion_ai.ai_agents import router as ai_agents_router  # noqa: E402
from fusion_ai.points_client import DEFAULT_AI_IMAGE_POINTS  # noqa: E402
from fastapi_app.api.dependencies import (  # noqa: E402
    create_test_access_token,
)


# ── 测试执行框架 ────────────────────────────────────────────
_FAILS = 0
_PASSES = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global _FAILS, _PASSES
    tag = "PASS" if cond else "FAIL"
    suffix = f" — {extra}" if extra else ""
    print(f"[{tag}] {label}{suffix}")
    if cond:
        _PASSES += 1
    else:
        _FAILS += 1


# ── mock 组件 ────────────────────────────────────────────────


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ai_agents_router)
    app.include_router(ai_design_router)
    return app


def _auth_headers(subject: str) -> Dict[str, str]:
    """构造 Authorization Bearer 头（合法 access token）。"""
    return {"Authorization": f"Bearer {create_test_access_token(subject)}"}


def _invalid_token(kind: str = "garbage") -> str:
    """生成一个无效 token（用于 JWT 校验测试）。"""
    if kind == "expired":
        # 使用合法签名但 exp 在过去
        now = datetime.now(timezone.utc)
        claims = {
            "sub": "u_expired",
            "type": "access",
            "iat": int((now - timedelta(minutes=120)).timestamp()),
            "exp": int((now - timedelta(minutes=60)).timestamp()),
        }
        from fastapi_app.api.dependencies import _jwt_config
        secret, alg = _jwt_config()
        return _pyjwt.encode(claims, secret, algorithm=alg)
    if kind == "refresh":
        # 使用合法签名，type=refresh（应当被拒）
        now = datetime.now(timezone.utc)
        claims = {
            "sub": "u_refresh",
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=60)).timestamp()),
        }
        from fastapi_app.api.dependencies import _jwt_config
        secret, alg = _jwt_config()
        return _pyjwt.encode(claims, secret, algorithm=alg)
    if kind == "nosub":
        # 使用合法签名，但缺 sub claim
        now = datetime.now(timezone.utc)
        claims = {
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=60)).timestamp()),
        }
        from fastapi_app.api.dependencies import _jwt_config
        secret, alg = _jwt_config()
        return _pyjwt.encode(claims, secret, algorithm=alg)
    return "not-a-jwt-string"


class MockCloud:
    """内存版 /cloud/points/* mock（对齐 M1 test）。"""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self._tx_seq = 0

    def __call__(self, method, url, *, headers=None, json=None, timeout=None, **_):
        self.calls.append({"method": method, "url": url, "json": json})
        path = url.split("/cloud/")[-1]
        if method.upper() == "GET" and path == "points/pricing":
            return {"status_code": 200, "data": {"pricingVersion": "mock", "items": [
                {"pricingKey": "aiImageGeneration", "points": DEFAULT_AI_IMAGE_POINTS,
                 "displayName": "AI生图", "category": "ai_design", "enabled": True, "sortOrder": 0},
            ]}}
        if method.upper() == "POST" and path == "points/freeze":
            self._tx_seq += 1
            fid = self._tx_seq
            return {"status_code": 200, "data": {"freezeTxId": fid, "amount": float(json["amount"]),
                                                  "status": "active"}}
        if method.upper() == "POST" and path == "points/consume":
            return {"status_code": 200, "data": {"freezeTxId": json["freeze_tx_id"], "status": "consumed"}}
        if method.upper() == "POST" and path == "points/rollback":
            return {"status_code": 200, "data": {"freezeTxId": json["freeze_tx_id"], "status": "rolled_back"}}
        raise AssertionError(f"unhandled: {method} {url}")


async def _mock_generate(model_def, prompt, size):
    return {"success": True, "url": f"https://mock/img/{abs(hash(prompt)) % 10_000_000}.png"}


def _make_mock_llm(content: str) -> Callable:
    """返回一个同步 LLM 抽取器 mock。"""
    def _fn(samples: List[str], design_principles: str) -> str:
        return content
    return _fn


def _reset_all() -> None:
    ai_agents.reset_store()
    ai_agents.reset_llm_analyzer()
    ai_design.reset_generate_fn()
    ai_design.reset_points_client_provider()


# ── 用例 ─────────────────────────────────────────────────────


def test_agent_store_crud():
    """存储层：add / list / get / remove / replace 完整闭环。"""
    print("\n== test_agent_store_crud ==")
    with tempfile.TemporaryDirectory() as td:
        store = ai_agents.AgentStore(Path(td) / "agents.json")
        uid = "u_crud"

        store.add(uid, {"id": "a1", "name": "Agent 1", "status": "active",
                         "created_at": 1, "updated_at": 1})
        store.add(uid, {"id": "a2", "name": "Agent 2", "status": "active",
                         "created_at": 2, "updated_at": 2})

        rows = store.list(uid)
        check("list 返回 2 条", len(rows) == 2, f"got={len(rows)}")
        # updated_at 倒序
        check("list 按 updated_at 倒序", rows[0]["id"] == "a2", f"got={rows[0]['id']}")

        got = store.get(uid, "a1")
        check("get 命中", got is not None and got["name"] == "Agent 1")
        check("get miss 返回 None", store.get(uid, "nope") is None)

        ok = store.remove(uid, "a1")
        check("remove 成功", ok)
        check("remove 后 list 剩 1 条", len(store.list(uid)) == 1)
        check("软删除后 get 不再命中", store.get(uid, "a1") is None)
        check("重复 remove 返回 False", not store.remove(uid, "a1"))

        res = store.replace(uid, "a2", name="Renamed")
        check("replace 命中并写回", res is not None and res["name"] == "Renamed")
        check("replace 更新 updated_at", res["updated_at"] > 2)
        check("replace 未命中返回 None", store.replace(uid, "nope", name="X") is None)


def test_quota_default_and_release():
    """配额：默认 2；创建 2 个后 403；删除后释放。"""
    print("\n== test_quota_default_and_release ==")
    _reset_all()
    with tempfile.TemporaryDirectory() as td:
        ai_agents.set_store(ai_agents.AgentStore(Path(td) / "agents.json"))
        ai_agents.set_llm_analyzer(_make_mock_llm("[风格指南]\n- Tone: 简洁"))

        client = TestClient(_make_app())
        uid = "u_quota"
        H = _auth_headers(uid)

        r = client.get("/ai-design/agents/quota", headers=H)
        check("初始配额 used=0", r.status_code == 200 and r.json()["used"] == 0, f"{r.status_code} {r.text}")
        check("初始 canCreate=True", r.json()["canCreate"] is True)
        check("默认 limit=2", r.json()["limit"] == 2, f"got={r.json()['limit']}")

        payload = {"name": "A", "sample_contents": ["sample-1"]}
        r1 = client.post("/ai-design/agents", json=payload, headers=H)
        check("第 1 次创建 200", r1.status_code == 200, r1.text[:200])
        r2 = client.post("/ai-design/agents", json={**payload, "name": "B"}, headers=H)
        check("第 2 次创建 200", r2.status_code == 200, r2.text[:200])

        r3 = client.post("/ai-design/agents", json={**payload, "name": "C"}, headers=H)
        check("配额满 → 403", r3.status_code == 403, r3.text[:200])
        detail = r3.json().get("detail", {})
        check("403 detail.code=quota_exceeded",
              isinstance(detail, dict) and detail.get("code") == "quota_exceeded", r3.text)

        q_after = client.get("/ai-design/agents/quota", headers=H).json()
        check("配额满 used=2", q_after["used"] == 2)
        check("配额满 canCreate=False", q_after["canCreate"] is False)

        # 删除后释放
        a2_id = r2.json()["id"]
        dr = client.delete(f"/ai-design/agents/{a2_id}", headers=H)
        check("删除 200", dr.status_code == 200, dr.text[:200])
        check("删除返回 quota.used=1", dr.json().get("quota", {}).get("used") == 1)

        r4 = client.post("/ai-design/agents", json=payload, headers=H)
        check("删除后能再创建", r4.status_code == 200, r4.text[:200])


def test_quota_env_override():
    """配额可被 env CLOUD_AGENT_QUOTA 覆盖。"""
    print("\n== test_quota_env_override ==")
    _reset_all()
    old = os.environ.get("CLOUD_AGENT_QUOTA")
    try:
        os.environ["CLOUD_AGENT_QUOTA"] = "5"
        with tempfile.TemporaryDirectory() as td:
            ai_agents.set_store(ai_agents.AgentStore(Path(td) / "agents.json"))
            r = TestClient(_make_app()).get(
                "/ai-design/agents/quota", headers=_auth_headers("u_env"),
            )
            check("env 覆盖 limit=5", r.json()["limit"] == 5, f"got={r.json()['limit']}")
    finally:
        if old is None:
            os.environ.pop("CLOUD_AGENT_QUOTA", None)
        else:
            os.environ["CLOUD_AGENT_QUOTA"] = old


def test_parse_samples_variants():
    """样例解析：str / list[str] / list[dict] 兼容；长度截断；空值过滤。"""
    print("\n== test_parse_samples_variants ==")
    # str 输入
    r = ai_agents._parse_samples("hello")
    check("str → list[str]", r == ["hello"], f"got={r}")

    # list[str]
    r = ai_agents._parse_samples(["a", "b", "  ", ""])
    check("list 过滤空值", r == ["a", "b"], f"got={r}")

    # list[dict]（澜途格式 {type, url}）
    r = ai_agents._parse_samples([
        {"type": "carousel", "url": "https://x/1.jpg"},
        {"type": "detail", "text": "some detail"},
        {"url": "https://x/2.jpg"},
    ])
    check("list[dict] 解析 3 条", len(r) == 3, f"got={r}")
    check("list[dict] 优先取 text", r[1] == "some detail")
    check("list[dict] 兜底取 url", r[2] == "https://x/2.jpg")

    # 长度截断
    long = "x" * (ai_agents.MAX_SAMPLE_LEN + 100)
    r = ai_agents._parse_samples([long])
    check("超长样例截断", len(r[0]) == ai_agents.MAX_SAMPLE_LEN)

    # 数量上限
    r = ai_agents._parse_samples(["s"] * (ai_agents.MAX_SAMPLES + 5))
    check("样例数上限", len(r) == ai_agents.MAX_SAMPLES, f"got={len(r)}")


def test_validation_errors():
    """参数校验：缺 name / 缺 samples / 超长原则 / 超长名字。"""
    print("\n== test_validation_errors ==")
    _reset_all()
    with tempfile.TemporaryDirectory() as td:
        ai_agents.set_store(ai_agents.AgentStore(Path(td) / "agents.json"))
        ai_agents.set_llm_analyzer(_make_mock_llm("[style]"))
        client = TestClient(_make_app())
        H = _auth_headers("u_val")

        r = client.post("/ai-design/agents", json={"sample_contents": ["s"]}, headers=H)
        check("缺 name → 400", r.status_code == 400, r.text[:200])
        check("缺 name detail", "name" in r.text)

        r = client.post("/ai-design/agents",
                        json={"name": "A", "sample_contents": ""}, headers=H)
        check("缺 samples → 400", r.status_code == 400, r.text[:200])

        r = client.post("/ai-design/agents",
                        json={"name": "A", "sample_contents": "s",
                              "design_principles": "x" * (ai_agents.MAX_DESIGN_PRINCIPLES_LEN + 1)},
                        headers=H)
        check("原则超长 → 400", r.status_code == 400)

        r = client.post("/ai-design/agents",
                        json={"name": "x" * 100, "sample_contents": "s"}, headers=H)
        check("名字超长 → 400", r.status_code == 400)


def test_llm_failure_returns_502():
    """LLM 抽取失败 → 502（不落库）。"""
    print("\n== test_llm_failure_returns_502 ==")
    _reset_all()
    with tempfile.TemporaryDirectory() as td:
        store = ai_agents.AgentStore(Path(td) / "agents.json")
        ai_agents.set_store(store)

        def _boom(samples, dp):
            raise RuntimeError("cloud LLM unreachable")

        ai_agents.set_llm_analyzer(_boom)
        client = TestClient(_make_app())
        uid = "u_llm_fail"

        r = client.post("/ai-design/agents",
                        json={"name": "A", "sample_contents": "s"},
                        headers=_auth_headers(uid))
        check("LLM 失败 → 502", r.status_code == 502, r.text[:200])
        check("LLM 失败未落库", len(store.list(uid)) == 0)


def test_create_and_detail_and_delete():
    """创建/详情/列表/删除完整闭环。"""
    print("\n== test_create_and_detail_and_delete ==")
    _reset_all()
    with tempfile.TemporaryDirectory() as td:
        ai_agents.set_store(ai_agents.AgentStore(Path(td) / "agents.json"))
        ai_agents.set_llm_analyzer(_make_mock_llm("[风格指南]\n- Tone: 简洁、克制\n- Visual: 冷色调"))

        client = TestClient(_make_app())
        uid = "u_full"
        H = _auth_headers(uid)
        H_OTHER = _auth_headers("other_user")

        payload = {
            "name": "冷色调海报",
            "description": "冷色调、极简排版",
            "sample_contents": [
                "标题：新周新品上市\n正文：三款夏日新品已上架，点击了解更多",
                "标题：夏末狂欢\n正文：全场 8 折起",
            ],
            "design_principles": "主色蓝紫 #2D3BFF；字体无衬线；字号 ≤ 24",
        }
        r = client.post("/ai-design/agents", json=payload, headers=H)
        check("创建 200", r.status_code == 200, r.text[:400])
        body = r.json()
        check("响应含 id", body.get("id", "").startswith("agent_"))
        check("响应含 name", body["name"] == "冷色调海报")
        check("响应含 style_prompt（LLM 返回）",
              "风格指南" in body["style_prompt"], body["style_prompt"][:60])
        check("响应含 style_tokens", body["style_tokens"] > 0)
        check("响应含 sample_contents 2 条", len(body["sample_contents"]) == 2)
        check("响应含 design_principles", "主色" in body["design_principles"])
        check("响应含时间戳", body["created_at"] > 0 and body["updated_at"] > 0)

        # 详情
        aid = body["id"]
        r = client.get(f"/ai-design/agents/{aid}", headers=H)
        check("详情 200", r.status_code == 200, r.text[:200])
        check("详情 name 一致", r.json()["name"] == "冷色调海报")

        # 列表
        r = client.get("/ai-design/agents", headers=H)
        check("列表 200", r.status_code == 200)
        check("列表 total=1", r.json()["total"] == 1)
        check("列表含 agent", r.json()["agents"][0]["id"] == aid)
        check("列表 user_id 来自 JWT sub", r.json()["user_id"] == uid)

        # 未知 id → 404
        r = client.get("/ai-design/agents/nope", headers=H)
        check("未知 id 详情 → 404", r.status_code == 404)

        # 跨用户隔离（用不同用户 JWT）
        r = client.get(f"/ai-design/agents/{aid}", headers=H_OTHER)
        check("跨用户访问 → 404", r.status_code == 404)

        # 删除
        r = client.delete(f"/ai-design/agents/{aid}", headers=H)
        check("删除 200", r.status_code == 200, r.text[:200])
        check("删除返回 deleted=true", r.json()["deleted"] is True)
        r = client.get(f"/ai-design/agents/{aid}", headers=H)
        check("删除后详情 → 404", r.status_code == 404)
        r = client.delete(f"/ai-design/agents/{aid}", headers=H)
        check("重复删除 → 404", r.status_code == 404)


def test_jwt_auth_required():
    """M2 hardening：JWT 鉴权行为（严格 401，不降级 anonymous）。"""
    print("\n== test_jwt_auth_required ==")
    _reset_all()
    with tempfile.TemporaryDirectory() as td:
        ai_agents.set_store(ai_agents.AgentStore(Path(td) / "agents.json"))
        ai_agents.set_llm_analyzer(_make_mock_llm("STYLE"))
        client = TestClient(_make_app())

        # 1) 无 Authorization → 401
        r = client.get("/ai-design/agents")
        check("无 token 列表 → 401", r.status_code == 401, r.text[:200])
        check("无 token 401 带 WWW-Authenticate", "Bearer" in r.headers.get("www-authenticate", ""))

        r = client.get("/ai-design/agents/quota")
        check("无 token 配额 → 401", r.status_code == 401)

        r = client.post("/ai-design/agents", json={"name": "A", "sample_contents": "s"})
        check("无 token 创建 → 401", r.status_code == 401)

        # 2) 非法字符串 token → 401
        bad = {"Authorization": f"Bearer {_invalid_token('garbage')}"}
        r = client.get("/ai-design/agents", headers=bad)
        check("非法 token → 401", r.status_code == 401, r.text[:200])

        # 3) 过期 token → 401
        expired = {"Authorization": f"Bearer {_invalid_token('expired')}"}
        r = client.get("/ai-design/agents", headers=expired)
        check("过期 token → 401", r.status_code == 401, r.text[:200])

        # 4) refresh token 当 access token 用 → 401
        refresh = {"Authorization": f"Bearer {_invalid_token('refresh')}"}
        r = client.get("/ai-design/agents", headers=refresh)
        check("refresh token → 401", r.status_code == 401, r.text[:200])

        # 5) 缺 sub claim → 401
        nosub = {"Authorization": f"Bearer {_invalid_token('nosub')}"}
        r = client.get("/ai-design/agents", headers=nosub)
        check("缺 sub claim → 401", r.status_code == 401, r.text[:200])

        # 6) 有效 token → 200 且 user_id 来自 JWT sub
        H = _auth_headers("alice_user")
        r = client.get("/ai-design/agents", headers=H)
        check("有效 token → 200", r.status_code == 200, r.text[:200])
        check("user_id 来自 JWT sub", r.json()["user_id"] == "alice_user")

        # 7) 创建时 user_id 不再来自 body/query（严格以 JWT 为准）
        r = client.post(
            "/ai-design/agents",
            json={"name": "A", "sample_contents": "s", "user_id": "hacker"},
            params={"user_id": "hacker"},
            headers=H,
        )
        check("body/query 伪造 user_id 不影响 → 200", r.status_code == 200, r.text[:200])
        # 列表按 alice_user 查得到
        r = client.get("/ai-design/agents", headers=H)
        check("创建落在 alice_user 名下", r.json()["total"] == 1)
        # hacker 视角查不到
        r = client.get("/ai-design/agents", headers=_auth_headers("hacker"))
        check("hacker 视角查不到", r.status_code == 200 and r.json()["total"] == 0)

        # 8) 不同 JWT subject 配额独立
        Ha = _auth_headers("alice")
        Hb = _auth_headers("bob")
        client.post("/ai-design/agents", json={"name": "A1", "sample_contents": "s"}, headers=Ha)
        client.post("/ai-design/agents", json={"name": "A2", "sample_contents": "s"}, headers=Ha)
        qa = client.get("/ai-design/agents/quota", headers=Ha).json()
        qb = client.get("/ai-design/agents/quota", headers=Hb).json()
        check("alice 配额满 2/2", qa["used"] == 2 and qa["limit"] == 2)
        check("bob 配额独立 0/2", qb["used"] == 0 and qb["canCreate"] is True)
        r = client.post("/ai-design/agents", json={"name": "B1", "sample_contents": "s"}, headers=Hb)
        check("bob 能创建", r.status_code == 200)
        r = client.post("/ai-design/agents", json={"name": "A3", "sample_contents": "s"}, headers=Ha)
        check("alice 再创建 → 403 配额满", r.status_code == 403)


def test_apply_agent_style_injection():
    """M1 集成点 `_apply_agent_style`：注入 / 无效 / 空。"""
    print("\n== test_apply_agent_style_injection ==")
    _reset_all()
    with tempfile.TemporaryDirectory() as td:
        store = ai_agents.AgentStore(Path(td) / "agents.json")
        ai_agents.set_store(store)
        uid = "u_apply"
        store.add(uid, {
            "id": "agent_x", "name": "Test", "status": "active",
            "style_prompt": "Tone: 简洁；Visual: 冷色调",
            "created_at": 1, "updated_at": 1,
        })
        store.add(uid, {
            "id": "agent_empty", "name": "Empty", "status": "active",
            "style_prompt": "",
            "created_at": 1, "updated_at": 1,
        })

        out = ai_agents._apply_agent_style("画一张猫", "agent_x", user_id=uid)
        check("注入成功含前缀", out.startswith("[风格指南: "), out[:80])
        check("注入成功含用户请求", "用户请求: 画一张猫" in out, out)

        out = ai_agents._apply_agent_style("画一张猫", "", user_id=uid)
        check("agent_id 空 → 原样返回", out == "画一张猫")

        out = ai_agents._apply_agent_style("画一张猫", "nope", user_id=uid)
        check("未知 id → 原样返回", out == "画一张猫")

        out = ai_agents._apply_agent_style("画一张猫", "agent_empty", user_id=uid)
        check("style_prompt 空 → 原样返回", out == "画一张猫")

        out = ai_agents._apply_agent_style("画一张猫", "agent_x", user_id="other")
        check("跨用户 → 原样返回", out == "画一张猫")


def test_ai_design_generate_with_agent_id():
    """M1 端到端：agent_id → provider 收到的 prompt 含风格指南。

    注：M1 `ai_design.generate` 仍使用 body/query user_id（M1 未纳入 M2 hardening
    范围），但 M2 agent 创建接口已改为 JWT 校验。为了让端到端能跑通，
    我们让 ai_design 请求的 body `user_id` 与 agent 归属的 JWT sub 保持一致。
    """
    print("\n== test_ai_design_generate_with_agent_id ==")
    _reset_all()
    with tempfile.TemporaryDirectory() as td:
        ai_agents.set_store(ai_agents.AgentStore(Path(td) / "agents.json"))
        ai_agents.set_llm_analyzer(_make_mock_llm("Tone: 简洁；Visual: 冷色调"))

        # mock points
        mock_cloud = MockCloud()
        from fusion_ai.points_client import PointsClient
        pc = PointsClient(transport=mock_cloud, token_provider=lambda: "tok_test")
        ai_design.set_points_client_provider(lambda: pc)

        # mock provider，捕获实际收到的 prompt
        captured_prompts: List[str] = []

        async def _capture_generate(model_def, prompt, size):
            captured_prompts.append(prompt)
            return {"success": True, "url": f"https://mock/{abs(hash(prompt)) % 10_000_000}.png"}

        ai_design.set_generate_fn(_capture_generate)

        client = TestClient(_make_app())
        uid = "u_gen"
        H = _auth_headers(uid)

        # 先创建智能体（现在用 JWT 鉴权）
        r = client.post("/ai-design/agents", json={
            "name": "Test", "sample_contents": "s",
        }, headers=H)
        check("创建智能体 200", r.status_code == 200, r.text[:200])
        aid = r.json()["id"]

        # 带 agent_id 生成（M1 user_id 从 body 取，与 agent 归属一致）
        r = client.post("/ai-design/generate", json={
            "user_id": uid,
            "model_key": "flux-pro",
            "prompt": "画一只猫",
            "agent_id": aid,
            "count": 1,
        })
        check("带 agent_id 生成 200", r.status_code == 200, r.text[:300])
        check("agent_id 透传响应", r.json().get("agent_id") == aid)
        check("provider 收到 1 次调用", len(captured_prompts) == 1, f"got={len(captured_prompts)}")
        sent = captured_prompts[0]
        check("provider 收到 prompt 含风格指南", "[风格指南:" in sent, sent[:120])
        check("provider 收到 prompt 含原始请求", "用户请求: 画一只猫" in sent, sent)
        check("provider 收到 prompt 含 style_prompt 内容", "Tone" in sent, sent)

        # 不带 agent_id：原样透传
        captured_prompts.clear()
        r = client.post("/ai-design/generate", json={
            "user_id": uid,
            "model_key": "flux-pro",
            "prompt": "画一只狗",
            "count": 1,
        })
        check("无 agent_id 生成 200", r.status_code == 200, r.text[:300])
        sent = captured_prompts[0]
        check("无 agent_id 时 prompt 不含风格指南", "[风格指南" not in sent, sent[:120])
        check("无 agent_id 时 prompt 原样", sent == "画一只狗", sent)
        # 无效 agent_id：不阻塞生成，prompt 原样
        captured_prompts.clear()
        r = client.post("/ai-design/generate", json={
            "user_id": uid,
            "model_key": "flux-pro",
            "prompt": "画一只兔子",
            "agent_id": "agent_nonexistent",
            "count": 1,
        })
        check("无效 agent_id 生成 200（不阻塞）", r.status_code == 200, r.text[:300])
        check("无效 agent_id prompt 原样", captured_prompts[0] == "画一只兔子")

        # 跨用户 agent_id：不阻塞生成，prompt 原样
        captured_prompts.clear()
        r = client.post("/ai-design/generate", json={
            "user_id": "other_user",
            "model_key": "flux-pro",
            "prompt": "画一只鸟",
            "agent_id": aid,
            "count": 1,
        })
        check("跨用户 agent_id 生成 200", r.status_code == 200)
        check("跨用户 agent_id prompt 原样", captured_prompts[0] == "画一只鸟")


def test_find_style_prompt_helper():
    """M1 可直接调用的 find_style_prompt。"""
    print("\n== test_find_style_prompt_helper ==")
    _reset_all()
    with tempfile.TemporaryDirectory() as td:
        store = ai_agents.AgentStore(Path(td) / "agents.json")
        ai_agents.set_store(store)
        store.add("u1", {"id": "a1", "status": "active",
                          "style_prompt": "STYLE-A", "created_at": 1, "updated_at": 1})
        store.add("u1", {"id": "a2", "status": "active",
                          "style_prompt": "", "created_at": 1, "updated_at": 1})
        store.add("u2", {"id": "a1", "status": "active",
                          "style_prompt": "STYLE-B", "created_at": 1, "updated_at": 1})

        check("命中返回 style_prompt",
              ai_agents.find_style_prompt("a1", user_id="u1") == "STYLE-A")
        check("跨用户 u2 命中 u2 的 a1",
              ai_agents.find_style_prompt("a1", user_id="u2") == "STYLE-B")
        check("空 style_prompt 返回空串",
              ai_agents.find_style_prompt("a2", user_id="u1") == "")
        check("未知 id 返回空串", ai_agents.find_style_prompt("nope", user_id="u1") == "")
        check("agent_id 空 返回空串", ai_agents.find_style_prompt("", user_id="u1") == "")


def test_query_user_id_no_longer_honored():
    """M2 hardening 后，query ?user_id=xxx 不再被接受。"""
    print("\n== test_query_user_id_no_longer_honored ==")
    _reset_all()
    with tempfile.TemporaryDirectory() as td:
        ai_agents.set_store(ai_agents.AgentStore(Path(td) / "agents.json"))
        ai_agents.set_llm_analyzer(_make_mock_llm("STYLE"))
        client = TestClient(_make_app())

        # 即使带 query user_id，无 token 也 401
        r = client.get("/ai-design/agents", params={"user_id": "anyone"})
        check("query user_id 不绕过 JWT → 401", r.status_code == 401)

        # 有效 token + query user_id（伪造）→ 仍以 JWT sub 为准
        H = _auth_headers("real_user")
        r = client.get("/ai-design/agents", params={"user_id": "hacker"}, headers=H)
        check("query user_id 被忽略，以 JWT 为准",
              r.status_code == 200 and r.json()["user_id"] == "real_user")


# ── main ────────────────────────────────────────────────────


def main() -> int:
    tests = [
        test_agent_store_crud,
        test_quota_default_and_release,
        test_quota_env_override,
        test_parse_samples_variants,
        test_validation_errors,
        test_llm_failure_returns_502,
        test_create_and_detail_and_delete,
        test_jwt_auth_required,
        test_query_user_id_no_longer_honored,
        test_apply_agent_style_injection,
        test_ai_design_generate_with_agent_id,
        test_find_style_prompt_helper,
    ]
    for t in tests:
        try:
            t()
        except Exception as exc:
            import traceback
            print(f"[FAIL] {t.__name__} raised: {exc!r}")
            traceback.print_exc()
            global _FAILS
            _FAILS += 1

    print()
    print(f"=" * 60)
    print(f"M2 backend tests: {_PASSES} PASS / {_FAILS} FAIL (total {_PASSES + _FAILS})")
    print("=" * 60)
    return 0 if _FAILS == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
