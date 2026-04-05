"""
measurements and measurements_secondary — quarter-hourly curve tables.
measurements_totalizer — band total table.

All three live inside per-account schemas.
The same model class is reused for both measurements and measurements_secondary
(they share the exact same structure).
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Measurement(Base):
    """Quarter-hourly curve records — TipoDato=E (primary measurements)."""

    __tablename__ = "measurements"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "pod", "data_misura", "periodo", "tipo_dato",
            name="uq_measurements_key",
        ),
        Index("ix_measurements_pod_date", "account_id", "pod", "data_misura"),
        Index("ix_measurements_mese_anno", "account_id", "mese_anno"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    pod: Mapped[str] = mapped_column(Text, nullable=False)
    data_misura: Mapped[date] = mapped_column(Date, nullable=False)
    periodo: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    ea_kwh: Mapped[float | None] = mapped_column(Numeric(10, 3))
    er_kvarh: Mapped[float | None] = mapped_column(Numeric(10, 3))
    dst: Mapped[int] = mapped_column(SmallInteger, default=0)
    tipo_dato: Mapped[str | None] = mapped_column(CHAR(1))
    raccolta: Mapped[str | None] = mapped_column(CHAR(1))
    validato: Mapped[str | None] = mapped_column(CHAR(1))
    tensione: Mapped[int | None] = mapped_column(Integer)
    trattamento: Mapped[str | None] = mapped_column(CHAR(1))
    pot_max: Mapped[float | None] = mapped_column(Numeric(10, 3))
    causa_ostativa: Mapped[bool | None] = mapped_column(Boolean)
    cod_flusso: Mapped[str | None] = mapped_column(Text)
    mese_anno: Mapped[str | None] = mapped_column(Text)
    file_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    progressivo: Mapped[int | None] = mapped_column(Integer)
    source_file: Mapped[str | None] = mapped_column(Text)


class MeasurementSecondary(Base):
    """Quarter-hourly curve records — TipoDato=S (estimated, fallback)."""

    __tablename__ = "measurements_secondary"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "pod", "data_misura", "periodo", "tipo_dato",
            name="uq_measurements_secondary_key",
        ),
        Index("ix_measurements_secondary_pod_date", "account_id", "pod", "data_misura"),
        Index("ix_measurements_secondary_mese_anno", "account_id", "mese_anno"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    pod: Mapped[str] = mapped_column(Text, nullable=False)
    data_misura: Mapped[date] = mapped_column(Date, nullable=False)
    periodo: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    ea_kwh: Mapped[float | None] = mapped_column(Numeric(10, 3))
    er_kvarh: Mapped[float | None] = mapped_column(Numeric(10, 3))
    dst: Mapped[int] = mapped_column(SmallInteger, default=0)
    tipo_dato: Mapped[str | None] = mapped_column(CHAR(1))
    raccolta: Mapped[str | None] = mapped_column(CHAR(1))
    validato: Mapped[str | None] = mapped_column(CHAR(1))
    tensione: Mapped[int | None] = mapped_column(Integer)
    trattamento: Mapped[str | None] = mapped_column(CHAR(1))
    pot_max: Mapped[float | None] = mapped_column(Numeric(10, 3))
    causa_ostativa: Mapped[bool | None] = mapped_column(Boolean)
    cod_flusso: Mapped[str | None] = mapped_column(Text)
    mese_anno: Mapped[str | None] = mapped_column(Text)
    file_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    progressivo: Mapped[int | None] = mapped_column(Integer)
    source_file: Mapped[str | None] = mapped_column(Text)


class MeasurementTotalizer(Base):
    """Band-total records (no quarter-hourly curves)."""

    __tablename__ = "measurements_totalizer"
    __table_args__ = (
        Index("ix_totalizer_pod_date", "account_id", "pod", "data_misura"),
        Index("ix_totalizer_mese_anno", "account_id", "mese_anno"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    pod: Mapped[str] = mapped_column(Text, nullable=False)
    data_misura: Mapped[date | None] = mapped_column(Date)
    data_prest: Mapped[date | None] = mapped_column(Date)
    mese_anno: Mapped[str | None] = mapped_column(Text)
    tipo_dato: Mapped[str | None] = mapped_column(CHAR(1))
    raccolta: Mapped[str | None] = mapped_column(CHAR(1))
    validato: Mapped[str | None] = mapped_column(CHAR(1))
    tensione: Mapped[int | None] = mapped_column(Integer)
    trattamento: Mapped[str | None] = mapped_column(CHAR(1))
    pot_max: Mapped[float | None] = mapped_column(Numeric(10, 3))
    ea_f1: Mapped[float | None] = mapped_column(Numeric(10, 3))
    ea_f2: Mapped[float | None] = mapped_column(Numeric(10, 3))
    ea_f3: Mapped[float | None] = mapped_column(Numeric(10, 3))
    ea_f4: Mapped[float | None] = mapped_column(Numeric(10, 3))
    ea_f5: Mapped[float | None] = mapped_column(Numeric(10, 3))
    ea_f6: Mapped[float | None] = mapped_column(Numeric(10, 3))
    ea_m: Mapped[float | None] = mapped_column(Numeric(10, 3))
    er_f1: Mapped[float | None] = mapped_column(Numeric(10, 3))
    er_f2: Mapped[float | None] = mapped_column(Numeric(10, 3))
    er_f3: Mapped[float | None] = mapped_column(Numeric(10, 3))
    pot_f1: Mapped[float | None] = mapped_column(Numeric(10, 3))
    pot_f2: Mapped[float | None] = mapped_column(Numeric(10, 3))
    pot_f3: Mapped[float | None] = mapped_column(Numeric(10, 3))
    tipo_rettifica: Mapped[str | None] = mapped_column(CHAR(1))
    motivazione: Mapped[int | None] = mapped_column(SmallInteger)
    data_rilevazione: Mapped[date | None] = mapped_column(Date)
    cod_flusso: Mapped[str | None] = mapped_column(Text)
    file_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    progressivo: Mapped[int | None] = mapped_column(Integer)
    source_file: Mapped[str | None] = mapped_column(Text)
