"""
技能工坊（AI 去 AIGC 味）
━━━━━━━━━━━━━━━━━━━━━━
将 AI 生成的"AI 味"文本改写为自然、有人味、平台风格化的内容。
每个 skill 是一段可配置的改写策略。

使用方式：
  result = apply_skill(content, skill_id, overrides={...})

技能类型：
  deai_style     — 去 AI 味：消除"首先/其次/最后"等套路句式
  deai_structure — 去 AI 结构味：打破"总-分-总"模板化结构
  deai_vocabulary— 去 AI 词汇：替换"值得关注的是""显而易见"等高频词
  deai_platform  — 平台适配：按平台风格重写
  deai_voice     — 语气定制：改成口语/严肃/活泼/幽默
"""

from __future__ import annotations
import os, json, re, hashlib
from typing import Dict, Any, List, Optional
from pathlib import Path
from loguru import logger

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_SKILLS_FILE = _DATA_DIR / "deai_skills.json"


# ============================================================
# 内置技能
# ============================================================
BUILTIN_SKILLS: List[Dict[str, Any]] = [
    {
        "id": "deai_style",
        "name": "🧹 去 AI 套路句式",
        "description": "消除「首先、其次、最后」「值得一提的是」「显而易见」「总的来说」等 AI 常见套路句式",
        "type": "local",
        "patterns": {
            r"首先[^，。]*，": "",
            r"其次[^，。]*，": "",
            r"最后[^，。]*，": "",
            r"值得一提的是[^，。]*，": "",
            r"显而易见[^，。]*，": "",
            r"总的来说[^，。]*，": "",
            r"值得注意的是[^，。]*，": "",
            r"不得不提的是[^，。]*，": "",
            r"在当今社会[^，。]*，": "",
            r"在当今这个[^，。]*，": "",
            r"在这个信息爆炸的时代[^，。]*，": "",
            r"不可否认[^，。]*，": "",
            r"可以说[^，。]*，": "",
            r"毫无疑问[^，。]*，": "",
        },
        "prompt_addition": "消除所有套路句式和连接词，让文字读起来像真人写的。",
        "enable_llm": True,
    },
    {
        "id": "deai_vocabulary",
        "name": "📝 去 AI 词汇",
        "description": "替换 AI 高频使用的词汇，让文字更接地气",
        "type": "local",
        "replacements": {
            "有助于": "能帮",
            "提升": "变好",
            "赋能": "帮忙",
            "助力": "帮",
            "优化": "改好",
            "策略": "办法",
            "方案": "法子",
            "进行": "做",
            "开展": "做",
            "实施": "做",
            "相关": "有关",
            "从而": "这样",
            "此外": "另外",
            "同时": "而且",
            "进而": "然后",
            "综上所述": "总的来说",
        },
        "prompt_addition": "把正式书面语改成自然口语，保留专业性。",
        "enable_llm": True,
    },
    {
        "id": "deai_structure",
        "name": "🏗️ 去 AI 结构味",
        "description": "打破 AI 常见的「总-分-总」模板化结构，让文章有起伏",
        "type": "local",
        "rules": [
            "删除首段总结句",
            "删除结尾「总之」「综上所述」等总结段",
            "打乱段落顺序，从具体案例开始",
            "增加反问句和短句制造节奏感",
        ],
        "prompt_addition": "完全重写段落结构，不要有「总-分-总」的模板感。开头直接切入主题，结尾留悬念或行动呼吁。",
        "enable_llm": True,
    },
    {
        "id": "deai_voice",
        "name": "🎭 语气定制",
        "description": "按指定语气改写（口语 / 严肃 / 活泼 / 幽默 / 故事化）",
        "type": "configurable",
        "modes": ["口语", "严肃", "活泼", "幽默", "故事化"],
        "prompt_addition": "用{mode}语气完全重写下面内容，保留信息量但改变表达方式。",
        "enable_llm": True,
    },
    {
        "id": "deai_platform",
        "name": "📱 平台适配",
        "description": "按目标平台风格重写（小红书 / 知乎 / 抖音 / 公众号 / B 站）",
        "type": "configurable",
        "modes": ["小红书", "知乎", "抖音", "公众号", "B 站"],
        "prompt_addition": "把下面内容改写为{platform}风格的文案，注意字数、emoji、标题和结构。",
        "enable_llm": True,
    },
]


