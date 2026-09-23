"""
AI 图像生成服务：多模型生成器注册表 + 自定义模型管理 + 搜索图
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
支持：
  - NanoBanana (Gemini 2.5 Flash Image)
  - DALL·E 3 (OpenAI)
  - 通义万象 (阿里云 DashScope wanx2.1)
  - Flux Pro / Flux 2 (Black Forest Labs, 走 NanoBanana 兼容接口)
  - 自定义 OpenAI 兼容生图模型（用户在前端配置）
  - 搜索图（通过 SearXNG 或 Openverse 抓取 CC 图片）

统一接口：generate_single_model(model_def, prompt, size) -> dict
"""

from __future__ import annotations
import os, asyncio, hashlib
from typing import Dict, Any, Optional, List
from loguru import logger


# ============================================================
# 内置模型定义
# ============================================================
BUILTIN_IMAGE_MODELS: List[Dict[str, Any]] = [
    {
        "id": "nano_banana", "model_name": "gemini-2.5-flash-image",
        "name": "🍌 Nano Banana", "provider": "Google Gemini",
        "price": "$0.02/张", "description": "速度快，性价比最高",
        "env_key": "NANO_BANANA_API_KEY", "base_url_env": "NANO_BANANA_BASE_URL",
        "response_type": "b64_json", "tags": ["推荐", "快速"],
    },
    {
        "id": "dalle3", "model_name": "dall-e-3",
        "name": "🎨 DALL-E 3", "provider": "OpenAI",
        "price": "$0.04/张", "description": "细节丰富，质量高",
        "env_key": "OPENAI_API_KEY", "base_url_env": "OPENAI_IMAGE_BASE_URL",
        "response_type": "url", "tags": ["高质量"],
    },
    {
        "id": "flux_pro", "model_name": "flux-pro",
        "name": "⚡ Flux Pro", "provider": "Black Forest Labs",
        "price": "$0.055/张", "description": "艺术风格出色",
        "env_key": "NANO_BANANA_API_KEY", "base_url_env": "NANO_BANANA_BASE_URL",
        "response_type": "b64_json", "tags": ["艺术"],
    },
    {
        "id": "flux_2_pro", "model_name": "flux-2-pro",
        "name": "⚡ Flux 2 Pro", "provider": "Black Forest Labs",
        "price": "$0.05/张", "description": "Flux 最新旗舰版",
        "env_key": "NANO_BANANA_API_KEY", "base_url_env": "NANO_BANANA_BASE_URL",
        "response_type": "b64_json", "tags": ["新版"],
    },
    {
        "id": "wanx", "model_name": "wanx2.1-t2i-turbo",
        "name": "🖌️ 通义万象", "provider": "阿里云",
        "price": "有免费额度", "description": "中文 prompt 友好",
        "env_key": "DASHSCOPE_API_KEY", "base_url_env": "",
        "response_type": "url", "tags": ["中文友好", "免费额度"],
    },
]

# 自定义模型存储（内存态，生产建议写数据库）
custom_image_models: List[Dict[str, Any]] = []


def list_builtin_models() -> List[Dict[str, Any]]:
    return list(BUILTIN_IMAGE_MODELS)


def list_custom_models() -> List[Dict[str, Any]]:
    return list(custom_image_models)


def add_custom_model(model_def: Dict[str, Any]) -> Dict[str, Any]:
    """添加自定义模型（env_key 必须是 __custom__，用户直传 api_key + base_url）"""
    model_def["_api_key"] = model_def.get("api_key", "").strip()
    model_def["_base_url"] = model_def.get("base_url", "").strip()
    model_def["env_key"] = "__custom__"
    model_def["base_url_env"] = ""
    model_def["tags"] = list(model_def.get("tags", [])) + ["自定义"]
    if "id" not in model_def:
        model_def["id"] = f"custom_{hashlib.md5(model_def.get('model_name','x').encode()).hexdigest()[:8]}"
    custom_image_models.append(model_def)
    return model_def


def remove_custom_model(model_id: str) -> bool:
    before = len(custom_image_models)
    custom_image_models[:] = [m for m in custom_image_models if m.get("id") != model_id]
    return len(custom_image_models) < before


def get_model_def(model_id: str) -> Optional[Dict[str, Any]]:
    for m in BUILTIN_IMAGE_MODELS:
        if m["id"] == model_id:
            return m
    for m in custom_image_models:
        if m.get("id") == model_id:
            return m
    return None


