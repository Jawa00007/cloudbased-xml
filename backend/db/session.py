"""
Async SQLAlchemy session management.

Each account uses a separate PostgreSQL schema. Sessions are scoped to an
account by issuing SET search_path immediately after acquisition.

Usage:
    async with get_session("bat") as session:
        await session.execute(...)
"""

from __future__ import annotations

import selectors
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.config import settings

# psycopg requires SelectorEventLoop on Windows (ProactorEventLoop is default)
# On Linux (production) this is a no-op
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(  # type: ignore[attr-defined]
        asyncio.WindowsSelectorEventLoopPolicy()
    )

# Normalise postgresql:// or postgres:// to the postgresql+psycopg:// scheme
# that psycopg3 (async) requires — fix it transparently.
def _fix_db_url(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
            break
    # Only add sslmode=require for remote hosts (Supabase/RDS/etc), not local Docker
    if "sslmode" not in url and _is_remote_host(url):
        sep = "&" if "?" in url else "?"
        url = url + sep + "sslmode=require"
    return url


def _is_remote_host(url: str) -> bool:
    """Return True if the DB host is not a local/Docker hostname."""
    local_hosts = ("localhost", "127.0.0.1", "db", "postgres", "database")
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        return not any(host == h or host.endswith(f".{h}") for h in local_hosts)
    except Exception:
        return True

engine = create_async_engine(
    _fix_db_url(settings.DATABASE_URL),
    echo=settings.LOG_LEVEL == "DEBUG",
    pool_pre_ping=True,
    pool_size=10,       # steady-state connections kept open
    max_overflow=20,    # extra connections allowed under burst load
    pool_timeout=30,    # seconds to wait for a connection before raising
    pool_recycle=1800,  # recycle connections every 30 min to clear stale state
)

_SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session(schema: str) -> AsyncIterator[AsyncSession]:
    """
    Yield an async session scoped to the given account schema.

    Sets search_path so all queries target the account's schema
    without needing to qualify every table name.
    """
    async with _SessionFactory() as session:
        safe_schema = _safe_schema(schema)
        await session.execute(
            text(f"SET search_path TO {safe_schema}, public")
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _safe_schema(schema: str) -> str:
    cleaned = schema.lower().replace(" ", "_").replace("-", "_")
    if not all(c.isalnum() or c == "_" for c in cleaned):
        raise ValueError(f"Invalid schema name: {schema!r}")
    return cleaned


@asynccontextmanager
async def get_public_session() -> AsyncIterator[AsyncSession]:
    """Yield a session scoped to the public schema (loss_config, dispatching_config, etc.)."""
    async with _SessionFactory() as session:
        await session.execute(text("SET search_path TO public"))
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Close all connections — call on app shutdown."""
    await engine.dispose()
