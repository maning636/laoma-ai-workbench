"""C12 · 用户体系 + JWT 模块。

对外:
  - `router`: FastAPI APIRouter,前缀挂载在 `cloud_service/main.py`
  - `models`: SQLAlchemy `User` 表
  - `security`: bcrypt + JWT (HS256) 工具
"""
