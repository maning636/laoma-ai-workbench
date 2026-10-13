"""SQLAlchemy engine + Session 工厂。

默认 SQLite (`cloud_service/cloud.db`);生产通过 `CLOUD_DB_URL` 或 `DB_URL` 切到
`mysql+pymysql://...` / `postgresql://...`。

约定:
  - `Base` 是所有表模型的基类(在 `auth.models` 里从本模块导入)。
  - `get_db` 是 FastAPI Depends 使用的会话依赖。
  - `init_db()` 幂等建表,适合开发;生产建议用 Alembic 迁移。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


_engine_kwargs: dict[str, Any] = {}
_DB_URL = get_settings()["db_url"]

if _DB_URL.startswith("sqlite"):
    # SQLite 需要 `check_same_thread=False` 才能配合 FastAPI 线程池使用
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # 生产(MySQL/PG):连接池参数,可调
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20

engine = create_engine(_DB_URL, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Iterator[Session]:
    """FastAPI Depends 依赖:每个请求一个独立 Session。"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表(幂等)+ seed prompt 库。

    C12 创建 users;C13 追加 subscriptions + usage;C14 追加 prompts 并 seed。
    """
    # 让 models 先注册到 Base.metadata,再统一 create_all
    from .auth import models as _auth_models  # noqa: F401
    from .billing import models as _billing_models  # noqa: F401
    from .llm_proxy import models as _llm_models  # noqa: F401
    from .llm_proxy import prompts as _llm_prompts  # noqa: F401
    from .payment import models as _payment_models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # seed prompt 库(幂等 upsert,按 name 唯一键)
    with SessionLocal() as _session:
        _llm_prompts.sync_prompts_to_db(_session)
