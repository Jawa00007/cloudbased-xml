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


def _get_active_schemas(conn) -> list[str]:
    rows = conn.execute(text("SELECT schema_name FROM public.accounts WHERE active = TRUE")).fetchall()
    return [r[0] for r in rows]


def upgrade() -> None:
    conn = op.get_bind()
    for schema in _get_active_schemas(conn):
        conn.execute(text(
            f"ALTER TABLE {schema}.forecast_periods RENAME COLUMN ea_mwh TO ea_kwh"
        ))
        conn.execute(text(
            f"ALTER TABLE {schema}.forecast_periods RENAME COLUMN ea_mwh_with_loss TO ea_kwh_with_loss"
        ))


def downgrade() -> None:
    conn = op.get_bind()
    for schema in _get_active_schemas(conn):
        conn.execute(text(
            f"ALTER TABLE {schema}.forecast_periods RENAME COLUMN ea_kwh TO ea_mwh"
        ))
        conn.execute(text(
            f"ALTER TABLE {schema}.forecast_periods RENAME COLUMN ea_kwh_with_loss TO ea_mwh_with_loss"
        ))
