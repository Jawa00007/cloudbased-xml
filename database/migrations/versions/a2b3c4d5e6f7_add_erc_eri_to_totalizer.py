"""Add ErcF1-F6, EriF1-F6, ErF4-F6, PotF4-F6 columns to measurements_totalizer.

These fields appear in RSN2G (and potentially other Flusso 2 totalizer) files and
were previously silently dropped. All columns are nullable NUMERIC(10,3).

Uses ADD COLUMN IF NOT EXISTS — safe on fresh deployments (initial migration already
has these) and on production where they will be newly added.

Revision ID: a2b3c4d5e6f7
Revises: f0a1b2c3d4e5
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None

_SCHEMAS = [
    "bat", "ch4", "dinamo_trade", "egogreen", "energetica", "energit",
    "enjoy_energy", "onda_piu", "power_it", "royal_group", "sos", "top_energy",
]

_NEW_COLS = [
    "er_f4", "er_f5", "er_f6",
    "pot_f4", "pot_f5", "pot_f6",
    "erc_f1", "erc_f2", "erc_f3", "erc_f4", "erc_f5", "erc_f6",
    "eri_f1", "eri_f2", "eri_f3", "eri_f4", "eri_f5", "eri_f6",
]


def upgrade() -> None:
    for schema in _SCHEMAS:
        op.execute(f"SET search_path TO {schema}, public")
        for col in _NEW_COLS:
            op.execute(
                f"ALTER TABLE measurements_totalizer "
                f"ADD COLUMN IF NOT EXISTS {col} NUMERIC(10,3)"
            )
    op.execute("SET search_path TO public")


def downgrade() -> None:
    for schema in _SCHEMAS:
        op.execute(f"SET search_path TO {schema}, public")
        for col in _NEW_COLS:
            op.execute(
                f"ALTER TABLE measurements_totalizer "
                f"DROP COLUMN IF EXISTS {col}"
            )
    op.execute("SET search_path TO public")
