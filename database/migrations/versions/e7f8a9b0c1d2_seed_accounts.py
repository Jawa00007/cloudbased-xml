"""Seed public.accounts with the 12 existing SII client accounts

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-06-09

Populates the public.accounts registry with the 12 pre-existing accounts
so that dynamic account lookup (sync_sii.sh, ingest_all) works correctly.
Uses ON CONFLICT DO NOTHING so re-running is safe.
"""

from __future__ import annotations

from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None

ACCOUNTS = [
    ("BAT",        "bat",          "BAT"),
    ("CH4",        "ch4",          "CH4"),
    ("DINAMO",     "dinamo_trade", "Dinamo Trade"),
    ("EGOGREEN",   "egogreen",     "Egogreen"),
    ("ENERGETICA", "energetica",   "Energetica"),
    ("ENERGIT",    "energit",      "Energit"),
    ("ENJOY",      "enjoy_energy", "Enjoy Energy"),
    ("ONDA",       "onda_piu",     "Onda Più"),
    ("POWERIT",    "power_it",     "Power.IT"),
    ("ROYAL",      "royal_group",  "Royal Group"),
    ("SOS",        "sos",          "SOS"),
    ("TOP",        "top_energy",   "Top Energy"),
]


def upgrade() -> None:
    for account_id, schema_name, display_name in ACCOUNTS:
        op.execute(
            f"INSERT INTO public.accounts (account_id, schema_name, display_name, active) "
            f"VALUES ('{account_id}', '{schema_name}', '{display_name}', true) "
            f"ON CONFLICT (account_id) DO NOTHING"
        )


def downgrade() -> None:
    for account_id, _, _ in ACCOUNTS:
        op.execute(
            f"DELETE FROM public.accounts WHERE account_id = '{account_id}'"
        )