# ============================================================
# 生成器：通义万象（阿里云异步任务）
# ============================================================
async def _wanx_generate(api_key: str, prompt: str, size: str) -> Dict[str, Any]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "X-DashScope-Async": "enable",
                },
                json={
                    "model": "wanx2.1-t2i-turbo",
                    "input": {"prompt": prompt},
                    "parameters": {"size": "1440*960", "n": 1},
                },
            )
            if resp.status_code != 200:
                return {"success": False, "error": f"创建任务失败: {resp.text[:120]}"}
            task_id = resp.json()["output"]["task_id"]

            # 轮询任务状态
            for _ in range(18):
                await asyncio.sleep(5)
                r2 = await client.get(
                    f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                out = r2.json().get("output", {})
                if out.get("task_status") == "SUCCEEDED":
                    return {"success": True, "url": out["results"][0]["url"]}
                elif out.get("task_status") in ("FAILED", "CANCELED"):
                    return {"success": False, "error": f"任务失败: {out}"}
            return {"success": False, "error": "生成超时"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ============================================================
# 生成器：OpenAI 兼容（NanoBanana / DALL-E / Flux / 自定义）
# ============================================================
async def _openai_compatible_generate(
    api_key: str, base_url: Optional[str], model_name: str, prompt: str, size: str
) -> Dict[str, Any]:
    try:
        from openai import AsyncOpenAI
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncOpenAI(**kwargs)
        resp = await client.images.generate(
            model=model_name,
            prompt=prompt,
            n=1,
            size=size,
        )
        item = resp.data[0]
        if item.b64_json:
            url = f"data:image/png;base64,{item.b64_json}"
        elif item.url:
            url = item.url
        else:
            return {"success": False, "error": "返回数据为空"}
        return {"success": True, "url": url}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ============================================================
# 统一生成入口
# ============================================================
async def generate_single_image(
    model_def: Dict[str, Any], prompt: str, size: str = "1024x1024"
) -> Dict[str, Any]:
    """为单个模型生成一张图片，返回结果字典"""
    model_id = model_def.get("id", "")
    model_name = model_def.get("model_name", "")
    display_name = model_def.get("name", model_id)

    try:
        # 通义万象走独立流程
        if model_id == "wanx":
            api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
            if not api_key:
                return {"model_id": model_id, "name": display_name, "success": False, "error": "DASHSCOPE_API_KEY 未配置"}
            result = await _wanx_generate(api_key, prompt, size)
            result.update({"model_id": model_id, "name": display_name})
            return result

        # 自定义模型：从 model_def 读取 api_key/base_url
        if model_def.get("env_key") == "__custom__":
            api_key = model_def.get("_api_key", "").strip()
            base_url = model_def.get("_base_url", "").strip()
        else:
            api_key = os.environ.get(model_def.get("env_key", ""), "").strip()
            base_url_env = model_def.get("base_url_env", "")
            base_url = os.environ.get(base_url_env, "").strip() if base_url_env else ""

        if not api_key:
            return {
                "model_id": model_id, "name": display_name, "success": False,
                "error": f"{model_def.get('env_key')} 未配置",
            }

        result = await _openai_compatible_generate(api_key, base_url, model_name, prompt, size)
        result.update({"model_id": model_id, "name": display_name})
        return result

    except Exception as e:
        logger.error(f"[{display_name}] 生图失败: {e}")
        return {"model_id": model_id, "name": display_name, "success": False, "error": str(e)[:200]}


# ============================================================
# 批量生成（多模型并发生成同一 prompt）
# ============================================================
async def generate_multi_model(
    model_ids: List[str], prompt: str, size: str = "1024x1024"
) -> List[Dict[str, Any]]:
    """并发调用多个模型生成同一 prompt，返回结果列表"""
    tasks = []
    for mid in model_ids:
        mdef = get_model_def(mid)
        if not mdef:
            tasks.append(_missing_result(mid))
            continue
        tasks.append(generate_single_image(mdef, prompt, size))

    return await asyncio.gather(*tasks)


def _missing_result(model_id: str) -> Dict[str, Any]:
    return {"model_id": model_id, "name": model_id, "success": False, "error": "未知模型"}


# ============================================================
# 图片搜索（SearXNG 或 Openverse，用于无 AI Key 时的降级方案）
# ============================================================
async def search_images(query: str, count: int = 10) -> List[Dict[str, Any]]:
    """
    通过 Openverse（免费，CC 协议）搜索图片。
    Openverse 需要 API Key，如果没配则返回空 + 提示。
    """
    api_key = os.environ.get("OPENVERSE_API_KEY", "").strip()
    if not api_key:
        return [
            {"success": False, "error": "OPENVERSE_API_KEY 未配置，无法搜索图片"},
        ]
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.openverse.engineering/v1/images/",
                params={"q": query, "page_size": count, "license_type": "all"},
                headers={"Authorization": f"Token {api_key}"},
            )
            if resp.status_code != 200:
                return [{"success": False, "error": f"搜索失败: {resp.status_code}"}]
            data = resp.json().get("results", [])
            return [
                {"url": item.get("url"), "thumbnail": item.get("thumbnail"),
                 "title": item.get("title"), "license": item.get("license_code")}
                for item in data
            ]
    except Exception as e:
        return [{"success": False, "error": str(e)[:200]}]