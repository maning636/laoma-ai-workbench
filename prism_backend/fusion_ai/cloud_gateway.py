"""C16:客户端双通道 Gateway(本地后端 ↔ 云端 cloud_service)。

职责(设计文档 §4.1 / §4.2):
  - **按功能路由**:
      * LLM / 订阅 / 认证 / 用户中心 → **云端** (`LAOMA_CLOUD_BASE_URL`,默认 `https://api.prism.local/cloud`)
      * 浏览器自动化 / 文件 / 账号同步 / 发布 / 本地 AI → **本地** (`http://127.0.0.1:7000`)
  - **Token 管理**:登录后存 JWT(access + refresh);内存 + 文件双写;可选 Electron safeStorage。
    每次调云端自动带 `Authorization: Bearer <access>`;过期时自动 refresh。
  - **订阅校验**:调 `POST /cloud/license/verify`(短 TTL 缓存);
    失败 / 过期 / 未登录 → 返回降级标记 `{"valid": False, "reason": "..."}`。
  - **离线降级**:云端不可达 / 未登录 / 未订阅 → 上层 `prompt_router.invoke` 会走
    `basic tier` 本地快照 + 用户自配 LLM key,不影响本地功能(浏览器自动化、文件、发布)。

设计原则:
  - 不启动服务、不阻塞导入:所有 HTTP 都用 `httpx`(懒加载,失败即离线)。
  - 支持**依赖注入**:`TransportFn = Callable[[method, url, **kw], dict]`,测试时可替换。
  - Token 存储默认落 `~/.prism-fusion/credentials.json`(mode 0600);
    Electron 环境若检测到 `ELECTRON_SAFE_STORAGE` 环境变量,则改用 `electron.safeStorage`。
  - 无 secret 日志:JWT / refresh_token 从不打印。
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    from fastapi_app.core.logger import logger  # type: ignore
except Exception:  # pragma: no cover - 独立运行时降级
    logger = None


# ──────────────────────────────────────────────────────────────
# 环境变量 & 常量
# ──────────────────────────────────────────────────────────────

_ENV_CLOUD_BASE_URL = "LAOMA_CLOUD_BASE_URL"
_DEFAULT_CLOUD_BASE_URL = "https://api.prism.local"

_ENV_LOCAL_BASE_URL = "LAOMA_LOCAL_BASE_URL"
_DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:7000"

_CRED_DIR = Path.home() / ".prism-fusion"
_CRED_FILE = _CRED_DIR / "credentials.json"

#: license 校验缓存 TTL(秒)
_LICENSE_CACHE_TTL = 300
#: access token 到期前多少秒尝试 refresh
_REFRESH_LEEWAY = 60


# ──────────────────────────────────────────────────────────────
# 类型 & 数据类
# ──────────────────────────────────────────────────────────────

#: 传输层函数签名:`(method, url, *, headers, json, timeout, ...) -> dict`
#: 默认实现基于 httpx;测试时可注入 fake。
TransportFn = Callable[..., dict[str, Any]]


@dataclass
class TokenPair:
    """一次登录 / refresh 得到的凭证。"""
    access_token: str
    refresh_token: str
    expires_in: int  # 秒
    obtained_at: float = field(default_factory=time.time)

    @property
    def expires_at(self) -> float:
        return self.obtained_at + max(1, int(self.expires_in))

    def is_expiring(self, leeway: int = _REFRESH_LEEWAY) -> bool:
        return time.time() >= self.expires_at - leeway

    def as_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": self.expires_in,
            "obtained_at": self.obtained_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenPair":
        return cls(
            access_token=str(data.get("access_token") or ""),
            refresh_token=str(data.get("refresh_token") or ""),
            expires_in=int(data.get("expires_in") or 0),
            obtained_at=float(data.get("obtained_at") or time.time()),
        )


@dataclass
class LicenseStatus:
    """`/cloud/license/verify` 结果 + 本地判定。"""
    valid: bool
    reason: str            # "active" | "free" | "expired" | "offline" | "unauthenticated" | "cloud_unreachable"
    plan: str = ""         # "free" | "pro"
    remaining: int = -1
    is_pro: bool = False
    cloud_reachable: bool = False
    checked_at: float = field(default_factory=time.time)

    def to_context(self) -> dict[str, Any]:
        """适配 `prompt_router.TierContext` 需要的字段。"""
        return {
            "subscribed": bool(self.valid and (self.is_pro or self.plan == "pro" or self.remaining > 0 or self.plan == "free")),
            # 说明:免费用户也允许走云端 basic 路径(quota 有限);设计文档 §4.3 明确"有订阅 + 云端可达"= 线上版。
            "cloud_reachable": bool(self.cloud_reachable),
        }


# ──────────────────────────────────────────────────────────────
# Token 存储(内存 + 文件;safeStorage 集成留给 Electron 主进程)
# ──────────────────────────────────────────────────────────────

class TokenStore:
    """线程安全的 JWT 存储:内存 + `~/.prism-fusion/credentials.json`。

    不引入 Electron `safeStorage` 硬依赖 —— 通过 `_encrypt_hook` / `_decrypt_hook`
    注入,Electron 侧(或未来封装)可以提供 DPAPI / macOS Keychain 版本。
    """

    def __init__(self, path: Path | None = None, *, encrypt_hook: Callable[[str], str] | None = None,
                 decrypt_hook: Callable[[str], str] | None = None) -> None:
        self._path = Path(path) if path else _CRED_FILE
        self._lock = threading.RLock()
        self._token: TokenPair | None = None
        self._encrypt = encrypt_hook
        self._decrypt = decrypt_hook
        self._load()

    # -- I/O -------------------------------------------------------------
    def _read_file(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_bytes()
            if self._decrypt is not None:
                try:
                    raw = self._decrypt(raw.decode("utf-8")).encode("utf-8")
                except Exception:  # pragma: no cover - 密钥错,降级为明文路径
                    pass
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _write_file(self, data: dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            if self._encrypt is not None:
                try:
                    raw = self._encrypt(raw.decode("utf-8")).encode("utf-8")
                except Exception:  # 加密失败不阻断,退化为明文
                    pass
            self._path.write_bytes(raw)
            try:
                os.chmod(self._path, 0o600)
            except Exception:
                pass
        except Exception as exc:  # pragma: no cover - 磁盘满等,不阻断主流程
            if logger:
                logger.warning(f"[cloud_gateway] write token store failed: {exc}")

    def _load(self) -> None:
        with self._lock:
            data = self._read_file()
            if not data or not data.get("access_token"):
                self._token = None
                return
            self._token = TokenPair.from_dict(data)

    # -- API -------------------------------------------------------------
    def set_token(self, pair: TokenPair) -> None:
        with self._lock:
            self._token = pair
            self._write_file(pair.as_dict())

    def get_access_token(self) -> str:
        with self._lock:
            return (self._token.access_token if self._token else "") or ""

    def get_refresh_token(self) -> str:
        with self._lock:
            return (self._token.refresh_token if self._token else "") or ""

    def is_logged_in(self) -> bool:
        with self._lock:
            return bool(self._token and self._token.access_token)

    def should_refresh(self) -> bool:
        with self._lock:
            return bool(self._token and self._token.is_expiring())

    def clear(self) -> None:
        with self._lock:
            self._token = None
            try:
                if self._path.exists():
                    self._path.unlink()
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────
# Gateway 主类
# ──────────────────────────────────────────────────────────────

class CloudGateway:
    """客户端双通道入口(单例,线程安全)。

    使用示例(不启动服务):

        gw = get_gateway()
        result = gw.chat("cognition.matrix_evaluate", {"content": "..."})
        #   {"tier": "cloud" | "basic", "content": "..." | "rendered": "..." | "error": "..."}

        lic = gw.verify_license()
        #   LicenseStatus(valid=True, reason="active", is_pro=True, cloud_reachable=True)
    """

    def __init__(
        self,
        *,
        cloud_base_url: str | None = None,
        local_base_url: str | None = None,
        store: TokenStore | None = None,
        transport: TransportFn | None = None,
        health_timeout_sec: float = 1.5,
        request_timeout_sec: float = 20.0,
    ) -> None:
        # 归一化 cloud_base_url:
        #   - 若用户提供的是 `https://api.prism.local/cloud`(带 /cloud),自动去掉
        #   - 内部统一持有**根 URL**(不带 /cloud),拼接时统一加 /cloud 前缀
        raw_cloud = (cloud_base_url or os.getenv(_ENV_CLOUD_BASE_URL) or _DEFAULT_CLOUD_BASE_URL).rstrip("/")
        if raw_cloud.lower().endswith("/cloud"):
            raw_cloud = raw_cloud[: -len("/cloud")].rstrip("/")
        self.cloud_base_url = raw_cloud
        self.local_base_url = (local_base_url or os.getenv(_ENV_LOCAL_BASE_URL) or _DEFAULT_LOCAL_BASE_URL).rstrip("/")
        self._store = store or TokenStore()
        self._transport: TransportFn = transport or _default_transport
        self._health_timeout = health_timeout_sec
        self._request_timeout = request_timeout_sec

        self._license_cache: LicenseStatus | None = None
        self._license_checked_at: float = 0.0
        self._license_lock = threading.RLock()

    def _cloud_path(self, *parts: str) -> str:
        """构造云端完整 URL:`{cloud_base_url}/cloud/{parts}`。"""
        base = self.cloud_base_url.rstrip("/")
        path = "".join("/" + p.strip("/") for p in parts if p)
        return f"{base}/cloud{path}"

    # -- 属性 -------------------------------------------------------------
    @property
    def is_logged_in(self) -> bool:
        return self._store.is_logged_in()

    @property
    def cloud_base(self) -> str:
        return self.cloud_base_url

    @property
    def local_base(self) -> str:
        return self.local_base_url

    # -- 1. Auth:登录 / 刷新 / 登出 --------------------------------------
    def login(self, username: str, password: str) -> TokenPair:
        """POST /cloud/auth/login → 存 token。失败抛 GatewayError。"""
        url = self._cloud_path("auth", "login")
        try:
            resp = self._transport(
                "POST", url,
                headers=self._no_auth_headers(),
                json={"username": username, "password": password},
                timeout=self._request_timeout,
            )
        except Exception as exc:
            raise GatewayError(f"cloud unreachable: {exc.__class__.__name__}: {exc}") from exc
        if not isinstance(resp, dict) or not resp.get("access_token"):
            detail = (resp or {}).get("detail", "login failed") if isinstance(resp, dict) else "unexpected response"
            raise GatewayError(f"login failed: {detail}")
        pair = TokenPair(
            access_token=resp["access_token"],
            refresh_token=resp.get("refresh_token", ""),
            expires_in=int(resp.get("expires_in") or 3600),
        )
        self._store.set_token(pair)
        return pair

    def refresh_access_token(self) -> TokenPair | None:
        """用 refresh_token 换新的 access_token。失败则清空 token。"""
        refresh = self._store.get_refresh_token()
        if not refresh:
            return None
        url = self._cloud_path("auth", "refresh")
        try:
            resp = self._transport(
                "POST", url,
                headers=self._no_auth_headers(),
                json={"refresh_token": refresh},
                timeout=self._request_timeout,
            )
        except Exception:
            return None
        if not isinstance(resp, dict) or not resp.get("access_token"):
            return None
        current = self._store.get_refresh_token()
        # refresh_token 可能被服务端轮换;若返回里没有新的,沿用旧的
        pair = TokenPair(
            access_token=resp["access_token"],
            refresh_token=resp.get("refresh_token") or current,
            expires_in=int(resp.get("expires_in") or 3600),
        )
        self._store.set_token(pair)
        return pair

    def logout(self) -> None:
        """清除本地 token(不做服务端注销,避免网络依赖)。"""
        self._store.clear()

    def ensure_access_token(self) -> str:
        """返回一个可用(未过期)的 access_token,过期则尝试 refresh。

        失败/未登录 → 返回空字符串(调用方据此决定是否走云端)。
        """
        tok = self._store.get_access_token()
        if not tok:
            return ""
        if self._store.should_refresh():
            new_pair = self.refresh_access_token()
            if new_pair is None:
                # refresh 失败:可能刷新 token 也过期了,清掉,让上层降级
                self._store.clear()
                return ""
            tok = new_pair.access_token
        return tok

    # -- 2. 订阅校验(带缓存) --------------------------------------------
    def verify_license(self, *, force: bool = False) -> LicenseStatus:
        """POST /cloud/license/verify,缓存 5 分钟。

        任何失败(网络 / 401 / 403)都返回降级状态,不抛异常 —— 上层据此走离线模式。
        """
        now = time.time()
        with self._license_lock:
            if not force and self._license_cache is not None and (now - self._license_checked_at) < _LICENSE_CACHE_TTL:
                return self._license_cache

            token = self.ensure_access_token()
            if not token:
                status = LicenseStatus(
                    valid=False, reason="unauthenticated", cloud_reachable=False
                )
            else:
                status = self._do_verify_license(token)

            self._license_cache = status
            self._license_checked_at = now
            return status

    def _do_verify_license(self, token: str) -> LicenseStatus:
        url = self._cloud_path("license", "verify")
        try:
            resp = self._transport(
                "POST", url,
                headers=self._bearer_headers(token),
                json={},
                timeout=self._request_timeout,
            )
        except Exception:
            return LicenseStatus(valid=False, reason="cloud_unreachable", cloud_reachable=False)
        if not isinstance(resp, dict):
            return LicenseStatus(valid=False, reason="cloud_unreachable", cloud_reachable=False)
        code = int(resp.get("status_code") or 200)
        data = resp.get("data") or {}
        if code == 401:
            # access token 失效,清 token(下次调用会重新登录)
            self._store.clear()
            return LicenseStatus(valid=False, reason="unauthenticated", cloud_reachable=True)
        if code == 403:
            # 订阅过期或已取消
            return LicenseStatus(
                valid=False,
                reason=str(data.get("detail", "subscription not active")),
                cloud_reachable=True,
            )
        if code >= 500:
            return LicenseStatus(valid=False, reason="cloud_unreachable", cloud_reachable=False)

        remaining_raw = data.get("remaining", -1)
        try:
            remaining = int(remaining_raw) if remaining_raw is not None else -1
        except (TypeError, ValueError):
            remaining = -1

        return LicenseStatus(
            valid=bool(data.get("valid", False)),
            reason=str(data.get("reason") or ""),
            plan=str(data.get("plan") or ""),
            remaining=remaining,
            is_pro=bool(data.get("is_pro", False)),
            cloud_reachable=True,
        )

    # -- 3. 云端可达性探测(轻量) ----------------------------------------
    def probe_cloud_reachable(self) -> bool:
        """GET /cloud/llm/health(不校验 JWT)。用于离线降级判断。"""
        url = self._cloud_path("llm", "health")
        try:
            resp = self._transport(
                "GET", url,
                headers=self._no_auth_headers(),
                json=None,
                timeout=self._health_timeout,
            )
        except Exception:
            return False
        if not isinstance(resp, dict):
            return False
        code = int(resp.get("status_code") or 0)
        return 200 <= code < 500

    # -- 4. 按功能路由的分发器 -------------------------------------------
    def route(
        self,
        feature: str,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """**双通道路由** —— 按功能名决定走本地还是云端。

        `feature` 白名单:
          * `auth` / `subscription` / `license` / `usage` / `llm` / `billing`
              → **云端** `/cloud/*`(LLM + 订阅 + 认证)
          * 其他(`files` / `accounts` / `publish` / `browser` / `hermes` / ...)
              → **本地** `127.0.0.1:7000`(/api/v1/*)

        降级策略:云端调用失败时,由调用方捕获 GatewayError,
        自动切换到本地离线路径(basic tier + 用户自配 LLM key)。
        """
        url, headers = self._resolve_route(feature, path, query=query)
        return self._transport(
            method.upper(), url,
            headers=headers,
            json=body,
            timeout=self._request_timeout,
        )

    def _resolve_route(
        self, feature: str, path: str, *, query: dict[str, Any] | None = None
    ) -> tuple[str, dict[str, Any]]:
        """决定走本地还是云端,拼出最终 URL + 需要的 headers。

        约定:`cloud_base_url` 是云端**根 URL**(如 `https://api.prism.local`),
        gateway 统一在路径前加 `/cloud` 前缀,与 cloud_service/main.py 的挂载点一致。
        """
        feature_l = (feature or "").lower()
        cloud_features = {"auth", "subscription", "license", "usage", "llm", "billing"}
        clean_path = path.lstrip("/")
        if feature_l in cloud_features:
            # 若 path 已带 /cloud 前缀,不重复加
            if not clean_path.startswith("cloud/"):
                clean_path = f"cloud/{clean_path}"
            return f"{self.cloud_base_url}/{clean_path}", self._bearer_headers(self.ensure_access_token())
        # 默认走本地
        if clean_path.startswith("api/v1/"):
            final = clean_path
        elif clean_path.startswith("api/"):
            final = clean_path
        else:
            final = f"api/v1/{clean_path}"
        return f"{self.local_base_url}/{final}", self._no_auth_headers()

    # -- 5. LLM chat(封装给 prompt_router.invoke 用) --------------------
    def chat(self, prompt_name: str, variables: dict[str, Any] | None = None,
             *, raw_prompt: str | None = None, allow_raw: bool = False,
             model: str | None = None, temperature: float | None = None,
             max_tokens: int | None = None) -> dict[str, Any]:
        """POST /cloud/llm/chat —— 只调云端;失败抛 GatewayError,由上层降级。

        成功返回:`{"status_code": 200, "data": {...}, "headers": {...}}`。
        失败(网络/401/402/403/5xx)抛 GatewayError,携带可读原因,
        上层可捕获后走 basic tier 本地降级。
        """
        url = self._cloud_path("llm", "chat")
        token = self.ensure_access_token()
        if not token:
            raise GatewayError("not logged in — cannot call cloud LLM")
        payload: dict[str, Any] = {"variables": variables or {}}
        if prompt_name:
            payload["prompt_name"] = prompt_name
        if raw_prompt is not None:
            payload["raw_prompt"] = raw_prompt
            payload["allow_raw"] = bool(allow_raw)
        if model:
            payload["model"] = model
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            resp = self._transport(
                "POST", url,
                headers=self._bearer_headers(token),
                json=payload,
                timeout=self._request_timeout,
            )
        except GatewayTransportError as exc:
            raise GatewayError(f"cloud LLM unreachable: {exc}") from exc

        if not isinstance(resp, dict):
            raise GatewayError("cloud LLM: unexpected response")
        code = int(resp.get("status_code") or 0)
        data = resp.get("data") or {}

        if code == 401:
            # access token 失效,清缓存,让下次调用要求重新登录
            self._store.clear()
            raise GatewayError("cloud LLM: unauthenticated (token expired)")
        if code == 402:
            # 订阅额度已用尽
            raise GatewayError(f"cloud LLM: quota exceeded — {data.get('detail', '')}")
        if code == 403:
            raise GatewayError(f"cloud LLM: subscription not active — {data.get('detail', '')}")
        if code >= 500:
            raise GatewayError(f"cloud LLM server error: HTTP {code} — {data.get('detail', '')}")
        if code >= 400:
            raise GatewayError(f"cloud LLM client error: HTTP {code} — {data.get('detail', '')}")

        return resp

    # -- 6. 便捷:TierContext 组装 ----------------------------------------
    def build_tier_context(self, *, offline_packaged: bool = False, force_tier: str | None = None) -> dict[str, Any]:
        """组装 `prompt_router.TierContext` 需要的字段。

        返回 dict 而不是 `TierContext` 对象,避免耦合到 `prompt_router`;
        上层(router.py)可用 `TierContext(**gw.build_tier_context())` 构造。

        约定:`cloud_base_url` 字段返回**带 /cloud 后缀**的完整 base,
        与 `prompt_router._default_health_check` 拼 `+ "/llm/health"` 的默认约定对齐;
        gateway 内部仍持有不带 /cloud 的根 URL,自行加前缀。
        """
        license_status = self.verify_license()
        reachable = license_status.cloud_reachable or self.probe_cloud_reachable()
        return {
            "subscribed": bool(license_status.valid),
            "cloud_base_url": self.cloud_base_url.rstrip("/") + "/cloud",
            "cloud_reachable": bool(reachable),
            "offline_packaged": offline_packaged,
            "force_tier": force_tier,
            "extra": {
                "is_pro": license_status.is_pro,
                "plan": license_status.plan,
                "remaining": license_status.remaining,
                "license_reason": license_status.reason,
                "logged_in": self.is_logged_in,
            },
        }

    # -- headers ---------------------------------------------------------
    def _bearer_headers(self, token: str) -> dict[str, Any]:
        h = self._no_auth_headers()
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    @staticmethod
    def _no_auth_headers() -> dict[str, Any]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Prism-Fusion-Client/0.16",
        }


# ──────────────────────────────────────────────────────────────
# 传输层默认实现(httpx,懒加载)
# ──────────────────────────────────────────────────────────────

def _default_transport(method: str, url: str, *, headers: dict[str, Any] | None = None,
                      json: dict[str, Any] | None = None,
                      params: dict[str, Any] | None = None,
                      timeout: float | None = None,
                      **_kwargs: Any) -> dict[str, Any]:
    """默认 HTTP 传输:优先 httpx;失败抛异常,由调用方降级。

    返回结构统一为:
      {"status_code": int, "data": dict, "headers": dict}
    """
    try:
        import httpx  # type: ignore
    except Exception as exc:  # pragma: no cover - 极端离线场景
        raise GatewayTransportError(f"httpx not available: {exc}") from exc

    t = float(timeout) if timeout else 20.0
    try:
        with httpx.Client(timeout=t) as client:
            r = client.request(
                method.upper(), url,
                headers=headers or {},
                json=json if json is not None else None,
                params=params or None,
            )
    except Exception as exc:
        raise GatewayTransportError(f"{method} {url}: {exc.__class__.__name__}: {exc}") from exc

    # 尽力解析 JSON,失败退化为 {"detail": text}
    try:
        data = r.json()
    except Exception:
        text = r.text or ""
        data = {"detail": text[:500]} if text else {}
    return {"status_code": r.status_code, "data": data, "headers": dict(r.headers.items())}


# ──────────────────────────────────────────────────────────────
# 异常
# ──────────────────────────────────────────────────────────────

class GatewayError(Exception):
    """云端网关调用失败(网络 / 未登录 / 云端 5xx)。上层应降级到离线模式。"""


class GatewayTransportError(GatewayError):
    """底层 HTTP 传输失败(通常是网络 / DNS / 超时)。"""


# ──────────────────────────────────────────────────────────────
# 单例 & 测试入口
# ──────────────────────────────────────────────────────────────

_gateway_instance: CloudGateway | None = None
_gateway_lock = threading.RLock()


def get_gateway(**overrides: Any) -> CloudGateway:
    """获取进程内单例 CloudGateway。传入 overrides 会**创建**新实例(不影响默认)。

    典型用法:
        gw = get_gateway()                        # 单例(读 env)
        gw = get_gateway(cloud_base_url="...")    # 显式构造(测试)
    """
    global _gateway_instance
    if overrides:
        return CloudGateway(**overrides)
    with _gateway_lock:
        if _gateway_instance is None:
            _gateway_instance = CloudGateway()
        return _gateway_instance


def reset_gateway_for_test() -> None:
    """测试用:清空单例(不删除磁盘 token)。"""
    global _gateway_instance
    with _gateway_lock:
        _gateway_instance = None


__all__ = [
    "CloudGateway",
    "TokenStore",
    "TokenPair",
    "LicenseStatus",
    "GatewayError",
    "GatewayTransportError",
    "get_gateway",
    "reset_gateway_for_test",
]
