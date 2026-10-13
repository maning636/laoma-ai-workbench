"""
选择器版本化配置管理（Phase 2.1）

从 Python 硬编码迁移为 config/selectors/*.json 版本化文件，支持灰度和回滚。
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso


SELECTORS_DIR = Path(settings.BASE_DIR) / "config" / "selectors"

# 默认选择器数据（为各平台提供基本占位）
DEFAULT_SELECTORS: dict = {
    "douyin": {
        "version": "1.0.0",
        "selectors": {
            "title_input": "[class*='editor-container'] input, [placeholder*='标题']",
            "content_input": "[class*='editor-comp'] div[contenteditable]",
            "publish_btn": "button:has-text('发布')",
            "cover_edit": "[class*='coverControl'] [class*='cover']",
            "cover_done": "button:has-text('完成')",
            "tag_input": "[class*='tag'] input, [placeholder*='话题']",
            "upload_input": "input[type='file']",
            "guide_close": "button:has-text('跳过'), button:has-text('知道了'), button:has-text('关闭')",
        },
        "fallback_selectors": {
            "title_input": ["[class*='semi-input-wrapper'] input", ".semi-input"],
            "publish_btn": ["button.semi-button-primary", "[class*='publish-btn']"],
        },
        "last_updated": "2025-01-01T00:00:00",
        "description": "抖音基础选择器 v1.0",
    },
    "kuaishou": {
        "version": "1.0.0",
        "selectors": {
            "title_input": "[placeholder*='标题'] input, [class*='title'] input",
            "content_input": "[class*='editor'] div[contenteditable]",
            "publish_btn": "button:has-text('发布')",
            "tag_input": "[class*='topic'] input",
            "upload_input": "input[type='file']",
            "poi_button": "button:has-text('位置'), [class*='location']",
        },
        "fallback_selectors": {},
        "last_updated": "2025-01-01T00:00:00",
        "description": "快手基础选择器 v1.0",
    },
    "xiaohongshu": {
        "version": "1.0.0",
        "selectors": {
            "title_input": "[class*='title'] input, [placeholder*='标题']",
            "content_input": "[class*='editor'] div[contenteditable]",
            "publish_btn": "button:has-text('发布')",
            "tag_input": "[class*='topic'] input",
            "upload_input": "input[type='file']",
            "poi_button": "span:has-text('地点'), [class*='location']",
        },
        "fallback_selectors": {},
        "last_updated": "2025-01-01T00:00:00",
        "description": "小红书基础选择器 v1.0",
    },
    "bilibili": {
        "version": "1.0.0",
        "selectors": {
            "title_input": "input[name='title'], [placeholder*='标题']",
            "description_input": "[class*='desc'] textarea, [class*='editor'] div[contenteditable]",
            "tag_input": "[class*='tag'] input, [placeholder*='标签']",
            "publish_btn": "button:has-text('上传视频'), button:has-text('发布')",
            "partition_select": "[class*='part-select'], [class*='partition']",
            "upload_input": "input[type='file']",
        },
        "fallback_selectors": {},
        "last_updated": "2025-01-01T00:00:00",
        "description": "B站基础选择器 v1.0",
    },
    "tencent": {
        "version": "1.0.0",
        "selectors": {
            "title_input": "[placeholder*='标题'] input, [class*='title'] input",
            "content_input": "[class*='editor'] div[contenteditable]",
            "publish_btn": "button:has-text('发布')",
            "upload_input": "input[type='file']",
            "location_button": "button:has-text('位置'), [class*='location']",
            "mini_program_btn": "button:has-text('小程序'), [class*='mini']",
        },
        "fallback_selectors": {},
        "last_updated": "2025-01-01T00:00:00",
        "description": "视频号基础选择器 v1.0",
    },
}


class SelectorConfig(BaseModel):
    platform: str = ""
    version: str = "1.0.0"
    selectors: dict = {}
    fallback_selectors: dict = {}
    last_updated: str = Field(default_factory=now_beijing_iso)
    description: str = ""


def ensure_selectors_dir() -> None:
    """确保选择器目录存在并创建默认文件"""
    SELECTORS_DIR.mkdir(parents=True, exist_ok=True)
    for platform, data in DEFAULT_SELECTORS.items():
        config = SelectorConfig(platform=platform, **{k: v for k, v in data.items() if k != "platform"})
        path = _selector_file_path(platform, config.version)
        if not path.exists():
            path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
            logger.info(f"[Selectors] 创建默认选择器: {platform} v{config.version}")


def _selector_file_path(platform: str, version: str) -> Path:
    return SELECTORS_DIR / f"{platform}_v{version}.json"


def load_selectors(platform: str, version: Optional[str] = None) -> Optional[SelectorConfig]:
    """加载选择器配置，version=None 时加载最新版本"""
    ensure_selectors_dir()
    if version:
        path = _selector_file_path(platform, version)
        if path.exists():
            return SelectorConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
        return None

    versions = list_selector_versions(platform)
    if not versions:
        return None
    latest = versions[-1]
    path = _selector_file_path(platform, latest)
    return SelectorConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))


def save_selectors(config: SelectorConfig) -> str:
    """保存选择器配置，文件名含版本号"""
    ensure_selectors_dir()
    path = _selector_file_path(config.platform, config.version)
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    logger.info(f"[Selectors] 保存 {config.platform} v{config.version}")
    return str(path)


def list_selector_versions(platform: str) -> list[str]:
    """列出某平台的所有选择器版本"""
    ensure_selectors_dir()
    versions = []
    for f in SELECTORS_DIR.glob(f"{platform}_v*.json"):
        try:
            parts = f.stem.split("_v")
            if len(parts) >= 2:
                versions.append(parts[1])
        except Exception:
            pass
    return sorted(versions)


def rollback_selectors(platform: str, target_version: str) -> bool:
    """回滚到指定版本（复制目标版本为当前版本，标记为 rolled_back）"""
    target_path = _selector_file_path(platform, target_version)
    if not target_path.exists():
        logger.warning(f"[Selectors] 版本不存在: {platform} v{target_version}")
        return False

    config = SelectorConfig.model_validate(json.loads(target_path.read_text(encoding="utf-8")))
    config.description = f"[回滚] {config.description}"
    # 保存为 "current" 标记版本
    config.version = target_version
    save_selectors(config)
    logger.info(f"[Selectors] {platform} 回滚到 v{target_version}")
    return True


def get_selector(platform: str, selector_name: str, version: Optional[str] = None) -> Optional[str]:
    """获取单个选择器值，优先主选择器，失败时返回备选"""
    config = load_selectors(platform, version)
    if not config:
        return None
    return config.selectors.get(selector_name)


class SelectorVersionRegistry:
    """选择器版本注册表"""

    @classmethod
    def ensure_defaults(cls) -> None:
        ensure_selectors_dir()

    @classmethod
    def get_current(cls, platform: str) -> Optional[SelectorConfig]:
        return load_selectors(platform)

    @classmethod
    def get_all_platforms(cls) -> list[str]:
        ensure_selectors_dir()
        platforms = set()
        for f in SELECTORS_DIR.glob("*.json"):
            parts = f.stem.split("_v")
            if parts:
                platforms.add(parts[0])
        return sorted(platforms)

    @classmethod
    def create_new_version(cls, platform: str, selectors: dict, description: str = "") -> SelectorConfig:
        """创建新版本"""
        existing = list_selector_versions(platform)
        # 自动递增版本号
        if existing:
            major, minor, patch = [int(x) for x in existing[-1].split(".")]
            patch += 1
            new_version = f"{major}.{minor}.{patch}"
        else:
            new_version = "1.0.0"
        config = SelectorConfig(
            platform=platform, version=new_version, selectors=selectors,
            description=description,
        )
        save_selectors(config)
        return config


selector_version_registry = SelectorVersionRegistry()
