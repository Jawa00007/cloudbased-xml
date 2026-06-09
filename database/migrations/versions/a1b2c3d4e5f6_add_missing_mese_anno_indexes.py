"""add missing mese_anno indexes on measurements_secondary and measurements_totalizer

Revision ID: a1b2c3d4e5f6
Revises: 9c0971ba5b78
Create Date: 2026-05-10

These indexes were declared in the SQLAlchemy models but were absent from the
initial migration, causing full-table scans on monthly aggregation queries.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "9c0971ba5b78"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use CREATE INDEX so the index builds without locking the table.
    # Alembic runs these outside of a transaction (execute_with_ddl_events handles it).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_measurements_secondary_mese_anno "
        "ON measurements_secondary (account_id, mese_anno)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_totalizer_mese_anno "
        "ON measurements_totalizer (account_id, mese_anno)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_measurements_secondary_mese_anno")
    op.execute("DROP INDEX IF EXISTS ix_totalizer_mese_anno")
