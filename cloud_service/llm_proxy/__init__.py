"""C14 · LLM Proxy (防逆向核心)。

云端 LLM 代理 + 高价值 prompt 库下沉:
  - 客户端只发 `prompt_name` + 变量,不接触 prompt 源码。
  - 云端持有 LLM API key (`CLOUD_LLM_API_KEY` / `CLOUD_LLM_BASE_URL` / `CLOUD_LLM_MODEL`)。
  - prompt 分层:`cloud`(高价值,仅云端)/ `basic`(基础,允许离线版复用)。

复用:
  - `..db`               SQLAlchemy session
  - `..auth.router`      C12 的 `get_current_user`(JWT)
  - `..billing.router`   C13 的额度校验与消耗

对外:
  `POST /cloud/llm/chat`   渲染 prompt + 调 LLM
  `GET  /cloud/llm/prompts` 列出可用 prompt 名(不含模板)
"""

from .router import router

__all__ = ["router"]
