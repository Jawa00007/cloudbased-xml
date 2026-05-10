"""
Ingestion concurrency guard tests.

Tests IngestionGuard behavior (synchronous — no async needed) and verifies
that the POST /sync endpoint enforces the guard via HTTP 409.

Run: pytest backend/tests/test_ingestion_lock.py -v
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.ingestion.lock import IngestionGuard


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh() -> IngestionGuard:
    """Return a brand-new guard instance, isolated from the module singleton."""
    return IngestionGuard()


# ── Unit tests (no HTTP, no DB) ───────────────────────────────────────────────

def test_claim_when_free_returns_true():
    g = _fresh()
    assert g.claim("api") is True


def test_claim_sets_triggered_by_and_started_at():
    g = _fresh()
    g.claim("scheduler")
    assert g.triggered_by == "scheduler"
    assert g.started_at is not None
    assert g.current_account is None


def test_is_running_true_after_claim():
    g = _fresh()
    g.claim("api")
    assert g.is_running() is True


def test_claim_when_running_returns_false():
    g = _fresh()
    g.claim("api")
    assert g.claim("scheduler") is False


def test_double_claim_does_not_overwrite_first_caller():
    g = _fresh()
    g.claim("api")
    g.claim("scheduler")  # rejected — should not overwrite
    assert g.triggered_by == "api"


def test_release_clears_all_fields():
    g = _fresh()
    g.claim("api")
    g.current_account = "BAT"
    g.release()
    assert g.is_running() is False
    assert g.triggered_by is None
    assert g.started_at is None
    assert g.current_account is None


def test_current_account_settable_after_claim():
    g = _fresh()
    g.claim("api")
    g.current_account = "CH4"
    assert g.current_account == "CH4"
    g.release()


def test_can_claim_again_after_release():
    g = _fresh()
    g.claim("api")
    g.release()
    assert g.claim("scheduler") is True


# ── HTTP tests — use the module-level singleton ───────────────────────────────

@asynccontextmanager
async def _mock_session(*_args, **_kwargs) -> AsyncIterator[AsyncMock]:
    mock = AsyncMock()
    mock.execute.return_value = MagicMock(fetchall=lambda: [], scalar=lambda: 0)
    yield mock


@pytest.fixture(scope="module")
def client():
    import backend.db.session as _s
    _s.get_session = _mock_session
    _s.get_public_session = _mock_session

    from backend.api.auth import set_admin_credentials
    from backend.core.config import settings
    set_admin_credentials("testadmin", hashlib.sha256(b"testpass").hexdigest())

    from backend.api.main import app
    from backend.db.session import get_public_session
    app.dependency_overrides[get_public_session] = lambda: _mock_session()

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def api_key():
    from backend.core.config import settings
    return settings.API_KEY


def test_sync_returns_409_when_guard_held(client, api_key):
    """POST /sync must return 409 when the ingestion guard is already claimed."""
    from backend.ingestion.lock import guard
    try:
        guard.claim("test")
        resp = client.post("/api/sync", headers={"X-API-Key": api_key})
        assert resp.status_code == 409, (
            f"Expected 409 Conflict when guard is held, got {resp.status_code}"
        )
        assert "already running" in resp.json()["detail"].lower()
    finally:
        if guard.is_running() and guard.triggered_by == "test":
            guard.release()


def test_sync_accepted_when_guard_free(client, api_key):
    """POST /sync must be accepted (not 409) when no ingestion is running."""
    from backend.ingestion.lock import guard
    # Ensure guard is free before the test
    if guard.is_running():
        guard.release()
    try:
        resp = client.post("/api/sync", headers={"X-API-Key": api_key})
        assert resp.status_code != 409, (
            f"Expected acceptance (not 409) when guard is free, got {resp.status_code}"
        )
    finally:
        # Background task may have claimed it; release to not contaminate other tests
        if guard.is_running():
            guard.release()
