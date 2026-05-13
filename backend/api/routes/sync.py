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
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

def _read_backfill_status() -> dict:
    """Read backfill container status written by run_backfill.sh. Returns {} if not active."""
    try:
        p = Path(settings.SII_DATA_PATH) / '.backfill_status.json'
        if p.exists():
            data = json.loads(p.read_text())
            if data.get('running'):
                return data
    except Exception:
        pass
    return {}

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from backend.api.auth import require_auth
from backend.api.schemas import SyncStatusOut, SyncTriggerOut
from backend.core.config import settings
from backend.db.session import get_session
from backend.ingestion.ingest import ACCOUNT_SCHEMA_MAP, ingest_account, ingest_all, schema_for
from backend.ingestion.lock import backfill_active, backfill_detail, guard

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sync"])

# Persist state across restarts in the data volume
_STATE_FILE = Path(settings.SII_DATA_PATH) / ".sync_state.json"

# Per-account historical results (last completed run)
_sync_state: dict[str, SyncStatusOut] = {}


def _load_state() -> None:
    """Load persisted sync state from disk on startup."""
    try:
        if _STATE_FILE.exists():
            raw = json.loads(_STATE_FILE.read_text())
            for acc, rec in raw.items():
                _sync_state[acc] = SyncStatusOut(
                    account_id=rec["account_id"],
                    started_at=rec.get("started_at"),
                    finished_at=rec.get("finished_at"),
                    files_ok=rec.get("files_ok", 0),
                    files_error=rec.get("files_error", 0),
                    files_skipped=rec.get("files_skipped", 0),
                    triggered_by=rec.get("triggered_by"),
                    running=False,
                )
    except Exception as exc:
        logger.warning("Could not load sync state: %s", exc)


def _save_state() -> None:
    """Persist current sync state to disk."""
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            acc: {
                "account_id": s.account_id,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
                "files_ok": s.files_ok,
                "files_error": s.files_error,
                "files_skipped": s.files_skipped,
                "triggered_by": s.triggered_by,
            }
            for acc, s in _sync_state.items()
        }
        _STATE_FILE.write_text(json.dumps(payload))
    except Exception as exc:
        logger.warning("Could not save sync state: %s", exc)


_load_state()

_ACCOUNT_TIMEOUT = 3600  # seconds — matches ingest_all's internal timeout

# DB-backed last-sync cache (30s TTL) so cron-triggered runs show up in the UI
_db_last_sync: dict[str, datetime | None] = {}
_db_file_counts: dict[str, tuple[int, int]] = {}   # account → (ok, error)
_db_last_sync_ts: float = 0.0
_DB_CACHE_TTL = 30.0


async def _refresh_db_last_syncs() -> None:
    """Query MAX(processed_at) and file counts per account schema from the files table."""
    global _db_last_sync, _db_file_counts, _db_last_sync_ts
    from sqlalchemy import text

    now = time.monotonic()
    if now - _db_last_sync_ts < _DB_CACHE_TTL:
        return
    syncs: dict[str, datetime | None] = {}
    counts: dict[str, tuple[int, int]] = {}
    for acc in ACCOUNT_SCHEMA_MAP:
        schema = schema_for(acc)
        try:
            async with get_session(schema) as session:
                row = await session.execute(text("""
                    SELECT
                        MAX(processed_at),
                        COUNT(*) FILTER (WHERE status = 'ok'),
                        COUNT(*) FILTER (WHERE status = 'error')
                    FROM files
                """))
                last_at, ok, err = row.one()
                syncs[acc] = last_at
                counts[acc] = (int(ok or 0), int(err or 0))
        except Exception:
            syncs[acc] = None
            counts[acc] = (0, 0)
    _db_last_sync = syncs
    _db_file_counts = counts
    _db_last_sync_ts = time.monotonic()


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
    accounts_to_run = [account_id] if account_id else list(ACCOUNT_SCHEMA_MAP.keys())
    guard.accounts_total = len(accounts_to_run)
    guard.accounts_done = 0
    guard.files_done = 0
    guard.files_total = 0
    guard.phase = ""

    def _on_account(acc: str) -> None:
        guard.current_account = acc
        guard.files_done = 0
        guard.files_total = 0
        guard.phase = "scanning"

    def _on_account_done(acc: str, ok: int, err: int, skipped: int) -> None:
        guard.accounts_done += 1
        guard.phase = ""
        _sync_state[acc] = SyncStatusOut(
            account_id=acc,
            started_at=started_at,
            finished_at=None,   # still running overall; will be set in finally
            files_ok=ok,
            files_error=err,
            files_skipped=skipped,
            running=False,
        )

    def _on_scan_start() -> None:
        guard.phase = "scanning"
        guard.files_done = 0
        guard.files_total = 0

    def _on_files_found(total: int) -> None:
        guard.files_total = total
        guard.files_done = 0
        guard.phase = "processing"

    def _on_file_done() -> None:
        guard.files_done += 1

    try:
        if account_id:
            guard.current_account = account_id
            try:
                await asyncio.wait_for(
                    ingest_account(
                        account_id,
                        on_scan_start=_on_scan_start,
                        on_files_found=_on_files_found,
                        on_file_done=_on_file_done,
                    ),
                    timeout=_ACCOUNT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.error("Sync: account %s timed out after %ds", account_id, _ACCOUNT_TIMEOUT)
            guard.accounts_done = 1
        else:
            await ingest_all(
                on_account=_on_account,
                on_account_done=_on_account_done,
                on_scan_start=_on_scan_start,
                on_files_found=_on_files_found,
                on_file_done=_on_file_done,
            )

    except Exception as exc:
        logger.error("Sync error: %s", exc)

    finally:
        triggered_by = guard.triggered_by  # capture before release clears it
        guard.release()
        finished = datetime.now(timezone.utc)
        for acc in accounts_to_run:
            prev = _sync_state.get(acc, _make_status(acc))
            _sync_state[acc] = SyncStatusOut(
                account_id=acc,
                started_at=started_at,
                finished_at=finished,
                files_ok=prev.files_ok,
                files_error=prev.files_error,
                files_skipped=prev.files_skipped,
                triggered_by=triggered_by,
                running=False,
            )
        _save_state()


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
    if backfill_active():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=backfill_detail())
    if not guard.claim("api"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_conflict_detail())
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
    if backfill_active():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=backfill_detail())
    if not guard.claim("api"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_conflict_detail())
    background_tasks.add_task(_run_ingest, account)
    return SyncTriggerOut(message=f"Ingestion started for {account}", account_id=account)


