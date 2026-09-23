"""
认知系统
━━━━━━━━
内容 DNA 分析 / 认知矩阵 / 受众画像 / 选题雷达（gap 检测）

内容 DNA：从正文中提取风格指纹（用词偏好、句长、观点密度、结构特征）
认知矩阵：多维度评估内容成熟度（选题/结构/情绪/权威/行动）
受众画像：根据内容推断目标受众（职业/年龄段/兴趣标签）
选题雷达：对比行业热点 vs 自有内容，找出内容空白
"""

from __future__ import annotations
import os, re, json, hashlib
from typing import Dict, Any, List, Optional
from pathlib import Path
from loguru import logger

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_PERSONA_FILE = _DATA_DIR / "audience_persona.json"


# ============================================================
# 内容 DNA 分析（本地计算，不依赖 LLM）
# ============================================================
def analyze_content_dna(content: str) -> Dict[str, Any]:
    """
    从正文提取风格指纹。
    返回：{ 字数, 句数, 平均句长, 段落数, 观点词计数, 数据点计数, 情感倾向 }
    """
    if not content:
        return {"error": "内容为空"}

    # 基础统计
    char_count = len(content)
    sentences = re.split(r"[。！？\.\!\?]", content)
    sentences = [s.strip() for s in sentences if s.strip()]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]

    # 观点词（表达立场）
    opinion_words = re.findall(r"[我认为|我觉得|事实上|实际上|本质上|核心是|关键在于|其实|说白了]", content)
    # 数据点（数字 + 单位）
    data_points = re.findall(r"\d+(?:\.\d+)?\s*[%％万亿千百亿|元/|次/|个/|人]", content)
    # 情绪词
    positive_words = re.findall(r"[优秀|成功|高效|增长|突破|创新|领先|卓越]", content)
    negative_words = re.findall(r"[失败|问题|困境|挑战|风险|危机|落后|错误]", content)

    # 句长分布
    lengths = [len(s) for s in sentences]
    avg_length = sum(lengths) / max(len(lengths), 1)
    long_ratio = sum(1 for l in lengths if l > 30) / max(len(lengths), 1)

    return {
        "char_count": char_count,
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "avg_sentence_length": round(avg_length, 1),
        "long_sentence_ratio": round(long_ratio, 2),
        "opinion_words": len(opinion_words),
        "data_points": len(data_points),
        "positive_words": len(positive_words),
        "negative_words": len(negative_words),
        "tone_score": round(len(positive_words) - len(negative_words), 2),  # >0 积极
        "style_hint": _classify_style(avg_length, len(opinion_words), len(data_points)),
    }


def _classify_style(avg_len: float, opinion_count: int, data_count: int) -> str:
    if avg_len > 25 and opinion_count > 3:
        return "观点密集型（适合知乎/公众号）"
    elif data_count > 5:
        return "数据密集型（适合科技/财经）"
    elif avg_len < 15:
        return "节奏快速型（适合小红书/抖音）"
    else:
        return "均衡型（通用）"


# ============================================================
# 认知矩阵：多维度评估
# ============================================================
def evaluate_cognition_matrix(content: str, dna: Optional[Dict] = None) -> Dict[str, Any]:
    """
    五个维度评分（0-100）：选题/结构/情绪/权威/行动
    每个维度给出分数 + 改进建议
    """
    if dna is None:
        dna = analyze_content_dna(content)
    if "error" in dna:
        return dna

    # 选题分：内容长度 + 有观点
    topic_score = min(100, int(dna["char_count"] / 30) + dna["opinion_words"] * 5)
    # 结构分：段落数 + 有层次
    structure_score = min(100, int(dna["paragraph_count"] * 8) + 30)
    # 情绪分：正向词 - 负向词
    emotion_score = max(0, min(100, 50 + int(dna["tone_score"] * 10)))
    # 权威分：数据点
    authority_score = min(100, dna["data_points"] * 12)
    # 行动分：包含行动呼吁词
    cta_count = len(re.findall(r"[快来|试试|看看|点赞|收藏|关注|留言|私信|点击|购买|下载]", content))
    action_score = min(100, 30 + cta_count * 15)

    return {
        "dimensions": {
            "选题": {"score": topic_score, "suggestion": _suggestion_topic(dna)},
            "结构": {"score": structure_score, "suggestion": _suggestion_structure(dna)},
            "情绪": {"score": emotion_score, "suggestion": _suggestion_emotion(dna)},
            "权威": {"score": authority_score, "suggestion": _suggestion_authority(dna)},
            "行动": {"score": action_score, "suggestion": f"CTA 次数 {cta_count}，建议 ≥2 个明确行动点"},
        },
        "overall_score": round((topic_score + structure_score + emotion_score + authority_score + action_score) / 5, 1),
    }


def _suggestion_topic(dna):
    if dna["opinion_words"] < 3:
        return "观点词较少，建议加入「我认为」「事实上」等表达立场的措辞"
    return "观点表达充分"


def _suggestion_structure(dna):
    if dna["paragraph_count"] < 4:
        return "段落较少，建议拆分到 6-10 段"
    return "段落结构合理"


