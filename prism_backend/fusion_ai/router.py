"""
Prism-Fusion 统一路由
━━━━━━━━━━━━━━━━━━━━
将 fusion_ai 所有模块暴露到 /api/fusion/* 前缀下。
在 fastapi_app/api/v1/router.py 中 include_router 注册。

模块:
  /providers       — Provider 注册表（P0）
  /platform-styles — 平台差异化风格（P0）
  /images          — AI 生图（P0）
  /hot-topics      — 热点话题（P0）
  /moderation      — 三层审核（P0）
  /model-market    — 模型广场（P1）
  /skills          — 技能工坊（P1）
  /cognition       — 认知系统（P1）
  /analytics       — NL→SQL 数据分析（P1）
  /config          — 前台配置中心（P1）
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any, List, Optional
import json

from fastapi_app.core.logger import logger

from .provider_registry import (
    list_providers, detect_provider, get_provider_config, build_model_list,
)
from .platform_styles import (
    PLATFORM_STYLES, get_platform_style, get_all_platform_styles,
    apply_platform_style, update_platform_style, delete_platform_override,
    list_platform_ids,
)
from .image_generators import (
    generate_single_image, generate_multi_model,
    list_builtin_models, list_custom_models, add_custom_model,
    remove_custom_model, get_model_def, search_images,
)
from .hot_topics import (
    fetch_hot_topics, fetch_all_hot_topics, fetch_with_cache,
    list_platforms as list_hot_platforms,
)
from .content_moderator import (
    moderate_content, list_sensitive, add_sensitive_word, remove_sensitive_word,
)
from .model_market import (
    list_all_models, get_model_detail, probe_api_keys, recommend_model,
)
from .skill_workshop import (
    list_builtin_skills, list_custom_skills, add_custom_skill,
    remove_custom_skill, apply_skill, apply_skill_chain,
)
from .cognition import (
    analyze_content_dna, evaluate_cognition_matrix,
    infer_audience_persona, detect_content_gaps,
    save_audience_persona, load_audience_persona,
)
from .config_center import (
    list_groups as list_config_groups,
    get_config as get_config_group,
    set_config as set_config_group,
    reset_config as reset_config_group,
)
from .nl_query import NLQueryEngine, get_engine

router = APIRouter(prefix="/fusion", tags=["Prism-Fusion"])


# ============================================================
# 0. 健康检查
# ============================================================
@router.get("/health")
async def fusion_health():
    return {
        "status": "ok",
        "modules": [
            "provider_registry", "platform_styles", "image_generators",
            "hot_topics", "content_moderator", "model_market",
            "skill_workshop", "cognition", "nl_query", "breakdown",
        ],
    }


# ============================================================
# 0.1 内容拆解（商汤 SenseNova 直连）
#     POST /api/v1/fusion/breakdown
#     入参: {"topic": str | "text": str}（二选一）
#     出参: {"status":"success","result":{summary,structure,hooks,beats,insights,actionItems,risks}}
#
#     Key 从 tools/hermes-home/config.yaml 读取（不硬编码、不落日志/响应）；
#     走 openai SDK → https://token.sensenova.cn/v1；429 自动重试 1 次。
# ============================================================
import os as _os
import re as _re
import time as _time
from pathlib import Path as _Path


def _resolve_hermes_config() -> dict:
    """读 tools/hermes-home/config.yaml，取 model.{api_key,base_url,default}。"""
    try:
        import yaml
    except ImportError:
        raise HTTPException(status_code=500, detail="服务端缺少 pyyaml，无法读取模型配置")
    cfg_path = _Path("D:/工作台/Prism-Fusion/tools/hermes-home/config.yaml")
    if not cfg_path.is_file():
        raise HTTPException(status_code=500, detail=f"未找到模型配置文件: {cfg_path}")
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"模型配置解析失败: {e}")
    model_cfg = (data or {}).get("model") or {}
    api_key = (model_cfg.get("api_key") or "").strip()
    base_url = (model_cfg.get("base_url") or "").strip()
    model = (model_cfg.get("default") or "glm-5.2").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="模型配置缺少 api_key")
    if not base_url:
        base_url = "https://token.sensenova.cn/v1"
    return {"api_key": api_key, "base_url": base_url, "model": model}


_BD_SYSTEM_PROMPT = (
    "你是资深内容策划，擅长把一条选题/文案拆解成可执行的结构化要点。"
    "只输出 JSON，不要任何解释、前后缀或 markdown 代码块标记。"
    "JSON 结构严格为："
    '{"summary":"一句话概括","structure":"内容骨架（如 3-2-1 / 总-分-总）",'
    '"hooks":["开头钩子1","开头钩子2"],'
    '"beats":[{"title":"段落/环节标题","detail":"要点说明"}],'
    '"insights":["可复用的观察1","可复用的观察2"],'
    '"actionItems":["下一步动作1"],"risks":["注意点/风险1"]}'
    "如果输入信息不足，用最保守的判断并在 risks 里说明信息缺失，不要编造事实、数据或来源。"
    "整个回答必须是一个合法 JSON 对象（以 { 开头、} 结尾，前后无任何文字）；"
    "beats 必须是 JSON 数组 [ {...}, {...} ]，元素是 {title,detail} 对象，"
    "绝不要使用 * 或 - 等 markdown 列表符号把 beats 拆成多行。"
)


def _strip_fences(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return s
    # ```json\n{...}\n``` 或 ```\n{...}\n```
    if s.startswith("```"):
        nl = s.find("\n")
        if nl > -1:
            tail = s[nl + 1:]
            # 去掉最后一个 ```
            last = tail.rfind("```")
            if last > -1:
                s = tail[:last].strip()
    # 兜底：取第一个 { 到最后一个 }
    a = s.find("{")
    b = s.rfind("}")
    if a > -1 and b > a:
        return s[a:b + 1]
    return s


def _extract_reasoning_content(msg: any) -> str:
    """glm-5.2 推理模型：content 是答案，reasoning_content 是思考。"""
    if msg is None:
        return ""
    rc = getattr(msg, "reasoning_content", None)
    if isinstance(rc, str):
        return rc
    # 部分 SDK 版本会挂到 additional_kwargs / model_extra
    try:
        for attr in ("additional_kwargs", "model_extra"):
            d = getattr(msg, attr, None)
            if isinstance(d, dict) and isinstance(d.get("reasoning_content"), str):
                return d["reasoning_content"]
    except Exception:
        pass
    return ""


@router.post("/breakdown")
async def breakdown_content(request: Request):
    """把选题/文案拆成结构化 JSON（summary/structure/hooks/beats/insights/actionItems/risks）。

    商汤 SenseNova 直连（openai SDK）；429 限速重试 1 次；错误以友好 JSON 返回，不 500 崩。
    Key 只在服务端内存读取，绝不出现在日志或响应里。
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    topic = (body.get("topic") or "").strip()
    text = (body.get("text") or "").strip()
    user_input = topic or text
    if not user_input:
        raise HTTPException(status_code=400, detail="需提供 topic 或 text")
    if len(user_input) < 4:
        raise HTTPException(status_code=400, detail="输入过短（至少 4 字），AI 拆解效果不佳")

    try:
        cfg = _resolve_hermes_config()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Fusion][Breakdown] 读模型配置失败: {e}")
        raise HTTPException(status_code=500, detail="模型配置不可用")

    try:
        from openai import AsyncOpenAI
        from openai import APIStatusError, APIConnectionError, APITimeoutError
    except Exception as e:
        logger.error(f"[Fusion][Breakdown] openai SDK 不可用: {e}")
        raise HTTPException(status_code=500, detail="服务端缺少 openai SDK")

    client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    model = cfg["model"]

    messages = [
        {"role": "system", "content": _BD_SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    last_err: str = ""
    for attempt in (1, 2):
        started = _time.time()
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=2400,
                temperature=0.4,
            )
            msg = resp.choices[0].message if resp.choices else None
            content = (getattr(msg, "content", None) or "").strip()
            reasoning = _extract_reasoning_content(msg)
            if not content and reasoning:
                # 有些推理模型把答案先塞进 reasoning_content（max_tokens 太小时）
                content = reasoning.strip()
            if not content:
                raise RuntimeError("模型未返回内容（reasoning_content 也空）")

            payload = _strip_fences(content)
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as je:
                logger.error(f"[Fusion][Breakdown] JSON 解析失败（attempt={attempt}）：{je}; payload={payload[:200]}")
                if attempt == 1:
                    # 模型偶尔把 beats 写成 * 分隔的 markdown 列表而非 JSON 数组；纠正后重试一次
                    messages = messages + [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": "你刚才的输出不是合法 JSON（beats 不应使用 * 或 - 等 markdown 符号，必须是数组 [...]）。请重新输出，严格只输出一个 JSON 对象，以 { 开头、} 结尾。"},
                    ]
                    last_err = f"JSON 解析失败：{je}"
                    continue
                raise HTTPException(
                    status_code=502,
                    detail="AI 返回的不是有效 JSON（已重试），请稍后重试",
                )

            elapsed = round(_time.time() - started, 2)
            return {
                "status": "success",
                "result": {
                    "summary": str(parsed.get("summary") or ""),
                    "structure": str(parsed.get("structure") or ""),
                    "hooks": parsed.get("hooks") if isinstance(parsed.get("hooks"), list) else [],
                    "beats": parsed.get("beats") if isinstance(parsed.get("beats"), list) else [],
                    "insights": parsed.get("insights") if isinstance(parsed.get("insights"), list) else [],
                    "actionItems": parsed.get("actionItems") if isinstance(parsed.get("actionItems"), list) else [],
                    "risks": parsed.get("risks") if isinstance(parsed.get("risks"), list) else [],
                    "_meta": {
                        "model": model,
                        "provider": "SenseNova",
                        "elapsed_seconds": elapsed,
                        "attempt": attempt,
                        "input_chars": len(user_input),
                    },
                },
            }
        except HTTPException:
            raise
        except APIStatusError as e:
            status = getattr(e, "status_code", None)
            last_err = f"API {status}: {str(e)[:200]}"
            if status == 429 and attempt == 1:
                # 商汤 rpm 限速，等一会重试
                await _asyncio_sleep(2.0)
                continue
            logger.warning(f"[Fusion][Breakdown] API 错误: {last_err}")
            raise HTTPException(status_code=502, detail=f"模型服务暂不可用：{last_err}")
        except (APIConnectionError, APITimeoutError) as e:
            last_err = f"连接失败：{str(e)[:200]}"
            if attempt == 1:
                await _asyncio_sleep(1.5)
                continue
            logger.warning(f"[Fusion][Breakdown] {last_err}")
            raise HTTPException(status_code=502, detail=f"模型服务连接失败：{last_err}")
        except RuntimeError as e:
            last_err = str(e)
            raise HTTPException(status_code=502, detail=f"模型返回异常：{last_err}")
        except Exception as e:
            last_err = str(e)
            logger.error(f"[Fusion][Breakdown] 未知错误: {e}")
            raise HTTPException(status_code=500, detail=f"拆解失败：{last_err[:200]}")

    # 理论上不会走到（两次尝试都 return 或 raise）
    raise HTTPException(status_code=502, detail=f"拆解失败：{last_err}")


async def _asyncio_sleep(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)


# ============================================================
# 1. Provider 注册表
# ============================================================
@router.get("/providers")
async def get_providers(include_models: bool = False):
    return {"providers": list_providers(include_models=include_models)}


@router.get("/providers/detect")
async def detect_current_provider():
    return detect_provider()


@router.get("/providers/models")
async def get_all_models():
    return {"models": build_model_list()}


@router.get("/providers/{provider_id}")
async def get_provider(provider_id: str):
    cfg = get_provider_config(provider_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="未知 provider")
    return cfg


# ============================================================
# 2. 平台差异化风格
# ============================================================
@router.get("/platform-styles")
async def list_platform_styles():
    return {"styles": get_all_platform_styles()}


@router.get("/platform-styles/{platform}")
async def get_style(platform: str):
    style = get_platform_style(platform)
    if not style:
        raise HTTPException(status_code=404, detail="未知平台")
    return style


@router.put("/platform-styles/{platform}")
async def update_style(platform: str, request: Request):
    body = await request.json()
    data = get_all_platform_styles()
    data[platform] = {**data.get(platform, {}), **body}
    return update_platform_style(platform, body)


@router.delete("/platform-styles/{platform}")
async def reset_style(platform: str):
    return {"removed": delete_platform_override(platform)}


@router.post("/platform-styles/apply")
async def apply_style_request(request: Request):
    body = await request.json()
    content = body.get("content", "")
    platform = body.get("platform", "zhihu")
    return apply_platform_style(content, platform)


# ============================================================
# 3. AI 生图
# ============================================================
@router.get("/images/models")
async def list_image_models():
    return {
        "builtin": list_builtin_models(),
        "custom": list_custom_models(),
    }


@router.post("/images/generate")
async def gen_image(request: Request):
    body = await request.json()
    model_id = body.get("model_id")
    prompt = body.get("prompt", "")
    size = body.get("size", "1024x1024")

    mdef = get_model_def(model_id)
    if not mdef:
        raise HTTPException(status_code=404, detail=f"未知生图模型: {model_id}")

    result = await generate_single_image(mdef, prompt, size)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "生图失败"))
    return result


