"""pod_metadata — F2G dispatching point lookup."""

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
    codice_dp: Mapped[str | None] = mapped_column(Text)
    tensione: Mapped[int | None] = mapped_column(Integer)
    trattamento: Mapped[str | None] = mapped_column(CHAR(1))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_file: Mapped[str | None] = mapped_column(Text)
