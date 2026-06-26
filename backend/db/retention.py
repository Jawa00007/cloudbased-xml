"""Rolling 12-month data retention.

Rule: keep the last 12 full months of data.

  cutoff = first day of (current month − 11 months)

Examples:
  June 15 2026  → cutoff 2025-07-01 → delete mese_anno ≤ 06/2025, keep ≥ 07/2025
  July 15 2026  → cutoff 2025-08-01 → delete mese_anno ≤ 07/2025, keep ≥ 08/2025

Tables NOT pruned: pod_metadata, anagrafica, loss_config, dispatching_config
(reference/config data needed for forecasting regardless of age).
"""

from __future__ import annotations

import json
import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


def retention_cutoff() -> date:
    """Return the oldest date to keep (inclusive).

    Deletes everything with data_misura < this date.
    On June 15 2026 returns 2025-07-01; on July 15 2026 returns 2025-08-01.
    """
    today = date.today()
    month = today.month - 11
    year = today.year
    if month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


async def delete_stale_data(
    session: AsyncSession,
    account_id: str,
    cutoff: date | None = None,
) -> dict[str, int]:
    """Delete measurement data older than cutoff for one account schema.

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
            WHERE account_id = :acct
              AND (
                data_misura < :cutoff
                OR (data_misura IS NULL
                    AND mese_anno IS NOT NULL
                    AND to_date(mese_anno, 'MM/YYYY') < :cutoff)
              )
        """),
        {"acct": account_id, "cutoff": cutoff},
    )
    deleted["measurements_totalizer"] = result.rowcount

    # Corrections audit log — data_misura nullable; mese_anno fallback
    result = await session.execute(
        text("""
            DELETE FROM corrections
            WHERE account_id = :acct
              AND (
                data_misura < :cutoff
                OR (data_misura IS NULL
                    AND mese_anno IS NOT NULL
                    AND to_date(mese_anno, 'MM/YYYY') < :cutoff)
              )
        """),
        {"acct": account_id, "cutoff": cutoff},
    )
    deleted["corrections"] = result.rowcount

    # Forecast periods — keyed by forecast_date
    result = await session.execute(
        text("DELETE FROM forecast_periods WHERE account_id = :acct AND forecast_date < :cutoff"),
        {"acct": account_id, "cutoff": cutoff},
    )
    deleted["forecast_periods"] = result.rowcount

    total = sum(deleted.values())
    log.info(
        "Retention %s cutoff=%s deleted=%d rows: %s",
        account_id, cutoff, total,
        {k: v for k, v in deleted.items() if v > 0},
    )

    # VACUUM ANALYZE on tables that had deletions — marks dead tuples reusable,
    # updates planner statistics. No lock; runs outside the transaction.
    if total > 0:
        await session.commit()
        for table in ("measurements", "measurements_secondary",
                      "measurements_totalizer", "corrections", "forecast_periods"):
            if deleted.get(table, 0) > 0:
                await session.execute(text(f"VACUUM (ANALYZE) {table}"))

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


async def run_retention_for_account(account_id: str, schema_name: str) -> dict[str, int]:
    """Run retention purge for a single account. Called by scheduler and admin endpoint."""
    from backend.db.session import get_public_session, get_session  # local import avoids circulars

    cutoff = retention_cutoff()
    log.info("Retention %s: cutoff=%s", account_id, cutoff)

    try:
        async with get_session(schema_name) as session:
            deleted = await delete_stale_data(session, account_id, cutoff=cutoff)
        async with get_public_session() as pub:
            await log_retention(pub, account_id, cutoff, deleted)
        return deleted
    except Exception as exc:
        log.error("Retention failed for %s: %s", account_id, exc, exc_info=True)
        return {"error": str(exc)}


async def run_monthly_retention() -> dict[str, dict[str, int]]:
    """Run retention for all active accounts. Called by admin /retention/run endpoint."""
    from backend.db.session import get_public_session

    cutoff = retention_cutoff()
    log.info("Full retention run: cutoff=%s", cutoff)

    async with get_public_session() as pub:
        accounts = (await pub.execute(
            text("SELECT account_id, schema_name FROM public.accounts WHERE active = true ORDER BY schema_name")
        )).fetchall()

    results: dict[str, dict[str, int]] = {}
    for account_id, schema_name in accounts:
        results[account_id] = await run_retention_for_account(account_id, schema_name)

    log.info("Full retention complete: %d accounts processed", len(results))
    return results