def list_builtin_skills() -> List[Dict[str, Any]]:
    return list(BUILTIN_SKILLS)


# 自定义技能（用户在前端创建）
_custom_skills: List[Dict[str, Any]] = []


def list_custom_skills() -> List[Dict[str, Any]]:
    if not _custom_skills:
        if _SKILLS_FILE.exists():
            try:
                _custom_skills.extend(json.loads(_SKILLS_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass
    return list(_custom_skills)


def add_custom_skill(skill: Dict[str, Any]) -> Dict[str, Any]:
    skill["env_key"] = "__custom__"
    if "id" not in skill:
        skill["id"] = f"custom_{hashlib.md5((skill.get('name','x')).encode()).hexdigest()[:8]}"
    skill["type"] = "custom"
    _custom_skills.append(skill)
    _save_custom_skills()
    return skill


def remove_custom_skill(skill_id: str) -> bool:
    before = len(_custom_skills)
    _custom_skills[:] = [s for s in _custom_skills if s.get("id") != skill_id]
    saved = _save_custom_skills()
    return len(_custom_skills) < before


def apply_skill(content: str, skill_id: str, **overrides) -> Dict[str, Any]:
    """
    应用单个 skill 到内容。
    返回：{ skill_id, applied, result, method }
    method 为 'local'（纯正则/替换）或 'llm'（调用大模型）
    """
    skill = next((s for s in BUILTIN_SKILLS if s["id"] == skill_id), None)
    if not skill:
        skill = next((s for s in _custom_skills if s.get("id") == skill_id), None)
    if not skill:
        return {"skill_id": skill_id, "applied": False, "result": content, "error": "未知技能"}

    # 本地规则应用（正则替换）
    if skill["type"] in ("local", "custom"):
        result = content
        patterns = skill.get("patterns", {})
        replacements = skill.get("replacements", {})
        for pat, repl in patterns.items():
            result = re.sub(pat, repl, result)
        for old, new in replacements.items():
            result = result.replace(old, new)

        # 如果有 LLM 增强，构造 prompt
        if skill.get("enable_llm") and overrides.get("use_llm"):
            prompt_add = skill.get("prompt_addition", "")
            mode = overrides.get("mode") or overrides.get("platform") or ""
            if mode:
                prompt_add = prompt_add.replace("{mode}", mode).replace("{platform}", mode)
            return {
                "skill_id": skill_id,
                "applied": True,
                "result": result,
                "method": "local+llm_prompt",
                "llm_prompt": prompt_add,
                "llm_prompt_ready": True,
            }
        return {"skill_id": skill_id, "applied": True, "result": result, "method": "local"}

    return {"skill_id": skill_id, "applied": True, "result": content, "method": "configurable"}


def apply_skill_chain(content: str, skill_ids: List[str], **overrides) -> Dict[str, Any]:
    """
    按顺序应用多个 skill（去 AIGC 味组合拳）
    返回：{ result, applied_skills, steps }
    """
    result = content
    steps = []
    for sid in skill_ids:
        r = apply_skill(result, sid, **overrides)
        result = r.get("result", result)
        steps.append({"skill_id": sid, "applied": r.get("applied", False), "method": r.get("method", "")})
    return {"result": result, "applied_skills": skill_ids, "steps": steps}


def _save_custom_skills() -> bool:
    try:
        _SKILLS_FILE.write_text(json.dumps(list(_custom_skills), ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"保存技能失败: {e}")
        return False