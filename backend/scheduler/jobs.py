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

from backend.ingestion.ingest import ingest_all

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _nightly_ingest() -> None:
    logger.info("Nightly scheduler: starting ingestion for all accounts")
    try:
        await ingest_all()
        logger.info("Nightly scheduler: ingestion complete")
    except Exception as exc:
        logger.error("Nightly scheduler error: %s", exc, exc_info=True)


def start_scheduler() -> None:
    """Add the nightly job and start the scheduler. Called on FastAPI startup."""
    scheduler.add_job(
        _nightly_ingest,
        trigger=CronTrigger(hour=2, minute=0),   # 02:00 server time every day
        id="nightly_ingest",
        name="Nightly SII ingestion — all accounts",
        replace_existing=True,
        misfire_grace_time=3600,   # allow up to 1 hour late start
    )
    scheduler.start()
    logger.info("Scheduler started — nightly job at 02:00")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler. Called on FastAPI shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
