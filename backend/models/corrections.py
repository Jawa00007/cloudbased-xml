"""corrections — Flusso 2 audit log."""

from datetime import date, datetime

from sqlalchemy import BigInteger, CHAR, Date, DateTime, Integer, SmallInteger, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    pod: Mapped[str] = mapped_column(Text, nullable=False)
    mese_anno: Mapped[str | None] = mapped_column(Text)
    data_misura: Mapped[date | None] = mapped_column(Date)
    tipo_rettifica: Mapped[str | None] = mapped_column(CHAR(1))
    motivazione: Mapped[int | None] = mapped_column(SmallInteger)
    data_rilevazione: Mapped[date | None] = mapped_column(Date)
    cod_flusso: Mapped[str | None] = mapped_column(Text)
    source_file: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