@router.post("/images/generate-batch")
async def gen_images_batch(request: Request):
    body = await request.json()
    model_ids = body.get("model_ids", [])
    prompt = body.get("prompt", "")
    size = body.get("size", "1024x1024")
    return {"results": await generate_multi_model(model_ids, prompt, size)}


@router.post("/images/models/custom")
async def add_image_model(request: Request):
    body = await request.json()
    return add_custom_model(body)


@router.delete("/images/models/custom/{model_id}")
async def remove_image_model(model_id: str):
    return {"removed": remove_custom_model(model_id)}


@router.post("/images/search")
async def search_image_api(request: Request):
    body = await request.json()
    query = body.get("query", "")
    count = body.get("count", 10)
    results = await search_images(query, count)
    return {"results": results}


# ============================================================
# 4. 热点话题
# ============================================================
@router.get("/hot-topics/platforms")
async def list_hot_platforms():
    return {"platforms": list_hot_platforms()}


@router.get("/hot-topics/all")
async def get_all_hot_topics():
    return await fetch_all_hot_topics()


@router.get("/hot-topics/{platform}")
async def get_hot_topics(platform: str, cached: bool = True):
    if cached:
        return await fetch_with_cache(platform)
    return {"platform": platform, "topics": await fetch_hot_topics(platform), "from_cache": False}


