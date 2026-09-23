"""
三层内容审核
━━━━━━━━━━━━
  Layer 1 — 敏感词检测（本地词库，毫秒级）
  Layer 2 — Qwen 语义审核（通义千问 + 阿里云 CIP，秒级；未配置时降级跳过）
  Layer 3 — AI 合规改写（DeepSeek/Qwen 自动修复违规内容）

每层可独立启用/禁用。
所有审核结果结构化输出，方便前端展示。
"""

from __future__ import annotations
import os, re, json, time
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
from loguru import logger

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_SENSITIVE_FILE = _DATA_DIR / "sensitive_words.json"


# ============================================================
# 内置敏感词库
# ============================================================
BUILTIN_SENSITIVE: List[Dict[str, Any]] = [
    {"category": "涉政违规", "words": [
        "颠覆国家政权", "分裂国家", "民族分裂", "反动", "反华", "颠覆", "台独", "疆独",
    ]},
    {"category": "涉黄违规", "words": [
        "色情", "淫秽", "一夜情", "卖淫", "嫖娼", "性交易", "裸聊",
    ]},
    {"category": "涉暴违规", "words": [
        "恐怖袭击", "爆炸物制作", "枪支持有", "非法武器", "杀人", "自杀方法",
    ]},
    {"category": "医疗违规", "words": [
        "包治百病", "祖传秘方", "根治癌症", "根治高血压", "包医百病", "神奇疗法",
    ]},
    {"category": "金融违规", "words": [
        "保本保息", "稳赚不赔", "年化 50%", "零风险高收益", "内幕消息", "内幕交易",
    ]},
    {"category": "广告违规", "words": [
        "最优秀", "最好", "唯一", "国家级", "顶级", "第一", "唯一官方",
    ]},
]


# ============================================================
# 类型定义
# ============================================================
class ModerationResult:
    def __init__(self):
        # Layer 1
        self.sensitive_words: List[Dict[str, Any]] = []
        self.has_blocked_words: bool = False
        # Layer 2
        self.qwen_passed: bool = True
        self.qwen_score: int = 100
        self.qwen_issues: List[Dict[str, Any]] = []
        self.qwen_summary: str = ""
        self.qwen_skipped: bool = False
        # Layer 3
        self.rewritten_content: Optional[str] = None
        self.was_rewritten: bool = False
        # 最终
        self.final_passed: bool = True
        self.final_content: str = ""
        self.requires_manual_review: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer1": {
                "sensitive_words": self.sensitive_words,
                "has_blocked_words": self.has_blocked_words,
            },
            "layer2": {
                "qwen_passed": self.qwen_passed,
                "qwen_score": self.qwen_score,
                "qwen_issues": self.qwen_issues,
                "qwen_summary": self.qwen_summary,
                "qwen_skipped": self.qwen_skipped,
            },
            "layer3": {
                "rewritten_content": self.rewritten_content,
                "was_rewritten": self.was_rewritten,
            },
            "final": {
                "final_passed": self.final_passed,
                "final_content": self.final_content,
                "requires_manual_review": self.requires_manual_review,
            },
        }


# ============================================================
# Layer 1: 敏感词检测
# ============================================================
def _load_sensitive() -> List[Dict[str, Any]]:
    if _SENSITIVE_FILE.exists():
        try:
            data = json.loads(_SENSITIVE_FILE.read_text(encoding="utf-8"))
            if data:
                return data
        except Exception:
            pass
    return list(BUILTIN_SENSITIVE)


def _save_sensitive(data: List[Dict[str, Any]]) -> None:
    _SENSITIVE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_layer1(content: str) -> tuple[List[Dict[str, Any]], bool]:
    """
    扫描敏感词。
    返回：(matched_list, has_blocked)
    """
    words_db = _load_sensitive()
    matches: List[Dict[str, Any]] = []
    has_blocked = False

    for cat in words_db:
        for word in cat.get("words", []):
            if not word:
                continue
            positions = []
            idx = content.find(word)
            while idx != -1:
                positions.append(idx)
                idx = content.find(word, idx + len(word))
            if positions:
                is_block = cat["category"] in ("涉政违规", "涉黄违规", "涉暴违规")
                if is_block:
                    has_blocked = True
                matches.append({
                    "word": word,
                    "category": cat["category"],
                    "severity": "block" if is_block else "warn",
                    "positions": positions,
                })

    return matches, has_blocked


# ============================================================
# Layer 2: Qwen 语义审核
# ============================================================
async def run_layer2(content: str) -> Dict[str, Any]:
    """
    通过通义千问做语义审核。未配置 DASHSCOPE_API_KEY 时跳过。
    """
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return {
            "qwen_passed": True,
            "qwen_score": 100,
            "qwen_issues": [],
            "qwen_summary": "未配置通义千问，跳过语义审核",
            "qwen_skipped": True,
        }

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        resp = await client.chat.completions.create(
            model="qwen-max",
            messages=[
                {"role": "system", "content": (
                    "你是内容安全审核员。审核以下内容，返回 JSON：\n"
                    '{"passed":true/false,"score":0-100,"issues":[{"type":"违规类型","location":"位置","reason":"原因"}],"summary":"一句话总结"}\n'
                    "仅输出 JSON，无其他文字。"
                )},
                {"role": "user", "content": content},
            ],
            temperature=0.1,
            max_tokens=600,
        )
        raw = resp.choices[0].message.content.strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group())
            return {
                "qwen_passed": bool(data.get("passed", True)),
                "qwen_score": int(data.get("score", 100)),
                "qwen_issues": data.get("issues", []),
                "qwen_summary": data.get("summary", ""),
                "qwen_skipped": False,
            }
        return {
            "qwen_passed": True, "qwen_score": 100,
            "qwen_issues": [], "qwen_summary": "解析失败",
            "qwen_skipped": False,
        }
    except Exception as e:
        logger.warning(f"Layer 2 Qwen 审核失败: {e}")
        return {
            "qwen_passed": True, "qwen_score": 100,
            "qwen_issues": [], "qwen_summary": f"Qwen 审核失败: {str(e)[:60]}",
            "qwen_skipped": True,
        }


