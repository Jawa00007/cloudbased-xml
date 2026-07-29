"""
APScheduler setup — fallback nightly ingestion at 05:00 UTC and staggered daily retention.

Scheduler is started on FastAPI startup and stopped on shutdown.

The primary ingestion path is now `server_scripts/sync_sii.sh` (root crontab, 02:00
UTC): it pulls new files from the Italian server per account, then chains a full
all-accounts re-check (POST /api/sync) itself once every account's pull finishes —
a real sequential dependency, not a scheduling guess. `nightly_ingest` here is a
resilience fallback only: if the shell cron never runs (server rebooted at 02:00,
cron misconfigured, etc.), this still guarantees one full ingest_all() pass every
day. It fires at 05:00 UTC — after retention (03:30) and safely clear of the shell
script's normal run window — so on a normal night it finds the ingestion guard
already idle and just does a harmless no-op re-scan.

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

# Same ceiling as the API's all-accounts sync path (backend/api/routes/sync.py) — without
# it, a DB connection dying silently mid-account leaves the guard "running" forever,
# blocking every future sync until someone restarts the API manually.
_ALL_ACCOUNTS_TIMEOUT = 6 * 3600


async def _nightly_ingest() -> None:
    """Fallback full ingest — see module docstring. Normally a no-op: the
    02:00 UTC shell-triggered sync + its chained re-check has already run and
    left the guard idle by the time this fires at 05:00 UTC."""
    if backfill_active():
        logger.info("Fallback scheduler: skipping — historical backfill is still running")
        return
    if not guard.claim("scheduler"):
        logger.warning(
            "Fallback scheduler: skipping — ingestion already running "
            "(triggered by %s, current account: %s)",
            guard.triggered_by, guard.current_account,
        )
        return

    logger.info("Fallback scheduler: starting ingestion for all accounts")
    try:
        await asyncio.wait_for(
            ingest_all(on_account=lambda acc: setattr(guard, "current_account", acc)),
            timeout=_ALL_ACCOUNTS_TIMEOUT,
        )
        logger.info("Fallback scheduler: ingestion complete")
    except asyncio.TimeoutError:
        logger.error("Fallback scheduler: ingestion timed out after %ds", _ALL_ACCOUNTS_TIMEOUT)
    except Exception as exc:
        logger.error("Fallback scheduler error: %s", exc, exc_info=True)
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
        trigger=CronTrigger(hour=5, minute=0),   # 05:00 UTC every day — fallback only, see module docstring
        id="nightly_ingest",
        name="Fallback SII ingestion — all accounts (05:00 UTC safety net)",
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
    logger.info(
        "Scheduler started — fallback ingestion 05:00 UTC (primary: cron sync_sii.sh "
        "at 02:00 UTC), retention 03:30 UTC (active 10th–21st)"
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler. Called on FastAPI shutdown."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
