"""M1 · 云端积分扣费客户端（对接 M3 · /cloud/points/*）。

M1 生成图片流程：
  1. POST /cloud/points/freeze    → freeze_tx_id   （生成前预扣）
  2. 调 provider 生成图片
  3a. 成功 → POST /cloud/points/consume  (freeze_tx_id)
  3b. 失败 → POST /cloud/points/rollback (freeze_tx_id)

M3 API 参考（见 docs/dev-reports/2026-10-16-m3-implementation.md）：
  - POST /cloud/points/freeze     body: {amount, use_function, ref_id, pricing_key?, note?}
    → {freezeTxId, amount, useFunction, refId, pricingKey, status, availablePoints, frozenPoints, createdAt}
  - POST /cloud/points/consume    body: {freeze_tx_id, note?}
    → {freezeTxId, consumeTxId, amount, status="consumed", ...}
  - POST /cloud/points/rollback   body: {freeze_tx_id, note?}
    → {freezeTxId, consumeTxId, amount, status="rolled_back", ...}
  - GET  /cloud/points/pricing    → {pricingVersion, items: [{pricingKey, points, ...}]}

设计原则：
  1. **薄客户端**：不做业务规则（定价读取、冻结/实扣决策由 ai_design 路由负责）。
  2. **可测试**：`PointsClient(transport=..., base_url=..., token_provider=...)` 全部可注入。
     - transport(method, url, *, headers, json) → {"status_code": int, "data": dict}
     - token_provider() → str（返回空串代表未登录，此时请求不带 Authorization）
     - base_url 允许传根（不带 /cloud），内部拼 /cloud 前缀。
  3. **错误分类**：把常见 M3 错误码转为语义化异常：
       - PointsInsufficient   → HTTP 402
       - PointsCloudError     → 5xx / 网络失败
       - PointsCloudClient    → 4xx（未知 freeze、状态非法等）
     调用方（ai_design 路由）根据异常决定 HTTP 响应。
  4. **不吞异常**：freeze 失败必须抛出（否则用户没被扣积分但拿到图 → 漏钱）。
     consume/rollback 失败**记录日志但不再抛**（避免用户已拿到图却收到 500）；
     路由层可选记录告警但不改变响应。
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

try:
    from fastapi_app.core.logger import logger  # type: ignore
except Exception:  # pragma: no cover
    logger = None

PointsTransportFn = Callable[..., Dict[str, Any]]
TokenProviderFn = Callable[[], str]


_ENV_CLOUD_BASE_URL = "LAOMA_CLOUD_BASE_URL"
_DEFAULT_CLOUD_BASE_URL = "https://api.prism.local"

#: aiImageGeneration 定价（澜途审计 = 1.5 积分/张），云端定价拉取失败时的本地兜底
DEFAULT_AI_IMAGE_POINTS = 1.5

#: M3 `use_function` 分类，与澜途"AI设计中心"记录类别对齐
DEFAULT_USE_FUNCTION = "AI设计中心"

#: 缓存云端价目表的 TTL（秒）
_PRICING_CACHE_TTL = 300


class PointsCloudError(Exception):
    """积分云端返回 5xx 或网络失败。"""


class PointsCloudClient(Exception):
    """积分云端返回 4xx（业务错）。"""

    def __init__(self, status: int, detail: str, raw: Optional[Dict[str, Any]] = None):
        self.status = int(status)
        self.detail = str(detail)
        self.raw = raw or {}
        super().__init__(f"[{status}] {self.detail}")


class PointsInsufficient(PointsCloudClient):
    """余额不足（HTTP 402）。"""


def _log(msg: str) -> None:
    if logger is not None:
        try:
            logger.warning(msg)
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# 默认 transport（httpx；测试时可替换）
# ──────────────────────────────────────────────────────────────


def _default_transport(method: str, url: str, *, headers: Optional[Dict[str, Any]] = None,
                      json: Optional[Dict[str, Any]] = None,
                      timeout: float = 15.0, **_: Any) -> Dict[str, Any]:
    import httpx
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.request(
                method.upper(), url,
                headers=headers or {},
                json=json if json is not None else None,
            )
    except Exception as exc:
        raise PointsCloudError(f"{method} {url} failed: {exc.__class__.__name__}: {exc}") from exc
    try:
        data = r.json()
    except Exception:
        data = {"detail": (r.text or "")[:500]}
    return {"status_code": int(r.status_code), "data": data}


# ──────────────────────────────────────────────────────────────
# PointsClient
# ──────────────────────────────────────────────────────────────


class PointsClient:
    """M3 积分 API 客户端。

    典型用法（默认 httpx + CloudGateway token）：
        from fusion_ai.cloud_gateway import get_gateway
        pc = PointsClient(
            base_url="https://api.prism.local",
            token_provider=lambda: get_gateway().ensure_access_token(),
        )
        freeze = pc.freeze(amount=1.5, use_function="AI设计中心", ref_id="gen_123")

    测试用法：
        pc = PointsClient(
            base_url="http://cloud.test",
            token_provider=lambda: "test-token",
            transport=fake_transport,
        )
    """

    def __init__(self,
                 base_url: Optional[str] = None,
                 token_provider: Optional[TokenProviderFn] = None,
                 transport: Optional[PointsTransportFn] = None,
                 timeout: float = 15.0,
                 pricing_cache_ttl: int = _PRICING_CACHE_TTL) -> None:
        # 归一化：如果用户传的是 https://api.prism.local/cloud，去掉 /cloud 后缀
        raw = (base_url
               or os.getenv(_ENV_CLOUD_BASE_URL)
               or _DEFAULT_CLOUD_BASE_URL).rstrip("/")
        if raw.lower().endswith("/cloud"):
            raw = raw[: -len("/cloud")].rstrip("/")
        self._base_url = raw
        self._token_provider = token_provider or (lambda: "")
        self._transport = transport or _default_transport
        self._timeout = float(timeout)
        self._pricing_cache_ttl = int(pricing_cache_ttl)

        # 价目缓存
        self._pricing_cache: Optional[Dict[str, Any]] = None
        self._pricing_cache_at: float = 0.0

    # -- URL 构造 ------------------------------------------------------
    @property
    def base_url(self) -> str:
        return self._base_url

    def _url(self, path: str) -> str:
        clean = path.lstrip("/")
        return f"{self._base_url}/cloud/{clean}"

    def _headers(self) -> Dict[str, Any]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Prism-Fusion-Backend/0.16",
        }
        try:
            token = self._token_provider() or ""
        except Exception as exc:
            _log(f"[points_client] token_provider failed: {exc}")
            token = ""
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    # -- 通用请求 ------------------------------------------------------
    def _request(self, method: str, path: str,
                 body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self._url(path)
        try:
            resp = self._transport(
                method.upper(), url,
                headers=self._headers(),
                json=body,
                timeout=self._timeout,
            )
        except PointsCloudError:
            raise
        except Exception as exc:
            raise PointsCloudError(f"{method} {url} failed: {exc.__class__.__name__}: {exc}") from exc
        if not isinstance(resp, dict):
            raise PointsCloudError(f"{method} {url}: unexpected response type {type(resp).__name__}")
        return resp

    @staticmethod
    def _unwrap(resp: Dict[str, Any]) -> Dict[str, Any]:
        """M3 endpoints 用 FastAPI，返回 data 字段就是 schema 序列化后的 dict。

        如果响应顶层直接就是业务数据（如某些 mock 场景），也接受。
        """
        if "status_code" in resp and "data" in resp:
            code = int(resp.get("status_code") or 0)
            data = resp.get("data") or {}
            if code >= 400:
                detail = ""
                if isinstance(data, dict):
                    detail = str(data.get("detail") or data)
                raise _raise_for_status(code, detail, raw=resp)
            return data
        # 非 gateway 场景：resp 本身是业务数据
        return resp

    # -- 价目表 --------------------------------------------------------
    def get_pricing(self, *, force: bool = False) -> Dict[str, Any]:
        """GET /cloud/points/pricing，带 TTL 缓存。

        失败降级：返回 {"pricingVersion": "fallback", "items": [], "_error": "..."}，
        由调用方决定用本地兜底定价。
        """
        import time as _t
        now = _t.time()
        if (not force and self._pricing_cache is not None
                and (now - self._pricing_cache_at) < self._pricing_cache_ttl):
            return self._pricing_cache
        try:
            resp = self._request("GET", "points/pricing")
            data = self._unwrap(resp)
        except Exception as exc:
            _log(f"[points_client] get_pricing failed: {exc}")
            return {"pricingVersion": "fallback", "items": [], "_error": str(exc)[:200]}
        self._pricing_cache = data
        self._pricing_cache_at = now
        return data

    def points_for_ai_image(self) -> float:
        """从云端价目表读 aiImageGeneration 单价；失败降级到本地常量。"""
        pricing = self.get_pricing()
        for item in pricing.get("items", []) or []:
            if item.get("pricingKey") == "aiImageGeneration":
                try:
                    return float(item.get("points") or 0)
                except (TypeError, ValueError):
                    pass
        return DEFAULT_AI_IMAGE_POINTS

    # -- 冻结 / 实扣 / 回滚 -------------------------------------------
    def freeze(self, *, amount: float,
               use_function: str = DEFAULT_USE_FUNCTION,
               ref_id: str = "",
               pricing_key: str = "aiImageGeneration",
               note: Optional[str] = None) -> Dict[str, Any]:
        """POST /cloud/points/freeze。

        返回 dict（含 freezeTxId）。余额不足 → PointsInsufficient；
        其他错误 → PointsCloudClient/PointCloudError。
        """
        body: Dict[str, Any] = {
            "amount": float(amount),
            "use_function": use_function,
            "ref_id": ref_id,
            "pricing_key": pricing_key,
        }
        if note:
            body["note"] = note
        resp = self._request("POST", "points/freeze", body)
        return self._unwrap(resp)

    def consume(self, freeze_tx_id: int, note: Optional[str] = None) -> Dict[str, Any]:
        """POST /cloud/points/consume。失败时**不抛**（业务上已成功生成图片）；
        仅返回 {"ok": False, "error": "..."} 便于路由层记录。
        """
        body: Dict[str, Any] = {"freeze_tx_id": int(freeze_tx_id)}
        if note:
            body["note"] = note
        try:
            resp = self._request("POST", "points/consume", body)
            return {"ok": True, **self._unwrap(resp)}
        except PointsCloudClient as exc:
            _log(f"[points_client] consume failed (tx={freeze_tx_id}): {exc}")
            return {"ok": False, "error": str(exc), "freeze_tx_id": int(freeze_tx_id)}
        except PointsCloudError as exc:
            _log(f"[points_client] consume unreachable (tx={freeze_tx_id}): {exc}")
            return {"ok": False, "error": str(exc), "freeze_tx_id": int(freeze_tx_id)}

    def rollback(self, freeze_tx_id: int, note: Optional[str] = None) -> Dict[str, Any]:
        """POST /cloud/points/rollback。失败**不抛**（生成已失败，用户不该再看到额外错误）；
        仅返回 {"ok": False, "error": "..."}。
        """
        body: Dict[str, Any] = {"freeze_tx_id": int(freeze_tx_id)}
        if note:
            body["note"] = note
        try:
            resp = self._request("POST", "points/rollback", body)
            return {"ok": True, **self._unwrap(resp)}
        except PointsCloudClient as exc:
            _log(f"[points_client] rollback failed (tx={freeze_tx_id}): {exc}")
            return {"ok": False, "error": str(exc), "freeze_tx_id": int(freeze_tx_id)}
        except PointsCloudError as exc:
            _log(f"[points_client] rollback unreachable (tx={freeze_tx_id}): {exc}")
            return {"ok": False, "error": str(exc), "freeze_tx_id": int(freeze_tx_id)}


# ──────────────────────────────────────────────────────────────
# HTTP status 分类
# ──────────────────────────────────────────────────────────────


def _raise_for_status(status: int, detail: str, *, raw: Dict[str, Any]) -> Exception:
    if status == 402:
        return PointsInsufficient(status, detail, raw)
    return PointsCloudClient(status, detail, raw)


# ──────────────────────────────────────────────────────────────
# 单例
# ──────────────────────────────────────────────────────────────


_default_client: Optional[PointsClient] = None


def get_points_client(**overrides: Any) -> PointsClient:
    """进程内单例；传 overrides 时返回新实例（不影响默认）。

    默认 token_provider 从 CloudGateway 拿 access_token（懒加载，避免循环导入）。
    """
    global _default_client
    if overrides:
        if "token_provider" not in overrides:
            overrides["token_provider"] = _default_token_provider
        return PointsClient(**overrides)
    if _default_client is None:
        _default_client = PointsClient(token_provider=_default_token_provider)
    return _default_client


def reset_points_client_for_test() -> None:
    global _default_client
    _default_client = None


def _default_token_provider() -> str:
    """懒加载 CloudGateway，避免顶层循环 import。"""
    try:
        from .cloud_gateway import get_gateway
        return get_gateway().ensure_access_token()
    except Exception:
        return ""


__all__ = [
    "PointsClient",
    "PointsCloudError",
    "PointsCloudClient",
    "PointsInsufficient",
    "DEFAULT_AI_IMAGE_POINTS",
    "DEFAULT_USE_FUNCTION",
    "get_points_client",
    "reset_points_client_for_test",
]
