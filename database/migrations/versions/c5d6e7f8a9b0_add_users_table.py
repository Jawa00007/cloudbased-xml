"""add public.users table for named user accounts with per-account access control

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-05-17

Creates a persistent user table in the public schema.
allowed_accounts = NULL means the user can access all accounts (admin-equivalent).
allowed_accounts = ['BAT','CH4'] means restricted to those accounts only.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "c5d6e7f8a9b0"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Only run on the public schema iteration (env.py iterates all schemas;
    # this table belongs in public and only needs creating once).
    current = conn.execute(text("SELECT current_schema()")).scalar()
    if current != "public":
        return

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS public.users (
            id               SERIAL PRIMARY KEY,
            username         TEXT NOT NULL UNIQUE,
            password_hash    TEXT NOT NULL,
            is_admin         BOOLEAN NOT NULL DEFAULT false,
            allowed_accounts TEXT[] DEFAULT NULL,
            is_active        BOOLEAN NOT NULL DEFAULT true,
            created_at       TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_users_username ON public.users (username)"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    current = conn.execute(text("SELECT current_schema()")).scalar()
    if current != "public":
        return
    conn.execute(text("DROP TABLE IF EXISTS public.users"))