# ============================================================
# Layer 3: AI 合规改写
# ============================================================
async def run_layer3(
    content: str,
    issues: List[Dict[str, Any]],
    sensitive_matches: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    通过 LLM 改写违规内容。使用 detect_provider 探测可用模型。
    """
    from fusion_ai.provider_registry import detect_provider
    cfg = detect_provider()
    if not cfg.get("api_key"):
        return {"rewritten_content": None, "was_rewritten": False, "note": "未配置 LLM"}

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
        issue_text = json.dumps(issues, ensure_ascii=False) if issues else "无 Qwen 报告"
        sens_text = json.dumps(sensitive_matches, ensure_ascii=False) if sensitive_matches else "无敏感词"

        resp = await client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": (
                    "你是内容合规改写专家。将下面内容改写为合规版本：\n"
                    "1. 去除或替换所有违规词汇\n"
                    "2. 保留原意、结构和信息量\n"
                    "3. 输出完整改写后的正文，不要解释\n"
                    "4. 若原文已合规，原样返回"
                )},
                {"role": "user", "content": f"违规报告：{issue_text}\n\n敏感词：{sens_text}\n\n原文：\n{content}"},
            ],
            temperature=0.3,
            max_tokens=3000,
        )
        rewritten = resp.choices[0].message.content or ""
        if not rewritten.strip():
            return {"rewritten_content": None, "was_rewritten": False, "note": "改写结果为空"}
        return {"rewritten_content": rewritten, "was_rewritten": True}
    except Exception as e:
        logger.warning(f"Layer 3 改写失败: {e}")
        return {"rewritten_content": None, "was_rewritten": False, "note": str(e)[:100]}


# ============================================================
# 统一审核入口
# ============================================================
async def moderate_content(
    content: str,
    enable_layer1: bool = True,
    enable_layer2: bool = True,
    enable_layer3: bool = True,
) -> Dict[str, Any]:
    """
    三层审核流水线。返回结构化结果。
    """
    result = ModerationResult()
    result.final_content = content

    # Layer 1
    if enable_layer1:
        matches, has_blocked = run_layer1(content)
        result.sensitive_words = matches
        result.has_blocked_words = has_blocked

    # Layer 2
    if enable_layer2:
        l2 = await run_layer2(content)
        result.qwen_passed = l2["qwen_passed"]
        result.qwen_score = l2["qwen_score"]
        result.qwen_issues = l2["qwen_issues"]
        result.qwen_summary = l2["qwen_summary"]
        result.qwen_skipped = l2["qwen_skipped"]

    # Layer 3: 只有 Layer 1 或 Layer 2 发现问题时才改写
    needs_rewrite = (
        enable_layer3
        and (result.has_blocked_words or not result.qwen_passed)
    )
    if needs_rewrite:
        l3 = await run_layer3(
            content,
            issues=result.qwen_issues,
            sensitive_matches=result.sensitive_words,
        )
        result.rewritten_content = l3["rewritten_content"]
        result.was_rewritten = l3["was_rewritten"]

    # 最终结论
    if result.has_blocked_words:
        result.final_passed = False
        result.requires_manual_review = True
    elif not result.qwen_passed and result.qwen_score < 60:
        result.final_passed = False
        result.requires_manual_review = True

    if result.was_rewritten:
        result.final_content = result.rewritten_content
        # 改写后重新过一遍 Layer 1 快速检查
        _, still_blocked = run_layer1(result.final_content)
        if still_blocked:
            result.final_passed = False
            result.requires_manual_review = True
        else:
            result.final_passed = True

    return result.to_dict()


# ============================================================
# 敏感词管理 API（供路由调用）
# ============================================================
def list_sensitive() -> List[Dict[str, Any]]:
    return _load_sensitive()


def add_sensitive_word(category: str, word: str) -> List[Dict[str, Any]]:
    data = _load_sensitive()
    cat = next((c for c in data if c["category"] == category), None)
    if cat:
        if word not in cat["words"]:
            cat["words"].append(word)
    else:
        data.append({"category": category, "words": [word]})
    _save_sensitive(data)
    return data


def remove_sensitive_word(category: str, word: str) -> List[Dict[str, Any]]:
    data = _load_sensitive()
    cat = next((c for c in data if c["category"] == category), None)
    if cat and word in cat["words"]:
        cat["words"].remove(word)
        if not cat["words"]:
            data = [c for c in data if c["category"] != category]
        _save_sensitive(data)
    return data