"""
Sync endpoints:

  POST /sync           — trigger ingestion for all accounts
  POST /sync/{account} — trigger ingestion for one account
  GET  /sync/status    — last sync run results per account
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

logger = logging.getLogger(__name__)
router = APIRouter(tags=["sync"])

# In-memory sync state — one entry per account
_sync_state: dict[str, SyncStatusOut] = {}


def _make_status(account_id: str, running: bool = False) -> SyncStatusOut:
    return SyncStatusOut(
        account_id=account_id,
        started_at=None,
        finished_at=None,
        files_ok=0,
        files_error=0,
        files_skipped=0,
        running=running,
    )


async def _run_ingest(account_id: str | None) -> None:
    """Background task — runs ingestion and updates _sync_state."""
    accounts = [account_id] if account_id else list(ACCOUNT_SCHEMA_MAP.keys())

    for acc in accounts:
        _sync_state[acc] = SyncStatusOut(
            account_id=acc,
            started_at=datetime.now(timezone.utc),
            finished_at=None,
            files_ok=0,
            files_error=0,
            files_skipped=0,
            running=True,
        )

    try:
        if account_id:
            await ingest_account(account_id)
        else:
            await ingest_all()
    except Exception as exc:
        logger.error("Sync error: %s", exc)
    finally:
        finished = datetime.now(timezone.utc)
        for acc in accounts:
            state = _sync_state.get(acc, _make_status(acc))
            _sync_state[acc] = SyncStatusOut(
                account_id=acc,
                started_at=state.started_at,
                finished_at=finished,
                files_ok=state.files_ok,
                files_error=state.files_error,
                files_skipped=state.files_skipped,
                running=False,
            )


@router.post("/sync", response_model=SyncTriggerOut)
async def trigger_sync_all(
    background_tasks: BackgroundTasks,
    _: Annotated[str, Depends(require_auth)],
) -> SyncTriggerOut:
    background_tasks.add_task(_run_ingest, None)
    return SyncTriggerOut(message="Ingestion started for all accounts", account_id=None)


@router.post("/sync/{account}", response_model=SyncTriggerOut)
async def trigger_sync_account(
    account: str,
    background_tasks: BackgroundTasks,
    _: Annotated[str, Depends(require_auth)],
) -> SyncTriggerOut:
    if account not in ACCOUNT_SCHEMA_MAP:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Unknown account: {account!r}")
    background_tasks.add_task(_run_ingest, account)
    return SyncTriggerOut(message=f"Ingestion started for {account}", account_id=account)


@router.get("/sync/status", response_model=list[SyncStatusOut])
async def sync_status(
    _: Annotated[str, Depends(require_auth)],
) -> list[SyncStatusOut]:
    if not _sync_state:
        return [_make_status(acc) for acc in ACCOUNT_SCHEMA_MAP]
    return list(_sync_state.values())
