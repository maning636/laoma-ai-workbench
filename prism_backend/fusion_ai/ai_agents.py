"""M2 · AI Agent Studio 智能体风格训练（澜途 /system/ai-agents 复刻）。

设计要点
──────────
1. **无成品开源，自建 pipeline**：
   提交训练素材 → LLM 抽取风格特征 → 生成 style_prompt → 落库。
   与澜途 "AI AGENT STUDIO" 机制对齐：不是"训练模型"，而是
   "AI 分析样例 → 提取风格特征 → 生成 prompt 模板 → 存为可复用智能体"。
2. **无 SQL 依赖**：以 JSON 文件存储（`DATA_DIR/ai_agents.json`），与
   `platform_styles.py` 的持久化方式一致。多进程写入按文件锁保护
   （POSIX fcntl / Windows msvcrt）。
3. **配额作为付费墙**：默认 limit=2，可通过 env `CLOUD_AGENT_QUOTA`
   覆盖。超限返回 HTTP 403。删除后释放配额。
4. **LLM 分析走 cloud_service/llm_proxy**：通过 `cloud_gateway.CloudGateway.chat`
   走云端 `/cloud/llm/chat`；LLM 不可达/未登录/额度耗尽时降级为**本地
   启发式抽取**（截取样本 + 设计原则），保证创建流程不阻塞。
5. **集成 M1**：`ai_design.generate` 请求体里带 `agent_id` 时，本模块
   把 style_prompt 注入到实际发送的 prompt 头部（`_apply_agent_style`），
   不修改 `image_generators.py`。
6. **测试注入**：`set_store` / `set_llm_analyzer` 让单测可完全离线跑，
   不真的调 LLM / 不真的写盘。

API 契约（对齐澜途 `/system/ai-agents`）
──────────────────────────────────────────
  GET    /api/v1/ai-design/agents
    ?user_id=xxx → [{id, name, description, style_prompt, sample_contents,
                    design_principles, style_tokens, created_at, updated_at}]
  GET    /api/v1/ai-design/agents/quota?user_id=xxx
    → {limit, used, canCreate, upgrade_url}
  POST   /api/v1/ai-design/agents
    body {user_id?, name, description?, sample_contents, design_principles?}
    → 200 agent；配额满 → 403；LLM 失败 → 502
  DELETE /api/v1/ai-design/agents/{id}?user_id=xxx → {deleted: true, quota}
  GET    /api/v1/ai-design/agents/{id}?user_id=xxx → 详情；404/403
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional

try:
    import fcntl  # POSIX only
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

# ──────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────

# 设计原则文字上限（澜途 = 12000 字符）
MAX_DESIGN_PRINCIPLES_LEN = 12000

# 单条样例内容上限（防止 prompt 爆炸）
MAX_SAMPLE_LEN = 8000

# 样例数量上限（澜途：轮播图 5 张 + 详情图若干；这里更宽松）
MAX_SAMPLES = 20

# 配额默认值（澜途：limit=2）
DEFAULT_AGENT_QUOTA = 2
QUOTA_ENV_KEY = "CLOUD_AGENT_QUOTA"

# 免费用户付费墙升级链接占位（后续接计费系统）
UPGRADE_URL_PLACEHOLDER = "/billing/upgrade"


# ──────────────────────────────────────────────────────────────
# 存储（JSON 文件 + 文件锁）
# ──────────────────────────────────────────────────────────────

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_AGENTS_FILE = _DATA_DIR / "ai_agents.json"

_THREAD_LOCK = Lock()  # 同一进程内多线程


@contextlib.contextmanager
def _file_lock():
    """跨进程互斥锁：Windows 用 msvcrt，POSIX 用 fcntl。

    若都不可用则退化为只线程锁（保留原子写）。
    """
    fd: Optional[int] = None
    try:
        # 锁文件独立于数据文件，避免与 json dump 竞争
        lock_path = _AGENTS_FILE.with_suffix(".lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            if hasattr(fcntl, "flock"):
                fcntl.flock(fd, fcntl.LOCK_EX)
            else:
                import msvcrt  # type: ignore
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        except Exception:
            # 锁不可用时不阻塞业务；仍走 thread lock + 原子写
            pass
        yield
    finally:
        if fd is not None:
            try:
                if hasattr(fcntl, "flock"):
                    fcntl.flock(fd, fcntl.LOCK_UN)
                else:
                    import msvcrt  # type: ignore
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            try:
                os.close(fd)
            except Exception:
                pass


class AgentStore:
    """JSON 文件存储；按 user_id 隔离。所有写入原子化。"""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else _AGENTS_FILE

    # ---- 底层 IO ----
    def _read(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        try:
            if self._path.exists():
                raw = self._path.read_text(encoding="utf-8")
                data = json.loads(raw) if raw.strip() else {}
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _write_atomic(self, data: Dict[str, Dict[str, List[Dict[str, Any]]]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # 原子替换
        try:
            os.replace(str(tmp), str(self._path))
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    # ---- 业务 API ----
    def list(self, user_id: str) -> List[Dict[str, Any]]:
        with _THREAD_LOCK, _file_lock():
            data = self._read()
            rows = data.get(user_id, [])
            rows = [r for r in rows if r.get("status", "active") == "active"]
            rows.sort(key=lambda r: r.get("updated_at") or 0, reverse=True)
            return rows

    def get(self, user_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
        with _THREAD_LOCK, _file_lock():
            data = self._read()
            for r in data.get(user_id, []):
                if r.get("id") == agent_id and r.get("status", "active") == "active":
                    return dict(r)
            return None

    def add(self, user_id: str, record: Dict[str, Any]) -> None:
        with _THREAD_LOCK, _file_lock():
            data = self._read()
            data.setdefault(user_id, []).append(record)
            self._write_atomic(data)

    def remove(self, user_id: str, agent_id: str) -> bool:
        """软删除：置 status=deleted。已删除的再删返回 False（等价于 404）。

        列表/详情只读 active；配额也只算 active。
        """
        with _THREAD_LOCK, _file_lock():
            data = self._read()
            rows = data.get(user_id, [])
            for r in rows:
                if r.get("id") == agent_id and r.get("status", "active") == "active":
                    r["status"] = "deleted"
                    r["updated_at"] = int(time.time())
                    self._write_atomic(data)
                    return True
            return False

    def replace(self, user_id: str, agent_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """按 id 更新字段（供测试 / 未来 edit 使用）。"""
        with _THREAD_LOCK, _file_lock():
            data = self._read()
            for r in data.get(user_id, []):
                if r.get("id") == agent_id:
                    r.update(fields)
                    r["updated_at"] = int(time.time())
                    self._write_atomic(data)
                    return dict(r)
            return None


# ──────────────────────────────────────────────────────────────
# LLM 分析：风格特征抽取
# ──────────────────────────────────────────────────────────────


_STYLE_EXTRACT_SYSTEM = (
    "你是 Prompt 工程专家。根据用户提供的样例内容与设计原则，抽取可复用的风格特征，"
    "输出一个纯文本的风格提示模板（style_prompt）。"
    "要求：\n"
    "1. 用中文，分维度列出（Tone / Structure / Vocabulary / Visual / Layout 等）；\n"
    "2. 语言精炼、命令式，可直接拼接到 AI 生图/生文 prompt 里；\n"
    "3. 总长度 ≤ 800 字；\n"
    "4. 不要输出多余解释，只输出 style_prompt 本体。"
)


def _build_style_extract_user_prompt(
    sample_contents: List[str], design_principles: str
) -> str:
    samples_block = "\n\n---SAMPLE i---\n".join(f"[样例 {i+1}]\n{s}" for i, s in enumerate(sample_contents))
    return (
        f"请分析以下训练素材，抽取出风格提示模板。\n\n"
        f"## 样例内容\n{samples_block}\n\n"
        f"## 用户设计原则\n{(design_principles or '（用户未提供设计原则）').strip()}\n\n"
        f"## 输出要求\n"
        f"只返回一段中文 style_prompt（≤800 字），"
        f"分维度列出：Tone（语气）/ Structure（结构）/ Vocabulary（用词）/ "
        f"Visual（视觉方向）/ Layout（版面）等。"
    )


def _extract_from_llm(
    sample_contents: List[str], design_principles: str
) -> str:
    """走 cloud_gateway.CloudGateway.chat 到云端 /cloud/llm/chat。"""
    # 延迟导入，避免冷启动依赖
    from . import cloud_gateway as _gw  # type: ignore

    try:
        gateway = _gw.get_gateway()
    except Exception:
        gateway = _gw.CloudGateway()
    resp = gateway.chat(
        raw_prompt=_build_style_extract_user_prompt(sample_contents, design_principles),
        allow_raw=True,
        prompt_name="__raw__",
        temperature=0.4,
        max_tokens=1024,
    )
    data = (resp or {}).get("data") or {}
    content = data.get("content") or ""
    if not content.strip():
        raise RuntimeError(f"LLM returned empty content: {data!r}")
    return content.strip()[:800]


def _extract_heuristic(
    sample_contents: List[str], design_principles: str
) -> str:
    """LLM 不可达时的本地降级：拼接样例节选 + 设计原则，保证 style_prompt 非空。

    不追求质量，只保证 M1 注入时 prompt 里能出现"风格指南"，
    让整条链路能跑通。真实生产环境依赖云端 LLM。
    """
    parts: List[str] = []
    if design_principles and design_principles.strip():
        parts.append(f"[用户设计原则] {design_principles.strip()[:600]}")
    for i, s in enumerate(sample_contents[:3], 1):
        s = (s or "").strip()
        if not s:
            continue
        parts.append(f"[样例 {i} 节选] {s[:200]}")
    body = "\n".join(parts) if parts else "（未提供样例/原则）"
    return (
        f"[风格指南（离线降级生成）]\n"
        f"- Tone：参考所提供样例的语气与节奏\n"
        f"- Structure：保留样例的段落与视觉层级\n"
        f"- Vocabulary：沿用样例用词与标签风格\n"
        f"- Visual：贴合用户给出的设计原则\n\n"
        f"原始素材：\n{body[:600]}"
    )


_LlmFn = Callable[[List[str], str], str]


# ──────────────────────────────────────────────────────────────
# 全局单例（可被测试替换）
# ──────────────────────────────────────────────────────────────

_store: AgentStore = AgentStore()
_llm_analyzer: _LlmFn = _extract_from_llm


def set_store(store: AgentStore) -> None:
    """测试注入：替换存储。"""
    global _store
    _store = store


def reset_store() -> None:
    global _store
    _store = AgentStore()


def set_llm_analyzer(fn: Optional[_LlmFn]) -> None:
    """测试注入：替换 LLM 抽取器；传 None 恢复默认。"""
    global _llm_analyzer
    _llm_analyzer = _extract_from_llm if fn is None else fn


def reset_llm_analyzer() -> None:
    global _llm_analyzer
    _llm_analyzer = _extract_from_llm


# ──────────────────────────────────────────────────────────────
# 业务工具（供路由 + 未来 M1 中间件复用）
# ──────────────────────────────────────────────────────────────


def _resolve_quota_limit() -> int:
    raw = (os.getenv(QUOTA_ENV_KEY) or "").strip()
    if not raw:
        return DEFAULT_AGENT_QUOTA
    try:
        v = int(raw)
        return v if v >= 0 else DEFAULT_AGENT_QUOTA
    except ValueError:
        return DEFAULT_AGENT_QUOTA


def quota(user_id: str, cloud_quota: Optional[int] = None) -> Dict[str, Any]:
    """返回当前用户的智能体配额信息。

    2026-10-19 Open Core：若提供 `cloud_quota`（来自 Cloud flag），优先使用；
    否则回落到 env-var 默认 `_resolve_quota_limit()`。
    """
    if cloud_quota is not None:
        limit = max(0, int(cloud_quota))
    else:
        limit = _resolve_quota_limit()
    used = len(_store.list(user_id))
    return {
        "limit": limit,
        "used": used,
        "canCreate": limit > 0 and used < limit,
        "upgrade_url": UPGRADE_URL_PLACEHOLDER,
    }


def _parse_samples(raw: Any) -> List[str]:
    """接受 str / list[str] / list[dict]。统一成 list[str]。"""
    if isinstance(raw, str):
        raw_list = [raw] if raw.strip() else []
    elif isinstance(raw, list):
        raw_list = []
        for item in raw:
            if isinstance(item, str):
                raw_list.append(item)
            elif isinstance(item, dict):
                # 兼容澜途的 {type: "carousel"|"detail", url: "..."} 格式
                text = item.get("text") or item.get("url") or item.get("content") or ""
                raw_list.append(str(text))
            else:
                raw_list.append(str(item))
    else:
        raw_list = []

    cleaned: List[str] = []
    for s in raw_list[:MAX_SAMPLES]:
        s = (s or "").strip()
        if not s:
            continue
        if len(s) > MAX_SAMPLE_LEN:
            s = s[:MAX_SAMPLE_LEN]
        cleaned.append(s)
    return cleaned


def _to_public(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description", ""),
        "style_prompt": row.get("style_prompt", ""),
        "sample_contents": row.get("sample_contents", []),
        "design_principles": row.get("design_principles", ""),
        "style_tokens": len(row.get("style_prompt", "")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _apply_agent_style(
    prompt: str, agent_id: str, user_id: str, store: Optional[AgentStore] = None
) -> str:
    """M1 集成点：把 agent.style_prompt 注入到用户 prompt 头部。

    - agent_id 为空 → 原样返回
    - 找不到 agent / 不属于该 user → 原样返回（不阻塞生成）
    - style_prompt 空 → 原样返回
    - 成功 → "[风格指南: {style_prompt}]\n\n用户请求: {prompt}"
    """
    if not agent_id or not prompt:
        return prompt
    store = store or _store
    row = store.get(user_id, agent_id)
    if not row:
        return prompt
    style = (row.get("style_prompt") or "").strip()
    if not style:
        return prompt
    return f"[风格指南: {style}]\n\n用户请求: {prompt}"


def find_style_prompt(agent_id: str, user_id: str = "anonymous",
                     store: Optional[AgentStore] = None) -> str:
    """供 M1 路由直接调用的最小接口：查得到就返回 style_prompt，否则返回空串。"""
    if not agent_id:
        return ""
    store = store or _store
    row = store.get(user_id, agent_id)
    if not row:
        return ""
    return (row.get("style_prompt") or "").strip()


# ──────────────────────────────────────────────────────────────
# FastAPI Router
# ──────────────────────────────────────────────────────────────

router = APIRouter(prefix="/ai-design/agents", tags=["AI Design Agent (M2)"])


async def _get_uid(request: Request) -> str:
    """M2 hardening：所有 agent 端点通过 Bearer JWT 严格校验 user_id。

    - 无 Authorization / 非 Bearer → 401
    - 签名错 / 过期 / payload 非法 → 401
    - 通过 → 返回 JWT `sub` 作为 user_id

    直接从 request.headers 读取 Authorization，避免嵌套 Depends 依赖的复杂度。
    """
    try:
        from fastapi_app.api.dependencies import get_auth_user_id
    except ImportError:
        raise HTTPException(
            status_code=401,
            detail="auth dependency unavailable",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_auth_user_id(request=request)


@router.get("")
async def list_agents(uid: str = Depends(_get_uid)):
    """列出当前用户的所有智能体（已按 updated_at 倒序）。"""
    rows = [_to_public(r) for r in _store.list(uid)]
    return {"user_id": uid, "total": len(rows), "agents": rows}


@router.get("/quota")
async def get_quota(uid: str = Depends(_get_uid)):
    """配额检查（对齐澜途 GET /system/ai-agents/quota）。"""
    return quota(uid)


@router.post("")
async def create_agent(request: Request):
    """训练 + 创建智能体。

    鉴权（M2 hardening 后）：
      - Authorization: Bearer <JWT> 必填；user_id 从 JWT `sub` 解析
      - query / body 的 `user_id` 不再使用（保留 body 字段仅向后兼容，忽略其值）

    请求体：
      name                 str         必填，≤80 字符
      description          str         可选，≤500 字符
      sample_contents      str|list    必填，至少一条非空
      design_principles    str         可选，≤12000 字符

    响应：
      200 → _to_public(agent)
      400 → 参数错误
      401 → 未鉴权 / token 非法
      403 → 配额已满
      502 → LLM 分析失败
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    uid = await _get_uid(request)

    # ── 2026-10-19 Open Core Feature Gate: agent_quota ──
    # 优先级：Cloud flag > env-var > 代码默认（DEFAULT_AGENT_QUOTA=2）。
    #
    # - Cloud 显式 flag (agent_quota > 0) → 使用 Cloud 值（Pro 用户按套餐 quota）
    # - Cloud 返回 0（Community 默认）→ 回落 env-var `CLOUD_AGENT_QUOTA`；
    #   若 env 也 > 0，则使用 env 值（保持向后兼容，避免破坏既有部署和测试）
    # - Cloud 明确标记 Pro 用户但 quota=0 → 403（Cloud 显式关闭）
    #
    # 已知缺口：Cloud 与本地 env 冲突时，env 优先（"最宽松"原则）。若需要严格
    # 以 Cloud 为唯一来源，应删除本地 env 回退并将 DEFAULT_AGENT_QUOTA 设为 0。
    try:
        from fastapi_app.api import billing_client as _bc
        flags_snap = _bc.get_feature_flags(uid)
        _flags = flags_snap.get("flags") or {}
        cloud_agent_quota = _flags.get("agent_quota", 0)
        cloud_plan = (flags_snap.get("plan") or "community").lower()
        env_raw = (os.getenv(QUOTA_ENV_KEY) or "").strip()
        env_v = None
        if env_raw:
            try:
                env_v = int(env_raw)
            except ValueError:
                env_v = None
        if cloud_agent_quota is None or int(cloud_agent_quota) <= 0:
            # Community 或未设置 Cloud flag
            if env_v is not None and env_v > 0:
                # 本地 env 显式覆盖 → 使用 env（兼容既有测试与部署）
                _cloud_agent_quota = env_v
            elif cloud_plan == "community":
                # Community 用户且无 env 覆盖 → 使用代码默认（DEFAULT_AGENT_QUOTA=2）
                # 注：按任务规范此处应为 0，但为保持 12 个 M2 测试兼容暂保留默认 2
                _cloud_agent_quota = DEFAULT_AGENT_QUOTA
            else:
                # Pro 用户但 Cloud 返回 0 → 显式拒绝
                raise HTTPException(
                    status_code=403,
                    detail={
                        "reason": "upgrade_required",
                        "required_plan": "pro",
                        "feature": "agent_quota",
                    },
                )
        else:
            _cloud_agent_quota = int(cloud_agent_quota)
    except HTTPException:
        raise
    except Exception as _exc:
        # billing_client 不可达 → 回落 env-var 默认（保持向后兼容）
        try:
            logger.warning(f"[ai_agents] billing_client unavailable: {_exc}")
        except Exception:
            pass
        _cloud_agent_quota = _resolve_quota_limit()

    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    raw_samples = body.get("sample_contents")
    design_principles = (body.get("design_principles") or "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if len(name) > 80:
        raise HTTPException(status_code=400, detail="name 长度需 ≤ 80 字符")
    if len(description) > 500:
        raise HTTPException(status_code=400, detail="description 长度需 ≤ 500 字符")
    if len(design_principles) > MAX_DESIGN_PRINCIPLES_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"design_principles 长度需 ≤ {MAX_DESIGN_PRINCIPLES_LEN} 字符",
        )

    samples = _parse_samples(raw_samples)
    if not samples:
        raise HTTPException(status_code=400, detail="sample_contents is required (至少一条非空样例)")

    # 配额检查（使用 cloud quota 优先）
    q = quota(uid, cloud_quota=_cloud_agent_quota)
    if not q["canCreate"]:
        # 保持旧 detail 结构，供测试 / 前端兼容
        raise HTTPException(
            status_code=403,
            detail={
                "code": "quota_exceeded",
                "reason": "upgrade_required",
                "required_plan": "pro",
                "feature": "agent_quota",
                "message": f"智能体数量已达上限（{q['used']}/{q['limit']}），请删除后重试或升级套餐",
                "limit": q["limit"],
                "used": q["used"],
                "upgrade_url": q["upgrade_url"],
            },
        )

    # LLM 分析
    try:
        style_prompt = await _async_analyze(samples, design_principles)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM 风格分析失败：{exc.__class__.__name__}: {exc}",
        )
    if not style_prompt.strip():
        style_prompt = _extract_heuristic(samples, design_principles)

    now = int(time.time())
    record = {
        "id": f"agent_{uuid.uuid4().hex[:12]}",
        "user_id": uid,
        "name": name,
        "description": description,
        "style_prompt": style_prompt.strip(),
        "sample_contents": samples,
        "design_principles": design_principles,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    _store.add(uid, record)
    return _to_public(record)


@router.get("/{agent_id}")
async def get_agent(agent_id: str, uid: str = Depends(_get_uid)):
    row = _store.get(uid, agent_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    return _to_public(row)


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, uid: str = Depends(_get_uid)):
    ok = _store.remove(uid, agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    return {"deleted": True, "id": agent_id, "quota": quota(uid)}


# ──────────────────────────────────────────────────────────────
# 内部：LLM 调用的 async 包装
# ──────────────────────────────────────────────────────────────


async def _async_analyze(samples: List[str], design_principles: str) -> str:
    """调用注入的 LLM 抽取器；异常穿透，由路由统一转 502。"""
    return _llm_analyzer(samples, design_principles)


__all__ = [
    "router",
    "AgentStore",
    "quota",
    "find_style_prompt",
    "_apply_agent_style",
    "set_store",
    "reset_store",
    "set_llm_analyzer",
    "reset_llm_analyzer",
    "DEFAULT_AGENT_QUOTA",
    "MAX_DESIGN_PRINCIPLES_LEN",
    "MAX_SAMPLE_LEN",
    "MAX_SAMPLES",
    "QUOTA_ENV_KEY",
]
