"""users 表(C12 唯一表;C13 会新增 plans/subscriptions/orders)。

字段设计参考 `docs/dev-reports/2026-10-13-saas-c-class-design.md` §3.3:
  users (id, username, email, password_hash, created_at, is_active)

我们同时保留 `username` 和 `email`,以匹配任务端点契约(register/login 用 username,
但 design doc 用 email 作主键)——两者都唯一。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 登录名,唯一,1-64 字符
    username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    # 邮箱,唯一,选填但要唯一;用于找回密码 / 邀请
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    # bcrypt hash 串(形如 `$2b$12$...`);明文绝不入库
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def to_dict(self, *, include_email: bool = True) -> dict:
        """序列化为 JSON 响应载荷(不返回 password_hash)。"""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email if include_email else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
