"""C14a:客户端 basic tier prompt 快照(离线版可用)。

背景(设计文档 §2.2):
  - 云端 `CLOUD_PROMPTS` 是高价值 prompt,只在服务端渲染,客户端**看不到模板源码**。
  - `BASIC_PROMPTS` 是基础模板(标题/标签/润色/兜底问候),逆向价值低,允许下沉到客户端,
    让离线版在没有云端 LLM 时仍能提供"够用"的基础能力。

数据来源:
  本文件是**手工同步**的快照,来源为云端 `cloud_service/llm_proxy/prompts.py::BASIC_PROMPTS`。
  同步方式:
    1. 官方方式 —— 打包脚本 `scripts/build_offline_prompts.py` 调
       `GET /cloud/prompts-export?tier=basic`(需 admin + HMAC 校验)拿到 JSON 快照。
    2. 开发方式 —— 手工对齐本文件与云端定义,`__prompts_sync__` 元数据里记录版本号 + 生成时间。
  每次云端升级 basic tier 都必须重跑一次同步并 bump `SCHEMA_VERSION`。

渲染约定:
  - 与云端共用简单的 Jinja2-lite 语法:`{{ var }}` 占位符。
  - 客户端本地渲染时,缺失变量渲染为字面量 `{{ name }}`(便于调试遗漏),不抛异常。
  - **不要** 在离线 prompt 里放"必须走云端才能算"的东西(如平台风格表、认知矩阵评分表)——
    那些属于 `cloud tier`,只通过 `prompt_router.render_cloud()` 走 `POST /cloud/llm/chat`。
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import re
from typing import Any


# ──────────────────────────────────────────────────────────────
# 同步元数据(打包脚本或人工对齐时更新)
# ──────────────────────────────────────────────────────────────

#: 快照 schema 版本,与云端 `/cloud/prompts-export` 响应的 `schema_version` 对齐。
SCHEMA_VERSION: str = "1.0"

#: 云端导出时间(ISO 8601)。人工维护;打包脚本自动覆盖。
GENERATED_AT: str = "2026-10-13T00:00:00+00:00"

#: 云端导出的 HMAC-SHA256 签名(`CLOUD_HMAC_SECRET` 计算)。
#: - 空串 = 未启用完整性校验(开发环境默认)
#: - 非空 = 客户端离线加载时用 `LOCAL_HMAC_SECRET` 复算比对,防止被篡改/二次分发
EXPORTED_HMAC: str = ""


# ──────────────────────────────────────────────────────────────
# Basic tier prompt 快照(name → PromptBasic)
# ──────────────────────────────────────────────────────────────

class PromptBasic:
    """客户端轻量版 prompt 定义。

    与云端 `PromptDef` 保持字段一致(name / version / variables / description / template),
    但不引入 dataclass/ORM 依赖 —— 离线端保持"能跑就行"的最小依赖集。
    """

    __slots__ = ("name", "version", "variables", "description", "template")

    def __init__(
        self,
        name: str,
        template: str,
        version: str = "1.0.0",
        variables: tuple[str, ...] = (),
        description: str = "",
    ) -> None:
        if not isinstance(template, str) or not template:
            raise ValueError(f"template must be non-empty str (prompt={name!r})")
        if not name:
            raise ValueError("name must not be empty")
        self.name = name
        self.version = version
        self.variables = tuple(variables)
        self.description = description
        self.template = template

    def render(self, variables: dict[str, Any] | None = None) -> str:
        """渲染模板。缺失变量渲染为 `{{ key }}` 字面量(便于调试)。"""
        return render_template(self.template, variables)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "variables": list(self.variables),
            "description": self.description,
            "template": self.template,
        }


#: 基础 prompt 快照(离线可用)。
#: 判据:抄了也用不出产品差异化 —— 只做"够用"的基础功能。
BASIC_PROMPTS: dict[str, PromptBasic] = {
    "title.basic_generate": PromptBasic(
        name="title.basic_generate",
        version="1.0.0",
        description="基础标题生成(无平台风格)",
        variables=("topic", "count"),
        template=(
            "为下面这个选题生成 {{ count }} 个中文标题。要求:15-30 字,直接陈述,不使用夸张词。\n\n"
            "选题:{{ topic }}\n\n"
            "输出格式:纯文本,每行一个标题。"
        ),
    ),
    "tag.basic_extract": PromptBasic(
        name="tag.basic_extract",
        version="1.0.0",
        description="基础标签抽取(纯关键词,无情感分析)",
        variables=("content", "max_tags"),
        template=(
            "从下面内容中提取最多 {{ max_tags }} 个关键词,作为话题标签。\n"
            "要求:2-6 字,中文或英文均可,不要重复。\n\n"
            "内容:{{ content }}\n\n"
            "输出格式:逗号分隔,如 `标题党,小红书,爆款,文案`。"
        ),
    ),
    "rewrite.basic_polish": PromptBasic(
        name="rewrite.basic_polish",
        version="1.0.0",
        description="基础文案润色(仅句式变换,不做平台适配)",
        variables=("content",),
        template=(
            "请对下面这段文字做一次润色:修正错别字、去除冗余、保持原意、不改语气。"
            "输出仅返回润色后的正文。\n\n"
            "原文:{{ content }}"
        ),
    ),
    "greeting.fallback": PromptBasic(
        name="greeting.fallback",
        version="1.0.0",
        description="兜底问候语",
        variables=("user_name",),
        template="你好,{{ user_name }}!有什么我可以帮你的?",
    ),
}


# ──────────────────────────────────────────────────────────────
# 渲染 & 查询
# ──────────────────────────────────────────────────────────────

_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([^{}\n]+?)\s*\}\}")


def render_template(template: str, variables: dict[str, Any] | None = None) -> str:
    """Jinja2-lite 渲染(与云端 `cloud_service/llm_proxy/prompts.render_template` 语义一致)。

    - `{{ key }}` 占位符,两侧空白可选。
    - 未提供的变量渲染为 `{{ key }}` 字面量(便于观察遗漏,不抛 KeyError)。
    - 值会 `str()` 后去除首尾空白。
    """
    ctx = variables or {}

    def _sub(match: "re.Match[str]") -> str:
        key = match.group(1).strip()
        if key in ctx:
            return str(ctx[key]).strip()
        return "{{ " + key + " }}"

    return _TEMPLATE_PATTERN.sub(_sub, template)


def get_prompt(name: str) -> PromptBasic | None:
    return BASIC_PROMPTS.get(name)


def list_names() -> list[str]:
    return sorted(BASIC_PROMPTS.keys())


def validate_variables(prompt_name: str, variables: dict[str, Any] | None) -> list[str]:
    """返回缺失的必填变量名列表;空列表 = 通过。"""
    p = get_prompt(prompt_name)
    if p is None:
        return []
    given = variables or {}
    return [v for v in p.variables if v not in given]


# ──────────────────────────────────────────────────────────────
# 完整性校验(HMAC,可选)
# ──────────────────────────────────────────────────────────────

def _canonical_body() -> str:
    """把当前快照序列化成 canonical JSON,便于与云端 HMAC 比对。"""
    body = {
        "tier": "basic",
        "schema_version": SCHEMA_VERSION,
        "total": len(BASIC_PROMPTS),
        "prompts": [p.to_dict() for p in sorted(BASIC_PROMPTS.values(), key=lambda x: x.name)],
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def verify_export_hmac(local_secret: str | None) -> bool:
    """用本地 `local_secret` 复算快照的 HMAC-SHA256,与 `EXPORTED_HMAC` 比对。

    - `local_secret` 为空 或 `EXPORTED_HMAC` 为空 → 视为"未启用校验",返回 True。
    - 否则恒定时间比对。
    """
    if not local_secret or not EXPORTED_HMAC:
        return True
    computed = _hmac.new(
        local_secret.encode("utf-8"),
        _canonical_body().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return _hmac.compare_digest(computed, EXPORTED_HMAC)


def snapshot_fingerprint() -> str:
    """返回快照的 SHA-256(与 HMAC 不同,仅用于日志/调试,不含密钥)。"""
    return hashlib.sha256(_canonical_body().encode("utf-8")).hexdigest()


__all__ = [
    "SCHEMA_VERSION",
    "GENERATED_AT",
    "EXPORTED_HMAC",
    "PromptBasic",
    "BASIC_PROMPTS",
    "render_template",
    "get_prompt",
    "list_names",
    "validate_variables",
    "verify_export_hmac",
    "snapshot_fingerprint",
]
