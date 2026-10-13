"""
多 LLM Provider 注册表 — 11+ 主流模型供应商
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
所有提供商兼容 OpenAI SDK，只需切换 base_url + api_key。
支持：自动探测（按 env var 优先级）、按 provider 调用、按 model 调用。

注册表结构:
  {
    "deepseek": {
      "name": "DeepSeek",
      "base_url": "https://api.deepseek.com",
      "env_key": "DEEPSEEK_API_KEY",
      "default_model": "deepseek-v4-flash",
      "models": { "deepseek-v4-flash": "DeepSeek V4 Flash（性价比最高）", ... },
      "price_note": "Flash: 输入 $0.22/M, 输出 $0.66/M"
    },
    ...
  }
"""

from __future__ import annotations
import os, json, hashlib
from typing import Dict, Any, Optional, List


# ============================================================
# Provider 注册表（11 家，全部兼容 OpenAI SDK）
# ============================================================
MODEL_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-v4-flash",
        "models": {
            "deepseek-v4-flash": "DeepSeek V4 Flash（速度快，性价比最高）",
            "deepseek-v4-pro": "DeepSeek V4 Pro（最强推理）",
            "deepseek-v3": "DeepSeek V3（主流版本）",
            "deepseek-coder-v3": "DeepSeek Coder V3（代码）",
        },
        "price_note": "Flash 输入 $0.22/M，输出 $0.66/M（非高峰半价）",
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_key": "GEMINI_TEXT_API_KEY",
        "default_model": "gemini-2.5-flash",
        "models": {
            "gemini-2.5-flash": "Gemini 2.5 Flash（最新稳定版）",
            "gemini-2.5-pro": "Gemini 2.5 Pro（最强推理）",
            "gemini-2.0-flash": "Gemini 2.0 Flash（高吞吐）",
            "gemini-2.0-flash-lite": "Gemini 2.0 Flash-Lite（最快最便宜）",
        },
        "price_note": "2.5 Flash 约 $0.075/M input，$0.30/M output",
    },
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "default_model": "llama-4-70b-versatile",
        "models": {
            "llama-4-70b-versatile": "Llama 4 70B Versatile（开源旗舰）",
            "llama-4-maverick": "Llama 4 Maverick（轻量版）",
            "llama-3.3-70b-versatile": "Llama 3.3 70B（上一代）",
        },
        "price_note": "完全免费额度，速度极快（LPU 推理）",
    },
    "silicon": {
        "name": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "env_key": "SILICON_API_KEY",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "models": {
            "deepseek-ai/DeepSeek-V3": "DeepSeek V3（主流）",
            "deepseek-ai/DeepSeek-R1": "DeepSeek R1（强推理）",
            "qwen2.5-72b-instruct": "通义千问 2.5 72B",
            "THUDM/GLM-4-9B": "智谱 GLM-4",
        },
        "price_note": "按量付费，支持批量并发",
    },
    "qwen": {
        "name": "阿里云通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "DASHSCOPE_API_KEY",
        "default_model": "qwen-turbo",
        "models": {
            "qwen-max": "通义千问 Max（最强）",
            "qwen-plus": "通义千问 Plus（均衡）",
            "qwen-turbo": "通义千问 Turbo（快速）",
            "qwen-long": "通义千问 Long（长文本）",
        },
        "price_note": "有免费额度，Turbo $0.0001/M",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "models": {
            "gpt-4o": "GPT-4o（最强）",
            "gpt-4o-mini": "GPT-4o Mini（快速）",
            "gpt-4-turbo": "GPT-4 Turbo",
        },
        "price_note": "Mini 输入 $0.15/M，输出 $0.60/M",
    },
    "kimi": {
        "name": "Kimi / Moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "env_key": "KIMI_API_KEY",
        "default_model": "moonshot-v1-8k",
        "models": {
            "moonshot-v1-8k": "Kimi 8K（免费额度高）",
            "moonshot-v1-32k": "Kimi 32K（长文本）",
            "moonshot-v1-128k": "Kimi 128K（超长文本）",
        },
        "price_note": "8K 免费额度极高",
    },
    "dashscope": {
        "name": "DashScope 百炼",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "DASHSCOPE_API_KEY",
        "default_model": "qwen-plus",
        "models": {"qwen-plus": "通义千问 Plus（百炼版）", "qwen-turbo": "通义千问 Turbo"},
        "price_note": "百炼平台统一调用",
    },
    "minimax": {
        "name": "MiniMax",
        "base_url": "https://api.minimax.chat/v1/open-api",
        "env_key": "MINIMAX_API_KEY",
        "default_model": "abab6.5",
        "models": {
            "abab6.5": "MiniMax Abab 6.5（最强）",
            "abab5.5": "MiniMax Abab 5.5（快速）",
        },
        "price_note": "中文对话效果出色",
    },
    "volcengine": {
        "name": "火山引擎豆包",
        "base_url": "https://ark.apis.volcengineapi.com/v3",
        "env_key": "VOLCENGINE_API_KEY",
        "default_model": "doubao-pro-32k",
        "models": {
            "doubao-pro-32k": "豆包 Pro 32K",
            "doubao-lite-32k": "豆包 Lite 32K",
        },
        "price_note": "字节系生态整合",
    },
    "moonshot": {
        "name": "Moonshot 独立",
        "base_url": "https://api.moonshot.cn/v1",
        "env_key": "MOONSHOT_API_KEY",
        "default_model": "moonshot-v1-8k",
        "models": {"moonshot-v1-8k": "Moonshot 8K"},
        "price_note": "独立接入 Moonshot",
    },
}

