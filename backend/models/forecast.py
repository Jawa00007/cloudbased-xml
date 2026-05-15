"""forecast_periods — generated forecast dataset."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, Numeric, SmallInteger, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ForecastPeriod(Base):
    """
    One row per (account_id, pod, forecast_date, periodo).

    Values are stored in kWh (full precision — NOT pre-rounded MWh).
    Two values per period:
      - ea_kwh            : raw energy from source (prev year or estimated)
      - ea_kwh_with_loss  : after applying the configured grid loss percentage

    MWh conversion (÷1000, round to 3dp) happens ONLY at aggregation time in SQL
    (ROUND(SUM(ea_kwh_with_loss) / 1000.0, 3)) so that summing many PODs within
    a dispatching point does not accumulate per-POD rounding errors.

    source_type codes:
      E         — copied from measurements (TipoDato=E)
      S         — copied from measurements_secondary (TipoDato=S)
      filled    — last available day carried forward (missing day fill)
      estimated — derived from CONSUMO_TOT / 365 × dispatching %
      padded    — zero/last-day padding to reach 31-day structure
    """

    __tablename__ = "forecast_periods"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "pod", "forecast_date", "periodo",
            name="uq_forecast_period_key",
        ),
        Index("ix_forecast_periods_acct_month", "account_id", "mese_anno"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    pod: Mapped[str] = mapped_column(Text, nullable=False)
    mese_anno: Mapped[str] = mapped_column(Text, nullable=False)          # forecast month MM/YYYY
    punto_dispacciamento: Mapped[str | None] = mapped_column(Text)
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_date: Mapped[date | None] = mapped_column(Date)                # prev-year date used as template
    periodo: Mapped[int] = mapped_column(SmallInteger, nullable=False)    # 1–96
    ea_kwh: Mapped[float | None] = mapped_column(Numeric(14, 6))
    ea_kwh_with_loss: Mapped[float | None] = mapped_column(Numeric(14, 6))
    loss_pct: Mapped[float | None] = mapped_column(Numeric(7, 5))
    source_type: Mapped[str] = mapped_column(Text, nullable=False)        # E/S/filled/estimated/padded
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
