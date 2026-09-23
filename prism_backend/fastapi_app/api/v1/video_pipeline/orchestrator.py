"""视频编排 8 阶段状态机（research→proposal★→script★→scene_plan★→assets★→edit→compose→publish★）。

- 商汤 SenseNova (glm-5.2) 直连，模式抄 fusion_ai/router.py 的 breakdown
- 每阶段产出结构化 JSON artifact；compose 阶段生成 HyperFrames index.html 并真渲染
- run 状态持久化到 data/video-pipeline/runs/{run_id}.json
- 阶段失败不崩后端，友好写入 failed 状态
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import time as _time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger

from .render import run_hyperframes_render as _run_hyperframes_render

_RUNS_DIR = Path(settings.DATA_DIR) / "video-pipeline" / "runs"
_MAX_REVISIONS_PER_STAGE = 3

# 阶段顺序 = 执行顺序；checkpoint=True 表示该阶段完成后暂停等用户批准
STAGES: list[dict] = [
    {"name": "research",    "label": "选题研究", "produces": ["research_brief"],                      "checkpoint": False},
    {"name": "proposal",    "label": "创意提案", "produces": ["proposal_packet", "decision_log"],     "checkpoint": True},
    {"name": "script",      "label": "脚本撰写", "produces": ["script"],                              "checkpoint": True},
    {"name": "scene_plan",  "label": "分镜规划", "produces": ["scene_plan"],                          "checkpoint": True},
    {"name": "assets",      "label": "素材清单", "produces": ["asset_manifest"],                      "checkpoint": True},
    {"name": "edit",        "label": "剪辑决策", "produces": ["edit_decisions"],                      "checkpoint": False},
    {"name": "compose",     "label": "合成渲染", "produces": ["render_report", "final_review"],      "checkpoint": False},
    {"name": "publish",     "label": "发布准备", "produces": ["publish_log"],                         "checkpoint": True},
]
_STAGES_BY_NAME = {s["name"]: s for s in STAGES}


# ==================== 模板素材库（E:\FDE\fde-landing-delivery，542 专业模板）====================
_TEMPLATE_LIB_DIR = Path(r"E:\FDE\fde-landing-delivery")
_catalog_cache: dict | None = None


def _load_catalog() -> dict:
    """加载 catalog.json（542 模板 + schema 索引 + backgrounds 底图）。模块级缓存。"""
    global _catalog_cache
    if _catalog_cache is None:
        try:
            _catalog_cache = json.loads((_TEMPLATE_LIB_DIR / "catalog.json").read_text(encoding="utf-8"))
            logger.info(f"[VideoPipeline] 模板库加载：{_catalog_cache.get('count', 0)} 模板")
        except Exception as e:
            logger.error(f"[VideoPipeline] 模板库加载失败: {e}")
            _catalog_cache = {"templates": [], "backgrounds": [], "count": 0}
    return _catalog_cache


def _template_dir(template_id: str) -> Path:
    return _TEMPLATE_LIB_DIR / "templates" / template_id


def _catalog_digest() -> str:
    """给 AI 看的精简目录：按 category 分组，每模板 id|name。控制 prompt 体积。"""
    cat = _load_catalog()
    by_cat: dict[str, list[str]] = {}
    for t in cat.get("templates", []):
        c = t.get("category") or "未分类"
        by_cat.setdefault(c, []).append(f"{t['id']}|{t.get('name', '')}")
    lines = []
    for c, items in by_cat.items():
        lines.append(f"【{c}】({len(items)})")
        lines.extend(items)
    return "\n".join(lines)


def _template_schema(template_id: str) -> list:
    """取某模板的 schema 变量定义 [{id,label,type,default}, ...]。"""
    cat = _load_catalog()
    for t in cat.get("templates", []):
        if t.get("id") == template_id:
            return t.get("schema") or []
    return []


def _template_meta(template_id: str) -> dict | None:
    """取某模板的完整元数据（id/name/description/category/tags/duration/size/schema）。"""
    cat = _load_catalog()
    for t in cat.get("templates", []):
        if t.get("id") == template_id:
            return t
    return None


# ==================== 模型配置 ====================
def _resolve_model_config() -> dict:
    try:
        import yaml
    except ImportError:
        raise HTTPException(status_code=500, detail="服务端缺少 pyyaml，无法读取模型配置")
    cfg_path = Path("D:/工作台/Prism-Fusion/tools/hermes-home/config.yaml")
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


def _strip_fences(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return s
    if s.startswith("```"):
        nl = s.find("\n")
        if nl > -1:
            tail = s[nl + 1:]
            last = tail.rfind("```")
            if last > -1:
                s = tail[:last].strip()
    a = s.find("{")
    b = s.rfind("}")
    if a > -1 and b > a:
        return s[a:b + 1]
    return s


def _extract_reasoning_content(msg) -> str:
    if msg is None:
        return ""
    rc = getattr(msg, "reasoning_content", None)
    if isinstance(rc, str):
        return rc
    try:
        for attr in ("additional_kwargs", "model_extra"):
            d = getattr(msg, attr, None)
            if isinstance(d, dict) and isinstance(d.get("reasoning_content"), str):
                return d["reasoning_content"]
    except Exception:
        pass
    return ""


async def _ai_json(system_prompt: str, user_prompt: str, max_tokens: int = 3200, temperature: float = 0.4) -> dict:
    """调 glm-5.2 拿 JSON（429 重试 1 次 + JSON 格式纠正重试 1 次）。Key 不落日志/响应。"""
    try:
        from openai import AsyncOpenAI, APIStatusError, APIConnectionError, APITimeoutError
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务端缺少 openai SDK: {e}")
    cfg = _resolve_model_config()
    client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_err = ""
    for attempt in (1, 2):
        started = _time.time()
        try:
            resp = await client.chat.completions.create(
                model=cfg["model"],
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            msg = resp.choices[0].message if resp.choices else None
            content = (getattr(msg, "content", None) or "").strip()
            reasoning = _extract_reasoning_content(msg)
            if not content and reasoning:
                content = reasoning.strip()
            if not content:
                raise RuntimeError("模型未返回内容")
            payload = _strip_fences(content)
            parsed = None
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as je:
                logger.warning(f"[VideoPipeline] AI JSON 解析失败 attempt={attempt}: {je}; head={payload[:120]}")
                # salvage：试 json_repair 修常见缺逗号/尾逗号/未闭合括号
                try:
                    from json_repair import repair_json
                    repaired = repair_json(payload)
                    if isinstance(repaired, dict) and repaired:
                        parsed = repaired
                        logger.info(f"[VideoPipeline] AI JSON salvage 修复成功 attempt={attempt}")
                except Exception as re_err:
                    logger.warning(f"[VideoPipeline] salvage 失败: {re_err}")
            if parsed is not None:
                elapsed = round(_time.time() - started, 2)
                logger.info(f"[VideoPipeline] AI JSON ok attempt={attempt} elapsed={elapsed}s chars={len(content)}")
                return parsed
            # json.loads + salvage 都失败 → 纠正重试（attempt 1）或 502（attempt 2）
            if attempt == 1:
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": "你刚才的输出不是合法 JSON。请重新输出，严格只输出一个 JSON 对象，以 { 开头、} 结尾；不要 markdown 代码块，不要 * 或 - 列表符号，所有数组必须是 [...]。"},
                ]
                last_err = f"JSON 解析失败（json_repair 也无法修复）"
                continue
            raise HTTPException(status_code=502, detail=f"AI 返回的不是有效 JSON（已重试+salvage）: {last_err[:200]}")
        except HTTPException:
            raise
        except APIStatusError as e:
            status = getattr(e, "status_code", None)
            last_err = f"API {status}: {str(e)[:200]}"
            if status == 429 and attempt == 1:
                await asyncio.sleep(3.0)
                continue
            raise HTTPException(status_code=502, detail=f"模型服务暂不可用（商汤限速或故障，可稍后 /approve 继续）：{last_err}")
        except (APIConnectionError, APITimeoutError) as e:
            last_err = f"连接失败：{str(e)[:200]}"
            if attempt == 1:
                await asyncio.sleep(1.5)
                continue
            raise HTTPException(status_code=502, detail=f"模型服务连接失败：{last_err}")
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=f"模型返回异常：{e}")
        except Exception as e:
            logger.error(f"[VideoPipeline] AI 未知错误: {e}")
            raise HTTPException(status_code=500, detail=f"AI 调用失败：{str(e)[:200]}")
    raise HTTPException(status_code=502, detail=f"AI 调用失败：{last_err}")


# ==================== run 持久化 ====================
def _run_path(run_id: str) -> Path:
    return _RUNS_DIR / f"{run_id}.json"


def _save_run(run: dict) -> None:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    _run_path(run["run_id"]).write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_run(run_id: str) -> Optional[dict]:
    p = _run_path(run_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[VideoPipeline] run 读取失败 {run_id}: {e}")
        return None


def _new_run(topic: str, style: str, reference_url: str, budget_usd: float) -> dict:
    run_id = uuid.uuid4().hex[:12]
    now = _dt.datetime.now().replace(microsecond=0).isoformat()
    return {
        "run_id": run_id,
        "topic": topic,
        "style": style,
        "reference_url": reference_url,
        "budget_usd": budget_usd,
        "status": "running",
        "stage_index": 0,
        "current_stage": STAGES[0]["name"],
        "completed": [],
        "artifacts": {},
        "pending_approval": None,
        "revisions": {},
        "history": [],
        "error": None,
        "created_at": now,
        "updated_at": now,
    }


def _now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def _log_history(run: dict, action: str, note: str = "") -> None:
    run["history"].append({"stage": run["current_stage"], "ts": _now_iso(), "action": action, "note": note})
    run["updated_at"] = _now_iso()


# ==================== 各阶段 prompt ====================
def _stage_prompt(stage_name: str, topic: str, style: str, artifacts: dict) -> tuple[str, str, int]:
    if stage_name == "research":
        system = (
            "你是资深内容研究员。为短视频选题输出结构化研究简报。"
            "只输出一个 JSON 对象，不要 markdown 代码块，不要任何前后解释。"
        )
        user = (
            f"选题：{topic}\n目标风格：{style or '默认'}\n"
            "要求：3+ data_points（value/claim/source_hint），3+ angles（title/grounded_in/rationale），"
            "5+ sources（name/url/type；URL 可占位但结构正确），1+ audience_questions。\n"
            "JSON schema: {\"topic\":\"...\",\"summary\":\"...\",\"data_points\":[{\"value\":\"...\",\"claim\":\"...\",\"source_hint\":\"...\"}],"
            "\"angles\":[{\"title\":\"...\",\"grounded_in\":\"...\",\"rationale\":\"...\"}],"
            "\"sources\":[{\"name\":\"...\",\"url\":\"https://...\",\"type\":\"web|paper|forum\"}],"
            "\"audience_questions\":[\"...\"],\"risks\":[\"...\"]}"
        )
        return system, user, 2800

    if stage_name == "proposal":
        research = artifacts.get("research_brief")
        system = "你是创意总监。基于研究简报出 3 个明显不同的短视频创意提案，标注推荐项。只输出一个 JSON 对象。"
        user = (
            f"选题：{topic}\n研究简报：{json.dumps(research, ensure_ascii=False)}\n"
            "要求：3 个 concept_options（concept_id/title/structure/hook/audience/estimated_duration_seconds/line_items），"
            "selected_concept 指向 concept_id，decision_log 数组，risk_notes。\n"
            "JSON schema: {\"concept_options\":[{\"concept_id\":\"A\",\"title\":\"...\",\"structure\":\"...\",\"hook\":\"...\",\"audience\":\"...\",\"estimated_duration_seconds\":45,"
            "\"line_items\":[{\"tool\":\"tts\",\"cost_usd\":0.2,\"note\":\"...\"}],\"total_cost_usd\":0.5}],"
            "\"selected_concept\":\"A\",\"decision_log\":[{\"stage\":\"proposal\",\"decision\":\"select A\",\"reason\":\"...\"}],\"risk_notes\":[\"...\"]}"
        )
        return system, user, 3200

    if stage_name == "script":
        proposal = artifacts.get("proposal_packet")
        research = artifacts.get("research_brief")
        system = "你是资深短视频编剧。基于已选 concept 写脚本。只输出一个 JSON 对象。"
        user = (
            f"选题：{topic}\n提案：{json.dumps(proposal, ensure_ascii=False)}\n研究（参考）：{json.dumps(research, ensure_ascii=False)}\n"
            "要求：sections[]（section_id/text/enhancement_cues 数组/speaker_directions），"
            "total_duration_seconds 与 concept 一致（±10%），voice_performance 含 pacing/pause_seconds/sample_phrase，cited_facts 引用 data_points。\n"
            "JSON schema: {\"total_duration_seconds\":45,\"sections\":[{\"section_id\":\"s1\",\"text\":\"...\",\"enhancement_cues\":[\"...\"],\"speaker_directions\":\"...\"}],"
            "\"voice_performance\":{\"pacing\":\"...\",\"pause_seconds\":0.5,\"sample_phrase\":\"...\"},\"cited_facts\":[\"...\"]}"
        )
        return system, user, 3200

    if stage_name == "scene_plan":
        script = artifacts.get("script")
        proposal = artifacts.get("proposal_packet")
        system = "你是分镜师。基于脚本产出分镜。只输出一个 JSON 对象。"
        user = (
            f"脚本：{json.dumps(script, ensure_ascii=False)}\n提案（参考）：{json.dumps(proposal, ensure_ascii=False)}\n"
            "要求：scenes[]（scene_id/type/duration_seconds/required_assets 数组/narration_ref），"
            "type 至少 3 种（title/intro/bullet/quote/summary/call_to_action/data_card），"
            "required_assets 引用 asset_id（as_tts_s1/as_bg/as_img_s2），narration_ref 指向 section_id。\n"
            "JSON schema: {\"scenes\":[{\"scene_id\":\"sc1\",\"type\":\"title\",\"duration_seconds\":3,\"required_assets\":[\"as_tts_s1\",\"as_bg\"],\"narration_ref\":\"s1\",\"visual_note\":\"...\"}],\"total_duration_seconds\":45}"
        )
        return system, user, 3200

    if stage_name == "assets":
        scene_plan = artifacts.get("scene_plan")
        script = artifacts.get("script")
        system = "你是素材总监。产出 asset_manifest（清单，不实际生成文件）。只输出一个 JSON 对象。"
        user = (
            f"分镜：{json.dumps(scene_plan, ensure_ascii=False)}\n脚本：{json.dumps(script, ensure_ascii=False)}\n"
            "要求：assets[]（asset_id/type/tts_text 或 image_prompt 或 music_prompt/dest_scene 数组/estimated_cost_usd/generation_status=\"manifest_only\"），"
            "汇总 total_cost_usd，标注 generation_status=\"manifest_only\"（未实际生成图片/TTS，仅清单）。\n"
            "JSON schema: {\"generation_status\":\"manifest_only\",\"assets\":[{\"asset_id\":\"as_tts_s1\",\"type\":\"tts\",\"tts_text\":\"...\",\"dest_scene\":[\"sc1\"],\"estimated_cost_usd\":0.2,\"generation_status\":\"manifest_only\"}],\"total_cost_usd\":1.5,\"estimated_render_cost_usd\":0.3}"
        )
        return system, user, 3200

    if stage_name == "edit":
        scene_plan = artifacts.get("scene_plan")
        assets = artifacts.get("asset_manifest")
        script = artifacts.get("script")
        system = "你是剪辑师。基于分镜 + 素材清单产出 edit_decisions。只输出一个 JSON 对象。"
        user = (
            f"分镜：{json.dumps(scene_plan, ensure_ascii=False)}\n素材：{json.dumps(assets, ensure_ascii=False)}\n脚本（参考）：{json.dumps(script, ensure_ascii=False)}\n"
            "要求：cuts[]（scene_id/start_second/end_second/required_assets/transition_in/transition_out），"
            "subtitles 含 enabled/font/color/position，music 含 ducking 参数，render_runtime=\"hyperframes\"。\n"
            "JSON schema: {\"render_runtime\":\"hyperframes\",\"cuts\":[{\"scene_id\":\"sc1\",\"start_second\":0,\"end_second\":3,\"required_assets\":[\"as_tts_s1\"],\"transition_in\":\"fade\",\"transition_out\":\"cut\"}],\"subtitles\":{\"enabled\":true,\"font\":\"Inter\",\"color\":\"#fff\",\"position\":\"bottom\"},\"music\":{\"ducking\":true,\"speech_ducker_db\":-12}}"
        )
        return system, user, 3200

    if stage_name == "publish":
        render_report = artifacts.get("render_report")
        proposal = artifacts.get("proposal_packet")
        system = "你是发布总监。产出 publish_log（含 SEO 元数据）。只输出一个 JSON 对象。"
        user = (
            f"渲染报告：{json.dumps(render_report, ensure_ascii=False)}\n提案（参考）：{json.dumps(proposal, ensure_ascii=False)}\n选题：{topic}\n"
            "要求：title/description/tags 数组/hashtags 数组/chapters[]（title/time_seconds）/cross_posts 平台建议。\n"
            "JSON schema: {\"title\":\"...\",\"description\":\"...\",\"tags\":[\"...\"],\"hashtags\":[\"#...\"],\"chapters\":[{\"title\":\"...\",\"time_seconds\":0}],\"cross_posts\":[{\"platform\":\"douyin\",\"aspect\":\"9:16\"}]}"
        )
        return system, user, 2400

    raise ValueError(f"未知阶段: {stage_name}")


# ==================== compose 阶段：从素材库选模板 + 填参（替代 AI 从零写 HTML）====================
async def _compose_select_template(topic: str, script: dict, scene_plan: dict, edit_decisions: dict) -> dict:
    """步骤1：AI 从素材库选一个最适合的模板。返回 {template_id, rationale}。"""
    digest = _catalog_digest()
    sections = (script or {}).get("sections") or [{}]
    system = (
        "你是视频合成导演。从给定的 HyperFrames 模板库里选**一个**最适合本视频的模板。"
        "只输出一个 JSON 对象，不要 markdown 代码块，不要解释。"
    )
    user = (
        f"选题：{topic}\n"
        f"脚本首段：{json.dumps(sections[0], ensure_ascii=False)[:300]}\n"
        f"分镜类型：{[s.get('type') for s in (scene_plan or {}).get('scenes', [])]}\n"
        f"渲染引擎：{(edit_decisions or {}).get('render_runtime', 'hyperframes')}\n\n"
        f"模板库目录（id|name，按分类）：\n{digest}\n\n"
        "要求：从上面的 id 里选 1 个 template_id（必须完全匹配列出的 id），给出 rationale。\n"
        'JSON: {"template_id":"上面列出的某个 id","rationale":"为什么选这个模板（贴合选题/脚本）"}'
    )
    return await _ai_json(system, user, max_tokens=800)


async def _compose_fill_variables(template_id: str, topic: str, script: dict, scene_plan: dict) -> dict:
    """步骤2：AI 为选中模板的 schema 变量填值。返回 variables dict。"""
    schema = _template_schema(template_id)
    if not schema:
        return {}
    system = (
        "你正在为一段视频的视觉模板填参数。只输出一个 JSON 对象：变量 id → 值。"
        "不要 markdown 代码块，不要解释。值的类型必须匹配 schema 声明的 type（text 给字符串，number 给数字）。"
    )
    schema_desc = json.dumps(
        [{k: f.get(k) for k in ("id", "label", "type", "default")} for f in schema],
        ensure_ascii=False,
    )
    sections = (script or {}).get("sections") or [{}]
    user = (
        f"选题：{topic}\n"
        f"脚本首段：{json.dumps(sections[0], ensure_ascii=False)[:400]}\n"
        f"模板变量定义：{schema_desc}\n\n"
        "为每个变量填一个贴合视频内容的值。只输出 {变量id: 值}。"
    )
    return await _ai_json(system, user, max_tokens=1200)


# ==================== compose 阶段专用：程序化生成 HyperFrames index.html（fallback）====================
def _html_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _compose_index_html(script: dict, scene_plan: dict, edit_decisions: dict, asset_manifest: dict, topic: str) -> str:
    """按 scene_plan 程序化生成 HyperFrames composition（HTML+GSAP）。

    不依赖 AI（语法严格），文本直接来自 script.sections + scene_plan。
    图片资源用色块+文字卡占位（assets 未实际生成）。
    """
    scenes = (scene_plan or {}).get("scenes") or []
    sections = (script or {}).get("sections") or []
    sections_by_id = {s.get("section_id"): s for s in sections}
    total_dur = float((scene_plan or {}).get("total_duration_seconds")
                      or (script or {}).get("total_duration_seconds") or 45)
    palette = ["#0f172a", "#1e293b", "#0b1220", "#134e4a", "#3b0764", "#312e81", "#7c2d12", "#713f12"]

    scene_blocks = []
    cursor = 0.0
    for i, sc in enumerate(scenes):
        dur = float(sc.get("duration_seconds") or 3)
        start = round(cursor, 2)
        cursor = round(cursor + dur, 2)
        sc_id = sc.get("scene_id", f"sc{i+1}")
        sc_type = sc.get("type", "intro")
        narr_ref = sc.get("narration_ref")
        section = sections_by_id.get(narr_ref, {}) if narr_ref else {}
        text = (section.get("text") or sc.get("visual_note") or "…").strip()
        if len(text) > 60:
            text = text[:60] + "…"
        cues = section.get("enhancement_cues") or []
        cue_html = f'<div class="cue">{_html_escape(cues[0])}</div>' if cues else ""
        bg = palette[i % len(palette)]
        big = sc_type in ("title", "hook", "call_to_action", "quote")
        fs = 128 if big else (88 if sc_type in ("intro", "summary") else 72)
        align = "center" if big else "left"
        scene_blocks.append(
            f'<div id="{sc_id}" class="clip" data-start="{start}" data-duration="{dur}" data-track-index="{i+1}" '
            f'style="position:absolute;inset:0;background:{bg};display:flex;align-items:center;justify-content:{align};flex-direction:column;padding:120px;opacity:0">'
            f'<div style="color:#94a3b8;font-size:28px;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:24px">{_html_escape(sc_type)} · {_html_escape(sc_id)}</div>'
            f'<div style="color:#fff;font-size:{fs}px;font-weight:700;line-height:1.15;max-width:1600px;text-align:{align}">{_html_escape(text)}</div>'
            f'{cue_html}</div>'
        )

    outro_start = round(cursor, 2)
    if outro_start < total_dur:
        outro_dur = round(total_dur - outro_start, 2)
        scene_blocks.append(
            f'<div id="outro" class="clip" data-start="{outro_start}" data-duration="{outro_dur}" data-track-index="99" '
            f'style="position:absolute;inset:0;background:#0b1220;display:flex;align-items:center;justify-content:center;opacity:0">'
            f'<div style="color:#fff;font-size:96px;font-weight:800;letter-spacing:0.05em">— END —</div></div>'
        )

    tl_lines = []
    cursor = 0.0
    for sc in scenes:
        sc_id = sc.get("scene_id", "")
        dur = float(sc.get("duration_seconds") or 3)
        start = round(cursor, 2)
        cursor = round(cursor + dur, 2)
        fade_dur = min(0.6, dur * 0.2)
        tl_lines.append(
            f'tl.fromTo("#{sc_id}", {{opacity:0, scale:1.04}}, '
            f'{{opacity:1, scale:1, duration:{fade_dur}, ease:"power2.out"}}, {start});'
        )
        tl_lines.append(
            f'tl.to("#{sc_id}", {{opacity:0, duration:{fade_dur}, ease:"power2.in"}}, {round(start+dur-fade_dur,2)});'
        )
    if outro_start < total_dur:
        tl_lines.append(
            f'tl.fromTo("#outro", {{opacity:0, scale:0.96}}, {{opacity:1, scale:1, duration:0.8, ease:"power2.out"}}, {outro_start});'
        )
    tl_src = "\n  ".join(tl_lines) if tl_lines else "// no timeline"

    return (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"UTF-8\" />\n"
        "<meta name=\"viewport\" content=\"width=1920, height=1080\" />\n"
        "<script src=\"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js\"></script>\n"
        "<style>\n* { margin:0; padding:0; box-sizing:border-box; }\n"
        "html, body { width:1920px; height:1080px; overflow:hidden; background:#000; }\n"
        "body { font-family: \"Inter\", \"PingFang SC\", \"Microsoft YaHei\", sans-serif; }\n"
        ".cue { color:#fbbf24; font-size:32px; font-weight:500; margin-top:40px; max-width:1400px; text-align:center; }\n"
        "</style>\n</head>\n<body>\n"
        f'<div id="root" data-composition-id="main" data-start="0" data-duration="{total_dur}" data-width="1920" data-height="1080">\n'
        f'  <div style="position:absolute;top:40px;right:48px;color:#64748b;font-size:20px;letter-spacing:0.2em;z-index:100">PRISM · {_html_escape(topic[:24])}</div>\n'
        f'  {"".join(scene_blocks)}\n'
        "</div>\n<script>\n  window.__timelines = window.__timelines || {};\n"
        "  const tl = gsap.timeline({ paused: true });\n"
        f"  {tl_src}\n"
        "  window.__timelines[\"main\"] = tl;\n</script>\n</body>\n</html>\n"
    )


def _write_composition(run_id: str, index_html: str) -> Path:
    comp_dir = _RUNS_DIR / run_id / "composition"
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "index.html").write_text(index_html, encoding="utf-8")
    if not (comp_dir / "hyperframes.json").exists():
        (comp_dir / "hyperframes.json").write_text(json.dumps({
            "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
            "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
            "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
            "media": {"autoProxy": True},
        }, indent=2), encoding="utf-8")
    if not (comp_dir / "package.json").exists():
        (comp_dir / "package.json").write_text(json.dumps({
            "name": f"run-{run_id}", "private": True, "type": "module",
            "scripts": {"render": "npx --yes hyperframes@0.8.20 render"},
        }, indent=2), encoding="utf-8")
    return comp_dir


# ==================== 阶段执行 ====================
def _stage_needs_approval(stage_name: str) -> bool:
    return bool(_STAGES_BY_NAME.get(stage_name, {}).get("checkpoint"))


async def _execute_stage(run: dict, stage_name: str) -> dict:
    """执行一个阶段。返回产出 artifact。"""
    stage_meta = _STAGES_BY_NAME[stage_name]
    run["current_stage"] = stage_name
    run["stage_index"] = STAGES.index(stage_meta)
    run["status"] = "running"
    _log_history(run, "stage_start")
    _save_run(run)
    started = _time.time()

    if stage_name == "compose":
        # 从素材库选模板 + AI 填参 → hyperframes render（失败 fallback 程序化生成 HTML）
        script = run["artifacts"].get("script") or {}
        scene_plan = run["artifacts"].get("scene_plan") or {}
        edit_decisions = run["artifacts"].get("edit_decisions") or {}
        asset_manifest = run["artifacts"].get("asset_manifest") or {}
        topic = run.get("topic", "")

        template_id = None
        variables: dict = {}
        comp_dir = None
        source = "fallback"

        try:
            sel = await _compose_select_template(topic, script, scene_plan, edit_decisions)
            tid = (sel.get("template_id") or "").strip()
            tdir = _template_dir(tid)
            if tid and tdir.is_dir():
                template_id = tid
                variables = await _compose_fill_variables(tid, topic, script, scene_plan)
                comp_dir = tdir
                source = f"library:{tid}"
                _log_history(run, "template_selected", f"{tid} · {sel.get('rationale','')[:80]}")
                logger.info(f"[VideoPipeline] compose 选模板 {tid} variables={list(variables.keys())}")
            else:
                logger.warning(f"[VideoPipeline] AI 选的模板不可用: {tid!r}，回退程序化生成")
        except Exception as e:
            logger.warning(f"[VideoPipeline] compose 选模板失败，回退程序化生成: {e}")

        if comp_dir is None:
            html = _compose_index_html(script, scene_plan, edit_decisions, asset_manifest, topic)
            comp_dir = _write_composition(run["run_id"], html)

        # 指定输出到 run 目录（不污染模板库目录）
        out_dir = _RUNS_DIR / run["run_id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(out_dir / f"compose-{run['run_id']}.mp4")
        render_result = await asyncio.to_thread(
            _run_hyperframes_render, comp_dir, "standard", 30,
            variables if template_id else None, out_path,
        )
        # 入素材库
        from fastapi_app.api.v1.files.services import FileService
        from fastapi_app.db.session import main_db_pool
        service = FileService()
        file_ids: list[int] = []
        with main_db_pool.get_connection() as conn:
            for out_path in render_result["outputs"]:
                p = Path(out_path)
                try:
                    file_id = await service.save_file_record(
                        conn,
                        filename=f"[video-pipeline:{run['run_id']}] {p.name}",
                        file_path=str(p),
                        filesize_mb=p.stat().st_size / (1024 * 1024),
                        note=f"video-pipeline:compose run={run['run_id']}",
                        group_name="video-pipeline:hyperframes",
                    )
                    file_ids.append(file_id)
                except Exception as e:
                    logger.error(f"[VideoPipeline] 产物入库失败 {p.name}: {e}")
        render_report = {
            "run_id": run["run_id"],
            "engine": "hyperframes",
            "quality": "standard",
            "fps": 30,
            "elapsed_seconds": render_result["elapsed_seconds"],
            "outputs": [Path(o).name for o in render_result["outputs"]],
            "output_paths": render_result["outputs"],
            "file_ids": file_ids,
            "composition_dir": str(comp_dir),
            "composition_html": str(comp_dir / "index.html"),
            "template_id": template_id,
            "template_source": source,
            "variables": variables,
        }
        final_review = {
            "duration_target": (scene_plan or {}).get("total_duration_seconds")
                               or (script or {}).get("total_duration_seconds"),
            "render_ok": True,
            "notes": (
                [f"使用素材库模板 {template_id}（542 专业模板之一），AI 填参 variables={list(variables.keys())}"]
                if template_id
                else ["fallback 程序化文字卡 composition（AI 选模板失败）", "画面用文字卡+色块占位"]
            ),
        }
        run["artifacts"]["render_report"] = render_report
        run["artifacts"]["final_review"] = final_review
        run["artifacts"]["compose_meta"] = {
            "elapsed_seconds": round(_time.time() - started, 2),
            "render_elapsed": render_result["elapsed_seconds"],
            "template_id": template_id,
            "source": source,
        }
        _log_history(run, "stage_done", f"render {render_result['elapsed_seconds']}s source={source} → file_ids={file_ids}")
        _save_run(run)
        return render_report
    else:
        system, user, max_tokens = _stage_prompt(stage_name, run.get("topic", ""), run.get("style", ""), run["artifacts"])
        artifact = await _ai_json(system, user, max_tokens=max_tokens)
        for name in stage_meta["produces"]:
            if name == "decision_log":
                run["artifacts"][name] = artifact.get("decision_log") or [
                    {"stage": stage_name, "decision": "generated", "reason": "auto"}
                ]
            elif name == "final_review":
                continue
            else:
                run["artifacts"][name] = artifact
        elapsed = round(_time.time() - started, 2)
        run["artifacts"][f"_{stage_name}_meta"] = {"elapsed_seconds": elapsed}
        _log_history(run, "stage_done", f"elapsed={elapsed}s")
        _save_run(run)
        return artifact


async def _advance_run(run: dict, from_stage_index: int) -> dict:
    """从 from_stage_index 顺序执行阶段，遇 checkpoint 或完成停。"""
    i = from_stage_index
    while i < len(STAGES):
        stage = STAGES[i]
        await _execute_stage(run, stage["name"])
        if stage["name"] not in run["completed"]:
            run["completed"].append(stage["name"])
        if _stage_needs_approval(stage["name"]):
            run["status"] = "awaiting_approval"
            run["pending_approval"] = {
                "stage": stage["name"],
                "produces": stage["produces"],
                "revisions_used": run["revisions"].get(stage["name"], 0),
                "message": f"阶段「{stage['label']}」已完成，请批准后继续。",
            }
            _log_history(run, "awaiting_approval", stage["name"])
            _save_run(run)
            return run
        i += 1
    run["status"] = "completed"
    run["pending_approval"] = None
    _log_history(run, "completed")
    _save_run(run)
    return run


def _serialize_run(run: dict) -> dict:
    """对外暴露的 run 视图。"""
    created = _dt.datetime.fromisoformat(run["created_at"]) if run.get("created_at") else None
    elapsed = None
    if created:
        elapsed = round((_dt.datetime.now() - created).total_seconds(), 1)
    return {
        "run_id": run["run_id"],
        "status": run["status"],
        "topic": run["topic"],
        "style": run.get("style"),
        "reference_url": run.get("reference_url"),
        "budget_usd": run.get("budget_usd"),
        "current_stage": run["current_stage"],
        "stage_index": run["stage_index"],
        "completed": run["completed"],
        "pending_approval": run["pending_approval"],
        "artifacts": run["artifacts"],
        "history": run["history"],
        "error": run["error"],
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "elapsed_seconds": elapsed,
        "stages": STAGES,
    }


# ==================== Endpoints ====================
async def list_templates(category: str | None = None, q: str | None = None) -> dict:
    """GET /templates — 列素材库模板（542 专业 HyperFrames 模板，可按 category/关键词过滤）。"""
    cat = _load_catalog()
    templates = cat.get("templates", [])
    if category and category != "全部":
        templates = [t for t in templates if (t.get("category") or "") == category]
    if q:
        ql = q.lower()
        templates = [t for t in templates if ql in (t.get("id", "") + t.get("name", "") + t.get("description", "")).lower()]
    items = [{
        "id": t.get("id"), "name": t.get("name"), "description": t.get("description", "")[:120],
        "category": t.get("category"), "tags": t.get("tags", []),
        "duration": t.get("duration"), "size": t.get("size"),
    } for t in templates]
    categories = sorted({t.get("category", "未分类") for t in cat.get("templates", [])})
    return {"status": "success", "result": {
        "count": len(items), "total": cat.get("count", 0),
        "categories": categories, "templates": items,
        "library_dir": str(_TEMPLATE_LIB_DIR),
    }}


async def get_template(template_id: str) -> dict:
    """GET /templates/{template_id} — 取单模板详情（含 schema 变量定义）。"""
    t = _template_meta(template_id)
    if not t:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    tdir = _template_dir(template_id)
    return {"status": "success", "result": {**t, "dir": str(tdir), "exists": tdir.is_dir()}}


async def get_template_html(template_id: str) -> str:
    """GET /templates/{template_id}/html — 返回模板 index.html 原文（供前端 srcdoc 注入变量实时预览）。

    同源返回，规避 4312 http.server 的跨域限制。前端 fetch 后注入 window.__hyperframes
    变量脚本 + 播放脚本，以 srcdoc 挂进 iframe，改参数即时生效（复刻 live-preview.js 机制）。
    """
    idx = _template_dir(template_id) / "index.html"
    if not idx.is_file():
        raise HTTPException(status_code=404, detail=f"模板 index.html 不存在: {template_id}")
    return idx.read_text(encoding="utf-8")


def _launch_background(run_id: str, from_index: int) -> None:
    """后台跑 _advance_run，立即返回；run 状态实时存盘供 GET 轮询。

    避免 POST /run 同步阻塞 100s+ 导致 Next.js dev 代理 500 超时。
    FastAPI 事件循环上的 asyncio.create_task 在响应发出后继续跑。
    """
    import asyncio
    async def _bg():
        run = _load_run(run_id)
        if not run:
            return
        try:
            await _advance_run(run, from_index)
        except HTTPException as e:
            run["status"] = "failed"
            run["error"] = e.detail if hasattr(e, "detail") else str(e)
            run["pending_approval"] = None
            _log_history(run, "failed", run["error"])
            _save_run(run)
        except Exception as e:
            logger.exception(f"[VideoPipeline] run {run_id} 后台异常")
            run["status"] = "failed"
            run["error"] = str(e)[:400]
            run["pending_approval"] = None
            _log_history(run, "failed", run["error"])
            _save_run(run)
    try:
        asyncio.create_task(_bg())
    except RuntimeError:
        logger.error(f"[VideoPipeline] 无法启动后台任务（无事件循环）run={run_id}")


async def start_run(request: Request) -> dict:
    """POST /run — 起一个 run，后台跑到首个 checkpoint 暂停；立即返回 run_id。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    topic = (body.get("topic") or "").strip()
    if not topic or len(topic) < 4:
        raise HTTPException(status_code=400, detail="topic 至少 4 字")
    style = (body.get("style") or "").strip()
    reference_url = (body.get("reference_url") or "").strip()
    try:
        budget_usd = float(body.get("budget_usd") or 2.0)
    except (TypeError, ValueError):
        budget_usd = 2.0
    if budget_usd <= 0 or budget_usd > 100:
        budget_usd = 2.0

    run = _new_run(topic, style, reference_url, budget_usd)
    run["status"] = "running"
    _save_run(run)
    _launch_background(run["run_id"], run["stage_index"])
    return {"status": "success", "result": _serialize_run(run)}


