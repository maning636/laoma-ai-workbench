"""Prism-Fusion Cloud Service (SaaS backend).

独立服务,与本地 `prism_backend/fastapi_app` 平行部署。
C12 提供基础用户体系 + JWT,后续 C13 订阅、C14 LLM 代理都会挂到本 app 下。
"""

__version__ = "0.1.0"
