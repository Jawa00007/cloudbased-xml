"""initial_schema

Creates all tables for one account schema:
  files, measurements, measurements_secondary, measurements_totalizer,
  corrections, pod_metadata

Also creates the public.accounts table (idempotent).

Revision ID: 9c0971ba5b78
Revises:
Create Date: 2026-04-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9c0971ba5b78"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── public.accounts (once per DB, not per schema) ──────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.accounts (
            account_id    TEXT PRIMARY KEY,
            schema_name   TEXT NOT NULL,
            display_name  TEXT,
            nextcloud_url TEXT,
            active        BOOLEAN DEFAULT true,
            created_at    TIMESTAMP DEFAULT now()
        )
    """)

    # ── files ──────────────────────────────────────────────────────────────────
    op.create_table(
        "files",
        sa.Column("file_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("cod_flusso", sa.Text(), nullable=True),
        sa.Column("piva_distributore", sa.Text(), nullable=True),
        sa.Column("piva_utente", sa.Text(), nullable=True),
        sa.Column("mese_anno", sa.Text(), nullable=True),
        sa.Column("file_timestamp", sa.DateTime(), nullable=True),
        sa.Column("progressivo", sa.Integer(), nullable=True),
        sa.Column("sm_status", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("file_id"),
        sa.UniqueConstraint("file_name", name="uq_files_file_name"),
    )

    # ── measurements (TipoDato=E, quarter-hourly curves) ───────────────────────
    op.create_table(
        "measurements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("pod", sa.Text(), nullable=False),
        sa.Column("data_misura", sa.Date(), nullable=False),
        sa.Column("periodo", sa.SmallInteger(), nullable=False),
        sa.Column("ea_kwh", sa.Numeric(10, 3), nullable=True),
        sa.Column("er_kvarh", sa.Numeric(10, 3), nullable=True),
        sa.Column("dst", sa.SmallInteger(), server_default=sa.text("0"), nullable=True),
        sa.Column("tipo_dato", sa.CHAR(1), nullable=False),
        sa.Column("raccolta", sa.CHAR(1), nullable=True),
        sa.Column("validato", sa.CHAR(1), nullable=True),
        sa.Column("tensione", sa.Integer(), nullable=True),
        sa.Column("trattamento", sa.CHAR(1), nullable=True),
        sa.Column("pot_max", sa.Numeric(10, 3), nullable=True),
        sa.Column("causa_ostativa", sa.Boolean(), nullable=True),
        sa.Column("cod_flusso", sa.Text(), nullable=True),
        sa.Column("mese_anno", sa.Text(), nullable=True),
        sa.Column("file_timestamp", sa.DateTime(), nullable=True),
        sa.Column("progressivo", sa.Integer(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "pod", "data_misura", "periodo", "tipo_dato",
            name="uq_measurements_key",
        ),
    )
    op.create_index("ix_measurements_pod_date", "measurements",
                    ["account_id", "pod", "data_misura"])
    op.create_index("ix_measurements_mese_anno", "measurements",
                    ["account_id", "mese_anno"])

    # ── measurements_secondary (TipoDato=S, estimated curves) ──────────────────
    op.create_table(
        "measurements_secondary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("pod", sa.Text(), nullable=False),
        sa.Column("data_misura", sa.Date(), nullable=False),
        sa.Column("periodo", sa.SmallInteger(), nullable=False),
        sa.Column("ea_kwh", sa.Numeric(10, 3), nullable=True),
        sa.Column("er_kvarh", sa.Numeric(10, 3), nullable=True),
        sa.Column("dst", sa.SmallInteger(), server_default=sa.text("0"), nullable=True),
        sa.Column("tipo_dato", sa.CHAR(1), nullable=False),
        sa.Column("raccolta", sa.CHAR(1), nullable=True),
        sa.Column("validato", sa.CHAR(1), nullable=True),
        sa.Column("tensione", sa.Integer(), nullable=True),
        sa.Column("trattamento", sa.CHAR(1), nullable=True),
        sa.Column("pot_max", sa.Numeric(10, 3), nullable=True),
        sa.Column("causa_ostativa", sa.Boolean(), nullable=True),
        sa.Column("cod_flusso", sa.Text(), nullable=True),
        sa.Column("mese_anno", sa.Text(), nullable=True),
        sa.Column("file_timestamp", sa.DateTime(), nullable=True),
        sa.Column("progressivo", sa.Integer(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "pod", "data_misura", "periodo", "tipo_dato",
            name="uq_measurements_secondary_key",
        ),
    )
    op.create_index("ix_measurements_secondary_pod_date", "measurements_secondary",
                    ["account_id", "pod", "data_misura"])

    # ── measurements_totalizer (band totals, no curves) ────────────────────────
    op.create_table(
        "measurements_totalizer",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("pod", sa.Text(), nullable=False),
        sa.Column("data_misura", sa.Date(), nullable=True),
        sa.Column("data_prest", sa.Date(), nullable=True),
        sa.Column("mese_anno", sa.Text(), nullable=True),
        sa.Column("tipo_dato", sa.CHAR(1), nullable=True),
        sa.Column("raccolta", sa.CHAR(1), nullable=True),
        sa.Column("validato", sa.CHAR(1), nullable=True),
        sa.Column("tensione", sa.Integer(), nullable=True),
        sa.Column("trattamento", sa.CHAR(1), nullable=True),
        sa.Column("pot_max", sa.Numeric(10, 3), nullable=True),
        sa.Column("ea_f1", sa.Numeric(10, 3), nullable=True),
        sa.Column("ea_f2", sa.Numeric(10, 3), nullable=True),
        sa.Column("ea_f3", sa.Numeric(10, 3), nullable=True),
        sa.Column("ea_f4", sa.Numeric(10, 3), nullable=True),
        sa.Column("ea_f5", sa.Numeric(10, 3), nullable=True),
        sa.Column("ea_f6", sa.Numeric(10, 3), nullable=True),
        sa.Column("ea_m", sa.Numeric(10, 3), nullable=True),
        sa.Column("er_f1", sa.Numeric(10, 3), nullable=True),
        sa.Column("er_f2", sa.Numeric(10, 3), nullable=True),
        sa.Column("er_f3", sa.Numeric(10, 3), nullable=True),
        sa.Column("pot_f1", sa.Numeric(10, 3), nullable=True),
        sa.Column("pot_f2", sa.Numeric(10, 3), nullable=True),
        sa.Column("pot_f3", sa.Numeric(10, 3), nullable=True),
        sa.Column("tipo_rettifica", sa.CHAR(1), nullable=True),
        sa.Column("motivazione", sa.SmallInteger(), nullable=True),
        sa.Column("data_rilevazione", sa.Date(), nullable=True),
        sa.Column("cod_flusso", sa.Text(), nullable=True),
        sa.Column("file_timestamp", sa.DateTime(), nullable=True),
        sa.Column("progressivo", sa.Integer(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_measurements_totalizer_pod_date", "measurements_totalizer",
                    ["account_id", "pod", "data_misura"])

    # ── corrections (Flusso 2 audit log) ───────────────────────────────────────
    op.create_table(
        "corrections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("pod", sa.Text(), nullable=False),
        sa.Column("mese_anno", sa.Text(), nullable=True),
        sa.Column("data_misura", sa.Date(), nullable=True),
        sa.Column("tipo_rettifica", sa.CHAR(1), nullable=True),
        sa.Column("motivazione", sa.SmallInteger(), nullable=True),
        sa.Column("data_rilevazione", sa.Date(), nullable=True),
        sa.Column("cod_flusso", sa.Text(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── pod_metadata (F2G dispatching points) ──────────────────────────────────
    op.create_table(
        "pod_metadata",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("pod", sa.Text(), nullable=False),
        sa.Column("codice_dp", sa.Text(), nullable=True),
        sa.Column("tensione", sa.Integer(), nullable=True),
        sa.Column("trattamento", sa.CHAR(1), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "pod", "valid_from",
            name="uq_pod_metadata_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("pod_metadata")
    op.drop_table("corrections")
    op.drop_table("measurements_totalizer")
    op.drop_table("measurements_secondary")
    op.drop_table("measurements")
    op.drop_table("files")
