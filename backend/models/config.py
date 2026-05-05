"""Configurable system tables: loss rules and dispatching percentages."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LossConfig(Base):
    """
    Grid loss percentage rules, evaluated in priority order.

    condition_type  | condition_value  | meaning
    ----------------+------------------+-----------------------------
    tensione_range  | "220,380"        | tensione IN those values
    tariffa_prefix  | "MT"             | codice_tariffa LIKE 'MT%'
    missing_pod     | null             | POD not found in pod_metadata
    default         | null             | catch-all fallback

    Evaluation order: rows with lowest `priority` value are checked first.
    First matching rule wins.
    """

    __tablename__ = "loss_config"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    condition_type: Mapped[str] = mapped_column(Text, nullable=False)
    condition_value: Mapped[str | None] = mapped_column(Text)
    loss_pct: Mapped[float] = mapped_column(Numeric(7, 5), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    description: Mapped[str | None] = mapped_column(Text)
    account_id: Mapped[str | None] = mapped_column(Text)   # NULL = applies to all
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DispatchingConfig(Base):
    """
    Per-period distribution percentages for a dispatching point.

    When a POD has no historical data, daily energy is estimated as
    CONSUMO_TOT / 365, then distributed across 96 periods using these weights.

    pct values for a given (account_id, punto_dispacciamento) must sum to 1.0.
    """

    __tablename__ = "dispatching_config"
    __table_args__ = {"schema": "public"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    punto_dispacciamento: Mapped[str] = mapped_column(Text, nullable=False)
    periodo: Mapped[int] = mapped_column(Integer, nullable=False)   # 1–96
    pct: Mapped[float] = mapped_column(Numeric(10, 8), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