@router.get("/sync/status", response_model=list[SyncStatusOut])
async def sync_status(
    _: Annotated[str, Depends(require_auth)],
) -> list[SyncStatusOut]:
    """
    Returns per-account ingestion status.

    While a run is in progress, running=True is shown for all accounts
    along with current_account, elapsed_seconds, and accounts_done/total.
    Finished-at times are sourced from the DB files table so cron-triggered
    runs (docker exec ... ingest --all) appear in the history.
    """
    from backend.scheduler.jobs import scheduler

    running = guard.is_running()
    result: list[SyncStatusOut] = []

    elapsed: int | None = None
    if running and guard.started_at:
        elapsed = int((datetime.now(timezone.utc) - guard.started_at).total_seconds())

    next_run: str | None = None
    try:
        job = scheduler.get_job("nightly_ingest")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
    except Exception:
        pass

    # Refresh DB-backed last-sync times (cached 30s) so cron runs appear
    try:
        await _refresh_db_last_syncs()
    except Exception:
        pass

    # Read external backfill container state
    backfill = _read_backfill_status()
    backfill_current = (backfill.get("current") or "").upper()
    backfill_queue = [a.upper() for a in (backfill.get("queue") or [])]
    backfill_active = bool(backfill_current)
    backfill_files_total: int | None = backfill.get("files_total")
    backfill_accounts_done: int | None = backfill.get("accounts_done")
    backfill_accounts_total: int | None = backfill.get("accounts_total")

    for acc in ACCOUNT_SCHEMA_MAP:
        prev = _sync_state.get(acc, _make_status(acc))

        # Pick the most recent finished_at between in-memory state and DB
        db_finished = _db_last_sync.get(acc)
        mem_finished = prev.finished_at
        best_finished: datetime | None
        if db_finished and mem_finished:
            best_finished = max(db_finished, mem_finished)
        else:
            best_finished = db_finished or mem_finished

        # Fall back to DB-derived counts when in-memory state is absent (backfill container)
        db_ok, db_err = _db_file_counts.get(acc, (0, 0))
        files_ok = prev.files_ok if prev.files_ok or not db_ok else db_ok
        files_error = prev.files_error if prev.files_error or not db_err else db_err

        is_backfill_current = backfill_active and acc == backfill_current
        is_backfill_queued = backfill_active and acc in backfill_queue

        if running:
            # API-triggered or scheduler sync in progress
            result.append(SyncStatusOut(
                account_id=acc,
                started_at=guard.started_at,
                finished_at=best_finished,
                files_ok=files_ok,
                files_error=files_error,
                files_skipped=prev.files_skipped,
                running=True,
                current_account=guard.current_account,
                triggered_by=guard.triggered_by,
                elapsed_seconds=elapsed,
                accounts_done=guard.accounts_done,
                accounts_total=guard.accounts_total,
                next_run=next_run,
                phase=guard.phase or None,
                files_done=guard.files_done if guard.files_total > 0 else None,
                files_total=guard.files_total if guard.files_total > 0 else None,
                backfill_queued=is_backfill_queued,
            ))
        elif is_backfill_current:
            # Backfill container is actively processing this account
            result.append(SyncStatusOut(
                account_id=acc,
                started_at=None,
                finished_at=best_finished,
                files_ok=files_ok,
                files_error=files_error,
                files_skipped=0,
                running=True,
                triggered_by="backfill",
                current_account=acc,
                next_run=next_run,
                phase="backfill",
                files_done=db_ok or None,
                files_total=backfill_files_total,
                backfill_queue=backfill_queue,
                backfill_accounts_done=backfill_accounts_done,
                backfill_accounts_total=backfill_accounts_total,
            ))
        else:
            data = prev.model_dump()
            data["finished_at"] = best_finished
            data["next_run"] = next_run
            data["files_ok"] = files_ok
            data["files_error"] = files_error
            data["backfill_queued"] = is_backfill_queued
            if (db_ok or db_err) and not data.get("triggered_by"):
                data["triggered_by"] = "backfill"
            result.append(SyncStatusOut(**data))

    return result
