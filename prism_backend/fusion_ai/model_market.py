"""
模型广场
━━━━━━━━
11+ LLM 模型能力对比、价格表、能力标签、API Key 状态探测。
数据是静态注册表 + 运行时探测。
"""

from __future__ import annotations
import os
from typing import Dict, Any, List
from .provider_registry import MODEL_PROVIDERS, PROBE_ORDER


# 各模型的详细能力卡
MODEL_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    # DeepSeek
    "deepseek-v4-flash": {
        "id": "deepseek-v4-flash", "provider": "deepseek",
        "context_length": "128K", "strengths": ["性价比", "中文写作"],
        "weaknesses": ["代码能力弱于 Pro"],
        "supported_features": ["chat", "completion"],
        "price_input": "$0.22/M", "price_output": "$0.66/M",
        "recommendation": "日常写作、批量内容生成的首选",
    },
    "deepseek-v4-pro": {
        "id": "deepseek-v4-pro", "provider": "deepseek",
        "context_length": "128K", "strengths": ["推理", "复杂任务"],
        "weaknesses": ["成本高"],
        "supported_features": ["chat", "completion"],
        "price_input": "$0.55/M", "price_output": "$2.19/M",
        "recommendation": "需要高质量推理时使用",
    },
    # Gemini
    "gemini-2.5-flash": {
        "id": "gemini-2.5-flash", "provider": "gemini",
        "context_length": "1M", "strengths": ["超长上下文", "速度"],
        "weaknesses": ["中文表达一般"],
        "supported_features": ["chat", "completion"],
        "price_input": "$0.075/M", "price_output": "$0.30/M",
        "recommendation": "长文档分析、大批量处理",
    },
    "gemini-2.5-pro": {
        "id": "gemini-2.5-pro", "provider": "gemini",
        "context_length": "1M", "strengths": ["最强推理", "多模态"],
        "weaknesses": ["价格高"],
        "supported_features": ["chat", "completion", "multimodal"],
        "price_input": "$1.25/M", "price_output": "$10.00/M",
        "recommendation": "需要顶级推理 + 多模态时使用",
    },
    # OpenAI
    "gpt-4o": {
        "id": "gpt-4o", "provider": "openai",
        "context_length": "128K", "strengths": ["综合能力", "多模态"],
        "weaknesses": ["贵", "国内访问需代理"],
        "supported_features": ["chat", "completion", "multimodal"],
        "price_input": "$2.50/M", "price_output": "$10.00/M",
        "recommendation": "追求极致质量的场景",
    },
    "gpt-4o-mini": {
        "id": "gpt-4o-mini", "provider": "openai",
        "context_length": "128K", "strengths": ["性价比", "速度"],
        "weaknesses": ["复杂任务能力弱"],
        "supported_features": ["chat", "completion"],
        "price_input": "$0.15/M", "price_output": "$0.60/M",
        "recommendation": "高频调用、批量生成",
    },
    # 通义千问
    "qwen-max": {
        "id": "qwen-max", "provider": "qwen",
        "context_length": "32K", "strengths": ["中文最强", "国内合规"],
        "weaknesses": ["国际视野弱"],
        "supported_features": ["chat", "completion"],
        "price_input": "$0.005/M", "price_output": "$0.02/M",
        "recommendation": "中文内容创作首选",
    },
    "qwen-turbo": {
        "id": "qwen-turbo", "provider": "qwen",
        "context_length": "1M", "strengths": ["速度快", "有免费额度"],
        "weaknesses": ["深度不够"],
        "supported_features": ["chat", "completion"],
        "price_input": "$0.0001/M", "price_output": "$0.0002/M",
        "recommendation": "高频调用、免费额度用尽前",
    },
    # SiliconFlow
    "deepseek-ai/DeepSeek-V3": {
        "id": "deepseek-ai/DeepSeek-V3", "provider": "silicon",
        "context_length": "32K", "strengths": ["稳定", "国内直连"],
        "weaknesses": ["价格略高"],
        "supported_features": ["chat", "completion"],
        "price_input": "$0.50/M", "price_output": "$2.00/M",
        "recommendation": "老马AI工作台默认模型",
    },
}


def list_all_models() -> List[Dict[str, Any]]:
    """列出所有模型（合并 provider 注册表 + 能力卡）"""
    result = []
    for pid, cfg in MODEL_PROVIDERS.items():
        api_key = os.environ.get(cfg["env_key"], "").strip()
        for model_name, desc in cfg.get("models", {}).items():
            cap = MODEL_CAPABILITIES.get(model_name, {})
            result.append({
                "id": model_name,
                "provider_id": pid,
                "provider_name": cfg["name"],
                "display": desc,
                "base_url": cfg["base_url"],
                "env_key": cfg["env_key"],
                "api_key_configured": bool(api_key),
                "context_length": cap.get("context_length", ""),
                "strengths": cap.get("strengths", []),
                "weaknesses": cap.get("weaknesses", []),
                "supported_features": cap.get("supported_features", ["chat"]),
                "price_input": cap.get("price_input", cfg.get("price_note", "")),
                "price_output": cap.get("price_output", ""),
                "recommendation": cap.get("recommendation", ""),
            })
    return result


def get_model_detail(model_id: str) -> Dict[str, Any]:
    """获取模型详情"""
    cap = MODEL_CAPABILITIES.get(model_id)
    if cap:
        return cap
    for pid, cfg in MODEL_PROVIDERS.items():
        if model_id in cfg.get("models", {}):
            return {
                "id": model_id,
                "provider": pid,
                "display": cfg["models"][model_id],
                "base_url": cfg["base_url"],
            }
    return {"error": f"未知模型: {model_id}"}


def probe_api_keys() -> Dict[str, bool]:
    """探测各 provider 的 API Key 配置状态"""
    result = {}
    for pid, cfg in MODEL_PROVIDERS.items():
        result[pid] = bool(os.environ.get(cfg["env_key"], "").strip())
    return result


def recommend_model(use_case: str) -> Dict[str, Any]:
    """
    按用例推荐模型：
      writing      — 中文内容创作（DeepSeek V4 Flash / Qwen Turbo）
      reasoning    — 深度推理（DeepSeek V4 Pro / Gemini 2.5 Pro）
      batch        — 大批量生成（Gemini Flash / Qwen Turbo）
      multimodal   — 多模态（GPT-4o / Gemini 2.5 Pro）
      cheap        — 最便宜（Qwen Turbo / Groq）
    """
    recommendations = {
        "writing": ["deepseek-v4-flash", "qwen-max", "deepseek-ai/DeepSeek-V3"],
        "reasoning": ["deepseek-v4-pro", "gemini-2.5-pro"],
        "batch": ["gemini-2.5-flash", "qwen-turbo"],
        "multimodal": ["gpt-4o", "gemini-2.5-pro"],
        "cheap": ["qwen-turbo", "deepseek-v4-flash"],
    }
    models = recommendations.get(use_case, recommendations["writing"])
    return {
        "use_case": use_case,
        "recommended": [{"model": m, "detail": MODEL_CAPABILITIES.get(m, {})} for m in models],
    }