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

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.LOG_LEVEL == "DEBUG",
    pool_pre_ping=True,
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


async def dispose_engine() -> None:
    """Close all connections — call on app shutdown."""
    await engine.dispose()
