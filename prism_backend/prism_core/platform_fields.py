"""
平台字段管理与扩展功能（Phase 1.1-1.5）

每个平台的发布字段配置与特殊功能支持：
- douyin: 商品挂载、自主声明、合集
- kuaishou: POI/地理位置、游戏挂载
- xiaohongshu: POI/地理位置
- bilibili: 游戏、标签扩展
- tencent: 地理位置、小程序、公众号文章
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field as PydanticField


class Platform(str, Enum):
    DOUYIN = "douyin"
    KUAISHOU = "kuaishou"
    XIAOHONGSHU = "xiaohongshu"
    BILIBILI = "bilibili"
    TENCENT = "tencent"
    CHANNELS = "channels"


class FieldCategory(str, Enum):
    BASIC = "basic"          # 标题、正文、标签
    LOCATION = "location"    # POI/地理位置
    PRODUCT = "product"      # 商品/游戏挂载
    DECLARATION = "declaration"  # 自主声明/AI标记
    ARTICLE = "article"      # 公众号文章/链接
    MINI_PROGRAM = "mini_program"
    COLLECTION = "collection"


@dataclass
class FieldSpec:
    key: str
    label: str
    category: FieldCategory
    required: bool = False
    enabled: bool = True
    default_value: Any = None
    max_length: Optional[int] = None
    options: List[str] = field(default_factory=list)
    description: str = ""


class PlatformFieldsConfig(BaseModel):
    platform: Platform
    platform_code: int
    fields: List[FieldSpec]
    extra_caps: List[str] = []
    description: str = ""


# ── 各平台字段定义 ──

DOUYIN_FIELDS = [
    FieldSpec(key="title", label="标题", category=FieldCategory.BASIC, required=True, max_length=55),
    FieldSpec(key="content", label="正文", category=FieldCategory.BASIC, required=False, max_length=2000),
    FieldSpec(key="tags", label="话题标签", category=FieldCategory.BASIC),
    FieldSpec(key="product_link", label="标记万物(购物车)", category=FieldCategory.PRODUCT, description="抖音2025新UI：购物车已变更为标记万物"),
    FieldSpec(key="declaration", label="自主声明", category=FieldCategory.DECLARATION,
              options=["无需添加自主声明", "内容由AI生成", "虚构演绎，仅供娱乐", "内容为个人观点或见解", "内容含营销推广信息"]),
    FieldSpec(key="collection_id", label="合集ID", category=FieldCategory.COLLECTION),
]

KUAISHOU_FIELDS = [
    FieldSpec(key="title", label="标题", category=FieldCategory.BASIC, required=True, max_length=30),
    FieldSpec(key="content", label="正文", category=FieldCategory.BASIC),
    FieldSpec(key="tags", label="话题标签", category=FieldCategory.BASIC),
    FieldSpec(key="poi", label="地理位置(POI)", category=FieldCategory.LOCATION),
    FieldSpec(key="game_link", label="游戏挂载", category=FieldCategory.PRODUCT),
]

XIAOHONGSHU_FIELDS = [
    FieldSpec(key="title", label="标题", category=FieldCategory.BASIC, required=True, max_length=20),
    FieldSpec(key="content", label="正文", category=FieldCategory.BASIC, required=True, max_length=1000),
    FieldSpec(key="tags", label="话题标签", category=FieldCategory.BASIC),
    FieldSpec(key="poi", label="地理位置(POI)", category=FieldCategory.LOCATION),
]

BILIBILI_FIELDS = [
    FieldSpec(key="title", label="标题", category=FieldCategory.BASIC, required=True, max_length=80),
    FieldSpec(key="description", label="简介", category=FieldCategory.BASIC, max_length=2500),
    FieldSpec(key="tags", label="标签", category=FieldCategory.BASIC),
    FieldSpec(key="partition", label="分区", category=FieldCategory.BASIC),
    FieldSpec(key="game", label="游戏", category=FieldCategory.PRODUCT),
]

TENCENT_FIELDS = [
    FieldSpec(key="title", label="标题", category=FieldCategory.BASIC, required=True, max_length=50),
    FieldSpec(key="content", label="正文", category=FieldCategory.BASIC, max_length=1000),
    FieldSpec(key="tags", label="话题标签", category=FieldCategory.BASIC),
    FieldSpec(key="location", label="地理位置", category=FieldCategory.LOCATION),
    FieldSpec(key="mini_program", label="小程序链接", category=FieldCategory.MINI_PROGRAM),
    FieldSpec(key="article_url", label="公众号文章", category=FieldCategory.ARTICLE),
]

CHANNELS_FIELDS = TENCENT_FIELDS  # 视频号与腾讯平台共享字段

PLATFORM_FIELD_MAP: Dict[Platform, List[FieldSpec]] = {
    Platform.DOUYIN: DOUYIN_FIELDS,
    Platform.KUAISHOU: KUAISHOU_FIELDS,
    Platform.XIAOHONGSHU: XIAOHONGSHU_FIELDS,
    Platform.BILIBILI: BILIBILI_FIELDS,
    Platform.TENCENT: TENCENT_FIELDS,
    Platform.CHANNELS: CHANNELS_FIELDS,
}

PLATFORM_CODES: Dict[Platform, int] = {
    Platform.DOUYIN: 3,
    Platform.KUAISHOU: 4,
    Platform.XIAOHONGSHU: 1,
    Platform.BILIBILI: 5,
    Platform.TENCENT: 2,
    Platform.CHANNELS: 2,
}


def get_platform_fields(platform: Platform) -> List[FieldSpec]:
    return PLATFORM_FIELD_MAP.get(platform, [])


def get_fields_by_category(platform: Platform, category: FieldCategory) -> List[FieldSpec]:
    return [f for f in get_platform_fields(platform) if f.category == category]


def get_field_spec(platform: Platform, key: str) -> Optional[FieldSpec]:
    return next((f for f in get_platform_fields(platform) if f.key == key), None)


def validate_publish_payload(platform: Platform, payload: Dict[str, Any]) -> Dict[str, Any]:
    """验证发布载荷是否符合平台字段规范"""
    fields = get_platform_fields(platform)
    result = {"valid": True, "errors": [], "warnings": []}
    for fs in fields:
        if fs.required and not payload.get(fs.key):
            result["errors"].append(f"必填字段缺失: {fs.label} ({fs.key})")
            result["valid"] = False
        val = payload.get(fs.key)
        if val and fs.max_length and isinstance(val, str) and len(val) > fs.max_length:
            result["warnings"].append(f"字段 {fs.label} 超过最大长度 {fs.max_length}")
        if fs.options and val and val not in fs.options:
            result["warnings"].append(f"字段 {fs.label} 值 '{val}' 不在有效选项中")
    return result


def normalize_declaration(platform: Platform, declaration: str) -> str:
    """归一化自主声明值（抖音特有）"""
    if platform == Platform.DOUYIN:
        MAP = {
            "不涉及（无需声明）": "无需添加自主声明",
            "不涉及": "无需添加自主声明",
            "使用AI工具生成": "内容由AI生成",
            "二次创作/剪辑": "内容为个人观点或见解",
            "剧情演绎/表演": "虚构演绎，仅供娱乐",
            "含广告/推广": "内容含营销推广信息",
            "知识科普": "内容为个人观点或见解",
        }
        return MAP.get(declaration, declaration)
    return declaration


class PlatformFieldsRegistry:
    """平台字段注册表"""

    @classmethod
    def get_config(cls, platform: Platform) -> PlatformFieldsConfig:
        fields = get_platform_fields(platform)
        extra = []
        if platform == Platform.DOUYIN:
            extra = ["cover_edit", "ai_declaration", "collection"]
        elif platform == Platform.KUAISHOU:
            extra = ["poi", "game_mount"]
        elif platform == Platform.XIAOHONGSHU:
            extra = ["poi", "topic_tag"]
        elif platform == Platform.BILIBILI:
            extra = ["game", "extended_tags", "partition"]
        elif platform in (Platform.TENCENT, Platform.CHANNELS):
            extra = ["location", "mini_program", "article"]
        return PlatformFieldsConfig(
            platform=platform,
            platform_code=PLATFORM_CODES.get(platform, 0),
            fields=fields,
            extra_caps=extra,
        )

    @classmethod
    def list_all_platforms(cls) -> List[PlatformFieldsConfig]:
        return [cls.get_config(p) for p in Platform]


platform_fields_registry = PlatformFieldsRegistry()
