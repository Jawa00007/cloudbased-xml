"""Narrow data retention: keep current year + same-month-last-year rolling window.

Retention rule (retention_policy):
  hard_cutoff = date(today.year, 1, 1)          e.g. 2026-01-01
  keep_start  = date(today.year-1, today.month, 1)   e.g. 2025-05-01
  keep_end    = first day of next month last year     e.g. 2025-06-01

  DELETE WHERE data_misura < keep_start
           OR (data_misura >= keep_end AND data_misura < hard_cutoff)

Example (2026-05-23):
  keep May 2025 + all 2026 data; delete Jun–Dec 2025 and earlier.
  On June 1 2026: keep June 2025 + all 2026; delete May 2025.

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


def retention_policy() -> tuple[date, date, date]:
    """Return (hard_cutoff, keep_start, keep_end) for the narrow retention window.

    hard_cutoff: first day of current year (e.g. 2026-01-01)
    keep_start:  first day of same month last year (e.g. 2025-05-01)
    keep_end:    first day of next month last year (e.g. 2025-06-01)

    Rows to delete: data_misura < keep_start
                 OR (data_misura >= keep_end AND data_misura < hard_cutoff)
    """
    today = date.today()
    hard_cutoff = date(today.year, 1, 1)
    keep_start = date(today.year - 1, today.month, 1)
    if today.month == 12:
        keep_end = date(today.year, 1, 1)  # same as hard_cutoff
    else:
        keep_end = date(today.year - 1, today.month + 1, 1)
    return hard_cutoff, keep_start, keep_end


def retention_cutoff() -> date:
    """Return keep_start from retention_policy() — the oldest date we keep.

    Kept for backward compatibility with admin endpoints that pass a single cutoff.
    """
    _, keep_start, _ = retention_policy()
    return keep_start


async def delete_stale_data(
    session: AsyncSession,
    account_id: str,
    cutoff: date | None = None,
    *,
    policy: tuple[date, date, date] | None = None,
) -> dict[str, int]:
    """Delete measurement data outside the retention window for one account schema.

    When policy=(hard_cutoff, keep_start, keep_end) is given, uses narrow retention:
      DELETE WHERE data_misura < keep_start
               OR (data_misura >= keep_end AND data_misura < hard_cutoff)

    When only cutoff is given (legacy), deletes WHERE data_misura < cutoff.

    The session must already be scoped to the correct account schema (via get_session()).
    Returns {table_name: rows_deleted}.
    """
    if policy is None:
        policy = retention_policy()

    hard_cutoff, keep_start, keep_end = policy

    deleted: dict[str, int] = {}

    # Curve measurement tables — data_misura is a DATE column with an index
    for table in ("measurements", "measurements_secondary"):
        result = await session.execute(
            text(f"""
                DELETE FROM {table}
                WHERE account_id = :acct
                  AND (data_misura < :keep_start
                       OR (data_misura >= :keep_end AND data_misura < :hard_cutoff))
            """),
            {"acct": account_id, "keep_start": keep_start,
             "keep_end": keep_end, "hard_cutoff": hard_cutoff},
        )
        deleted[table] = result.rowcount

    # Totalizer — data_misura is nullable; fall back to mese_anno parse for NULL rows
    result = await session.execute(
        text("""
            DELETE FROM measurements_totalizer
            WHERE account_id = :acct AND (
                (data_misura < :keep_start
                 OR (data_misura >= :keep_end AND data_misura < :hard_cutoff))
                OR (data_misura IS NULL AND mese_anno IS NOT NULL AND (
                    to_date(mese_anno, 'MM/YYYY') < :keep_start
                    OR (to_date(mese_anno, 'MM/YYYY') >= :keep_end
                        AND to_date(mese_anno, 'MM/YYYY') < :hard_cutoff)))
            )
        """),
        {"acct": account_id, "keep_start": keep_start,
         "keep_end": keep_end, "hard_cutoff": hard_cutoff},
    )
    deleted["measurements_totalizer"] = result.rowcount

    # Files log — no data_misura; parse mese_anno (sequential scan is fine — much smaller)
    result = await session.execute(
        text("""
            DELETE FROM files
            WHERE account_id = :acct
              AND mese_anno IS NOT NULL
              AND (to_date(mese_anno, 'MM/YYYY') < :keep_start
                   OR (to_date(mese_anno, 'MM/YYYY') >= :keep_end
                       AND to_date(mese_anno, 'MM/YYYY') < :hard_cutoff))
        """),
        {"acct": account_id, "keep_start": keep_start,
         "keep_end": keep_end, "hard_cutoff": hard_cutoff},
    )
    deleted["files"] = result.rowcount

    # Corrections audit log
    result = await session.execute(
        text("""
            DELETE FROM corrections
            WHERE account_id = :acct
              AND (data_misura < :keep_start
                   OR (data_misura >= :keep_end AND data_misura < :hard_cutoff))
        """),
        {"acct": account_id, "keep_start": keep_start,
         "keep_end": keep_end, "hard_cutoff": hard_cutoff},
    )
    deleted["corrections"] = result.rowcount

    # Forecast periods — keyed by forecast_date
    result = await session.execute(
        text("""
            DELETE FROM forecast_periods
            WHERE account_id = :acct
              AND (forecast_date < :keep_start
                   OR (forecast_date >= :keep_end AND forecast_date < :hard_cutoff))
        """),
        {"acct": account_id, "keep_start": keep_start,
         "keep_end": keep_end, "hard_cutoff": hard_cutoff},
    )
    deleted["forecast_periods"] = result.rowcount

    log.info(
        "Retention %s policy=(%s, [%s,%s)): %s",
        account_id, hard_cutoff, keep_start, keep_end,
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

    policy = retention_policy()
    hard_cutoff, keep_start, _ = policy
    log.info("Monthly retention: hard_cutoff=%s  keep_start=%s", hard_cutoff, keep_start)

    async with get_public_session() as pub:
        accounts = (await pub.execute(
            text("SELECT account_id, schema_name FROM public.accounts WHERE active = true")
        )).fetchall()

    results: dict[str, dict[str, int]] = {}
    for account_id, schema_name in accounts:
        try:
            async with get_session(schema_name) as session:
                deleted = await delete_stale_data(session, account_id, policy=policy)
            async with get_public_session() as pub:
                await log_retention(pub, account_id, keep_start, deleted)
            results[account_id] = deleted
        except Exception as exc:
            log.error("Retention failed for %s: %s", account_id, exc, exc_info=True)
            results[account_id] = {"error": str(exc)}

    log.info("Monthly retention complete: %d accounts processed", len(results))
    return results
