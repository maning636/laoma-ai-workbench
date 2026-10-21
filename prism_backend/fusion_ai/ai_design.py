"""M1 · AI 生图 API（澜途 /ai-design/* 复刻 + 稳健性修复）。

端点：
  GET  /api/v1/ai-design/capabilities  → 澜途格式的模型能力清单
  POST /api/v1/ai-design/generate       → 生成图片（幂等键 + 积分扣费 + 落库）
  GET  /api/v1/ai-design/records        → 用户生成记录分页查询

业务流程（POST /generate）：
  1. 参数解析（含可选 idempotency_key / user_id）
  2. 幂等：命中缓存 → 直接返回；已处理中 → 202；未处理 → 写 processing 标记，继续
  3. modelKey 路由 + 约束校验
  4. 调 M3 `POST /cloud/points/freeze` 冻结积分
  5. 生成前先落库一条 pending 记录（image_generations）
  6. 按 count 循环调 provider
  7. 全部成功 → `POST /cloud/points/consume`
     成功 → 更新记录为 success + 写幂等缓存
     consume 失败 → 记录 consume_pending 待后台重试（响应仍返回 200）
     任一失败 → `POST /cloud/points/rollback`，更新记录为 failed + 写幂等缓存（若为 4xx）
  8. 返回响应

幂等性：
  - 请求体加可选 idempotency_key（前端生成 UUID）。
  - Redis key: m1:gen_idem:{user_id}:{idempotency_key}，TTL 24h，Redis 不可用降级到内存。
  - 同一 key 重复请求 → 已完成直接返回缓存（不重复 freeze）；处理中 → 202。
  - 未传 idempotency_key 也兼容（走完整流程，只记 warning）。

consume_pending 重试：
  - consume 失败时调用 consume_retry.record_pending 记录 freeze_tx_id。
  - 后台每 5 分钟扫描 pending 重试（默认重试 5 次上限，达上限保留 pending 供人工介入）。

参考：
  - docs/dev-reports/2026-10-16-m1-implementation.md §遗留问题
  - docs/dev-reports/2026-10-16-m1-hardening.md
  - docs/dev-reports/2026-10-16-m3-implementation.md（积分 API）
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from . import consume_retry, idempotency, image_gen_models
from .image_generators import generate_single_image
from .model_key_registry import (
    CAP_IMAGE_GENERATE,
    get_provider,
    list_capabilities,
    resolve_size,
    validate_request,
)
from .points_client import (
    DEFAULT_AI_IMAGE_POINTS,
    DEFAULT_USE_FUNCTION,
    PointsClient,
    PointsCloudClient,
    PointsCloudError,
    PointsInsufficient,
    get_points_client,
)

router = APIRouter(prefix="/ai-design", tags=["AI Design (M1)"])

#: 单次请求最大 count 上限（防刷/防放大攻击）。真实单次生成 1 张由
#: `maxOutputCount` 校验决定，这里是二次防御。
_MAX_COUNT_PER_REQUEST = 10

#: 单次请求 prompt 字符数上限（2026-10-19 medium-hardening）。
#: 目的：防止超长 prompt 消耗过多 provider token / 触发上游超时，
#: 也避免把巨型 payload 存进 `image_generations.prompt`（SQLite TEXT 无硬上限）。
#: 10000 已远超正常生图 prompt（一般 < 500 字符）。
_MAX_PROMPT_LEN = 10000


def _decode_jwt_sub(token: str) -> Optional[str]:
    """best-effort 解 JWT 的 `sub` claim（HS256）；失败返回 None。

    密钥解析顺序：CLOUDJWT_SECRET → JWT_SECRET → CLOUD_SECRET_KEY → SECRET_KEY。
    复用 prism_backend/fastapi_app/api/dependencies.py 的顺序约定。

    注意：这里做**校验**（signature + exp），不像限流模块那样只是分组。
    """
    try:
        import os as _os
        import jwt as _pyjwt  # PyJWT
    except Exception:
        return None
    secret = None
    for k in ("CLOUDJWT_SECRET", "JWT_SECRET", "CLOUD_SECRET_KEY", "SECRET_KEY"):
        v = _os.getenv(k)
        if v:
            secret = v
            break
    if not secret:
        return None
    alg = _os.getenv("JWT_ALGORITHM", "HS256")
    try:
        payload = _pyjwt.decode(token, secret, algorithms=[alg])
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    sub = payload.get("sub")
    if sub is None:
        return None
    return str(sub)


def _extract_user_id(request: Request, body_user_id: str) -> str:
    """从 Authorization header / body 提取 user_id。

    2026-10-19 medium-hardening（§3.2-5）：
      - 若携带 `Authorization: Bearer <jwt>`：
          * 校验成功 → 使用 token 中的 `sub`（**忽略** body 里的 user_id）
          * 校验失败 → HTTP 401（拒绝伪造，不允许"降级到 body"）
      - 若**没有** Authorization header（兼容本地开发 / 未接入 JWT 的
        旧客户端 / 现有 M1 测试）：
          * 依次使用 body.user_id → "anonymous"

    这是**兼容模式**：无 header 时仍信任 body，防止 140 个现有 M1 测试
    因 user_id 校验失败而集体挂掉。残余风险已在报告中登记（"匿名/未认证
    客户端仍可伪造 body.user_id"）。

    未来若前端全面接入 JWT，可加 env `M1_REQUIRE_JWT=true` 关闭该回退。
    """
    import os as _os
    require_jwt = _os.getenv("M1_REQUIRE_JWT", "false").lower() in {
        "1", "true", "yes"
    }
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    auth_stripped = (auth or "").strip()

    if auth_stripped:
        # 携带 header → 必须校验通过
        if auth_stripped.lower().startswith("bearer "):
            token = auth_stripped[7:].strip()
            if token:
                sub = _decode_jwt_sub(token)
                if sub:
                    return sub
        # 校验失败：
        # - 若强制模式：401
        # - 兼容模式（默认）：仍返回 401（因为客户端明确声称携带凭证，
        #   不允许"降级到 body"，否则攻击者可以在 header 里放一个
        #   无效 token 然后从 body 里塞任意 user_id）
        raise HTTPException(status_code=401, detail="invalid or expired JWT")

    if require_jwt:
        raise HTTPException(
            status_code=401, detail="missing Authorization Bearer token"
        )

    # 无 Authorization header → 兼容旧行为：body.user_id → anonymous
    uid = (body_user_id or "").strip()
    if uid:
        return uid
    return "anonymous"


def _apply_agent_style_from_m2(prompt: str, agent_id: str, user_id: str) -> str:
    """M1↔M2 集成点：把 M2 智能体的 style_prompt 注入到用户 prompt 头部。

    延迟导入，避免冷启动时 M1 依赖 M2；也便于测试时 monkey-patch。
    找不到智能体 / 权限不匹配时原样返回 prompt，不阻塞生成。
    """
    if not agent_id or not prompt:
        return prompt
    try:
        from .ai_agents import _apply_agent_style  # noqa: PLC0415
    except Exception:
        return prompt
    try:
        return _apply_agent_style(prompt, agent_id, user_id=user_id)
    except Exception:
        return prompt


# ──────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────


#: provider 调用点，可被测试 patch 替换
_generate_fn: Callable[[Dict[str, Any], str, str], Awaitable[Dict[str, Any]]] = generate_single_image

#: points_client 获取函数，可被测试 patch 替换（例如注入 mock transport）
_get_points_client: Callable[[], PointsClient] = get_points_client


def set_generate_fn(fn: Callable[[Dict[str, Any], str, str], Awaitable[Dict[str, Any]]]) -> None:
    """测试注入：替换 provider 调用。"""
    global _generate_fn
    _generate_fn = fn


def reset_generate_fn() -> None:
    global _generate_fn
    _generate_fn = generate_single_image


def set_points_client_provider(fn: Callable[[], PointsClient]) -> None:
    """测试注入：替换 PointsClient 提供者。"""
    global _get_points_client
    _get_points_client = fn


def reset_points_client_provider() -> None:
    global _get_points_client
    _get_points_client = get_points_client


def _new_ref_id() -> str:
    return f"gen_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"


def _register_generation_artifacts(
    *,
    record_id: Optional[int],
    urls: List[str],
    prompt: str,
    model_key: str,
    aspect_ratio: str,
    agent_id: str,
    task_id: str,
) -> List[str]:
    """把生图产出登记进「统一产物总线」，返回 artifact_id 列表。

    这是「生成 → 送审 → 发布」串联的第一环：生图产出不再是孤立的一串 URL，
    而是拿到统一产物 ID（art_xxx），后续任何功能都能按这个 ID 找到它、
    推进它的阶段、或者把它作为父产物派生新版本。

    - provider 返回远程 URL → path 直接存 URL；
    - provider 返回 data:base64 → 先落盘到 VIDEO_FILES_DIR/generated/，
      path 存相对路径（/getFile?filename= 可取），避免把几 MB 的 base64 塞进 DB。
    - 登记失败只记日志、不阻断生成（safe_register_artifact）。
    """
    from prism_core import artifacts as artifact_service

    artifact_ids: List[str] = []
    for idx, raw_url in enumerate(urls or []):
        if not raw_url:
            continue
        path = raw_url
        media_type = ""
        if raw_url.startswith("data:"):
            path, media_type = artifact_service.persist_data_url(
                raw_url, subdir="generated"
            )
            if not path:
                # 落盘失败：保留原始 data URL（不阻断主流程）
                path = raw_url
        aid = artifact_service.safe_register_artifact(
            source=artifact_service.SOURCE_IMAGE_GEN,
            ref_type="image_generation",
            ref_id=str(record_id if record_id is not None else task_id),
            path=path,
            kind=artifact_service.KIND_IMAGE,
            stage=artifact_service.STAGE_GENERATED,
            title=(prompt or "")[:120],
            thumb=path,
            media_type=media_type,
            meta={
                "model_key": model_key,
                "aspect_ratio": aspect_ratio,
                "agent_id": agent_id,
                "task_id": task_id,
                "index": idx,
                "remote_url": raw_url if raw_url.startswith("http") else "",
            },
        )
        if aid:
            artifact_ids.append(aid)
    return artifact_ids


# ──────────────────────────────────────────────────────────────
# GET /api/v1/ai-design/capabilities
# ──────────────────────────────────────────────────────────────


@router.get("/capabilities")
async def get_capabilities():
    """返回澜途格式的模型能力清单。"""
    return list_capabilities()


# ──────────────────────────────────────────────────────────────
# GET /api/v1/ai-design/records
# ──────────────────────────────────────────────────────────────


@router.get("/records")
async def list_generation_records(request: Request,
                                  current: int = 1,
                                  size: int = 20,
                                  status: Optional[str] = None):
    """用户生成记录分页查询。

    用户身份来自 Authorization Bearer，或 query 参数 user_id（本地调试用）。
    返回：{"total": N, "current": page, "size": page_size, "records": [...]}
    """
    user_id = _extract_user_id(request, (request.query_params.get("user_id") or ""))
    return image_gen_models.list_records(
        user_id=user_id, current=current, size=size, status=status,
    )


# ──────────────────────────────────────────────────────────────
# POST /api/v1/ai-design/generate
# ──────────────────────────────────────────────────────────────


@router.post("/generate")
async def generate_images(request: Request):
    """生成图片（走 modelKey 路由 + M3 积分扣费 + 幂等 + 落库）。

    请求体：
      model_key          str   必填，如 "dall-e-3" / "flux-1" / "wanx"
      prompt             str   必填
      reference_images   list  可选（当前所有 provider maxReferenceImages=0，传非空即 400）
      aspect_ratio       str   可选，默认 "1:1"
      count              int   可选，默认 1（> 1 时循环调用 provider）
      agent_id           str   可选，用于统计归因（M2 智能体，本模块只透传不校验）
      idempotency_key    str   可选，前端生成的幂等键；同一 (user, key) 24 小时内返回缓存

    响应体：见 M1 实现报告 §4.2。
    幂等重复请求：
      - 已完成 → 直接返回缓存的响应（不再 freeze/consume）。
      - 处理中 → 202 + {"task_id": "...", "message": "任务处理中，请稍后重试"}。
    """
    body = await request.json()

    model_key = (body.get("model_key") or "").strip()
    prompt = (body.get("prompt") or "").strip()
    reference_images = body.get("reference_images") or []
    aspect_ratio = (body.get("aspect_ratio") or "1:1").strip()
    count_raw = body.get("count", 1)
    agent_id = (body.get("agent_id") or "").strip()
    idempotency_key = (body.get("idempotency_key") or "").strip()

    user_id = _extract_user_id(request, (body.get("user_id") or ""))

    # ── 2026-10-19 Open Core Feature Gate: ai_mode / image_gen ──
    # 从 billing_client 拉一次 flag 快照，供下游逻辑参考（Pro vs Community）。
    # 策略（保守兼容）：
    #   - Cloud 显式 ai_mode="local_key" 且 image_gen="local_key" → Community
    #     走本地模式，本端点仍会执行（M1 尚无 local_key provider 概念），
    #     但把 mode 写进 response 的 `mode` 字段供前端 UI 提示。
    #   - Cloud ai_mode="cloud" → Pro 走云端，正常放行。
    #   - Cloud 不可达（→ 回落 Community 默认）→ 与"未登录"等价，放行。
    # 硬性阻断（Community 用户走云端 provider 时报 403）待 M1 接入
    # local_key provider 后启用；当前仅记录审计日志。
    try:
        from fastapi_app.api import billing_client as _bc
        _billing_flags = _bc.get_feature_flags(user_id)
        _billing_plan = (_billing_flags.get("plan") or "community").lower()
        _billing_ai_mode = _billing_flags.get("ai_mode") or "local_key"
        _billing_image_gen = _billing_flags.get("image_gen") or _billing_ai_mode
        _billing_mode_allowed = True  # 当前不做硬性阻断
    except Exception as _exc:
        try:
            if logger is not None:
                logger.warning(
                    f"[ai_design] billing_client unavailable user={user_id}: {_exc}"
                )
        except Exception:
            pass
        _billing_flags = {}
        _billing_plan = "unknown"
        _billing_ai_mode = "local_key"
        _billing_image_gen = "local_key"
        _billing_mode_allowed = True
    if len(prompt) > _MAX_PROMPT_LEN:
        raise HTTPException(
            status_code=400,
            detail=(
                f"prompt too long: {len(prompt)} > {_MAX_PROMPT_LEN} "
                f"(max {_MAX_PROMPT_LEN} chars per request)"
            ),
        )

    # M1↔M2 集成：agent_id → style_prompt 注入（找不到 agent 就原样返回，不阻塞）
    if agent_id:
        prompt = _apply_agent_style_from_m2(prompt, agent_id, user_id=user_id)

    # 1. 基础参数校验
    if not model_key:
        raise HTTPException(status_code=400, detail="model_key is required")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    try:
        count = int(count_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"count 必须是整数，收到 {count_raw!r}")
    # 防止 count 过大导致积分/上游消耗放大（防刷）：单请求上限 10 张。
    if count < 1:
        raise HTTPException(status_code=400, detail=f"count 必须 ≥ 1，收到 {count}")
    if count > _MAX_COUNT_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"count 超出上限（{count} > {_MAX_COUNT_PER_REQUEST}）",
        )

    # 2. 幂等：命中缓存或处理中 → 直接返回
    if idempotency_key:
        acq = idempotency.acquire(user_id, idempotency_key)
        if acq.cached_result is not None:
            return dict(acq.cached_result)
        if acq.cached_error is not None:
            err = acq.cached_error
            http_status = int(err.get("status") or 500)
            raise HTTPException(status_code=http_status,
                                detail=str(err.get("detail") or err))
        if acq.in_flight:
            return JSONResponse202(
                {"message": "任务处理中，请稍后重试",
                 "idempotency_key": idempotency_key}
            )
    else:
        # 兼容旧客户端：无 idempotency_key 直接放行，但记 warning
        try:
            if logger is not None:
                logger.warning(
                    f"[ai_design] generate without idempotency_key user={user_id} model={model_key}"
                )
        except Exception:
            pass

    # 3. modelKey 路由
    model_def, entry = get_provider(model_key)
    if entry is None or model_def is None:
        raise HTTPException(
            status_code=404,
            detail=f"未知 modelKey: {model_key}（调用 GET /ai-design/capabilities 查看可用模型）",
        )

    # 4. 约束校验（capabilities / aspect_ratio / reference_images / count）
    err = validate_request(
        entry,
        aspect_ratio=aspect_ratio,
        count=count,
        reference_images=reference_images,
        capability=CAP_IMAGE_GENERATE,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)

    # 5. 计算定价 & 冻结积分
    client = _get_points_client()
    unit_price = float(client.points_for_ai_image()) if client else DEFAULT_AI_IMAGE_POINTS
    if unit_price <= 0:
        unit_price = DEFAULT_AI_IMAGE_POINTS
    total_amount = round(unit_price * count, 4)

    task_id = _new_ref_id()

    # 6. 生成前落库一条 pending 记录
    record_id: Optional[int] = None
    try:
        record_id = image_gen_models.insert_record(
            user_id=user_id,
            model_key=model_key,
            prompt=prompt,
            agent_id=agent_id,
            aspect_ratio=aspect_ratio,
            count=count,
            freeze_tx_id=None,
            idempotency_key=idempotency_key,
            status="pending",
        )
    except Exception:
        record_id = None

    try:
        freeze = client.freeze(
            amount=total_amount,
            use_function=DEFAULT_USE_FUNCTION,
            ref_id=task_id,
            pricing_key="aiImageGeneration",
            note=f"AI生图 {model_key}×{count}",
        )
    except PointsInsufficient as e:
        if record_id is not None:
            image_gen_models.update_failed(
                record_id, error_message=f"积分不足：{e.detail}", status="failed"
            )
        raise HTTPException(status_code=402, detail=f"积分不足：{e.detail}") from e
    except PointsCloudClient as e:
        if record_id is not None:
            image_gen_models.update_failed(
                record_id, error_message=str(e), status="failed"
            )
        raise HTTPException(status_code=e.status, detail=e.detail) from e
    except PointsCloudError as e:
        if record_id is not None:
            image_gen_models.update_failed(
                record_id, error_message=f"积分服务不可用：{e}", status="failed"
            )
        raise HTTPException(
            status_code=503,
            detail=f"积分服务不可用，本次生成已取消：{e}",
        ) from e

    freeze_tx_id = freeze.get("freezeTxId") or freeze.get("freeze_tx_id")
    if not freeze_tx_id:
        if record_id is not None:
            image_gen_models.update_failed(
                record_id, error_message="积分冻结响应异常：缺少 freezeTxId", status="failed"
            )
        raise HTTPException(status_code=502, detail="积分冻结响应异常：缺少 freezeTxId")

    # 冻结成功后回写 freeze_tx_id 到 DB 记录（原本 insert 时冻结还没返回，只能先写 None）
    if record_id is not None:
        try:
            image_gen_models.update_freeze_tx_id(record_id, freeze_tx_id)
        except Exception:
            pass

    # 7. 调 provider 生成图片（循环 count 次）
    size = resolve_size(entry, aspect_ratio=aspect_ratio)
    urls: List[str] = []
    failures: List[Dict[str, Any]] = []

    for _ in range(max(1, count)):
        try:
            result = await _generate_fn(model_def, prompt, size)
        except Exception as exc:  # pragma: no cover
            failures.append({"error": f"provider 调用异常: {exc.__class__.__name__}: {exc}"})
            continue
        if isinstance(result, dict) and result.get("success"):
            urls.append(result.get("url") or "")
        else:
            err_msg = "unknown provider error"
            if isinstance(result, dict):
                err_msg = result.get("error") or err_msg
            failures.append({"error": err_msg})

    # 8. 结算：全部成功 → consume；有失败 → rollback
    response: Dict[str, Any]
    if len(urls) >= count:
        consume_res = client.consume(freeze_tx_id, note=f"AI生图成功 {model_key}×{len(urls)}")
        points_status = "consumed"
        if not consume_res.get("ok"):
            # 生成已成功；consume 失败记录 pending 供后台重试，但不影响响应
            points_status = "consumed_consume_pending"
            consume_retry.record_pending(
                freeze_tx_id,
                user_id=user_id,
                amount=total_amount,
                task_id=task_id,
                model_key=model_key,
                note=f"AI生图成功但 consume 失败，待后台重试",
                last_error=str(consume_res.get("error") or ""),
            )
        if record_id is not None:
            image_gen_models.update_success(
                record_id, images=urls, points_cost=total_amount, status="success"
            )
        # 统一产物总线：登记产物，返回 artifact_ids（失败不阻断生成）
        try:
            artifact_ids = _register_generation_artifacts(
                record_id=record_id,
                urls=urls,
                prompt=prompt,
                model_key=model_key,
                aspect_ratio=aspect_ratio,
                agent_id=agent_id,
                task_id=task_id,
            )
        except Exception as _art_exc:
            logger.warning(f"[ai_design] 产物登记失败（不阻断生成）: {_art_exc}")
            artifact_ids = []
        response = {
            "task_id": task_id,
            "model_key": model_key,
            "aspect_ratio": aspect_ratio,
            "count": count,
            "images": urls,
            "agent_id": agent_id,
            "points": {
                "unit": unit_price,
                "total": total_amount,
                "freeze_tx_id": freeze_tx_id,
                "status": points_status,
            },
            "record_id": record_id,
            # 统一产物 ID：下游（送审 / 发布 / 二次编辑）凭这个 ID 找到产出
            "artifact_ids": artifact_ids,
        }
        if idempotency_key:
            idempotency.complete(user_id, idempotency_key, response)
        return response

    # 失败分支
    client.rollback(freeze_tx_id, note=f"AI生图失败 {model_key}: {failures[:1]}")
    points_status = "rolled_back"
    detail = (
        f"生成失败：{failures[0].get('error')} (已回滚积分 {total_amount})"
        if failures
        else "生成结果为空（已回滚积分）"
    )
    if record_id is not None:
        image_gen_models.update_failed(
            record_id, error_message=detail, status="failed"
        )
    # 对失败也写幂等缓存，避免前端重试时重复冻结。返回 status=502。
    if idempotency_key:
        idempotency.fail(user_id, idempotency_key, {"status": 502, "detail": detail})
    raise HTTPException(status_code=502, detail=detail)


# ──────────────────────────────────────────────────────────────
# HTTP 202 helper（避免依赖 fastapi.responses 顶层）
# ──────────────────────────────────────────────────────────────


try:
    from fastapi.responses import JSONResponse as _JSONResponse  # type: ignore
except Exception:  # pragma: no cover
    _JSONResponse = None


def JSONResponse202(body: Dict[str, Any]):
    if _JSONResponse is not None:
        return _JSONResponse(status_code=202, content=body)
    # fallback：直接返回 dict（FastAPI 会包成 200，但极少触发）
    return {"status": "in_flight", **body}


try:
    from fastapi_app.core.logger import logger  # type: ignore
except Exception:
    logger = None


__all__ = ["router"]
