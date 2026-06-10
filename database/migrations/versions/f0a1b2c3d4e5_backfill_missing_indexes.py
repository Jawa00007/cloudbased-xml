"""Backfill query indexes that the initial migration defined but were never created
on production (the DB was stamped rather than migrated from scratch).

All DDL uses IF NOT EXISTS so this is safe to run on any environment — on fresh
deployments the initial migration (9c0971ba5b78) already creates these; on the
production DB they may already exist from the server-side backfill script; in
both cases this migration is a no-op.

Revision ID: f0a1b2c3d4e5
Revises: e7f8a9b0c1d2
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # measurements — primary query indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_measurements_pod_date "
        "ON measurements (account_id, pod, data_misura)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_measurements_mese_anno "
        "ON measurements (account_id, mese_anno)"
    )
    # Covering index for the forecast source query:
    # WHERE account_id=? AND pod=ANY(?) AND mese_anno=? AND tipo_dato=?
    # ORDER BY pod, data_misura, periodo
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_measurements_pod_month "
        "ON measurements (account_id, pod, mese_anno, data_misura, periodo)"
    )
    # measurements_secondary — same set
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_measurements_secondary_pod_date "
        "ON measurements_secondary (account_id, pod, data_misura)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_measurements_secondary_mese_anno "
        "ON measurements_secondary (account_id, mese_anno)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_measurements_secondary_pod_month "
        "ON measurements_secondary (account_id, pod, mese_anno, data_misura, periodo)"
    )
    # measurements_totalizer
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_totalizer_pod_date "
        "ON measurements_totalizer (account_id, pod, data_misura)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_measurements_pod_date")
    op.execute("DROP INDEX IF EXISTS ix_measurements_mese_anno")
    op.execute("DROP INDEX IF EXISTS ix_measurements_pod_month")
    op.execute("DROP INDEX IF EXISTS ix_measurements_secondary_pod_date")
    op.execute("DROP INDEX IF EXISTS ix_measurements_secondary_mese_anno")
    op.execute("DROP INDEX IF EXISTS ix_measurements_secondary_pod_month")
    op.execute("DROP INDEX IF EXISTS ix_totalizer_pod_date")
