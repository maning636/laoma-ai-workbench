"""Subscriptions + Usage 表(C13)。

设计参考 `docs/dev-reports/2026-10-13-saas-c-class-design.md` §3.3;
本迭代刻意保持简单 —— 无 `plans` / `invoices` 表(留待 C19 支付接入)。

  subscriptions (id, user_id, plan, status, expire_at, quota, created_at)
  usage         (id, user_id, period, used)        -- period 形如 "YYYY-MM"

约定:
  - `plan`: "free" | "pro"(可扩展;见 `settings.get_settings()["billing"]`)
  - `status`: "active" | "expired" | "cancelled"
  - `quota`: -1 表示无限;0 表示明确封禁;>=0 为月度上限
  - `expire_at`: `None` 表示永久(目前仅 free 使用);否则为有效截止时间
  - `Usage.period`: 单用户单期间聚合(唯一键),consume 时 upsert
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 用字符串 forward-ref "User" 避免与 auth.models 的循环导入
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    expire_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    quota: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # 单向 relationship;不调用 back_populates,避免 auth.models.User 反向绑定
    user = relationship("User", lazy="joined")

    def is_expired(self) -> bool:
        if self.expire_at is None:
            return False
        # SQLite 存回 DateTime(timezone=True) 后可能是 naive datetime;
        # 这里兜底补 UTC tzinfo,避免 `can't compare offset-naive and offset-aware`
        exp = self.expire_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= exp

    def to_dict(self, used: int = 0) -> dict:
        return {
            "plan": self.plan,
            "status": "expired" if self.is_expired() else self.status,
            "expire_at": self.expire_at.isoformat() if self.expire_at else None,
            "quota": self.quota,
            "used": used,
            "remaining": -1 if self.quota == -1 else max(0, self.quota - used),
            "is_pro": self.plan == "pro",
        }


class Usage(Base):
    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("user_id", "period", name="uq_usage_user_period"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "used": self.used,
        }
