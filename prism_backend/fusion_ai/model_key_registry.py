"""M1 · modelKey 路由层（澜途 /ai-design/capabilities 对齐）。

参考澜途 API 审计 `/ai-design/capabilities` 响应结构：

    {
      "models": [
        {
          "modelKey": "dall-e-3",
          "displayName": "DALL-E 3",
          "capabilities": ["IMAGE_GENERATE"],
          "supportedAspectRatios": ["1:1", "16:9", "9:16"],
          "maxOutputCount": 1,
          "maxReferenceImages": 0,
          "supportedInputMediaTypes": ["TEXT"]
        },
        ...
      ]
    }

设计原则：
  1. **只加路由层，不重写 provider**：底层仍调用 `image_generators.generate_single_image`，
     每个 modelKey 映射到 `BUILTIN_IMAGE_MODELS[*].id` 或 `custom_image_models[*].id`。
  2. **如实声明能力**：现有 provider 只支持 prompt→图，不支持参考图编辑/商品分析，
     所以 `capabilities` 只声明 `IMAGE_GENERATE`；`maxReferenceImages=0`；
     `supportedInputMediaTypes=["TEXT"]`。不要伪造。
  3. **maxOutputCount=1**：现有所有 provider 的 OpenAI 兼容调用都硬编码 `n=1`，
     单请求只返回 1 张；多张由业务层循环调用。
  4. **aspect_ratio → size 映射**：把用户可见的 aspect_ratio（"1:1"/"16:9"/...）
     翻译为 provider 需要的 `size` 字符串（如 "1024x1024"）。每个 provider 只声明
     自己真实支持的宽高比；请求了不支持的比例会 400。

扩展点：
  - 新增 provider：在 `BUILTIN_IMAGE_MODELS` 加一条 → 在本文件 `MODEL_REGISTRY` 加对应 modelKey。
  - 新增能力：给 MODEL_REGISTRY 的对应条目补 `"IMAGE_EDIT"` / `"PRODUCT_ANALYSIS"`，
    但要先在 `image_generators.py` 里实现对应分支（例如 `_openai_compatible_edit`）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .image_generators import get_model_def, list_custom_models

# ──────────────────────────────────────────────────────────────
# 能力常量（澜途对齐）
# ──────────────────────────────────────────────────────────────

CAP_IMAGE_GENERATE = "IMAGE_GENERATE"
CAP_IMAGE_EDIT = "IMAGE_EDIT"
CAP_PRODUCT_ANALYSIS = "PRODUCT_ANALYSIS"

# 输入媒介类型
MEDIA_TEXT = "TEXT"
MEDIA_IMAGE = "IMAGE"

# ──────────────────────────────────────────────────────────────
# MODEL_REGISTRY：澜途格式的能力声明表
#
# 每个条目对应 image_generators 里的一个 provider（id）；
# modelKey 是前端/业务调用方使用的稳定标识（对外暴露）。
#
# 约束：
#   - capabilities 只列 provider 真实支持的能力，不写占位。
#   - supportedAspectRatios 只列 provider 真实支持的宽高比。
#   - maxOutputCount 与 provider 单次请求 n 值对齐（当前全部为 1）。
#   - maxReferenceImages=0（现有 provider 不吃参考图）。
# ──────────────────────────────────────────────────────────────

MODEL_REGISTRY: List[Dict[str, Any]] = [
    {
        "modelKey": "nanobanana",
        "displayName": "Nano Banana (Gemini 2.5 Flash Image)",
        "version": 1,
        "capabilities": [CAP_IMAGE_GENERATE],
        "supportedAspectRatios": ["1:1"],
        "maxOutputCount": 1,
        "maxReferenceImages": 0,
        "supportedInputMediaTypes": [MEDIA_TEXT],
        "_model_id": "nano_banana",  # 内部 provider id（下划线前缀 → 不对前端暴露）
    },
    {
        "modelKey": "dall-e-3",
        "displayName": "DALL-E 3",
        "version": 1,
        "capabilities": [CAP_IMAGE_GENERATE],
        # OpenAI DALL-E 3 官方支持三种：1024x1024 / 1792x1024 / 1024x1792
        "supportedAspectRatios": ["1:1", "16:9", "9:16"],
        "maxOutputCount": 1,
        "maxReferenceImages": 0,
        "supportedInputMediaTypes": [MEDIA_TEXT],
        "_model_id": "dalle3",
    },
    {
        "modelKey": "flux-pro",
        "displayName": "Flux Pro",
        "version": 1,
        "capabilities": [CAP_IMAGE_GENERATE],
        # 走 NanoBanana 兼容接口，兼容常用比例
        "supportedAspectRatios": ["1:1", "3:4", "4:3", "16:9", "9:16"],
        "maxOutputCount": 1,
        "maxReferenceImages": 0,
        "supportedInputMediaTypes": [MEDIA_TEXT],
        "_model_id": "flux_pro",
    },
    {
        "modelKey": "flux-2-pro",
        "displayName": "Flux 2 Pro",
        "version": 1,
        "capabilities": [CAP_IMAGE_GENERATE],
        "supportedAspectRatios": ["1:1", "3:4", "4:3", "16:9", "9:16"],
        "maxOutputCount": 1,
        "maxReferenceImages": 0,
        "supportedInputMediaTypes": [MEDIA_TEXT],
        "_model_id": "flux_2_pro",
    },
    {
        "modelKey": "wanx",
        "displayName": "通义万象 (Wanx2.1 Turbo)",
        "version": 1,
        "capabilities": [CAP_IMAGE_GENERATE],
        # 阿里云 DashScope wanx2.1-t2i-turbo 固定 1440*960（≈3:2）
        "supportedAspectRatios": ["3:2"],
        "maxOutputCount": 1,
        "maxReferenceImages": 0,
        "supportedInputMediaTypes": [MEDIA_TEXT],
        "_model_id": "wanx",
    },
]

# ──────────────────────────────────────────────────────────────
# aspect_ratio → provider size 映射
# ──────────────────────────────────────────────────────────────

# 通用映射（用于 nano_banana / flux_pro / flux_2_pro 这类走 OpenAI 兼容接口的 provider）
_ASPECT_SIZE_MAP: Dict[str, str] = {
    "1:1": "1024x1024",
    "3:4": "768x1024",
    "4:3": "1024x768",
    "16:9": "1024x576",
    "9:16": "576x1024",
}

# DALL-E 3 官方只支持三种精确尺寸
_DALLE3_SIZE_MAP: Dict[str, str] = {
    "1:1": "1024x1024",
    "16:9": "1792x1024",
    "9:16": "1024x1792",
}

# 通义万象固定 1440*960
_WANX_SIZE_MAP: Dict[str, str] = {
    "3:2": "1440*960",  # 注意通义用 `*` 分隔，image_generators 里也是这个格式
}

# ──────────────────────────────────────────────────────────────
# 对外函数
# ──────────────────────────────────────────────────────────────


def _custom_model_entry(custom_def: Dict[str, Any]) -> Dict[str, Any]:
    """为自定义模型动态生成 MODEL_REGISTRY 条目。

    自定义模型走 _openai_compatible_generate 路径，能力声明与 flux 一致：
    IMAGE_GENERATE，宽高比 1:1 起（保守声明），maxOutputCount=1。
    """
    mid = custom_def.get("id", "custom")
    return {
        "modelKey": mid,  # 自定义模型的 modelKey 直接用其 id
        "displayName": custom_def.get("name") or custom_def.get("model_name") or f"Custom ({mid})",
        "version": 1,
        "capabilities": [CAP_IMAGE_GENERATE],
        "supportedAspectRatios": ["1:1", "3:4", "4:3", "16:9", "9:16"],
        "maxOutputCount": 1,
        "maxReferenceImages": 0,
        "supportedInputMediaTypes": [MEDIA_TEXT],
        "_model_id": mid,
        "_is_custom": True,
    }


def _public(entry: Dict[str, Any]) -> Dict[str, Any]:
    """剥掉 `_model_id` / `_is_custom` 等下划线前缀字段，返回对外响应体。"""
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def list_capabilities() -> Dict[str, Any]:
    """返回澜途格式的 capabilities 列表（内置 + 用户自定义）。"""
    entries: List[Dict[str, Any]] = [dict(e) for e in MODEL_REGISTRY]
    for cm in list_custom_models():
        entries.append(_custom_model_entry(cm))
    return {"models": [_public(e) for e in entries]}


def find_entry(model_key: str) -> Optional[Dict[str, Any]]:
    """按 modelKey 查内置 registry；找不到再查自定义模型。返回 None 表示未知。"""
    for e in MODEL_REGISTRY:
        if e["modelKey"] == model_key:
            return dict(e)
    for cm in list_custom_models():
        if cm.get("id") == model_key:
            return _custom_model_entry(cm)
    return None


def get_provider(model_key: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """按 modelKey 路由到 provider。

    返回 (model_def, entry)：
      - model_def: 现有 image_generators.get_model_def() 返回的 provider 定义
        （传给 generate_single_image 用）。
      - entry: 完整 registry 条目（含 capabilities / constraints）。
    model_key 未知时返回 (None, {})。
    """
    entry = find_entry(model_key)
    if entry is None:
        return None, {}
    model_def = get_model_def(entry["_model_id"])
    if model_def is None:
        # 理论上不应该发生：entry 是从 BUILTIN 或 custom_image_models 派生的
        return None, {}
    return model_def, entry


def resolve_size(entry: Dict[str, Any], aspect_ratio: Optional[str] = None,
                 width: Optional[int] = None, height: Optional[int] = None) -> str:
    """把 aspect_ratio（可选 + 显式 width/height）解析成 provider 需要的 size 字符串。

    规则：
      - CUSTOM + width + height：优先使用显式尺寸（走通用映射 fallback）。
      - 其他：按 provider 支持的映射表；未知比例 fallback 到 "1:1"。
    """
    mr = (aspect_ratio or "1:1").strip()

    # 自定义模型 → 走通用映射
    model_id = entry.get("_model_id", "")

    if mr == "CUSTOM" and width and height and int(width) > 0 and int(height) > 0:
        return f"{int(width)}x{int(height)}"

    if model_id == "dalle3":
        return _DALLE3_SIZE_MAP.get(mr, "1024x1024")
    if model_id == "wanx":
        return _WANX_SIZE_MAP.get(mr, "1440*960")

    return _ASPECT_SIZE_MAP.get(mr, "1024x1024")


def validate_request(entry: Dict[str, Any], *,
                     aspect_ratio: Optional[str],
                     count: Optional[int],
                     reference_images: Optional[List[Any]],
                     capability: str = CAP_IMAGE_GENERATE) -> Optional[str]:
    """校验请求是否满足该 provider 的约束。

    返回 None 表示通过；返回字符串表示人类可读的错误信息。
    """
    if capability not in entry.get("capabilities", []):
        return f"model '{entry['modelKey']}' 不支持能力 {capability}"

    if capability != CAP_IMAGE_GENERATE:
        # IMAGE_EDIT / PRODUCT_ANALYSIS 当前所有 provider 都未实现，直接拒绝
        return f"model '{entry['modelKey']}' 尚未实现 {capability}"

    # aspect_ratio 校验
    mr = (aspect_ratio or "1:1")
    allowed = entry.get("supportedAspectRatios", [])
    if mr not in allowed:
        return f"model '{entry['modelKey']}' 不支持宽高比 {mr}（支持：{allowed}）"

    # count 校验：单请求最大 maxOutputCount
    c = int(count) if count else 1
    if c < 1:
        return "count 必须 >= 1"
    # 业务层允许 count > 1（循环调用），但单请求 maxOutputCount 是内部限制，
    # 这里不做强拒绝，仅记录到日志；真正约束在 provider 调用层由 count 循环完成。

    # reference_images：所有 provider maxReferenceImages=0，如传入则拒绝
    max_ref = int(entry.get("maxReferenceImages", 0))
    refs = reference_images or []
    if len(refs) > max_ref:
        return (f"model '{entry['modelKey']}' 最多支持 {max_ref} 张参考图，"
                f"实际传入 {len(refs)} 张")

    return None


__all__ = [
    "CAP_IMAGE_GENERATE", "CAP_IMAGE_EDIT", "CAP_PRODUCT_ANALYSIS",
    "MEDIA_TEXT", "MEDIA_IMAGE",
    "MODEL_REGISTRY",
    "list_capabilities", "find_entry", "get_provider",
    "resolve_size", "validate_request",
]
