"""
Sync endpoints:

  POST /sync           — trigger ingestion for all accounts
  POST /sync/{account} — trigger ingestion for one account
  GET  /sync/status    — last sync run results per account

Concurrency contract
--------------------
The guard (backend.ingestion.lock.guard) is a module-level singleton shared
between this route and the APScheduler job.  guard.claim() is synchronous and
has no await points, so the check-and-set is atomic within asyncio's
single-threaded event loop.

Flow:
  1. Endpoint checks guard.is_running() → 409 if True
  2. Endpoint calls guard.claim("api") — flag is set *before* the background
     task is queued, closing the window between check and task start
  3. Background task does the work; releases guard in finally
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from backend.api.auth import require_auth
from backend.api.schemas import SyncStatusOut, SyncTriggerOut
from backend.ingestion.ingest import ACCOUNT_SCHEMA_MAP, ingest_account, ingest_all
from backend.ingestion.lock import guard

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sync"])

# Per-account historical results (last completed run)
_sync_state: dict[str, SyncStatusOut] = {}

_ACCOUNT_TIMEOUT = 3600  # seconds — matches ingest_all's internal timeout


def _make_status(account_id: str) -> SyncStatusOut:
    return SyncStatusOut(
        account_id=account_id,
        started_at=None,
        finished_at=None,
        files_ok=0,
        files_error=0,
        files_skipped=0,
        running=False,
    )


async def _run_ingest(account_id: str | None) -> None:
    """
    Background task — runs ingestion and updates _sync_state.
    The guard must already be claimed by the calling endpoint before this runs.
    """
    started_at = guard.started_at or datetime.now(timezone.utc)
    accounts_to_update = [account_id] if account_id else list(ACCOUNT_SCHEMA_MAP.keys())

    try:
        if account_id:
            guard.current_account = account_id
            try:
                await asyncio.wait_for(ingest_account(account_id), timeout=_ACCOUNT_TIMEOUT)
            except asyncio.TimeoutError:
                logger.error("Sync: account %s timed out after %ds", account_id, _ACCOUNT_TIMEOUT)
        else:
            await ingest_all(on_account=lambda acc: setattr(guard, "current_account", acc))

    except Exception as exc:
        logger.error("Sync error: %s", exc)

    finally:
        guard.release()
        finished = datetime.now(timezone.utc)
        for acc in accounts_to_update:
            prev = _sync_state.get(acc, _make_status(acc))
            _sync_state[acc] = SyncStatusOut(
                account_id=acc,
                started_at=started_at,
                finished_at=finished,
                files_ok=prev.files_ok,
                files_error=prev.files_error,
                files_skipped=prev.files_skipped,
                running=False,
            )


def _conflict_detail() -> str:
    elapsed = ""
    if guard.started_at:
        secs = int((datetime.now(timezone.utc) - guard.started_at).total_seconds())
        elapsed = f", running for {secs}s"
    current = guard.current_account or "initializing"
    return (
        f"Ingestion already running (triggered by {guard.triggered_by}{elapsed}, "
        f"current account: {current})"
    )


@router.post("/sync", response_model=SyncTriggerOut)
async def trigger_sync_all(
    background_tasks: BackgroundTasks,
    _: Annotated[str, Depends(require_auth)],
) -> SyncTriggerOut:
    if not guard.claim("api"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(),
        )
    background_tasks.add_task(_run_ingest, None)
    return SyncTriggerOut(message="Ingestion started for all accounts", account_id=None)


@router.post("/sync/{account}", response_model=SyncTriggerOut)
async def trigger_sync_account(
    account: str,
    background_tasks: BackgroundTasks,
    _: Annotated[str, Depends(require_auth)],
) -> SyncTriggerOut:
    if account not in ACCOUNT_SCHEMA_MAP:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown account: {account!r}",
        )
    if not guard.claim("api"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(),
        )
    background_tasks.add_task(_run_ingest, account)
    return SyncTriggerOut(message=f"Ingestion started for {account}", account_id=account)


@router.get("/sync/status", response_model=list[SyncStatusOut])
async def sync_status(
    _: Annotated[str, Depends(require_auth)],
) -> list[SyncStatusOut]:
    """
    Returns per-account ingestion status.

    While a run is in progress, running=True is shown for all accounts
    along with current_account (the account being processed right now)
    and triggered_by ("scheduler" or "api").
    """
    running = guard.is_running()
    result: list[SyncStatusOut] = []

    for acc in ACCOUNT_SCHEMA_MAP:
        prev = _sync_state.get(acc, _make_status(acc))
        if running:
            result.append(SyncStatusOut(
                account_id=acc,
                started_at=guard.started_at,
                finished_at=None,
                files_ok=prev.files_ok,
                files_error=prev.files_error,
                files_skipped=prev.files_skipped,
                running=True,
                current_account=guard.current_account,
                triggered_by=guard.triggered_by,
            ))
        else:
            result.append(prev)

    return result
