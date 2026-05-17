from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # NULL = unrestricted (all accounts); list = restricted to named accounts
    allowed_accounts: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True, default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
