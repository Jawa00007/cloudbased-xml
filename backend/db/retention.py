"""Rolling 12-month data retention.

Retention rule:
  cutoff = date(today.year - 1, today.month, 1)
  Delete measurement rows WHERE measurement_date < cutoff

Example: running on 2026-06-01 → cutoff = 2025-06-01
         → deletes May 2025 and earlier; keeps June 2025+

Tables NOT pruned: pod_metadata, anagrafica, loss_config, dispatching_config
(these are reference/config data needed for forecasting regardless of age).
"""

from __future__ import annotations

import json
import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


def retention_cutoff() -> date:
    """Return the first day of the same month one year ago.

    Data with measurement_date strictly before this date will be deleted.
    """
    today = date.today()
    return date(today.year - 1, today.month, 1)


async def delete_stale_data(
    session: AsyncSession,
    account_id: str,
    cutoff: date | None = None,
) -> dict[str, int]:
    """Delete measurement data older than the retention window for one account schema.

    The session must already be scoped to the correct account schema (via get_session()).
    Returns {table_name: rows_deleted}.
    """
    if cutoff is None:
        cutoff = retention_cutoff()

    deleted: dict[str, int] = {}

    # Curve measurement tables — data_misura is a DATE column with an index
    for table in ("measurements", "measurements_secondary"):
        result = await session.execute(
            text(f"DELETE FROM {table} WHERE account_id = :acct AND data_misura < :cutoff"),
            {"acct": account_id, "cutoff": cutoff},
        )
        deleted[table] = result.rowcount

    # Totalizer — data_misura is nullable; fall back to mese_anno parse for NULL rows
    result = await session.execute(
        text("""
            DELETE FROM measurements_totalizer
            WHERE account_id = :acct AND (
                data_misura < :cutoff
                OR (data_misura IS NULL
                    AND mese_anno IS NOT NULL
                    AND to_date(mese_anno, 'MM/YYYY') < :cutoff)
            )
        """),
        {"acct": account_id, "cutoff": cutoff},
    )
    deleted["measurements_totalizer"] = result.rowcount

    # Files log — no data_misura column; parse mese_anno
    # Sequential scan is acceptable: files table is much smaller than measurements
    result = await session.execute(
        text("""
            DELETE FROM files
            WHERE account_id = :acct
              AND mese_anno IS NOT NULL
              AND to_date(mese_anno, 'MM/YYYY') < :cutoff
        """),
        {"acct": account_id, "cutoff": cutoff},
    )
    deleted["files"] = result.rowcount

    # Corrections audit log — data_misura is present
    result = await session.execute(
        text("DELETE FROM corrections WHERE account_id = :acct AND data_misura < :cutoff"),
        {"acct": account_id, "cutoff": cutoff},
    )
    deleted["corrections"] = result.rowcount

    # Forecast periods — use forecast_date
    result = await session.execute(
        text("DELETE FROM forecast_periods WHERE account_id = :acct AND forecast_date < :cutoff"),
        {"acct": account_id, "cutoff": cutoff},
    )
    deleted["forecast_periods"] = result.rowcount

    log.info(
        "Retention %s cutoff=%s: %s",
        account_id, cutoff,
        {k: v for k, v in deleted.items() if v > 0},
    )
    return deleted


async def log_retention(
    pub_session: AsyncSession,
    account_id: str,
    cutoff: date,
    rows_deleted: dict[str, int],
) -> None:
    """Record a retention run in public.archive_catalog (upsert — idempotent)."""
    await pub_session.execute(
        text("""
            INSERT INTO public.archive_catalog
                (account_id, cutoff_date, deleted_at, rows_deleted)
            VALUES (:acct, :cutoff, now(), cast(:rows AS jsonb))
            ON CONFLICT (account_id, cutoff_date) DO UPDATE
                SET deleted_at   = now(),
                    rows_deleted = EXCLUDED.rows_deleted
        """),
        {"acct": account_id, "cutoff": cutoff, "rows": json.dumps(rows_deleted)},
    )


async def run_monthly_retention() -> dict[str, dict[str, int]]:
    """Run the retention purge for all active accounts.

    Called by the monthly scheduler job and the admin /retention/run endpoint.
    Returns {account_id: rows_deleted_dict}.
    """
    from backend.db.session import get_public_session, get_session  # local import avoids circulars

    cutoff = retention_cutoff()
    log.info("Monthly retention: cutoff=%s", cutoff)

    async with get_public_session() as pub:
        accounts = (await pub.execute(
            text("SELECT account_id, schema_name FROM public.accounts WHERE active = true")
        )).fetchall()

    results: dict[str, dict[str, int]] = {}
    for account_id, schema_name in accounts:
        try:
            async with get_session(schema_name) as session:
                deleted = await delete_stale_data(session, account_id, cutoff)
            async with get_public_session() as pub:
                await log_retention(pub, account_id, cutoff, deleted)
            results[account_id] = deleted
        except Exception as exc:
            log.error("Retention failed for %s: %s", account_id, exc, exc_info=True)
            results[account_id] = {"error": str(exc)}

    log.info("Monthly retention complete: %d accounts processed", len(results))
    return results
