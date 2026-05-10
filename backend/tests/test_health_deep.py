"""
Deep health endpoint tests.

Verifies that GET /api/health:
  - Always returns HTTP 200 (even when DB is down)
  - Returns the correct JSON structure with database, scheduler, and ingestion sections
  - Sets status="degraded" in the body when DB is unreachable
  - Reflects the live state of the ingestion guard

Run: pytest backend/tests/test_health_deep.py -v
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Mocked session (normal — returns empty results) ───────────────────────────

@asynccontextmanager
async def _ok_session(*_args, **_kwargs) -> AsyncIterator[AsyncMock]:
    mock = AsyncMock()
    mock.execute.return_value = MagicMock(fetchall=lambda: [], scalar=lambda: 0)
    yield mock


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """TestClient with DB session mocked to succeed."""
    import backend.db.session as _session_module
    _session_module.get_session = _ok_session
    _session_module.get_public_session = _ok_session

    from backend.api.main import app
    from backend.db.session import get_public_session
    app.dependency_overrides[get_public_session] = lambda: _ok_session()

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health_returns_200_always(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_health_has_required_structure(client):
    body = client.get("/api/health").json()
    assert "status" in body
    assert "environment" in body
    assert "database" in body
    assert "scheduler" in body
    assert "ingestion" in body


def test_health_database_status_ok(client):
    body = client.get("/api/health").json()
    db = body["database"]
    assert db["status"] == "ok"
    # latency_ms may be None if the mock runs too fast, but it should be a number or None
    assert db["latency_ms"] is None or isinstance(db["latency_ms"], (int, float))


def test_health_db_error_returns_degraded_not_500(client):
    """When DB raises, health returns 200 with status=degraded — never 500."""
    @asynccontextmanager
    async def _broken_session(*_a, **_kw):
        raise Exception("DB offline")
        yield  # unreachable — needed for asynccontextmanager protocol

    # Patch the name as imported into main.py's namespace (not the source module)
    with patch("backend.api.main.get_public_session", _broken_session):
        resp = client.get("/api/health")

    assert resp.status_code == 200, "Health check must never return 500"
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"]["status"] == "error"


def test_health_never_returns_500_on_db_error(client):
    """Redundant but explicit: 500 on /api/health would break uptime monitors."""
    @asynccontextmanager
    async def _crash(*_a, **_kw):
        raise RuntimeError("connection refused")
        yield

    with patch("backend.api.main.get_public_session", _crash):
        resp = client.get("/api/health")

    assert resp.status_code != 500


def test_health_environment_field_present(client):
    body = client.get("/api/health").json()
    assert isinstance(body["environment"], str)
    assert body["environment"] != ""


def test_health_scheduler_key_present(client):
    body = client.get("/api/health").json()
    sched = body["scheduler"]
    assert "running" in sched
    assert "next_run" in sched
    assert isinstance(sched["running"], bool)


def test_health_ingestion_reflects_guard_state(client):
    """When the ingestion guard is claimed, health reports ingestion.running=True."""
    from backend.ingestion.lock import guard
    try:
        claimed = guard.claim("test")
        if claimed:
            body = client.get("/api/health").json()
            assert body["ingestion"]["running"] is True
            assert body["ingestion"]["triggered_by"] == "test"
    finally:
        if guard.is_running() and guard.triggered_by == "test":
            guard.release()