def _suggestion_emotion(dna):
    if dna["tone_score"] < -3:
        return "负面情绪词偏多，建议增加平衡视角"
    if dna["tone_score"] > 10:
        return "过于乐观，加入客观数据或挑战视角可增强可信度"
    return "情绪平衡"


def _suggestion_authority(dna):
    if dna["data_points"] < 3:
        return "数据点较少，建议补充具体数字/百分比增强权威性"
    return "数据支撑充分"


# ============================================================
# 受众画像推断
# ============================================================
def infer_audience_persona(content: str, dna: Optional[Dict] = None) -> Dict[str, Any]:
    """
    根据内容推断目标受众。
    返回：{ 年龄段, 职业倾向, 兴趣标签, 语言风格偏好 }
    """
    if dna is None:
        dna = analyze_content_dna(content)

    # 关键词映射
    tech_words = ["API", "SDK", "GitHub", "Python", "JavaScript", "TypeScript", "模型", "算法"]
    business_words = ["增长", "ROI", "营收", "市场", "用户", "变现", "获客"]
    lifestyle_words = ["健康", "健身", "穿搭", "美食", "旅行", "生活方式"]
    academic_words = ["研究", "论文", "理论", "文献", "实证"]
    entertainment_words = ["明星", "综艺", "剧", "电影", "游戏", "追"]

    tech_hits = sum(1 for w in tech_words if w in content)
    business_hits = sum(1 for w in business_words if w in content)
    lifestyle_hits = sum(1 for w in lifestyle_words if w in content)
    academic_hits = sum(1 for w in academic_words if w in content)
    entertainment_hits = sum(1 for w in entertainment_words if w in content)

    scores = {
        "科技/开发者": tech_hits,
        "商业/创业者": business_hits,
        "生活方式": lifestyle_hits,
        "学术/研究员": academic_hits,
        "泛娱乐": entertainment_hits,
    }
    top_domain = max(scores, key=scores.get)

    # 年龄：数据密度和句长决定
    if dna["avg_sentence_length"] > 30 and dna["data_points"] > 5:
        age_group = "25-35 岁"
    elif dna["avg_sentence_length"] < 20:
        age_group = "18-25 岁"
    else:
        age_group = "25-40 岁"

    return {
        "primary_domain": top_domain,
        "all_domain_scores": scores,
        "age_group": age_group,
        "language_style": "专业术语多" if tech_hits + academic_hits > 3 else ("生活化" if lifestyle_hits + entertainment_hits > 3 else "均衡"),
        "content_depth": "深度" if dna["char_count"] > 2000 else ("中度" if dna["char_count"] > 500 else "轻量"),
        "engagement_strategy": "引导评论互动" if top_domain in ("科技/开发者", "商业/创业者") else "引导点赞收藏",
    }


# ============================================================
# 选题雷达：内容 gap 检测
# ============================================================
async def detect_content_gaps(
    own_topics: List[str],
    hot_topics: List[str],
) -> Dict[str, Any]:
    """
    对比自有话题和热门话题，找出内容空白。
    own_topics: 已有内容标题/标签列表
    hot_topics: 热点话题标题列表
    """
    # 简单 Jaccard 相似度；兼容字符串列表和热点 API 返回的对象列表。
    def extract_text(item: Any) -> str:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            return " ".join(str(value) for value in item.values())
        return str(item)

    def tokenize(items: List[Any]) -> set[str]:
        tokens: set[str] = set()
        for item in items:
            tokens.update(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", extract_text(item).lower()))
        return tokens

    own_tokens = tokenize(own_topics)
    hot_tokens = tokenize(hot_topics)

    # 找出热门但自有缺失的话题
    covered_tokens = own_tokens & hot_tokens
    gap_tokens = hot_tokens - own_tokens
    overlap_ratio = len(covered_tokens) / max(len(hot_tokens), 1)

    # 高价值 gap（热门中不常见的但被覆盖的词，说明有差异化）
    unique_tokens = own_tokens - hot_tokens

    return {
        "overlap_ratio": round(overlap_ratio, 2),
        "overlap_tokens": list(covered_tokens)[:20],
        "gap_tokens": list(gap_tokens)[:20],
        "unique_tokens": list(unique_tokens)[:20],
        "own_topic_count": len(own_topics),
        "hot_topic_count": len(hot_topics),
        "suggestion": (
            f"自有内容覆盖热点的 {int(overlap_ratio*100)}%。"
            + (f"建议补充缺失话题：{', '.join(list(gap_tokens)[:5])}。" if gap_tokens else "热点覆盖充分。")
        ),
    }


# ============================================================
# 画像存储/读取
# ============================================================
def save_audience_persona(persona: Dict[str, Any]) -> None:
    _PERSONA_FILE.write_text(json.dumps(persona, ensure_ascii=False, indent=2), encoding="utf-8")


def load_audience_persona() -> Dict[str, Any]:
    try:
        if _PERSONA_FILE.exists():
            return json.loads(_PERSONA_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}