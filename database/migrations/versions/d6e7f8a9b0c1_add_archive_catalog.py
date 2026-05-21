"""add public.archive_catalog for rolling data retention history

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-05-21

Records which account/cutoff pairs have been pruned by the monthly retention job.
The JSONB rows_deleted column stores per-table row counts so operators know
exactly what was removed and can decide whether to re-import from archive.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Public schema only — this table lives once, not per-account.
    current = conn.execute(text("SELECT current_schema()")).scalar()
    if current != "public":
        return

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS public.archive_catalog (
            id            SERIAL PRIMARY KEY,
            account_id    TEXT NOT NULL,
            cutoff_date   DATE NOT NULL,
            deleted_at    TIMESTAMP WITH TIME ZONE DEFAULT now(),
            rows_deleted  JSONB,
            UNIQUE (account_id, cutoff_date)
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()
    current = conn.execute(text("SELECT current_schema()")).scalar()
    if current != "public":
        return
    conn.execute(text("DROP TABLE IF EXISTS public.archive_catalog"))
