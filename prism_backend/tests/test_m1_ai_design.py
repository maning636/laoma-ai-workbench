"""M1 · AI 生图后端测试（自运行，不启动服务）。

覆盖：
  1. modelKey 路由层（不同 modelKey 路由到不同 provider / 未知报错 / 约束声明）
  2. capabilities 端点返回（澜途格式 + 所有模型都返回）
  3. generate 端点 freeze→consume 成功路径
  4. generate 端点 freeze→rollback 失败路径（全部失败 / 部分失败）
  5. 错误处理（无效 model_key / 积分不足 / 云端不可达 / 约束违反）
  6. points_client 单元（缓存 / 错误分类 / 降级）

约定：
  - **完全 mock provider**：不真的调 NanoBanana/DALL-E/Flux/通义。
  - **完全 mock cloud_service**：不真的调 /cloud/points/* HTTP。
  - 用例之间严格隔离：每次调用 reset_generate_fn / reset_points_client_provider。

用法：
  cd prism_backend && python tests/test_m1_ai_design.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 测试默认跳过云端 feature flag（避免 billing_client 调云端 HTTP 超时卡住）
os.environ.setdefault("FEATURE_FLAGS_DISABLED", "1")
from typing import Any, Callable, Dict, List

# 确保 prism_backend 在 sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from fusion_ai import ai_design  # noqa: E402
from fusion_ai.model_key_registry import (  # noqa: E402
    CAP_IMAGE_GENERATE,
    MODEL_REGISTRY,
    get_provider,
    list_capabilities,
    resolve_size,
    validate_request,
)
from fusion_ai.points_client import (  # noqa: E402
    DEFAULT_AI_IMAGE_POINTS,
    PointsClient,
    PointsCloudClient,
    PointsInsufficient,
)


# ──────────────────────────────────────────────────────────────
# 测试执行框架（对齐 test_c17_subscription_tier.py 风格）
# ──────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────
# Mock cloud_service transport
# ──────────────────────────────────────────────────────────────


class MockCloud:
    """内存版 /cloud/points/* mock。

    记录所有请求，返回契约符合的响应：
      - GET  /points/pricing     → {pricingVersion, items:[{pricingKey, points}]}
      - POST /points/freeze      → {freezeTxId, amount, status:"active", ...}
      - POST /points/consume     → {freezeTxId, consumeTxId, status:"consumed"}
      - POST /points/rollback    → {freezeTxId, consumeTxId, status:"rolled_back"}
    """

    def __init__(self, *, pricing=None, insufficient_after_freeze=None):
        self.pricing = pricing or {"aiImageGeneration": DEFAULT_AI_IMAGE_POINTS}
        self.insufficient_after_freeze = insufficient_after_freeze
        self.calls: List[Dict[str, Any]] = []
        self._tx_seq = 0
        self.frozen: Dict[int, float] = {}
        self.consumed: List[int] = []
        self.rolled: List[int] = []

    def _next_id(self) -> int:
        self._tx_seq += 1
        return self._tx_seq

    def __call__(self, method: str, url: str, *, headers=None, json=None,
                 timeout=None, **_: Any) -> Dict[str, Any]:
        self.calls.append({"method": method, "url": url, "json": json})
        path = url.split("/cloud/")[-1]

        if method.upper() == "GET" and path == "points/pricing":
            items = [{"pricingKey": k, "points": float(v), "displayName": k,
                      "category": "ai_design", "enabled": True, "sortOrder": 0}
                     for k, v in self.pricing.items()]
            return {"status_code": 200, "data": {"pricingVersion": "mock", "items": items}}

        if method.upper() == "POST" and path == "points/freeze":
            if self.insufficient_after_freeze:
                return {"status_code": 402,
                        "data": {"detail": f"积分不足（{self.insufficient_after_freeze}）"}}
            amt = float(json["amount"])
            fid = self._next_id()
            self.frozen[fid] = amt
            return {"status_code": 200, "data": {
                "freezeTxId": fid, "amount": amt,
                "useFunction": json.get("use_function", ""),
                "refId": json.get("ref_id", ""),
                "pricingKey": json.get("pricing_key", ""),
                "status": "active",
                "availablePoints": 0.0, "frozenPoints": amt,
                "createdAt": "2026-10-18T00:00:00Z",
            }}

        if method.upper() == "POST" and path == "points/consume":
            fid = int(json["freeze_tx_id"])
            if fid not in self.frozen:
                return {"status_code": 404, "data": {"detail": "freeze not found"}}
            self.consumed.append(fid)
            return {"status_code": 200, "data": {
                "freezeTxId": fid, "consumeTxId": self._next_id(),
                "amount": self.frozen[fid], "status": "consumed",
                "availablePoints": 0.0, "frozenPoints": 0.0,
                "totalConsumed": self.frozen[fid],
                "createdAt": "2026-10-18T00:00:00Z",
            }}

        if method.upper() == "POST" and path == "points/rollback":
            fid = int(json["freeze_tx_id"])
            if fid not in self.frozen:
                return {"status_code": 404, "data": {"detail": "freeze not found"}}
            self.rolled.append(fid)
            return {"status_code": 200, "data": {
                "freezeTxId": fid, "consumeTxId": self._next_id(),
                "amount": self.frozen[fid], "status": "rolled_back",
                "availablePoints": self.frozen[fid], "frozenPoints": 0.0,
                "totalConsumed": 0.0,
                "createdAt": "2026-10-18T00:00:00Z",
            }}

        return {"status_code": 404, "data": {"detail": f"unknown {method} {path}"}}


class MockProvider:
    """内存版 provider。"""

    def __init__(self, *, success=True, url="https://img.example/1.png", error=None):
        self.success = success
        self.url = url
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, model_def: Dict[str, Any], prompt: str, size: str) -> Dict[str, Any]:
        self.calls.append({
            "model_id": model_def.get("id"),
            "model_name": model_def.get("model_name"),
            "prompt": prompt,
            "size": size,
        })
        if self.success:
            return {"success": True, "url": self.url,
                    "model_id": model_def.get("id"),
                    "name": model_def.get("name", "")}
        return {"success": False, "error": self.error or "mock failure",
                "model_id": model_def.get("id")}


def _make_client(cloud: MockCloud, provider: MockProvider) -> TestClient:
    """构建一个挂载 ai_design.router 的 TestClient，并注入 mock。"""
    pc = PointsClient(base_url="http://cloud.mock",
                      token_provider=lambda: "mock-token",
                      transport=cloud)
    ai_design.reset_generate_fn()
    ai_design.reset_points_client_provider()
    ai_design.set_generate_fn(provider)
    ai_design.set_points_client_provider(lambda: pc)
    app = FastAPI()
    app.include_router(ai_design.router)
    return TestClient(app)


# ──────────────────────────────────────────────────────────────
# 1. modelKey 路由层
# ──────────────────────────────────────────────────────────────


def test_01_registry_has_all_builtin_models():
    keys = {e["modelKey"] for e in MODEL_REGISTRY}
    check("registry 包含 5 个内置 modelKey",
          keys == {"nanobanana", "dall-e-3", "flux-pro", "flux-2-pro", "wanx"},
          str(sorted(keys)))


def test_02_registry_capabilities_only_declare_supported():
    """如实声明：现有 provider 全部只支持 IMAGE_GENERATE，无 IMAGE_EDIT / PRODUCT_ANALYSIS。"""
    ok = True
    problems = []
    for entry in MODEL_REGISTRY:
        if entry["capabilities"] != [CAP_IMAGE_GENERATE]:
            ok = False
            problems.append(f"{entry['modelKey']} capabilities={entry['capabilities']}")
        if entry["maxReferenceImages"] != 0:
            ok = False
            problems.append(f"{entry['modelKey']} maxReferenceImages={entry['maxReferenceImages']}")
        if entry["maxOutputCount"] != 1:
            ok = False
            problems.append(f"{entry['modelKey']} maxOutputCount={entry['maxOutputCount']}")
    check("所有 registry 条目如实声明能力（无伪造）", ok, "; ".join(problems))


def test_03_get_provider_routes_each_model_key():
    expected = {
        "nanobanana": "nano_banana",
        "dall-e-3": "dalle3",
        "flux-pro": "flux_pro",
        "flux-2-pro": "flux_2_pro",
        "wanx": "wanx",
    }
    ok = True
    problems = []
    for key, expected_id in expected.items():
        model_def, entry = get_provider(key)
        if model_def is None or model_def.get("id") != expected_id:
            ok = False
            problems.append(f"{key} → {model_def.get('id') if model_def else None} (expect {expected_id})")
        if entry.get("modelKey") != key:
            ok = False
            problems.append(f"{key} entry.modelKey={entry.get('modelKey')}")
    check("5 个 modelKey 都能正确路由到 provider", ok, "; ".join(problems))


def test_04_get_provider_unknown_key_returns_empty():
    model_def, entry = get_provider("nonexistent-model")
    check("未知 modelKey 返回 (None, {})",
          model_def is None and entry == {})


def test_05_registry_supports_only_truly_supported_aspect_ratios():
    _, wanx = get_provider("wanx")
    _, dalle = get_provider("dall-e-3")
    ok = (wanx["supportedAspectRatios"] == ["3:2"]
          and "1:1" in dalle["supportedAspectRatios"]
          and "16:9" in dalle["supportedAspectRatios"]
          and "9:16" in dalle["supportedAspectRatios"])
    check("wanx 只支持 3:2；dall-e-3 支持 1:1/16:9/9:16", ok)


def test_06_resolve_size_maps_correctly():
    _, wanx = get_provider("wanx")
    _, dalle = get_provider("dall-e-3")
    _, flux = get_provider("flux-pro")
    checks = [
        ("wanx 3:2", resolve_size(wanx, aspect_ratio="3:2"), "1440*960"),
        ("dalle 1:1", resolve_size(dalle, aspect_ratio="1:1"), "1024x1024"),
        ("dalle 16:9", resolve_size(dalle, aspect_ratio="16:9"), "1792x1024"),
        ("dalle 9:16", resolve_size(dalle, aspect_ratio="9:16"), "1024x1792"),
        ("flux 16:9", resolve_size(flux, aspect_ratio="16:9"), "1024x576"),
        ("flux CUSTOM 800x600", resolve_size(flux, aspect_ratio="CUSTOM", width=800, height=600), "800x600"),
    ]
    for label, got, exp in checks:
        check(f"resolve_size: {label}", got == exp, f"got={got!r} expected={exp!r}")


def test_07_validate_request_rejects_unsupported_aspect():
    _, wanx = get_provider("wanx")
    err = validate_request(wanx, aspect_ratio="16:9", count=1, reference_images=[])
    check("wanx 拒绝 16:9（只支持 3:2）",
          err is not None and "3:2" in err, err or "")


def test_08_validate_request_rejects_reference_images():
    _, dalle = get_provider("dall-e-3")
    err = validate_request(dalle, aspect_ratio="1:1", count=1,
                           reference_images=["https://ref.example/x.jpg"])
    check("dall-e-3 拒绝参考图（maxReferenceImages=0）",
          err is not None and "参考图" in err, err or "")


def test_09_validate_request_rejects_unimplemented_capability():
    _, dalle = get_provider("dall-e-3")
    err = validate_request(dalle, aspect_ratio="1:1", count=1, reference_images=[],
                           capability="IMAGE_EDIT")
    check("IMAGE_EDIT 未实现时拒绝调用", err is not None, err or "")


# ──────────────────────────────────────────────────────────────
# 2. capabilities 端点
# ──────────────────────────────────────────────────────────────


def test_10_capabilities_returns_all_models():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)

    resp = tc.get("/ai-design/capabilities")
    ok = resp.status_code == 200
    check("GET /ai-design/capabilities → 200", ok, str(resp.status_code))
    if not ok:
        return
    data = resp.json()
    keys = {m["modelKey"] for m in data["models"]}
    check("capabilities 返回所有内置 modelKey",
          keys >= {"nanobanana", "dall-e-3", "flux-pro", "flux-2-pro", "wanx"},
          str(sorted(keys)))

    ok = all(
        "displayName" in m and "capabilities" in m
        and "supportedAspectRatios" in m and "maxOutputCount" in m
        and "maxReferenceImages" in m and "_model_id" not in m
        for m in data["models"]
    )
    check("每个 model 都含必要字段且不暴露 _model_id", ok)


def test_11_capabilities_shape_matches_lantyou():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)
    resp = tc.get("/ai-design/capabilities")
    required = {"modelKey", "displayName", "capabilities",
                "supportedAspectRatios", "maxOutputCount",
                "maxReferenceImages", "supportedInputMediaTypes"}
    missing = [(m.get("modelKey"), sorted(required - set(m.keys())))
               for m in resp.json()["models"]
               if not required.issubset(m.keys())]
    check("所有 model 字段与澜途审计 §3.1 对齐", not missing, str(missing[:3]))


# ──────────────────────────────────────────────────────────────
# 3. generate：freeze → consume 成功
# ──────────────────────────────────────────────────────────────


def test_12_generate_success_calls_freeze_then_consume():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)

    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3",
        "prompt": "a red apple on white background",
        "aspect_ratio": "1:1",
        "count": 1,
    })
    check("POST /generate 成功 → 200", resp.status_code == 200, resp.text[:200])
    if resp.status_code != 200:
        return
    data = resp.json()
    check("响应包含 image url", data["images"] == ["https://img.example/1.png"])
    check("points.status == consumed", data["points"]["status"] == "consumed",
          data["points"])
    check("points.unit == 1.5", abs(data["points"]["unit"] - 1.5) < 1e-6, str(data["points"]))
    check("points.total == 1.5", abs(data["points"]["total"] - 1.5) < 1e-6, str(data["points"]))

    check("provider 被调 1 次", len(prov.calls) == 1)
    check("provider 收到正确 model_id", prov.calls[0]["model_id"] == "dalle3")
    check("provider 收到正确 size", prov.calls[0]["size"] == "1024x1024")

    methods = [(c["method"], c["url"].split("/cloud/")[-1]) for c in cloud.calls]
    check("M3 收到 pricing GET", ("GET", "points/pricing") in methods, str(methods))
    check("M3 收到 freeze POST", ("POST", "points/freeze") in methods)
    check("M3 收到 consume POST", ("POST", "points/consume") in methods)
    check("M3 consume 成功 1 次", len(cloud.consumed) == 1)


def test_13_generate_multi_count_calls_provider_n_times_and_freezes_total():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)
    resp = tc.post("/ai-design/generate", json={
        "model_key": "flux-pro",
        "prompt": "cyberpunk city",
        "aspect_ratio": "16:9",
        "count": 3,
    })
    check("count=3 生成 → 200", resp.status_code == 200, resp.text[:200])
    if resp.status_code != 200:
        return
    data = resp.json()
    check("count=3 → 返回 3 张图", len(data["images"]) == 3, str(data["images"]))
    check("count=3 → total 积分为 4.5", abs(data["points"]["total"] - 4.5) < 1e-6,
          str(data["points"]))
    check("provider 被调 3 次", len(prov.calls) == 3)
    freeze_call = [c for c in cloud.calls if c["url"].endswith("points/freeze")][0]
    check("freeze 金额 = 4.5", abs(freeze_call["json"]["amount"] - 4.5) < 1e-6,
          str(freeze_call["json"]["amount"]))
    check("freeze pricing_key = aiImageGeneration",
          freeze_call["json"]["pricing_key"] == "aiImageGeneration")
    check("freeze use_function = AI设计中心",
          freeze_call["json"]["use_function"] == "AI设计中心")


def test_14_generate_ref_id_is_task_id():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)
    resp = tc.post("/ai-design/generate", json={
        "model_key": "nanobanana",
        "prompt": "cat",
        "aspect_ratio": "1:1",
        "count": 1,
    })
    check("count=1 单张 → 200", resp.status_code == 200, resp.text[:200])
    if resp.status_code != 200:
        return
    task_id = resp.json()["task_id"]
    freeze_call = [c for c in cloud.calls if c["url"].endswith("points/freeze")][0]
    check("freeze ref_id 与响应 task_id 一致",
          freeze_call["json"]["ref_id"] == task_id)


# ──────────────────────────────────────────────────────────────
# 4. generate：freeze → rollback（失败路径）
# ──────────────────────────────────────────────────────────────


def test_15_generate_provider_failure_triggers_rollback():
    cloud = MockCloud()
    prov = MockProvider(success=False, error="quota exceeded")
    tc = _make_client(cloud, prov)

    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3",
        "prompt": "test",
        "aspect_ratio": "1:1",
        "count": 1,
    })
    check("provider 失败 → 502", resp.status_code == 502, resp.text[:200])
    detail = resp.json().get("detail", "") if resp.status_code == 502 else ""
    check("502 detail 提示已回滚", "回滚" in detail, detail)
    check("M3 rollback 成功 1 次", len(cloud.rolled) == 1)
    check("M3 consume 0 次", len(cloud.consumed) == 0)


def test_16_generate_partial_failure_also_rolls_back():
    cloud = MockCloud()

    async def flaky(model_def, prompt, size):
        call_id = MockProvider()  # 用不到；仅触发一次调用计数
        # 用全局计数器
        flaky.n += 1
        if flaky.n == 1:
            return {"success": True, "url": "https://img.example/1.png"}
        return {"success": False, "error": "provider failed on 2nd call"}
    flaky.n = 0

    ai_design.reset_generate_fn()
    ai_design.reset_points_client_provider()
    ai_design.set_generate_fn(flaky)
    ai_design.set_points_client_provider(
        lambda: PointsClient(base_url="http://cloud.mock",
                             token_provider=lambda: "t", transport=cloud))
    app = FastAPI()
    app.include_router(ai_design.router)
    tc = TestClient(app)

    resp = tc.post("/ai-design/generate", json={
        "model_key": "flux-pro",
        "prompt": "test",
        "count": 2,
    })
    check("部分失败 → 502", resp.status_code == 502, resp.text[:200])
    check("部分失败 → M3 rollback 1 次", len(cloud.rolled) == 1)
    check("部分失败 → M3 consume 0 次", len(cloud.consumed) == 0)


# ──────────────────────────────────────────────────────────────
# 5. 错误处理
# ──────────────────────────────────────────────────────────────


def test_17_generate_unknown_model_key_returns_404():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)
    resp = tc.post("/ai-design/generate", json={
        "model_key": "gpt-image-999",
        "prompt": "test",
    })
    check("未知 modelKey → 404", resp.status_code == 404, resp.text[:200])
    check("未知 modelKey → 未调 M3", cloud.calls == [])
    check("未知 modelKey → 未调 provider", prov.calls == [])


def test_18_generate_insufficient_points_returns_402():
    cloud = MockCloud(insufficient_after_freeze="balance < 1.5")
    prov = MockProvider()
    tc = _make_client(cloud, prov)
    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3",
        "prompt": "test",
        "count": 1,
    })
    check("积分不足 → 402", resp.status_code == 402, resp.text[:200])
    detail = resp.json().get("detail", "") if resp.status_code == 402 else ""
    check("402 detail 提示积分不足", "积分不足" in detail, detail)
    check("402 → 未调 provider", prov.calls == [])


def test_19_generate_cloud_unreachable_returns_503():
    def fail(*a, **kw):
        raise RuntimeError("connection refused")

    pc = PointsClient(base_url="http://cloud.mock",
                      token_provider=lambda: "t", transport=fail)
    ai_design.reset_generate_fn()
    ai_design.reset_points_client_provider()
    ai_design.set_generate_fn(MockProvider())
    ai_design.set_points_client_provider(lambda: pc)

    app = FastAPI()
    app.include_router(ai_design.router)
    tc = TestClient(app)
    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3",
        "prompt": "test",
        "count": 1,
    })
    check("云端不可达 → 503", resp.status_code == 503, resp.text[:200])
    detail = resp.json().get("detail", "") if resp.status_code == 503 else ""
    check("503 detail 提示积分服务不可用", "积分服务不可用" in detail, detail)


def test_20_generate_invalid_aspect_ratio_returns_400():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)
    resp = tc.post("/ai-design/generate", json={
        "model_key": "wanx",
        "prompt": "test",
        "aspect_ratio": "16:9",
    })
    check("wanx 请求 16:9 → 400", resp.status_code == 400, resp.text[:200])
    detail = resp.json().get("detail", "") if resp.status_code == 400 else ""
    check("400 detail 提示支持的宽高比", "3:2" in detail, detail)
    check("约束违反 → 未调 M3", cloud.calls == [])


def test_21_generate_reference_images_returns_400():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)
    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3",
        "prompt": "test",
        "reference_images": ["https://example.com/ref.jpg"],
    })
    check("传参考图 → 400", resp.status_code == 400, resp.text[:200])
    detail = resp.json().get("detail", "") if resp.status_code == 400 else ""
    check("400 detail 提示参考图限制", "参考图" in detail, detail)


def test_22_generate_missing_model_key_returns_400():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)
    resp = tc.post("/ai-design/generate", json={"prompt": "test"})
    check("缺 model_key → 400", resp.status_code == 400, resp.text[:200])
    check("400 detail 提及 model_key", "model_key" in resp.json().get("detail", ""))


def test_23_generate_missing_prompt_returns_400():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)
    resp = tc.post("/ai-design/generate", json={"model_key": "dall-e-3"})
    check("缺 prompt → 400", resp.status_code == 400, resp.text[:200])
    check("400 detail 提及 prompt", "prompt" in resp.json().get("detail", ""))


def test_24_generate_passes_agent_id_through():
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client(cloud, prov)
    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3",
        "prompt": "test",
        "agent_id": "agent_abc",
    })
    check("agent_id 透传", resp.status_code == 200
          and resp.json().get("agent_id") == "agent_abc")


# ──────────────────────────────────────────────────────────────
# 6. points_client 单元
# ──────────────────────────────────────────────────────────────


def test_25_points_client_get_pricing_uses_cache():
    cloud = MockCloud(pricing={"aiImageGeneration": 2.0})
    pc = PointsClient(base_url="http://cloud.mock",
                      token_provider=lambda: "t", transport=cloud)

    p1 = pc.get_pricing()
    p2 = pc.get_pricing()
    pricing_calls = [c for c in cloud.calls if c["url"].endswith("points/pricing")]
    check("get_pricing 缓存命中（第二次不发 HTTP）", len(pricing_calls) == 1,
          str(len(pricing_calls)))
    check("缓存前后返回一致", p1 == p2)
    check("points_for_ai_image 从缓存取值", abs(pc.points_for_ai_image() - 2.0) < 1e-6)


def test_26_points_client_freeze_raises_on_402():
    cloud = MockCloud(insufficient_after_freeze="not enough")
    pc = PointsClient(base_url="http://cloud.mock",
                      token_provider=lambda: "t", transport=cloud)
    try:
        pc.freeze(amount=100.0, ref_id="gen_x", use_function="AI设计中心")
        check("freeze 402 → PointsInsufficient", False, "未抛异常")
    except PointsInsufficient as e:
        check("freeze 402 → PointsInsufficient", e.status == 402, f"status={e.status}")
    except Exception as e:
        check("freeze 402 → PointsInsufficient", False, f"抛了错误类型 {type(e).__name__}: {e}")


def test_27_points_client_consume_swallows_failure():
    cloud = MockCloud()
    # 先手动触发一次 freeze 拿到 fid（用于对比）
    freeze = cloud("POST", "http://cloud.mock/cloud/points/freeze",
                   json={"amount": 1.5, "use_function": "AI设计中心",
                         "ref_id": "gen_x", "pricing_key": "aiImageGeneration"})
    _ = freeze["data"]["freezeTxId"]

    pc = PointsClient(base_url="http://cloud.mock",
                      token_provider=lambda: "t", transport=cloud)
    # 传入不存在的 freeze_tx_id → 404 → 应被 swallow
    res = pc.consume(freeze_tx_id=9999, note="test")
    check("consume 失败不抛", isinstance(res, dict))
    check("consume 失败返回 ok=False", res.get("ok") is False, str(res))
    check("consume 失败回传 freeze_tx_id", res.get("freeze_tx_id") == 9999, str(res))


def test_28_points_client_rollback_swallows_failure():
    cloud = MockCloud()
    pc = PointsClient(base_url="http://cloud.mock",
                      token_provider=lambda: "t", transport=cloud)
    res = pc.rollback(freeze_tx_id=9999, note="test")
    check("rollback 失败不抛", isinstance(res, dict))
    check("rollback 失败返回 ok=False", res.get("ok") is False, str(res))


def test_29_points_client_points_for_ai_image_fallback_on_cloud_error():
    def fail(*a, **kw):
        raise RuntimeError("cloud down")
    pc = PointsClient(base_url="http://cloud.mock",
                      token_provider=lambda: "t", transport=fail)
    val = pc.points_for_ai_image()
    check("云端不可达 → points_for_ai_image 降级到默认 1.5",
          abs(val - DEFAULT_AI_IMAGE_POINTS) < 1e-6, str(val))


# ──────────────────────────────────────────────────────────────
# 7. 幂等性（M1 hardening）
# ──────────────────────────────────────────────────────────────


def _make_client_with_isolation(cloud: MockCloud, provider: MockProvider, *,
                                drop_db: bool = True):
    """每次调用都重置幂等/DB/retry 状态，保证用例之间隔离。

    drop_db=False 用于同一测试内需要累积 DB 记录的阶段（如 test_41 先造成功再失败）。
    """
    from fusion_ai import consume_retry, idempotency, image_gen_models
    idempotency.force_memory_backend()
    idempotency.clear_cache()
    consume_retry.force_memory_store()
    consume_retry.clear_all_pending()
    if drop_db:
        # SQLite 表跨用例累积（尤其是 idempotency_key 反查、records 分页等直接查表），
        # 必须 DROP+recreate 保证每个 DB 相关用例看到干净状态。
        image_gen_models.drop_table_for_test()
    else:
        image_gen_models.reset_ensured()
    tc = _make_client(cloud, provider)
    return tc


def test_30_idempotency_same_key_returns_cached_result():
    """同一 idempotency_key 重复请求 → 第二次直接返回缓存，不再 freeze。"""
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client_with_isolation(cloud, prov)

    key = "idem-test-001"
    resp1 = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test", "count": 1,
        "idempotency_key": key,
    })
    check("首次带 idempotency_key → 200", resp1.status_code == 200, resp1.text[:200])
    if resp1.status_code != 200:
        return
    d1 = resp1.json()

    resp2 = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test", "count": 1,
        "idempotency_key": key,
    })
    check("重复同 key → 200（缓存返回）", resp2.status_code == 200, resp2.text[:200])
    d2 = resp2.json()
    check("重复同 key → task_id 一致", d1["task_id"] == d2["task_id"])
    check("重复同 key → images 一致", d1["images"] == d2["images"])
    check("重复同 key → provider 仅被调 1 次", len(prov.calls) == 1, str(len(prov.calls)))

    freeze_calls = [c for c in cloud.calls if c["url"].endswith("points/freeze")]
    consume_calls = [c for c in cloud.calls if c["url"].endswith("points/consume")]
    check("重复同 key → freeze 仅调 1 次", len(freeze_calls) == 1, str(len(freeze_calls)))
    check("重复同 key → consume 仅调 1 次", len(consume_calls) == 1, str(len(consume_calls)))


def test_31_idempotency_different_key_does_not_dedupe():
    """不同 idempotency_key → 视为独立请求。"""
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client_with_isolation(cloud, prov)

    resp1 = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test", "idempotency_key": "k1",
    })
    resp2 = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test", "idempotency_key": "k2",
    })
    check("不同 key 都返回 200",
          resp1.status_code == 200 and resp2.status_code == 200)
    check("不同 key 生成两张不同 task_id",
          resp1.json()["task_id"] != resp2.json()["task_id"])
    check("不同 key 都调 provider", len(prov.calls) == 2, str(len(prov.calls)))


def test_32_idempotency_same_key_different_user_not_deduped():
    """幂等键作用域是 (user_id, key)，不同用户不冲突。"""
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client_with_isolation(cloud, prov)

    r1 = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test",
        "idempotency_key": "shared", "user_id": "alice",
    })
    r2 = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test",
        "idempotency_key": "shared", "user_id": "bob",
    })
    check("两个用户各自 200", r1.status_code == 200 and r2.status_code == 200)
    check("两个用户 task_id 不同",
          r1.json()["task_id"] != r2.json()["task_id"])
    check("两个用户各 freeze 一次",
          len([c for c in cloud.calls if c["url"].endswith("points/freeze")]) == 2)


def test_33_no_idempotency_key_backward_compatible():
    """不传 idempotency_key → 走完整流程（向后兼容）。"""
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client_with_isolation(cloud, prov)

    resp1 = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test",
    })
    resp2 = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test",
    })
    check("无 idempotency_key 两次都 200",
          resp1.status_code == 200 and resp2.status_code == 200)
    check("无 idempotency_key 两次 freeze",
          len([c for c in cloud.calls if c["url"].endswith("points/freeze")]) == 2)
    check("无 idempotency_key 不写缓存（provider 2 次）", len(prov.calls) == 2)


def test_34_idempotency_failed_request_is_cached():
    """失败也写幂等缓存：同一 key 的后续请求不再重复 freeze。"""
    cloud = MockCloud()
    prov = MockProvider(success=False, error="quota exceeded")
    tc = _make_client_with_isolation(cloud, prov)

    key = "idem-fail-001"
    r1 = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test", "idempotency_key": key,
    })
    check("失败首次 → 502", r1.status_code == 502, r1.text[:200])

    r2 = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test", "idempotency_key": key,
    })
    check("失败重复 → 仍返回 502（缓存）", r2.status_code == 502)
    check("失败重复 → 不再 freeze（1 次）",
          len([c for c in cloud.calls if c["url"].endswith("points/freeze")]) == 1)


# ──────────────────────────────────────────────────────────────
# 8. consume_pending 重试（M1 hardening）
# ──────────────────────────────────────────────────────────────


def _make_cloud_with_consume_failure_once():
    """MockCloud 包装：首次 consume 返回 503（失败），后续成功。"""
    state = {"consume_attempts": 0, "freeze_seq": 0, "frozen": {}}

    class PatchedCloud(MockCloud):
        def __init__(self):
            super().__init__()
            self.state = state

        def __call__(self, method, url, *, headers=None, json=None, timeout=None, **kw):
            path = url.split("/cloud/")[-1]
            if method.upper() == "POST" and path == "points/consume":
                state["consume_attempts"] += 1
                fid = int(json["freeze_tx_id"])
                if state["consume_attempts"] == 1:
                    return {"status_code": 503, "data": {"detail": "cloud points down"}}
                if fid in state["frozen"]:
                    state["frozen"].pop(fid, None)
                    return {"status_code": 200, "data": {
                        "freezeTxId": fid, "consumeTxId": fid, "amount": 1.5,
                        "status": "consumed",
                    }}
                return {"status_code": 404, "data": {"detail": "freeze not found"}}
            # 记录所有调用（含 freeze）便于断言
            self.calls.append({"method": method, "url": url, "json": json})
            if method.upper() == "POST" and path == "points/freeze":
                state["freeze_seq"] += 1
                fid = state["freeze_seq"]
                state["frozen"][fid] = float(json["amount"])
                return {"status_code": 200, "data": {
                    "freezeTxId": fid, "amount": float(json["amount"]),
                    "useFunction": json.get("use_function", ""),
                    "refId": json.get("ref_id", ""),
                    "pricingKey": json.get("pricing_key", ""),
                    "status": "active",
                    "availablePoints": 0.0,
                    "frozenPoints": float(json["amount"]),
                    "createdAt": "2026-10-18T00:00:00Z",
                }}
            # 其它（GET pricing 等）走原逻辑
            return super().__call__(method, url, headers=headers, json=json,
                                    timeout=timeout, **kw)

    return PatchedCloud(), state


def test_35_consume_failure_records_pending():
    """consume 失败 → 生成仍返回 200（用户已拿到图），但记录 pending。"""
    from fusion_ai import consume_retry
    cloud, state = _make_cloud_with_consume_failure_once()
    tc = _make_client_with_isolation(cloud, MockProvider())

    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test", "count": 1,
        "user_id": "alice",
    })
    check("consume 失败 → 仍 200", resp.status_code == 200, resp.text[:200])
    if resp.status_code != 200:
        return
    points = resp.json()["points"]
    check("consume 失败 → points.status == consumed_consume_pending",
          points["status"] == "consumed_consume_pending", str(points))

    pending = consume_retry.pending_list()
    check("consume 失败 → pending_list 有 1 条", len(pending) == 1, str(pending))
    if pending:
        check("pending 记录 freeze_tx_id",
              int(pending[0]["freeze_tx_id"]) == int(points["freeze_tx_id"]))
        check("pending 记录 user_id", pending[0]["user_id"] == "alice")


def test_36_retry_pending_retries_and_clears():
    """重试 pending：consume 成功 → 清 pending；attempts 递增。"""
    from fusion_ai import consume_retry

    class RetryPC:
        def __init__(self):
            self.fail_first = True
        def consume(self, tx, note=None):
            if self.fail_first:
                self.fail_first = False
                return {"ok": False, "error": "first try failed"}
            return {"ok": True, "freezeTxId": tx}

    consume_retry.force_memory_store()
    consume_retry.clear_all_pending()
    consume_retry.record_pending(42, user_id="u1", amount=1.5,
                                 task_id="t1", model_key="dall-e-3")

    pc = RetryPC()
    stats1 = consume_retry.retry_pending(points_client=pc)
    check("首次重试失败 → pending 仍存在", len(consume_retry.pending_list()) == 1)
    check("首次重试失败 → attempts 变为 1",
          consume_retry.pending_list()[0]["attempts"] == 1)

    stats2 = consume_retry.retry_pending(points_client=pc)
    check("第二次重试成功 → pending 清空", len(consume_retry.pending_list()) == 0)
    check("第二次重试成功 → stats.success 含 tx",
          42 in stats2["success"], str(stats2))


def test_37_retry_pending_max_attempts_keeps_pending():
    """超过重试上限 → 保留 pending + 停止重试（供人工介入）。"""
    from fusion_ai import consume_retry

    class AlwaysFailPC:
        def consume(self, tx, note=None):
            return {"ok": False, "error": "cloud still down"}

    consume_retry.force_memory_store()
    consume_retry.clear_all_pending()
    consume_retry.record_pending(77, user_id="u2", amount=2.0)

    pc = AlwaysFailPC()
    for _ in range(6):
        consume_retry.retry_pending(points_client=pc, max_attempts=3)

    pending = consume_retry.pending_list()
    check("超限后 pending 仍存在（供人工介入）", len(pending) == 1)
    check("超限后 attempts 停在 3",
          pending[0]["attempts"] == 3, str(pending[0]["attempts"]))


# ──────────────────────────────────────────────────────────────
# 9. image_generations 表 + records 端点
# ──────────────────────────────────────────────────────────────


def test_38_generate_writes_success_record_to_db():
    """成功路径 → image_generations 表写入 success 记录。"""
    from fusion_ai import image_gen_models
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client_with_isolation(cloud, prov)

    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "a red apple",
        "aspect_ratio": "1:1", "count": 1,
        "user_id": "alice",
    })
    check("生成 → 200", resp.status_code == 200, resp.text[:200])
    if resp.status_code != 200:
        return
    record_id = resp.json().get("record_id")
    check("响应含 record_id", record_id is not None and record_id > 0,
          str(record_id))

    listing = image_gen_models.list_records(user_id="alice", current=1, size=10)
    check("DB 有 1 条记录", listing["total"] == 1, str(listing))
    if listing["records"]:
        rec = listing["records"][0]
        check("DB 记录 status == success", rec["status"] == "success")
        check("DB 记录 model_key == dall-e-3", rec["model_key"] == "dall-e-3")
        check("DB 记录 points_cost == 1.5",
              abs(float(rec["points_cost"]) - 1.5) < 1e-6, str(rec["points_cost"]))
        check("DB 记录 images 解析为列表",
              isinstance(rec["images"], list) and len(rec["images"]) == 1)
        check("DB 记录 freeze_tx_id 非空", rec["freeze_tx_id"] is not None)


def test_39_generate_writes_failed_record_to_db():
    """失败路径 → image_generations 表写入 failed 记录 + error_message。"""
    from fusion_ai import image_gen_models
    cloud = MockCloud()
    prov = MockProvider(success=False, error="provider down")
    tc = _make_client_with_isolation(cloud, prov)

    resp = tc.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "test", "user_id": "bob",
    })
    check("失败 → 502", resp.status_code == 502, resp.text[:200])

    listing = image_gen_models.list_records(user_id="bob", current=1, size=10)
    check("DB 有 1 条 failed 记录", listing["total"] == 1, str(listing))
    if listing["records"]:
        rec = listing["records"][0]
        check("failed 记录 status == failed", rec["status"] == "failed")
        check("failed 记录 error_message 非空", bool(rec["error_message"]))
        check("failed 记录 error_message 含 '回滚'",
              "回滚" in rec["error_message"], str(rec["error_message"]))


def test_40_records_endpoint_paginates():
    """GET /ai-design/records 分页查询。"""
    from fusion_ai import image_gen_models
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client_with_isolation(cloud, prov)

    # 造 5 条记录（不同 idempotency_key 避免幂等去重）
    for i in range(5):
        r = tc.post("/ai-design/generate", json={
            "model_key": "dall-e-3", "prompt": f"prompt-{i}",
            "user_id": "carol",
            "idempotency_key": f"rec-{i}",
        })
        assert r.status_code == 200, r.text

    resp = tc.get("/ai-design/records", params={"user_id": "carol", "current": 1, "size": 2})
    check("records 端点 → 200", resp.status_code == 200, resp.text[:200])
    if resp.status_code != 200:
        return
    data = resp.json()
    check("total == 5", data["total"] == 5, str(data["total"]))
    check("current == 1", data["current"] == 1)
    check("size == 2", data["size"] == 2)
    check("第一页返回 2 条", len(data["records"]) == 2, str(len(data["records"])))

    resp2 = tc.get("/ai-design/records", params={"user_id": "carol", "current": 3, "size": 2})
    check("第三页返回 1 条", len(resp2.json()["records"]) == 1,
          str(len(resp2.json()["records"])))


def test_41_records_endpoint_status_filter():
    """records 端点支持 status 过滤。"""
    from fusion_ai import image_gen_models
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client_with_isolation(cloud, prov)

    # 3 张成功（不同 key 避免去重）
    for i in range(3):
        r = tc.post("/ai-design/generate", json={
            "model_key": "dall-e-3", "prompt": "p", "user_id": "dave",
            "idempotency_key": f"succ-{i}",
        })
        assert r.status_code == 200

    # 1 条失败（保留之前 3 条成功记录，不清 DB）
    cloud2 = MockCloud()
    prov_fail = MockProvider(success=False, error="nope")
    tc2 = _make_client_with_isolation(cloud2, prov_fail, drop_db=False)
    r2 = tc2.post("/ai-design/generate", json={
        "model_key": "dall-e-3", "prompt": "p", "user_id": "dave",
        "idempotency_key": "fail",
    })
    assert r2.status_code == 502

    listing_ok = image_gen_models.list_records(user_id="dave", status="success")
    listing_fail = image_gen_models.list_records(user_id="dave", status="failed")
    check("status=success 过滤正确",
          listing_ok["total"] >= 3, str(listing_ok["total"]))
    check("status=failed 过滤正确",
          listing_fail["total"] >= 1, str(listing_fail["total"]))


def test_42_records_idempotency_key_persisted():
    """记录里保存 idempotency_key，便于幂等反查。"""
    from fusion_ai import image_gen_models
    cloud, prov = MockCloud(), MockProvider()
    tc = _make_client_with_isolation(cloud, prov)

    tc.post("/ai-design/generate", json={
        "model_key": "flux-pro", "prompt": "test",
        "user_id": "eve", "idempotency_key": "my-key-123",
    })

    rec = image_gen_models.get_by_idempotency("eve", "my-key-123")
    check("按 idempotency_key 可反查", rec is not None)
    if rec:
        check("反查记录 idempotency_key 一致",
              rec["idempotency_key"] == "my-key-123")
        check("反查记录 status == success", rec["status"] == "success")


# ──────────────────────────────────────────────────────────────
# 10. idempotency / consume_retry 单元
# ──────────────────────────────────────────────────────────────


def test_43_idempotency_module_direct_api():
    """直接调 idempotency 模块的 acquire/complete/fail API。"""
    from fusion_ai import idempotency
    idempotency.force_memory_backend()
    idempotency.clear_cache()

    acq1 = idempotency.acquire("u1", "k1")
    check("首次 acquire → not seen_before", not acq1.seen_before)
    check("首次 acquire → not in_flight", not acq1.in_flight)

    acq2 = idempotency.acquire("u1", "k1")
    check("第二次 acquire → seen_before", acq2.seen_before)
    check("第二次 acquire → in_flight=True", acq2.in_flight)

    idempotency.complete("u1", "k1", {"images": ["a"], "task_id": "t1"})
    acq3 = idempotency.acquire("u1", "k1")
    check("完成后 acquire → seen_before", acq3.seen_before)
    check("完成后 acquire → cached_result 非空", acq3.cached_result is not None)
    check("完成后 acquire → cached_result 正确",
          acq3.cached_result == {"images": ["a"], "task_id": "t1"})

    idempotency.fail("u2", "k2", {"status": 500, "detail": "boom"})
    acq4 = idempotency.acquire("u2", "k2")
    check("失败后 acquire → cached_error 非空", acq4.cached_error is not None)
    check("失败后 acquire → cached_error.status == 500",
          acq4.cached_error["status"] == 500)


def test_44_consume_retry_pending_list_shape():
    """consume_retry.pending_list 返回结构正确的 dict 列表。"""
    from fusion_ai import consume_retry
    consume_retry.force_memory_store()
    consume_retry.clear_all_pending()

    consume_retry.record_pending(101, user_id="u1", amount=1.5,
                                 task_id="t1", model_key="dall-e-3")
    consume_retry.record_pending(102, user_id="u2", amount=3.0,
                                 task_id="t2", model_key="flux-pro")

    lst = consume_retry.pending_list()
    check("pending_list 有 2 条", len(lst) == 2, str(lst))
    fields = {"freeze_tx_id", "user_id", "amount", "task_id", "model_key"}
    ok = all(fields.issubset(x.keys()) for x in lst)
    check("pending_list 每条含必要字段", ok, str(lst))
    consume_retry.clear_pending(101)
    check("clear_pending 后剩 1 条", len(consume_retry.pending_list()) == 1)


# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────


def main() -> int:
    tests = [
        # 1. modelKey 路由层
        test_01_registry_has_all_builtin_models,
        test_02_registry_capabilities_only_declare_supported,
        test_03_get_provider_routes_each_model_key,
        test_04_get_provider_unknown_key_returns_empty,
        test_05_registry_supports_only_truly_supported_aspect_ratios,
        test_06_resolve_size_maps_correctly,
        test_07_validate_request_rejects_unsupported_aspect,
        test_08_validate_request_rejects_reference_images,
        test_09_validate_request_rejects_unimplemented_capability,
        # 2. capabilities 端点
        test_10_capabilities_returns_all_models,
        test_11_capabilities_shape_matches_lantyou,
        # 3. 成功路径
        test_12_generate_success_calls_freeze_then_consume,
        test_13_generate_multi_count_calls_provider_n_times_and_freezes_total,
        test_14_generate_ref_id_is_task_id,
        # 4. 失败路径
        test_15_generate_provider_failure_triggers_rollback,
        test_16_generate_partial_failure_also_rolls_back,
        # 5. 错误处理
        test_17_generate_unknown_model_key_returns_404,
        test_18_generate_insufficient_points_returns_402,
        test_19_generate_cloud_unreachable_returns_503,
        test_20_generate_invalid_aspect_ratio_returns_400,
        test_21_generate_reference_images_returns_400,
        test_22_generate_missing_model_key_returns_400,
        test_23_generate_missing_prompt_returns_400,
        test_24_generate_passes_agent_id_through,
        # 6. points_client 单元
        test_25_points_client_get_pricing_uses_cache,
        test_26_points_client_freeze_raises_on_402,
        test_27_points_client_consume_swallows_failure,
        test_28_points_client_rollback_swallows_failure,
        test_29_points_client_points_for_ai_image_fallback_on_cloud_error,
        # 7. 幂等性
        test_30_idempotency_same_key_returns_cached_result,
        test_31_idempotency_different_key_does_not_dedupe,
        test_32_idempotency_same_key_different_user_not_deduped,
        test_33_no_idempotency_key_backward_compatible,
        test_34_idempotency_failed_request_is_cached,
        # 8. consume_pending 重试
        test_35_consume_failure_records_pending,
        test_36_retry_pending_retries_and_clears,
        test_37_retry_pending_max_attempts_keeps_pending,
        # 9. image_generations 表 + records 端点
        test_38_generate_writes_success_record_to_db,
        test_39_generate_writes_failed_record_to_db,
        test_40_records_endpoint_paginates,
        test_41_records_endpoint_status_filter,
        test_42_records_idempotency_key_persisted,
        # 10. idempotency / consume_retry 单元
        test_43_idempotency_module_direct_api,
        test_44_consume_retry_pending_list_shape,
    ]

    for t in tests:
        try:
            t()
        except Exception as exc:
            global _FAILS
            _FAILS += 1
            print(f"[FAIL] {t.__name__} 抛出异常: {exc.__class__.__name__}: {exc}")
            import traceback
            traceback.print_exc()

    total = _PASSES + _FAILS
    print(f"\n{'=' * 60}")
    print(f"总计 {total} 断言，PASS={_PASSES}，FAIL={_FAILS}")
    if _FAILS == 0:
        print("ALL TESTS PASSED")
        return 0
    print("SOME TESTS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
