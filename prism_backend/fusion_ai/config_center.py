"""
前台配置中心
━━━━━━━━━━━
统一管理所有前台可编辑的配置组，每组独立存 JSON 文件。

设计：
- 20 组配置，覆盖敏感词、平台风格覆盖、预设问题、技能、画像等
- 每组有稳定的 config_id（slug），前台用 URL 参数直接访问
- 所有配置持久化到 $DATA_DIR/fusion_config/ 下的独立文件
- 提供 list / get / set 三接口，支持任意 JSON 值（数组、对象、字符串、数字）
"""

from __future__ import annotations
import os, json
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
_CONFIG_DIR = _DATA_DIR / "fusion_config"
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 20 组配置定义（元数据 + 默认值）
# ============================================================
CONFIG_GROUPS: Dict[str, Dict[str, Any]] = {
    "sensitive_words": {
        "label": "敏感词库",
        "description": "内容审核的第一层敏感词列表",
        "category": "内容审核",
        "default": [],
        "schema_hint": "array of {category, word}",
    },
    "sensitive_categories": {
        "label": "敏感词分类",
        "description": "敏感词的分类定义",
        "category": "内容审核",
        "default": ["色情", "赌博", "暴力", "政治", "广告", "其他"],
        "schema_hint": "array of string",
    },
    "moderation_thresholds": {
        "label": "审核阈值",
        "description": "各层审核的阈值配置",
        "category": "内容审核",
        "default": {
            "layer1_block_count": 1,
            "layer2_min_confidence": 0.7,
            "layer3_auto_rewrite": True,
        },
        "schema_hint": "object",
    },
    "platform_style_overrides": {
        "label": "平台风格覆盖",
        "description": "对默认平台风格的自定义修改",
        "category": "平台",
        "default": {},
        "schema_hint": "object keyed by platform id",
    },
    "platform_style_enabled": {
        "label": "平台风格启用",
        "description": "各平台风格是否启用",
        "category": "平台",
        "default": {},
        "schema_hint": "object {platform_id: bool}",
    },
    "hot_topics_sources": {
        "label": "热点来源",
        "description": "启用的热点抓取平台",
        "category": "热点",
        "default": ["weibo", "zhihu", "douyin", "toutiao", "xiaohongshu"],
        "schema_hint": "array of string",
    },
    "hot_topics_cache_ttl": {
        "label": "热点缓存时长",
        "description": "热点缓存过期时间（秒）",
        "category": "热点",
        "default": 1800,
        "schema_hint": "integer (seconds)",
    },
    "image_model_defaults": {
        "label": "生图默认模型",
        "description": "默认使用的生图模型 ID",
        "category": "生图",
        "default": "nanobanana",
        "schema_hint": "string (model_id)",
    },
    "image_size_defaults": {
        "label": "生图默认尺寸",
        "description": "默认生图尺寸",
        "category": "生图",
        "default": "1024x1024",
        "schema_hint": "string",
    },
    "image_search_api_key": {
        "label": "图片搜索 API Key",
        "description": "Unsplash 等搜索 API Key",
        "category": "生图",
        "default": "",
        "schema_hint": "string",
    },
    "provider_probe_order": {
        "label": "Provider 探测顺序",
        "description": "多 Provider 自动探测时的优先级",
        "category": "AI Provider",
        "default": [
            "deepseek", "gemini", "groq", "silicon", "qwen",
            "openai", "kimi", "zhipu", "minimax", "volcengine", "moonshot",
        ],
        "schema_hint": "array of provider id",
    },
    "provider_default_model": {
        "label": "Provider 默认模型",
        "description": "各 Provider 默认使用的模型",
        "category": "AI Provider",
        "default": {},
        "schema_hint": "object {provider_id: model_name}",
    },
    "ai_rewriter_prompt": {
        "label": "AI 改写 Prompt",
        "description": "L3 内容审核改写时使用的 prompt 模板",
        "category": "AI Provider",
        "default": "请把以下内容改写为符合平台规范的版本，保持原意但去除违规表述：",
        "schema_hint": "string",
    },
    "model_recommend_rules": {
        "label": "模型推荐规则",
        "description": "按用例推荐的模型规则",
        "category": "模型广场",
        "default": {
            "writing": "deepseek/deepseek-v4-flash",
            "reasoning": "deepseek/deepseek-v4-pro",
            "batch": "gemini/gemini-2.5-flash",
            "multimodal": "openai/gpt-4o",
            "coding": "deepseek/deepseek-coder-v3",
            "fast": "groq/llama-3.1-8b-instant",
        },
        "schema_hint": "object",
    },
    "skill_defaults": {
        "label": "技能默认链",
        "description": "默认应用的技能链",
        "category": "技能工坊",
        "default": ["deai_style", "deai_vocab"],
        "schema_hint": "array of skill id",
    },
    "skill_auto_rewrite": {
        "label": "技能自动改写",
        "description": "是否对 AI 生成内容自动应用去 AIGC 技能",
        "category": "技能工坊",
        "default": False,
        "schema_hint": "boolean",
    },
    "audience_persona_default": {
        "label": "默认受众画像",
        "description": "系统默认的受众画像",
        "category": "认知",
        "default": {},
        "schema_hint": "object",
    },
    "cognition_min_length": {
        "label": "认知分析最小长度",
        "description": "内容 DNA 分析的最小字数阈值",
        "category": "认知",
        "default": 50,
        "schema_hint": "integer",
    },
    "nl_query_source": {
        "label": "NL→SQL 数据源",
        "description": "NL 查询的数据源切换（prism/fusion）",
        "category": "数据分析",
        "default": "prism",
        "schema_hint": "enum: prism|fusion",
    },
    "nl_query_presets": {
        "label": "NL 查询预设",
        "description": "预设的自然语言查询问题",
        "category": "数据分析",
        "default": [
            {"question": "近 30 天发布最多的账号是谁？", "title": "账号活跃度"},
            {"question": "最近 7 天发布的视频总数是多少？", "title": "发布量"},
            {"question": "各平台发布数量分布如何？", "title": "平台分布"},
            {"question": "发布最多的 10 个视频是什么？", "title": "热门视频"},
        ],
        "schema_hint": "array of {question, title}",
    },
}