# ============================================================
# 5. 三层内容审核
# ============================================================
@router.post("/moderation/check")
async def moderate(request: Request):
    body = await request.json()
    content = body.get("content", "")
    result = await moderate_content(
        content,
        enable_layer1=body.get("enable_layer1", True),
        enable_layer2=body.get("enable_layer2", True),
        enable_layer3=body.get("enable_layer3", True),
    )
    return result


@router.get("/moderation/sensitive-words")
async def get_sensitive_words():
    return {"words": list_sensitive()}


@router.post("/moderation/sensitive-words")
async def add_sens_word(request: Request):
    body = await request.json()
    return {"words": add_sensitive_word(body["category"], body["word"])}


@router.delete("/moderation/sensitive-words")
async def del_sens_word(category: str, word: str):
    return {"words": remove_sensitive_word(category, word)}


# ============================================================
# 6. 模型广场
# ============================================================
@router.get("/model-market/models")
async def list_market_models():
    return {"models": list_all_models()}


@router.get("/model-market/models/{model_id}")
async def market_model_detail(model_id: str):
    return get_model_detail(model_id)


@router.get("/model-market/api-keys")
async def market_keys():
    return {"keys": probe_api_keys()}


@router.get("/model-market/recommend")
async def market_recommend(use_case: str = "writing"):
    return recommend_model(use_case)


