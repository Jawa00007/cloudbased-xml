"""
Migration: allow NULL account_id in dispatching_config so weights can be global.
Run once: py migrate_dispatch_nullable.py
"""
import asyncio
import os
import selectors
import sys

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)


async def run() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE public.dispatching_config ALTER COLUMN account_id DROP NOT NULL"
        ))
    await engine.dispose()
    print("OK: dispatching_config.account_id is now nullable (global weights supported)")


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())
