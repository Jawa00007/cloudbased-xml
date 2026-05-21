"""
Alembic env.py — multi-schema aware, synchronous engine.

Uses psycopg in sync mode (no asyncio) to avoid the Windows
ProactorEventLoop incompatibility with psycopg 3.

Run commands:
    # Generate initial migration (auto-detect from ORM models):
    alembic -x schema=bat revision --autogenerate -m "initial_schema"

    # Apply to one schema:
    alembic -x schema=bat upgrade head

    # Apply to all active schemas (reads public.accounts):
    alembic upgrade head
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

# Make project root importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.config import settings
from backend.models.base import Base

# Import all models so their tables are registered on Base.metadata
import backend.models.accounts       # noqa: F401
import backend.models.corrections    # noqa: F401
import backend.models.files          # noqa: F401
import backend.models.measurements   # noqa: F401
import backend.models.pod_metadata   # noqa: F401

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# Build a synchronous URL from the async DATABASE_URL.
# postgresql+psycopg:// works in sync mode — no driver swap needed.
sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg").replace(
    "postgresql+psycopg://", "postgresql+psycopg://"
)
alembic_config.set_main_option("sqlalchemy.url", sync_url)

target_metadata = Base.metadata

# Tables that live in public schema only — excluded from per-account migrations
PUBLIC_TABLES = {"accounts"}


def get_target_schema() -> str | None:
    """Return schema override from -x schema=<name> CLI option."""
    return context.get_x_argument(as_dictionary=True).get("schema")


def do_run_migrations(connection, schema: str) -> None:
    """Run Alembic migrations scoped to one account schema."""
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    connection.execute(text(f"SET search_path TO {schema}, public"))
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Per-schema version table so each schema tracks its own migration state
        version_table=f"alembic_version_{schema}",
        include_schemas=False,
        include_object=lambda obj, name, type_, reflected, compare_to: (
            name not in PUBLIC_TABLES if type_ == "table" else True
        ),
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Generate SQL script without a live DB connection."""
    url = alembic_config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations using a live DB connection (sync engine)."""
    connectable = create_engine(
        alembic_config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )

    schema = get_target_schema()

    with connectable.connect() as connection:
        if schema:
            do_run_migrations(connection, schema)
        else:
            # Always run public-schema migrations first (users, archive_catalog, etc.)
            do_run_migrations(connection, "public")
            # Then apply to all active account schemas
            rows = connection.execute(
                text("SELECT schema_name FROM public.accounts WHERE active = true")
            )
            for (s,) in rows:
                do_run_migrations(connection, s)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