# ============================================================
# 7. 技能工坊
# ============================================================
@router.get("/skills/builtin")
async def get_builtin_skills():
    return {"skills": list_builtin_skills()}


@router.get("/skills/custom")
async def get_custom_skills():
    return {"skills": list_custom_skills()}


@router.post("/skills/custom")
async def create_skill(request: Request):
    body = await request.json()
    return add_custom_skill(body)


@router.delete("/skills/custom/{skill_id}")
async def delete_skill(skill_id: str):
    return {"removed": remove_custom_skill(skill_id)}


@router.post("/skills/apply")
async def apply_skill_api(request: Request):
    body = await request.json()
    return apply_skill(body["content"], body["skill_id"], **{k: v for k, v in body.items() if k not in ("content", "skill_id")})


@router.post("/skills/apply-chain")
async def apply_chain_api(request: Request):
    body = await request.json()
    return apply_skill_chain(body["content"], body.get("skill_ids", []), **{k: v for k, v in body.items() if k not in ("content", "skill_ids")})


# ============================================================
# 8. 认知系统
# ============================================================
@router.post("/cognition/dna")
async def dna_analysis(request: Request):
    body = await request.json()
    dna = analyze_content_dna(body.get("content", ""))
    return {"dna": dna}


@router.post("/cognition/matrix")
async def matrix_analysis(request: Request):
    body = await request.json()
    dna = analyze_content_dna(body.get("content", ""))
    return {"matrix": evaluate_cognition_matrix(body.get("content", ""), dna)}


