"""rename ea_mwh/ea_mwh_with_loss to ea_kwh/ea_kwh_with_loss in forecast_periods

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-16

Store full-precision kWh values instead of pre-rounded MWh per row.
MWh conversion now happens only at aggregation time (ROUND(SUM(ea_kwh_with_loss)/1000,3))
so that summing many PODs within a dispatching point does not accumulate rounding errors.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "b3c4d5e6f7a8"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _column_exists(conn, column: str) -> bool:
    """Check if column exists in forecast_periods in the current search_path schema."""
    row = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'forecast_periods' AND column_name = :col "
        "AND table_schema = current_schema()"
    ), {"col": column}).fetchone()
    return row is not None


def upgrade() -> None:
    # env.py already iterates schemas and sets SET search_path per schema.
    # This migration only needs to operate on the current schema.
    conn = op.get_bind()
    if _column_exists(conn, "ea_mwh"):
        conn.execute(text("ALTER TABLE forecast_periods RENAME COLUMN ea_mwh TO ea_kwh"))
    if _column_exists(conn, "ea_mwh_with_loss"):
        conn.execute(text("ALTER TABLE forecast_periods RENAME COLUMN ea_mwh_with_loss TO ea_kwh_with_loss"))


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "ea_kwh"):
        conn.execute(text("ALTER TABLE forecast_periods RENAME COLUMN ea_kwh TO ea_mwh"))
    if _column_exists(conn, "ea_kwh_with_loss"):
        conn.execute(text("ALTER TABLE forecast_periods RENAME COLUMN ea_kwh_with_loss TO ea_mwh_with_loss"))