async def get_run(run_id: str) -> dict:
    run = _load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"run 不存在: {run_id}")
    return {"status": "success", "result": _serialize_run(run)}


async def approve_run(run_id: str) -> dict:
    run = _load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"run 不存在: {run_id}")
    if run["status"] == "completed":
        raise HTTPException(status_code=400, detail="run 已完成")
    if run["status"] != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"run 当前状态 {run['status']}，无需批准")
    if not run.get("pending_approval"):
        raise HTTPException(status_code=400, detail="无待批准 checkpoint")
    current_stage = run["pending_approval"]["stage"]
    run["status"] = "running"
    run["pending_approval"] = None
    _log_history(run, "approved", current_stage)
    _save_run(run)
    idx = STAGES.index(_STAGES_BY_NAME[current_stage]) + 1
    _launch_background(run_id, idx)
    return {"status": "success", "result": _serialize_run(run)}


async def reject_run(run_id: str, request: Request) -> dict:
    """POST /run/{id}/reject — 打回当前阶段带 feedback 重做（每阶段最多 3 次）。"""
    run = _load_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"run 不存在: {run_id}")
    if run["status"] != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"run 当前状态 {run['status']}，无法打回")
    current_stage = run["pending_approval"]["stage"]
    if current_stage == "compose":
        raise HTTPException(status_code=400, detail="compose 阶段不支持打回（渲染失败请手动修 composition 再 /render）")
    used = run["revisions"].get(current_stage, 0)
    if used >= _MAX_REVISIONS_PER_STAGE:
        raise HTTPException(status_code=400, detail=f"阶段 {current_stage} 已重做 {used} 次（上限 {_MAX_REVISIONS_PER_STAGE}）")
    try:
        body = await request.json()
    except Exception:
        body = {}
    feedback = (body.get("feedback") or "").strip()
    run["status"] = "running"
    run["pending_approval"] = None
    run["revisions"][current_stage] = used + 1
    _log_history(run, "rejected", feedback[:120])
    _save_run(run)
    stage_meta = _STAGES_BY_NAME[current_stage]
    try:
        system, user, max_tokens = _stage_prompt(current_stage, run.get("topic", ""), run.get("style", ""), run["artifacts"])
        if feedback:
            user = user + f"\n\n【用户反馈（请据此改进）】：{feedback}"
        artifact = await _ai_json(system, user, max_tokens=max_tokens)
        for name in stage_meta["produces"]:
            if name == "decision_log":
                run["artifacts"][name] = artifact.get("decision_log") or [
                    {"stage": current_stage, "decision": "revised", "reason": feedback or "auto"}
                ]
            else:
                run["artifacts"][name] = artifact
        _log_history(run, "stage_redone", f"revisions={used+1}")
        run["status"] = "awaiting_approval"
        run["pending_approval"] = {
            "stage": current_stage,
            "produces": stage_meta["produces"],
            "revisions_used": used + 1,
            "message": f"已按反馈重做「{stage_meta['label']}」（第 {used+1} 次），请再审。",
        }
    except HTTPException as e:
        run["status"] = "failed"
        run["error"] = e.detail if hasattr(e, "detail") else str(e)
        _log_history(run, "failed", run["error"])
    except Exception as e:
        logger.exception(f"[VideoPipeline] run {run_id} reject 异常")
        run["status"] = "failed"
        run["error"] = str(e)[:400]
        _log_history(run, "failed", run["error"])
    _save_run(run)
    return {"status": "success", "result": _serialize_run(run)}