@router.post("/cognition/audience")
async def audience_analysis(request: Request):
    body = await request.json()
    dna = analyze_content_dna(body.get("content", ""))
    return {"audience": infer_audience_persona(body.get("content", ""), dna)}


@router.post("/cognition/gaps")
async def gap_detection(request: Request):
    body = await request.json()
    own = body.get("own_topics", [])
    hot = body.get("hot_topics", [])
    return await detect_content_gaps(own, hot)


@router.get("/cognition/persona")
async def get_persona():
    return load_audience_persona()


@router.post("/cognition/persona")
async def save_persona(request: Request):
    body = await request.json()
    save_audience_persona(body)
    return {"success": True}


# ============================================================
# 9. NL→SQL 数据分析
# ============================================================
@router.post("/analytics/query")
async def nl_query_api(request: Request):
    body = await request.json()
    question = body.get("question", "")
    if not question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    try:
        engine = get_engine()
        result = engine.query(question)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analytics/presets")
async def get_presets():
    engine = get_engine()
    return {"presets": engine.list_presets()}


# ============================================================
# 10. 前台配置中心（敏感词/风格覆盖等统一入口）
# ============================================================
# ---------- 通用配置组（20 组 CRUD）----------
@router.get("/config/groups")
async def config_groups_list():
    return {"groups": list_config_groups()}


@router.get("/config/sensitive-words")
async def get_config_sensitive():
    return {"words": list_sensitive()}


@router.post("/config/sensitive-words")
async def post_config_sensitive(request: Request):
    body = await request.json()
    return {"words": add_sensitive_word(body["category"], body["word"])}


@router.delete("/config/sensitive-words")
async def del_config_sensitive(category: str, word: str):
    return {"words": remove_sensitive_word(category, word)}


@router.get("/config/{config_id}")
async def config_group_get(config_id: str):
    result = get_config_group(config_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"未知配置组: {config_id}")
    return result


@router.post("/config/{config_id}")
async def config_group_set(config_id: str, request: Request):
    body = await request.json()
    try:
        return set_config_group(config_id, body.get("value"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/config/{config_id}")
async def config_group_reset(config_id: str):
    try:
        return reset_config_group(config_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))