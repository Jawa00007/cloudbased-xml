"""
API smoke tests — route registration and basic status code contract.

Verifies that every major registered route:
  - Is reachable (no 404 from missing route registration)
  - Does not return 500 for any request (broken imports or unhandled startup errors)
  - Enforces auth on protected endpoints (401 without credentials)
  - Returns 422 (not 500) when required query parameters are missing

No real database needed — DB session is mocked.

Run: pytest backend/tests/test_api_smoke.py -v
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


# ── DB mock ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _mock_session(*_args, **_kwargs) -> AsyncIterator[AsyncMock]:
    mock = AsyncMock()
    mock.execute.return_value = MagicMock(
        fetchall=lambda: [],
        scalar=lambda: 0,
        fetchone=lambda: None,
    )
    yield mock


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    import backend.db.session as _s
    _s.get_session = _mock_session
    _s.get_public_session = _mock_session

    from backend.api.main import app
    from backend.db.session import get_public_session
    app.dependency_overrides[get_public_session] = lambda: _mock_session()

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def app_instance():
    from backend.api.main import app
    return app


@pytest.fixture(scope="module")
def api_key():
    from backend.core.config import settings
    return settings.API_KEY


# ── Endpoint tables ───────────────────────────────────────────────────────────

PUBLIC_ENDPOINTS = [
    ("GET", "/api/health"),
]

PROTECTED_NO_PARAMS = [
    ("GET",  "/api/accounts"),
    ("GET",  "/api/sync/status"),
    ("GET",  "/api/admin/loss-config"),
    ("GET",  "/api/admin/dispatching-config"),
]

# These require query params — calling without them must return 422, not 500
MISSING_PARAMS_422 = [
    ("GET",  "/api/pods"),
    ("GET",  "/api/measurements"),
    ("GET",  "/api/aggregation/daily"),
    ("GET",  "/api/aggregation/monthly"),
    ("GET",  "/api/monitoring/missing"),
    ("GET",  "/api/files"),
    ("GET",  "/api/totals"),
]

POST_NO_AUTH_401 = [
    ("POST", "/api/sync"),
    ("POST", "/api/forecast/generate"),
]


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", PUBLIC_ENDPOINTS)
def test_public_endpoints_return_200(client, method, path):
    resp = client.request(method, path)
    assert resp.status_code == 200, (
        f"{method} {path} should be publicly accessible (200), got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", PROTECTED_NO_PARAMS)
def test_protected_endpoints_return_401_without_auth(client, method, path):
    resp = client.request(method, path)
    assert resp.status_code == 401, (
        f"{method} {path} should return 401 without credentials, got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", MISSING_PARAMS_422)
def test_missing_required_params_return_422_not_500(client, api_key, method, path):
    # Auth passes; missing required query params should trigger validation (422) not crash (500)
    resp = client.request(method, path, headers={"X-API-Key": api_key})
    assert resp.status_code == 422, (
        f"{method} {path} with no params should return 422 (not 500), got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", POST_NO_AUTH_401)
def test_post_endpoints_return_401_without_auth(client, method, path):
    resp = client.request(method, path)
    assert resp.status_code == 401, (
        f"{method} {path} should return 401 without auth, got {resp.status_code}"
    )


@pytest.mark.parametrize("method,path", (
    PUBLIC_ENDPOINTS
    + PROTECTED_NO_PARAMS
    + MISSING_PARAMS_422
    + POST_NO_AUTH_401
))
def test_no_endpoint_returns_500(client, method, path):
    resp = client.request(method, path)
    assert resp.status_code != 500, (
        f"{method} {path} returned 500 — indicates unhandled error or broken import"
    )


def test_metrics_endpoint_registered(client):
    """Prometheus /api/metrics must be registered and reachable (nginx blocks external access)."""
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert b"http_requests_total" in resp.content


def test_minimum_route_count(app_instance):
    """Guard against accidental router de-registration — we expect at least 35 routes."""
    route_count = len(app_instance.routes)
    assert route_count >= 35, (
        f"Expected at least 35 registered routes, found {route_count}. "
        "A router may have been accidentally removed."
    )
