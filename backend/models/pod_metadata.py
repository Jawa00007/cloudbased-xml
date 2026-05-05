"""pod_metadata — enriched dispatching point register (F2G + SOF + SNF + ANAGRAFICA)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, CHAR, Date, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PodMetadata(Base):
    __tablename__ = "pod_metadata"
    __table_args__ = (
        UniqueConstraint("account_id", "pod", "valid_from", name="uq_pod_metadata_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    pod: Mapped[str] = mapped_column(Text, nullable=False)

    # Dispatching contract (from F2G CodContrDisp)
    codice_dp: Mapped[str | None] = mapped_column(Text)

    # Meter characteristics
    tensione: Mapped[int | None] = mapped_column(Integer)
    trattamento: Mapped[str | None] = mapped_column(CHAR(1))

    # Extended fields (populated from ANAGRAFICA or enriched F2G/SOF/SNF)
    piva_utente: Mapped[str | None] = mapped_column(Text)
    piva_distributore: Mapped[str | None] = mapped_column(Text)
    punto_dispacciamento: Mapped[str | None] = mapped_column(Text)
    tipo_misuratore: Mapped[str | None] = mapped_column(Text)
    codice_tariffa: Mapped[str | None] = mapped_column(Text)

    # Validity window
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    source_file: Mapped[str | None] = mapped_column(Text)