# 探测优先级：从最常见、性价比最高的开始
PROBE_ORDER = [
    "deepseek", "gemini", "groq", "silicon", "qwen",
    "kimi", "openai", "minimax", "volcengine",
]


def get_provider_config(provider_id: str) -> Optional[Dict[str, Any]]:
    """获取指定 provider 的配置"""
    return MODEL_PROVIDERS.get(provider_id)


def list_providers(include_models: bool = False) -> List[Dict[str, Any]]:
    """列出所有 provider（可选包含 models 详情），并标注 api_key_configured 状态"""
    import os
    result = []
    for pid, cfg in MODEL_PROVIDERS.items():
        api_key_configured = bool(os.environ.get(cfg["env_key"], "").strip())
        entry = {
            "id": pid,
            "name": cfg["name"],
            "default_model": cfg["default_model"],
            "env_key": cfg["env_key"],
            "base_url": cfg["base_url"],
            "price_note": cfg.get("price_note", ""),
            "api_key_configured": api_key_configured,
        }
        if include_models:
            entry["models"] = cfg.get("models", {})
        result.append(entry)
    return result


def detect_provider() -> Dict[str, Any]:
    """
    自动探测：按 PROBE_ORDER 优先级，返回第一个有有效 API Key 的 provider。
    若都没配置，返回 siliconflow 默认（老马AI工作台 原生默认）。
    """
    for pid in PROBE_ORDER:
        cfg = MODEL_PROVIDERS.get(pid)
        if not cfg:
            continue
        api_key = os.environ.get(cfg["env_key"], "").strip()
        if api_key:
            return {
                "provider": pid,
                "name": cfg["name"],
                "base_url": cfg["base_url"],
                "api_key": api_key,
                "model": cfg["default_model"],
                "models": cfg.get("models", {}),
            }

    # fallback: 如果 env 里有 SILICON_API_KEY 就走 老马AI工作台 原生默认
    if os.environ.get("SILICON_API_KEY"):
        return {
            "provider": "silicon",
            "name": "SiliconFlow",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": os.environ["SILICON_API_KEY"],
            "model": "deepseek-ai/DeepSeek-V3",
            "models": MODEL_PROVIDERS["silicon"]["models"],
        }

    # 最后兜底（配置错误时让上层抛明确异常）
    return {
        "provider": None,
        "name": None,
        "base_url": None,
        "api_key": None,
        "model": "deepseek-ai/DeepSeek-V3",
        "models": {},
        "error": "未配置任何 LLM API Key，请在 Provider 配置页设置",
    }


def build_model_list() -> List[Dict[str, Any]]:
    """
    展开所有 provider 的所有 model 为扁平列表
    [{id: 'deepseek', model_name: 'deepseek-v4-flash', display: 'DeepSeek V4 Flash ...', ...}, ...]
    """
    result = []
    for pid, cfg in MODEL_PROVIDERS.items():
        for model_name, desc in cfg.get("models", {}).items():
            result.append({
                "provider_id": pid,
                "provider_name": cfg["name"],
                "model_name": model_name,
                "display": f"{cfg['name']} - {desc}",
                "base_url": cfg["base_url"],
                "env_key": cfg["env_key"],
                "price_note": cfg.get("price_note", ""),
            })
    return result