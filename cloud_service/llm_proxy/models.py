"""Prompt 表(C14)。

设计参考 `docs/dev-reports/2026-10-13-saas-c-class-design.md` §3.3。
本迭代刻意从简:不建 `prompt_versions` / `params_schema`(留给 C14b)。

  prompts (id, name /*unique*/, tier /*cloud|basic*/, template, variables_json,
           version, is_active, created_at)

约定:
  - `tier`:
      * `cloud` — 高价值 prompt,只在云端;客户端只按 name 触发。
      * `basic` — 基础模板,允许客户端离线版复用(离线版 `prompts_basic.py`)。
  - `variables_json`: JSON 字符串,列出模板占位符列表,便于校验和 UI 展示。
  - `version`: 字符串,如 "1.0.0";云端渲染后返回给客户端做灰度追踪。
  - 表数据由 `prompts.py` 的 SEED 常量在 `init_db()` 阶段 upsert,
    避免每次部署手写迁移;生产建议后续切换到 Alembic 迁移 + 后台 admin 编辑。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Prompt(Base):
    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("name", name="uq_prompts_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # prompt 的唯一标识(客户端 /cloud/llm/chat 用这个名字触发)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # cloud | basic
    tier: Mapped[str] = mapped_column(String(16), default="cloud", nullable=False, index=True)

    # Jinja2 风格占位符模板,如 "请以{{tone}}的口吻写一段关于{{topic}}的开头"
    template: Mapped[str] = mapped_column(Text, nullable=False)

    # 变量列表(JSON 数组字符串,如 '["tone","topic"]')
    variables_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 版本(如 1.0.0)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)

    # 是否为活跃版本(旧版本置 false,支持灰度)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def to_dict(self, *, include_template: bool = False) -> dict:
        base = {
            "id": self.id,
            "name": self.name,
            "tier": self.tier,
            "version": self.version,
            "is_active": self.is_active,
            "variables": self.variables_json or "[]",
        }
        # 默认不带模板,避免任何路径意外把高价值 prompt 源泄露给客户端
        if include_template:
            base["template"] = self.template
        return base
