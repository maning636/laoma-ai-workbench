"""Prompt 库(C14):分层注册表 + 渲染 + 校验。

分层(设计文档 §2.2):
  cloud tier — 高价值 prompt,只在云端;客户端只按 name 触发,看不到模板源码。
  basic tier — 基础模板,允许离线版复用(未来客户端 `prompts_basic.py` 直接同步)。

模板语法:Jinja2 风格 `{{ var }}` 占位符;渲染用 `render_template()`。
不做 `| safe` / `{% block %}` 等高级语法 —— prompt 是"给 LLM 看的文字",
不需要执行代码;`_StrictFormatter` 只做键值替换 + 未定义变量报错。

SEED 数据由 `sync_prompts_to_db()` 幂等 upsert 到 `prompts` 表(供 DB 驱动的路径使用),
但线上真正渲染走本模块的内存表 `CLOUD_PROMPTS` / `BASIC_PROMPTS`,
避免每次请求打 DB;表主要给运营/后台查询 + 未来版本管理用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Prompt


# ──────────────────────────────────────────────────────────────
# Prompt 定义
# ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PromptDef:
    """内存版 prompt 定义(与 `Prompt` ORM 结构对齐,但不落 DB)。"""

    name: str
    template: Any  # 允许 str 或 tuple[str, ...];__post_init__ 会归一化
    tier: str  # "cloud" | "basic"
    variables: tuple[str, ...] = ()
    version: str = "1.0.0"
    description: str = ""

    def __post_init__(self) -> None:
        # 源码中 `template=( "a" "b", "c" "d" )` 会被解析成 tuple。
        # 兼容写法:把 tuple 里所有字符串无分隔符拼接(相邻字符串本应自动拼接)。
        if isinstance(self.template, tuple):
            joined = "".join(str(x) for x in self.template)
            object.__setattr__(self, "template", joined)
        if not isinstance(self.template, str):
            raise TypeError(f"template must be str, got {type(self.template)}")
        if self.tier not in {"cloud", "basic"}:
            raise ValueError(f"tier must be 'cloud' or 'basic', got {self.tier!r}")
        if not self.name:
            raise ValueError("name must not be empty")

    def variables_json(self) -> str:
        return json.dumps(list(self.variables), ensure_ascii=False)

    def to_orm(self) -> Prompt:
        return Prompt(
            name=self.name,
            tier=self.tier,
            template=self.template,
            variables_json=self.variables_json(),
            version=self.version,
            is_active=True,
        )

    def render(self, variables: dict[str, Any]) -> str:
        return render_template(self.template, variables)


# ──────────────────────────────────────────────────────────────
# Cloud tier — 高价值 prompt(下沉核心资产)
# ──────────────────────────────────────────────────────────────
# 变量占位符:
#   topic         — 主题/选题关键词
#   tone          — 语气(专业 / 幽默 / 情绪饱满 ...)
#   style         — 风格补充(平台/领域)
#   audience      — 目标受众
#   content       — 输入正文(评审类 prompt)
#   platform      — 目标平台(xiaohongshu / douyin / zhihu ...)
#   constraints   — 约束(字数、tag 上限 ...)
# ──────────────────────────────────────────────────────────────

CLOUD_PROMPTS: dict[str, PromptDef] = {
    "cognition.matrix_evaluate": PromptDef(
        name="cognition.matrix_evaluate",
        tier="cloud",
        version="1.0.0",
        description="认知矩阵:5 维度评估内容(选题/结构/情绪/权威/行动)",
        variables=("content", "audience"),
        template=(
            "你是一位资深内容编辑顾问,擅长从多维视角评估一篇内容的质量。\n\n"
            "【任务】对下面这篇内容做一次「认知矩阵」评估。\n\n"
            "【目标受众】{{ audience }}\n\n"
            "【评估维度】\n"
            "1. 选题分 — 主题是否明确、是否具备讨论价值、观点表达是否充分\n"
            "2. 结构分 — 段落层次是否清晰、是否有引导逻辑、是否易读\n"
            "3. 情绪分 — 情绪基调是否平衡(不过度乐观 / 不过度消极)\n"
            "4. 权威分 — 数据点、案例、来源是否充分\n"
            "5. 行动分 — 是否有明确的 CTA(点赞 / 收藏 / 关注 / 评论)\n\n"
            "【评分规则】\n"
            "每个维度 0-100 分,给出分数、简短理由(≤40 字)、1 条改进建议。\n\n"
            "【输出格式(严格 JSON)】\n"
            "{\n"
            '  "dimensions": {\n'
            '    "选题": {"score": 0, "reason": "", "suggestion": ""},\n'
            '    "结构": {"score": 0, "reason": "", "suggestion": ""},\n'
            '    "情绪": {"score": 0, "reason": "", "suggestion": ""},\n'
            '    "权威": {"score": 0, "reason": "", "suggestion": ""},\n'
            '    "行动": {"score": 0, "reason": "", "suggestion": ""}\n'
            "  },\n"
            '  "overall_score": 0,\n'
            '  "top3_actions": ["", "", ""]\n'
            "}\n\n"
            "【内容】\n{{ content }}",
        ),
    ),
    "cognition.audience_persona": PromptDef(
        name="cognition.audience_persona",
        tier="cloud",
        version="1.0.0",
        description="受众画像:从内容反推目标人群 + 语言风格偏好",
        variables=("content",),
        template=(
            "你是一位用户研究分析师。基于下面这篇内容,推断最可能的目标受众。\n\n"
            "【任务】从四个角度刻画受众:\n"
            "1. 主领域(tech / business / lifestyle / academic / entertainment 之一)\n"
            "2. 年龄段(如 25-35 岁)\n"
            "3. 语言风格偏好(专业术语多 / 生活化 / 均衡)\n"
            "4. 互动偏好(引导评论 / 点赞收藏 / 私域转发)\n\n"
            "【输出格式(严格 JSON)】\n"
            "{\n"
            '  "primary_domain": "",\n'
            '  "age_group": "",\n'
            '  "language_style": "",\n'
            '  "engagement_strategy": "",\n'
            '  "confidence": 0.0\n'
            "}\n\n"
            "【内容】\n{{ content }}",
        ),
    ),
    "platform_style.match": PromptDef(
        name="platform_style.match",
        tier="cloud",
        version="1.0.0",
        description="平台风格适配:根据平台生成符合调性的标题 + 结构 + tag",
        variables=("platform", "topic", "constraints"),
        template=(
            "你是一位多平台内容策略专家,深度掌握以下平台的语气、结构与排版规则:\n"
            "  - xiaohongshu(小红书):种草感、emoji 密集、1200 字内、竖版封面、10 个标签上限\n"
            "  - douyin(抖音):网感强、节奏快、前 3 秒抓人、9:16、8 个标签上限\n"
            "  - zhihu(知乎):专业理性、深度分析、观点表达、5 个标签上限\n"
            "  - wechat(公众号):深度长文、叙事性强、封面+标题决定打开率\n"
            "  - bilibili(B 站):UP 主风格、梗文化、三连引导\n"
            "  - toutiao(头条):资讯风、三段式标题、信息密度高\n"
            "  - kuaishou(快手):接地气、老铁文化、口语化\n"
            "  - xigua(西瓜):长视频脚本、结构严谨、16:9\n\n"
            "【任务】针对目标平台 `{{ platform }}`,为选题 `{{ topic }}` 生成一版发布包。\n"
            "【附加约束】{{ constraints }}\n\n"
            "【输出格式(严格 JSON)】\n"
            "{\n"
            '  "platform": "",\n'
            '  "titles": ["", "", ""],\n'
            '  "opening": "",\n'
            '  "body_outline": ["", "", ""],\n'
            '  "closing": "",\n'
            '  "tags": [],\n'
            '  "cover_hint": "",\n'
            '  "emoji_density": ""\n'
            "}",
        ),
    ),
    "hot_topic.mining": PromptDef(
        name="hot_topic.mining",
        tier="cloud",
        version="1.0.0",
        description="热点挖掘:从话题簇中挑选高潜力选题 + 差异化角度",
        variables=("topic_cluster", "audience"),
        template=(
            "你是一位热点编辑。基于下面这组近期话题/关键词簇,选出最有内容潜力的选题,并给出差异化切入角度。\n\n"
            "【目标受众】{{ audience }}\n\n"
            "【话题簇】\n{{ topic_cluster }}\n\n"
            "【评估维度】\n"
            "1. 搜索热度(是否具备大众基础)\n"
            "2. 讨论空间(是否有多种视角,不是一锤定音)\n"
            "3. 差异化空间(与已有爆款标题的差异点)\n"
            "4. 时效窗口(建议发布时长)\n\n"
            "【输出格式(严格 JSON)】\n"
            "{\n"
            '  "top_topics": [\n'
            '    {"topic": "", "reason": "", "angle": "", "urgency": "hot|warm|cold"}\n'
            "  ],\n"
            '  "avoid": [""]\n'
            "}",
        ),
    ),
    "moderator.review": PromptDef(
        name="moderator.review",
        tier="cloud",
        version="1.0.0",
        description="内容合规审核:识别平台红线 + 敏感表达",
        variables=("content", "platform"),
        template=(
            "你是一位内容合规审核员,熟悉中国大陆主流平台(小红书、抖音、B 站、公众号、知乎、快手、头条)的社区规则。\n\n"
            "【任务】审核下面这段 `{{ platform }}` 平台的内容,标记潜在违规点并给出改写建议。\n\n"
            "【审核维度】\n"
            "1. 违禁词 / 极限词(最、第一、绝对、100% 等)\n"
            "2. 医疗 / 金融 / 政务 敏感表述\n"
            "3. 诱导性话术(点击、私信、返利)\n"
            "4. 版权 / 肖像 / 商标 风险\n"
            "5. 平台专属红线(如小红书医疗美妆、抖音金融)\n\n"
            "【输出格式(严格 JSON)】\n"
            "{\n"
            '  "risk_level": "none|low|medium|high",\n'
            '  "flags": [\n'
            '    {"keyword": "", "category": "", "severity": "low|medium|high", "rewrite_hint": ""}\n'
            "  ],\n"
            '  "suggestions": [""]\n'
            "}",
        ),
    ),
}


# ──────────────────────────────────────────────────────────────
# Basic tier — 基础模板(允许离线版复用)
# ──────────────────────────────────────────────────────────────
# 判据:抄了也用不出产品差异化,只做"够用"的基础功能。
# ──────────────────────────────────────────────────────────────

BASIC_PROMPTS: dict[str, PromptDef] = {
    "title.basic_generate": PromptDef(
        name="title.basic_generate",
        tier="basic",
        version="1.0.0",
        description="基础标题生成(无平台风格)",
        variables=("topic", "count"),
        template=(
            "为下面这个选题生成 {{ count }} 个中文标题。要求:15-30 字,直接陈述,不使用夸张词。\n\n"
            "选题:{{ topic }}\n\n"
            "输出格式:纯文本,每行一个标题。",
        ),
    ),
    "tag.basic_extract": PromptDef(
        name="tag.basic_extract",
        tier="basic",
        version="1.0.0",
        description="基础标签抽取(纯关键词,无情感分析)",
        variables=("content", "max_tags"),
        template=(
            "从下面内容中提取最多 {{ max_tags }} 个关键词,作为话题标签。\n"
            "要求:2-6 字,中文或英文均可,不要重复。\n\n"
            "内容:{{ content }}\n\n"
            "输出格式:逗号分隔,如 `标题党,小红书,爆款,文案`。",
        ),
    ),
    "rewrite.basic_polish": PromptDef(
        name="rewrite.basic_polish",
        tier="basic",
        version="1.0.0",
        description="基础文案润色(仅句式变换,不做平台适配)",
        variables=("content",),
        template=(
            "请对下面这段文字做一次润色:修正错别字、去除冗余、保持原意、不改语气。输出仅返回润色后的正文。\n\n"
            "原文:{{ content }}",
        ),
    ),
    "greeting.fallback": PromptDef(
        name="greeting.fallback",
        tier="basic",
        version="1.0.0",
        description="兜底问候语",
        variables=("user_name",),
        template="你好,{{ user_name }}!有什么我可以帮你的?",
    ),
}


ALL_PROMPTS: dict[str, PromptDef] = {**BASIC_PROMPTS, **CLOUD_PROMPTS}


# ──────────────────────────────────────────────────────────────
# 渲染
# ──────────────────────────────────────────────────────────────

class _MissingKey(dict):
    """渲染时若变量缺失,渲染出字面量 `{{ name }}` 而不是抛 KeyError。

    好处:模板调试期看到占位符原文,而不是断在中间。
    """

    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return "{{ " + key + " }}"


def render_template(template: str, variables: dict[str, Any] | None = None) -> str:
    """Jinja2-lite 渲染。

    - 支持 `{{ key }}` 占位符(空格可选)。
    - 未提供的变量渲染为字面量占位符,便于观察遗漏。
    - 值会 `str()` 后去除首尾空白,避免多行变量污染布局。
    """
    if variables is None:
        variables = {}

    class _StringifyDict(_MissingKey):
        def __getitem__(self, key):  # type: ignore[override]
            try:
                raw = super().__getitem__(key)
            except KeyError:
                return super().__missing__(key)
            return str(raw).strip()

    ctx = _StringifyDict(**variables)

    def _sub(match: Any) -> str:
        return ctx[match.group(1).strip()]

    import re

    return re.sub(r"\{\{\s*([^{}\n]+?)\s*\}\}", _sub, template)


# ──────────────────────────────────────────────────────────────
# 查询 / 校验
# ──────────────────────────────────────────────────────────────

def get_prompt(name: str) -> PromptDef | None:
    return ALL_PROMPTS.get(name)


def list_prompt_names(tier: str | None = None) -> list[str]:
    if tier is None:
        return sorted(ALL_PROMPTS.keys())
    if tier == "cloud":
        return sorted(CLOUD_PROMPTS.keys())
    if tier == "basic":
        return sorted(BASIC_PROMPTS.keys())
    raise ValueError(f"unknown tier: {tier!r} (expect 'cloud' or 'basic')")


def validate_variables(prompt_name: str, variables: dict[str, Any] | None) -> list[str]:
    """返回缺失的必填变量名列表;空列表 = 通过。"""
    p = get_prompt(prompt_name)
    if p is None:
        return []
    given = variables or {}
    return [v for v in p.variables if v not in given]


# ──────────────────────────────────────────────────────────────
# 同步到 DB(供运营/后台查询用,不参与渲染)
# ──────────────────────────────────────────────────────────────

def sync_prompts_to_db(db: Session) -> dict[str, dict[str, int]]:
    """把内存注册表 upsert 到 `prompts` 表。

    语义:
      - 按 name 唯一键 upsert;模板或版本变更时更新。
      - 返回统计 `{tier: {"inserted": n, "updated": m}}`。
    """
    stats: dict[str, dict[str, int]] = {}
    for tier, registry in (("cloud", CLOUD_PROMPTS), ("basic", BASIC_PROMPTS)):
        inserted = updated = 0
        for pdef in registry.values():
            row = db.execute(
                select(Prompt).where(Prompt.name == pdef.name)
            ).scalar_one_or_none()
            if row is None:
                db.add(pdef.to_orm())
                inserted += 1
            else:
                row.tier = pdef.tier
                row.template = pdef.template
                row.variables_json = pdef.variables_json()
                row.version = pdef.version
                row.is_active = True
                updated += 1
        stats[tier] = {"inserted": inserted, "updated": updated}
    db.commit()
    return stats


def prompt_count_by_tier() -> dict[str, int]:
    return {"cloud": len(CLOUD_PROMPTS), "basic": len(BASIC_PROMPTS), "total": len(ALL_PROMPTS)}


__all__ = [
    "PromptDef",
    "CLOUD_PROMPTS",
    "BASIC_PROMPTS",
    "ALL_PROMPTS",
    "render_template",
    "get_prompt",
    "list_prompt_names",
    "validate_variables",
    "sync_prompts_to_db",
    "prompt_count_by_tier",
]
