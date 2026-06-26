"""
APScheduler setup — nightly ingestion at 02:00 UTC and staggered daily retention.

Scheduler is started on FastAPI startup and stopped on shutdown.
The nightly job calls ingest_all() which processes all active accounts.

Retention runs once per day from the 10th to the 21st of each month at 03:30 UTC,
processing one account per day (alphabetical by schema_name).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from backend.db.retention import run_retention_for_account
from backend.ingestion.ingest import ingest_all
from backend.ingestion.lock import backfill_active, guard

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _nightly_ingest() -> None:
    if backfill_active():
        logger.info("Nightly scheduler: skipping — historical backfill is still running")
        return
    if not guard.claim("scheduler"):
        logger.warning(
            "Nightly scheduler: skipping — ingestion already running "
            "(triggered by %s, current account: %s)",
            guard.triggered_by, guard.current_account,
        )
        return

    logger.info("Nightly scheduler: starting ingestion for all accounts")
    try:
        await ingest_all(on_account=lambda acc: setattr(guard, "current_account", acc))
        logger.info("Nightly scheduler: ingestion complete")
    except Exception as exc:
        logger.error("Nightly scheduler error: %s", exc, exc_info=True)
    finally:
        guard.release()


async def _daily_retention() -> None:
    """Purge one account per day, days 10–21 of each month at 03:30 UTC.

    Accounts are sorted alphabetically by schema_name so the day→account mapping
    is stable and predictable:
      day 10 = bat, 11 = ch4, 12 = dinamo_trade, 13 = egogreen, ...
    """
    day = date.today().day
    if not (10 <= day <= 21):
        return

    from backend.db.session import get_public_session

    async with get_public_session() as pub:
        rows = (await pub.execute(
            text("SELECT account_id, schema_name FROM public.accounts WHERE active = true ORDER BY schema_name")
        )).fetchall()

    idx = day - 10
    if idx >= len(rows):
        logger.info("Retention day %d: no account at index %d (only %d active)", day, idx, len(rows))
        return

    account_id, schema_name = rows[idx]
    logger.info("Retention day %d: processing account %s (%s)", day, account_id, schema_name)
    await run_retention_for_account(account_id, schema_name)


def start_scheduler() -> None:
    """Add the nightly job and start the scheduler. Called on FastAPI startup."""
    scheduler.add_job(
        _nightly_ingest,
        trigger=CronTrigger(hour=2, minute=0),   # 02:00 UTC every day
        id="nightly_ingest",
        name="Nightly SII ingestion — all accounts",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )
    scheduler.add_job(
        _daily_retention,
        trigger=CronTrigger(hour=3, minute=30),  # 03:30 UTC every day (no-op outside 10th–21st)
        id="daily_retention",
        name="Daily retention — one account per day, 10th–21st of each month",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started — ingestion at 02:00 UTC, retention 03:30 UTC (active 10th–21st)")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler. Called on FastAPI shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
