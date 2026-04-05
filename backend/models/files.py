"""files — ingestion log table (one row per processed file)."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class FileLog(Base):
    __tablename__ = "files"

    file_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    cod_flusso: Mapped[str | None] = mapped_column(Text)
    piva_distributore: Mapped[str | None] = mapped_column(Text)
    piva_utente: Mapped[str | None] = mapped_column(Text)
    mese_anno: Mapped[str | None] = mapped_column(Text)
    file_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    progressivo: Mapped[int | None] = mapped_column(Integer)
    sm_status: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str | None] = mapped_column(Text)        # ok / rejected / duplicate / error
    error_message: Mapped[str | None] = mapped_column(Text)
