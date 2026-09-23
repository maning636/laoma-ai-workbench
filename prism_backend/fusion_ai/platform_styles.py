"""
平台差异化风格模板
━━━━━━━━━━━━━━━━━━
7+ 平台各自的语气、结构、排版、标签策略、封面规则。
同时支持前台 CRUD（PUT / DELETE）修改或自定义。

每个模板包含:
  - tone:          语气（如「专业理性」「轻松活泼」）
  - opening:       开头模板
  - closing:       结尾模板
  - max_word_count:字数上限
  - emoji_policy:  emoji 使用策略
  - structure_hint:结构建议
  - title_style:   标题写法
  - tags_max:      标签数量
  - cover_aspect:  封面比例
"""

from __future__ import annotations
import os, json
from pathlib import Path
from typing import Dict, Any, Optional, List
from loguru import logger

# 持久化目录（兼容 Railway volume 挂载，可通过 DATA_DIR 环境变量覆盖）
_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_OVERRIDES_FILE = _DATA_DIR / "platform_style_overrides.json"


# ============================================================
# 7 家平台默认风格模板
# ============================================================
PLATFORM_STYLES: Dict[str, Dict[str, Any]] = {
    "zhihu": {
        "name": "知乎",
        "tone": "专业理性，深度分析，有观点",
        "opening": "最近在思考一个问题，想和大家分享一下我的看法。",
        "closing": "以上是我的一点看法，欢迎在评论区讨论。",
        "max_word_count": 4000,
        "emoji_policy": "极少，仅关键处点缀",
        "structure_hint": "问题 → 分析 → 观点 → 总结",
        "title_style": "疑问句或观点句，控制在 30 字内",
        "tags_max": 5,
        "cover_aspect": "1280x720",
        "platform_specific": "首图+正文首段很重要，影响推荐",
    },
    "wechat": {
        "name": "微信公众号",
        "tone": "深度长文，叙事性强，有温度",
        "opening": "你有没有想过……",
        "closing": "如果你觉得这篇文章对你有启发，欢迎分享给朋友。",
        "max_word_count": 6000,
        "emoji_policy": "适中，增强可读性",
        "structure_hint": "故事引入 → 问题展开 → 分析 → 启示",
        "title_style": "引发好奇的疑问或断言句",
        "tags_max": 3,
        "cover_aspect": "900x500",
        "platform_specific": "封面图+标题决定打开率，首图需高清",
    },
    "xiaohongshu": {
        "name": "小红书",
        "tone": "轻松活泼，种草感，emoji 丰富",
        "opening": "姐妹们！最近发现一个宝藏好物✨",
        "closing": "希望这篇笔记帮到你～记得点赞收藏哦💖",
        "max_word_count": 1200,
        "emoji_policy": "大量使用，每段 2-3 个",
        "structure_hint": "标题党 → 痛点 → 解决方案 → 效果展示 → 引导互动",
        "title_style": "夸张+数字+emoji，18 字内抓眼球",
        "tags_max": 10,
        "cover_aspect": "3:4（竖版）",
        "platform_specific": "首图即一切，封面必须精修",
    },
    "douyin": {
        "name": "抖音",
        "tone": "网感强，节奏快，情绪饱满",
        "opening": "（无正文，纯口播/字幕）",
        "closing": "关注我不迷路！",
        "max_word_count": 500,
        "emoji_policy": "标题可多，正文极少",
        "structure_hint": "3 秒抓人 → 5 秒冲突 → 揭示 → 互动",
        "title_style": "悬念句或对比句，15 字内",
        "tags_max": 8,
        "cover_aspect": "9:16",
        "platform_specific": "前 3 秒决定生死，字幕要醒目",
    },
    "bilibili": {
        "name": "B 站",
        "tone": "UP 主风格，梗文化，亲切",
        "opening": "大家好我是 XXX，今天来聊一个……",
        "closing": "三连走一波～",
        "max_word_count": 3000,
        "emoji_policy": "适中，弹幕互动风",
        "structure_hint": "开场白 → 引入 → 正片 → 总结 → 三连引导",
        "title_style": "【主题】+ 亮点 + 情绪词，25 字内",
        "tags_max": 6,
        "cover_aspect": "16:9",
        "platform_specific": "封面文字 + 视频封面决定点击率",
    },
    "toutiao": {
        "name": "今日头条",
        "tone": "资讯风，客观中立，观点鲜明",
        "opening": "近日，……",
        "closing": "你怎么看？欢迎留言。",
        "max_word_count": 2500,
        "emoji_policy": "不使用",
        "structure_hint": "事件 → 背景 → 分析 → 观点",
        "title_style": "三段式标题，信息密度高，20 字内",
        "tags_max": 5,
        "cover_aspect": "16:9",
        "platform_specific": "标题信息密度影响推荐权重",
    },
    "juejin": {
        "name": "掘金",
        "tone": "技术干货，代码先行，有深度",
        "opening": "最近在项目中遇到了一个问题，记录一下解决过程。",
        "closing": "以上就是全部内容，欢迎在评论区交流。",
        "max_word_count": 5000,
        "emoji_policy": "极少，保持专业",
        "structure_hint": "问题 → 环境 → 方案 → 代码 → 总结",
        "title_style": "技术关键词+解决方案，25 字内",
        "tags_max": 5,
        "cover_aspect": "16:9",
        "platform_specific": "代码块多，README 风格",
    },
}


def get_platform_style(platform: str) -> Optional[Dict[str, Any]]:
    """获取指定平台风格，已加载用户覆盖"""
    data = _load_overrides()
    return data.get(platform, PLATFORM_STYLES.get(platform))


def get_all_platform_styles() -> Dict[str, Dict[str, Any]]:
    """获取所有平台风格（合并覆盖）"""
    data = _load_overrides()
    return {**PLATFORM_STYLES, **data}


def apply_platform_style(content: str, platform: str) -> Dict[str, Any]:
    """
    将内容按平台风格包装（标题/开头/结尾拼接）。
    返回：{ original, styled, platform, meta }
    """
    style = get_platform_style(platform)
    if not style:
        return {"original": content, "styled": content, "platform": platform, "meta": {}}

    styled = f"{style['opening']}\n\n{content}\n\n{style['closing']}"

    return {
        "original": content,
        "styled": styled,
        "platform": platform,
        "meta": {
            "tone": style["tone"],
            "max_word_count": style["max_word_count"],
            "tags_max": style["tags_max"],
            "cover_aspect": style["cover_aspect"],
        },
    }


def update_platform_style(platform: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """前台 PUT：覆盖某个平台的风格配置"""
    data = _load_overrides()
    base = PLATFORM_STYLES.get(platform, {})
    merged = {**base, **updates}
    data[platform] = merged
    _save_overrides(data)
    return merged


def delete_platform_override(platform: str) -> bool:
    """前台 DELETE：恢复默认风格"""
    data = _load_overrides()
    removed = platform in data
    data.pop(platform, None)
    _save_overrides(data)
    return removed


def list_platform_ids() -> List[str]:
    return list(PLATFORM_STYLES.keys())


# ---- 持久化 helper ----
def _load_overrides() -> Dict[str, Dict[str, Any]]:
    try:
        if _OVERRIDES_FILE.exists():
            raw = _OVERRIDES_FILE.read_text(encoding="utf-8")
            return json.loads(raw) if raw.strip() else {}
    except Exception as e:
        logger.warning(f"加载平台风格覆盖失败: {e}")
    return {}


def _save_overrides(data: Dict[str, Dict[str, Any]]) -> None:
    try:
        _OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
        _OVERRIDES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"保存平台风格覆盖失败: {e}")