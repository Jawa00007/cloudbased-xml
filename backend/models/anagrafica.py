"""anagrafica — master POD register from ANAGRAFICA CSV/ZIP files."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Anagrafica(Base):
    """
    Master POD register loaded from ANAGRAFICA_YYYYMM_PIvautente_PuntoDisp.zip files.

    One row per (account_id, pod, mese_anno) combination.
    Only rows where the filter column = 'O' are stored (included=True).

    Used by the forecast engine to:
    - Determine which PODs to include in a forecast run
    - Look up CONSUMO_TOT for estimation when no historical data exists
    - Get CodiceTariffa and Tensione for loss calculation
    - Map POD → PuntoDispacciamento for output grouping
    """

    __tablename__ = "anagrafica"
    __table_args__ = (
        UniqueConstraint("account_id", "pod", "mese_anno", name="uq_anagrafica_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    mese_anno: Mapped[str] = mapped_column(Text, nullable=False)          # MM/YYYY from filename
    piva_utente: Mapped[str | None] = mapped_column(Text)
    piva_distributore: Mapped[str | None] = mapped_column(Text)
    pod: Mapped[str] = mapped_column(Text, nullable=False)                # 14-char normalized
    pod_raw: Mapped[str | None] = mapped_column(Text)                     # original value before normalization
    punto_dispacciamento: Mapped[str | None] = mapped_column(Text)
    tipo_misuratore: Mapped[str | None] = mapped_column(Text)
    trattamento: Mapped[str | None] = mapped_column(Text)
    tensione: Mapped[int | None] = mapped_column(Integer)
    codice_tariffa: Mapped[str | None] = mapped_column(Text)
    consumo_tot: Mapped[float | None] = mapped_column(Numeric(14, 3))     # annual kWh total
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_file: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