def _config_file(config_id: str) -> Path:
    return _CONFIG_DIR / f"{config_id}.json"


def list_groups() -> List[Dict[str, Any]]:
    """列出所有配置组元数据 + 当前值"""
    result = []
    for cid, meta in CONFIG_GROUPS.items():
        value = _load_value(cid)
        result.append({
            "id": cid,
            **meta,
            "value": value,
        })
    return result


def get_config(config_id: str) -> Optional[Dict[str, Any]]:
    """获取单个配置组的元数据 + 当前值"""
    meta = CONFIG_GROUPS.get(config_id)
    if not meta:
        return None
    return {
        "id": config_id,
        **meta,
        "value": _load_value(config_id),
    }


def set_config(config_id: str, value: Any) -> Dict[str, Any]:
    """保存配置值（覆盖整个值）"""
    if config_id not in CONFIG_GROUPS:
        raise ValueError(f"未知配置组: {config_id}")
    _save_value(config_id, value)
    return get_config(config_id)


def reset_config(config_id: str) -> Dict[str, Any]:
    """重置为默认值"""
    if config_id not in CONFIG_GROUPS:
        raise ValueError(f"未知配置组: {config_id}")
    _save_value(config_id, json.loads(json.dumps(CONFIG_GROUPS[config_id]["default"])))
    return get_config(config_id)


def _load_value(config_id: str) -> Any:
    """加载单个配置组的值（无文件则返回默认值）"""
    f = _config_file(config_id)
    if not f.exists():
        return json.loads(json.dumps(CONFIG_GROUPS[config_id]["default"]))
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"读取配置 {config_id} 失败，回退默认值：{e}")
        return json.loads(json.dumps(CONFIG_GROUPS[config_id]["default"]))


def _save_value(config_id: str, value: Any) -> None:
    """保存单个配置组的值"""
    f = _config_file(config_id)
    f.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")