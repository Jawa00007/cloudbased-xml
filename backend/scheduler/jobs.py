"""
APScheduler setup — nightly ingestion at 02:00 server time.

Scheduler is started on FastAPI startup and stopped on shutdown.
The nightly job calls ingest_all() which processes all active accounts.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.db.retention import run_monthly_retention
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


async def _monthly_retention() -> None:
    """Purge measurement data older than 12 months for all active accounts."""
    await run_monthly_retention()


def start_scheduler() -> None:
    """Add the nightly job and start the scheduler. Called on FastAPI startup."""
    scheduler.add_job(
        _nightly_ingest,
        trigger=CronTrigger(hour=2, minute=0),   # 02:00 server time every day
        id="nightly_ingest",
        name="Nightly SII ingestion — all accounts",
        replace_existing=True,
        misfire_grace_time=3600,   # allow up to 1 hour late start
        max_instances=1,           # never overlap with a previous run still in progress
    )
    scheduler.add_job(
        _monthly_retention,
        trigger=CronTrigger(day=1, hour=3, minute=0),   # 1st of each month at 03:00 UTC
        id="monthly_retention",
        name="Monthly data retention — rolling 12-month window",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started — nightly job at 02:00, retention on 1st of month at 03:00")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler. Called on FastAPI shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
