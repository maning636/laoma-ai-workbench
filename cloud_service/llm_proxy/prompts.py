"""Prompt 库(C14):分层注册表 + 渲染 + 校验。

分层(设计文档 §2.2):
  cloud tier — 高价值 prompt,**只在云端**;客户端只按 name 触发,看不到模板源码。
  basic tier — 基础模板,允许离线版复用(客户端 `fusion_ai/prompts_basic.py` 是其快照)。

模板语法:Jinja2 风格 `{{ var }}` 占位符;渲染用 `render_template()`。
不做 `| safe` / `{% block %}` 等高级语法 —— prompt 是"给 LLM 看的文字",
不需要执行代码;`_StrictFormatter` 只做键值替换 + 未定义变量报错。

## 开源边界(D6)

**cloud tier 的提示词正文是核心资产,不在开源仓里。** 本文件是开源仓版本:

| 内容 | 开源仓 | Pro 部署 |
|---|---|---|
| `PromptDef` 数据结构 | ✅ 在这里 | 同 |
| `BASIC_PROMPTS`(基础模板正文) | ✅ 在这里 | 同 |
| `CLOUD_PROMPT_MANIFEST`(云端模板的**名字/描述/变量**,API 契约) | ✅ 在这里 | 同 |
| `CLOUD_PROMPTS`(**云端模板正文**) | ❌ 空 | 由 `_pro_assets/prompts_cloud.py` 注入 |

Pro 版的注入方式:把私有资产文件放到
`cloud_service/llm_proxy/_pro_assets/prompts_cloud.py`(该目录被 `.gitignore` 排除),
本模块在 import 时按路径加载它。注入脚本见 `scripts/cloud/inject_pro_assets.py`。

开源仓下调用云端模板会得到明确的「需 Pro 版」提示,而不是 404 式的"不存在"。

SEED 数据由 `sync_prompts_to_db()` 幂等 upsert 到 `prompts` 表(供 DB 驱动的路径使用),
但线上真正渲染走本模块的内存表 `CLOUD_PROMPTS` / `BASIC_PROMPTS`,
避免每次请求打 DB;表主要给运营/后台查询 + 未来版本管理用。
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Prompt
from .prompt_def import PromptDef

logger = logging.getLogger(__name__)


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


# ──────────────────────────────────────────────────────────────
# Cloud tier — 清单(公开) + 正文(Pro 私有,运行时注入)
# ──────────────────────────────────────────────────────────────
# 变量占位符:
#   topic         — 主题/选题关键词
#   tone          — 语气(专业 / 幽默 / 情绪饱满 ...)
#   style         — 风格补充(平台/领域)
#   audience      — 目标受众
#   content       — 输入正文(评审类 prompt)
#   platform      — 目标平台(xiaohongshu / douyin / zhihu ...)
#   constraints   — 约束(字数、tag 上限 ...)
#
# `CLOUD_PROMPT_MANIFEST` 只登记 **API 契约**(名字 / 版本 / 描述 / 变量列表),
# 不含任何提示词正文 —— 客户端需要它来构建表单,服务端需要它来判定
# "这个名字是存在的,只是开源版拿不到模板"。
# ──────────────────────────────────────────────────────────────

CLOUD_PROMPT_MANIFEST: dict[str, dict[str, Any]] = {
    "cognition.matrix_evaluate": {
        "version": "1.0.0",
        "description": "认知矩阵:5 维度评估内容(选题/结构/情绪/权威/行动)",
        "variables": ["content", "audience"],
    },
    "cognition.audience_persona": {
        "version": "1.0.0",
        "description": "受众画像:从内容反推目标人群 + 语言风格偏好",
        "variables": ["content"],
    },
    "platform_style.match": {
        "version": "1.0.0",
        "description": "平台风格适配:根据平台生成符合调性的标题 + 结构 + tag",
        "variables": ["platform", "topic", "constraints"],
    },
    "hot_topic.mining": {
        "version": "1.0.0",
        "description": "热点挖掘:从话题簇中挑选高潜力选题 + 差异化角度",
        "variables": ["topic_cluster", "audience"],
    },
    "moderator.review": {
        "version": "1.0.0",
        "description": "内容合规审核:识别平台红线 + 敏感表达",
        "variables": ["content", "platform"],
    },
}


#: 云端模板正文所在的私有资产目录(被 .gitignore 排除,Pro 部署时注入)
_PRO_ASSETS_DIRNAME = "_pro_assets"
_PRO_ASSET_FILENAME = "prompts_cloud.py"

#: 开源仓下调用云端模板时统一返回的提示
PRO_REQUIRED_DETAIL = (
    "该 prompt 属于 Pro 版云端能力,开源版本不包含其模板。"
    "请升级到 Pro 版后重试,或改用 basic tier prompt。"
)


def _default_asset_path() -> Path:
    return Path(__file__).resolve().parent / _PRO_ASSETS_DIRNAME / _PRO_ASSET_FILENAME


def _read_asset_module(asset_path: Path) -> dict[str, Any]:
    """按文件路径加载私有资产模块,取其中的 `CLOUD_PROMPT_ASSETS` 字典。

    资产文件是**纯数据**(不 import 任何模块),所以用 `importlib` 按路径加载
    既不会形成循环依赖,也便于在 Pro 打包时整体替换。
    """
    spec = importlib.util.spec_from_file_location("_prism_pro_prompts_cloud", asset_path)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御
        raise ImportError(f"cannot load pro asset spec from {asset_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assets = getattr(module, "CLOUD_PROMPT_ASSETS", None)
    if not isinstance(assets, dict):
        raise ImportError(
            f"{asset_path} must define a dict named CLOUD_PROMPT_ASSETS"
        )
    return assets


def _build_cloud_prompts(raw: dict[str, Any]) -> dict[str, PromptDef]:
    """把纯数据资产转成 `PromptDef` 字典。

    变量清单以**资产文件**为准;资产缺字段时回退到 manifest 里的声明。
    """
    out: dict[str, PromptDef] = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            raise ValueError(f"cloud asset {name!r} must be a dict")
        manifest_item = CLOUD_PROMPT_MANIFEST.get(name, {})
        template = item.get("template")
        if not isinstance(template, str) or not template.strip():
            raise ValueError(f"cloud asset {name!r} has no non-empty template")
        variables = item.get("variables")
        if variables is None:
            variables = manifest_item.get("variables", [])
        out[name] = PromptDef(
            name=name,
            template=template,
            tier="cloud",
            variables=tuple(variables),
            version=str(item.get("version") or manifest_item.get("version") or "1.0.0"),
            description=str(item.get("description") or manifest_item.get("description") or ""),
        )
    return out


def reload_cloud_prompts(asset_path: str | Path | None = None) -> bool:
    """(重新)加载云端模板正文,返回是否加载成功。

    - Pro 部署:资产文件存在 → 成功,`CLOUD_PROMPTS` 被就地填充。
    - 开源仓:资产文件不存在 → 返回 `False`,`CLOUD_PROMPTS` 为空,
      调用云端模板会得到明确的「需 Pro 版」提示。

    幂等:重复调用安全。加载失败(文件存在但内容坏)不抛异常,
    只记日志并降级为空 —— 服务不应因为资产损坏而整体起不来。
    """
    path = Path(asset_path) if asset_path is not None else _default_asset_path()
    global CLOUD_PROMPTS
    if not path.is_file():
        logger.info(
            "[prompts] cloud tier 资产未注入(%s),云端模板不可用(开源版预期行为)", path
        )
        CLOUD_PROMPTS = {}
        _rebuild_all_prompts()
        return False
    try:
        raw = _read_asset_module(path)
        built = _build_cloud_prompts(raw)
    except Exception as exc:  # noqa: BLE001 - 资产损坏不应拖垮服务
        logger.error("[prompts] 云端资产加载失败(%s): %s", path, exc)
        CLOUD_PROMPTS = {}
        _rebuild_all_prompts()
        return False
    CLOUD_PROMPTS = built
    _rebuild_all_prompts()
    logger.info("[prompts] 已加载云端模板 %d 条(%s)", len(built), path)
    return True


def _rebuild_all_prompts() -> None:
    """同步 `ALL_PROMPTS` = basic + 已加载的 cloud。"""
    ALL_PROMPTS.clear()
    ALL_PROMPTS.update(BASIC_PROMPTS)
    ALL_PROMPTS.update(CLOUD_PROMPTS)


#: 云端模板正文(Pro 私有,开源仓为空)
CLOUD_PROMPTS: dict[str, PromptDef] = {}

#: 全部 prompt(basic + 已加载的 cloud)
ALL_PROMPTS: dict[str, PromptDef] = {**BASIC_PROMPTS}


# 模块 import 时自动加载一次(Pro 部署能直接生效)
reload_cloud_prompts()


# ──────────────────────────────────────────────────────────────
# 查询 / 校验
# ──────────────────────────────────────────────────────────────

def get_prompt(name: str) -> PromptDef | None:
    return ALL_PROMPTS.get(name)


def is_pro_required(name: str) -> bool:
    """该 prompt 名属于云端 tier,但当前部署没有它的模板正文。

    用于把"开源版拿不到"和"名字不存在"区分开,给出可操作的错误提示。
    """
    return name in CLOUD_PROMPT_MANIFEST and name not in ALL_PROMPTS


def list_prompt_names(tier: str | None = None) -> list[str]:
    if tier is None:
        return sorted(ALL_PROMPTS.keys())
    if tier == "cloud":
        return sorted(CLOUD_PROMPTS.keys())
    if tier == "basic":
        return sorted(BASIC_PROMPTS.keys())
    raise ValueError(f"unknown tier: {tier!r} (expect 'cloud' or 'basic')")


def list_prompt_manifest(tier: str | None = None) -> list[dict[str, Any]]:
    """列出 **声明存在** 的 prompt(含未注入正文、需 Pro 的那些)。

    用途:让客户端能展示"有哪些云端能力",而不泄露模板正文。
    返回项:`{name, tier, version, description, variables, available}`。
    `available=False` 表示当前部署拿不到模板正文。
    """
    out: list[dict[str, Any]] = []
    names: list[str]
    if tier is None:
        names = sorted(set(ALL_PROMPTS) | set(CLOUD_PROMPT_MANIFEST))
    elif tier == "cloud":
        names = sorted(CLOUD_PROMPT_MANIFEST)
    elif tier == "basic":
        names = sorted(BASIC_PROMPTS)
    else:
        raise ValueError(f"unknown tier: {tier!r} (expect 'cloud' or 'basic')")

    for name in names:
        pdef = ALL_PROMPTS.get(name)
        if pdef is not None:
            out.append(
                {
                    "name": pdef.name,
                    "tier": pdef.tier,
                    "version": pdef.version,
                    "description": pdef.description,
                    "variables": list(pdef.variables),
                    "available": True,
                }
            )
            continue
        meta = CLOUD_PROMPT_MANIFEST.get(name)
        if meta is None:
            continue
        out.append(
            {
                "name": name,
                "tier": "cloud",
                "version": str(meta.get("version") or "1.0.0"),
                "description": str(meta.get("description") or ""),
                "variables": list(meta.get("variables") or []),
                "available": False,
            }
        )
    return out


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
      - 开源仓没有云端正文,`cloud` 一档会是 0 —— 这是预期,不是错误。
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
    """各 tier 的 prompt 数量。

    - `cloud`:当前部署**实际可渲染**的云端模板数(开源仓为 0)。
    - `cloud_declared`:清单里声明的云端模板数(开源仓也是 5)。
    - `pro_assets_loaded`:1/0,表示云端资产是否已注入。
    """
    return {
        "cloud": len(CLOUD_PROMPTS),
        "cloud_declared": len(CLOUD_PROMPT_MANIFEST),
        "basic": len(BASIC_PROMPTS),
        "total": len(ALL_PROMPTS),
        "pro_assets_loaded": 1 if CLOUD_PROMPTS else 0,
    }


__all__ = [
    "PromptDef",
    "CLOUD_PROMPTS",
    "CLOUD_PROMPT_MANIFEST",
    "BASIC_PROMPTS",
    "ALL_PROMPTS",
    "PRO_REQUIRED_DETAIL",
    "render_template",
    "get_prompt",
    "is_pro_required",
    "list_prompt_names",
    "list_prompt_manifest",
    "validate_variables",
    "sync_prompts_to_db",
    "prompt_count_by_tier",
    "reload_cloud_prompts",
]
