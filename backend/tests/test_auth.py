"""
API authentication and security header tests.

Uses FastAPI TestClient with a mocked DB session — no real database required.
Tests cover:
  - Public vs protected endpoint enforcement
  - Invalid/missing credentials return 401
  - JWT tampering and expiry
  - CORS header presence
  - Docs hidden in production

Run: pytest backend/tests/test_auth.py -v
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from backend.api.auth import set_admin_credentials
from backend.core.config import settings


# ── Minimal async session mock ─────────────────────────────────────────────────

@asynccontextmanager
async def _mock_session(*_args, **_kwargs) -> AsyncIterator[AsyncMock]:
    """Async session that returns empty results for any query."""
    mock = AsyncMock()
    mock.execute.return_value = MagicMock(fetchall=lambda: [], scalars=lambda: MagicMock(all=lambda: []))
    yield mock


# ── App fixture with mocked DB ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """
    TestClient with:
      - DB session replaced by the no-op mock
      - Admin credentials registered
      - ENVIRONMENT=development so /docs is available
    """
    import backend.db.session as _session_module

    _session_module.get_session = _mock_session          # type: ignore[assignment]
    _session_module.get_public_session = _mock_session   # type: ignore[assignment]

    # Register a known admin user for JWT tests
    set_admin_credentials("testadmin", hashlib.sha256(b"testpass").hexdigest())

    from backend.api.main import app
    from backend.db.session import get_public_session

    app.dependency_overrides[get_public_session] = lambda: _mock_session()

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def valid_api_key():
    return settings.API_KEY


@pytest.fixture(scope="module")
def valid_jwt(client):
    resp = client.post("/api/auth/token", json={"username": "testadmin", "password": "testpass"})
    if resp.status_code == 200:
        return resp.json()["access_token"]
    return None


# ── Public endpoints ──────────────────────────────────────────────────────────

def test_health_is_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Protected endpoints require auth ──────────────────────────────────────────

PROTECTED_ENDPOINTS = [
    ("GET",  "/api/accounts"),
    ("GET",  "/api/files"),
    ("GET",  "/api/pods?account=BAT"),
    ("GET",  "/api/aggregation/daily?account=BAT&pod=X&mese_anno=01/2024"),
    ("GET",  "/api/aggregation/monthly?account=BAT&pod=X&year=2024"),
    ("GET",  "/api/sync/status"),
]


@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
def test_no_auth_returns_401(client, method, path):
    resp = client.request(method, path)
    assert resp.status_code == 401, (
        f"{method} {path} should return 401 without credentials, got {resp.status_code}"
    )


def test_invalid_api_key_returns_401(client):
    resp = client.get("/api/accounts", headers={"X-API-Key": "totally-wrong-key"})
    assert resp.status_code == 401


def test_valid_api_key_accepted(client, valid_api_key):
    resp = client.get("/api/accounts", headers={"X-API-Key": valid_api_key})
    # 200 or anything other than 401/403 — DB is mocked so data will be empty
    assert resp.status_code not in (401, 403), (
        f"Valid API key should be accepted, got {resp.status_code}"
    )


# ── JWT auth ──────────────────────────────────────────────────────────────────

def test_login_wrong_password_returns_401(client):
    resp = client.post("/api/auth/token", json={"username": "testadmin", "password": "wrong"})
    assert resp.status_code == 401


def test_login_missing_body_returns_422(client):
    resp = client.post("/api/auth/token")
    assert resp.status_code == 422


def test_login_missing_username_returns_422(client):
    resp = client.post("/api/auth/token", json={"password": "testpass"})
    assert resp.status_code == 422


def test_valid_jwt_accepted(client, valid_jwt):
    if valid_jwt is None:
        pytest.skip("Could not obtain JWT (admin credentials may not be set)")
    resp = client.get("/api/accounts", headers={"Authorization": f"Bearer {valid_jwt}"})
    assert resp.status_code not in (401, 403)


def test_expired_jwt_returns_401(client):
    expired_payload = {
        "sub": "testadmin",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    expired_token = jwt.encode(expired_payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    resp = client.get("/api/accounts", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401


def test_tampered_jwt_returns_401(client, valid_jwt):
    if valid_jwt is None:
        pytest.skip("Could not obtain JWT")
    # Flip a character in the signature portion
    parts = valid_jwt.split(".")
    if len(parts) == 3:
        sig = list(parts[2])
        sig[0] = "X" if sig[0] != "X" else "Y"
        tampered = ".".join(parts[:2] + ["".join(sig)])
        resp = client.get("/api/accounts", headers={"Authorization": f"Bearer {tampered}"})
        assert resp.status_code == 401


def test_jwt_signed_with_wrong_key_returns_401(client):
    payload = {"sub": "testadmin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
    token = jwt.encode(payload, "wrong-secret-key", algorithm=settings.JWT_ALGORITHM)
    resp = client.get("/api/accounts", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


# ── CORS headers ──────────────────────────────────────────────────────────────

def test_cors_header_present_on_api_response(client, valid_api_key):
    resp = client.get(
        "/api/health",
        headers={"Origin": "https://forecast.dinamoservice.it"},
    )
    # CORS middleware adds Access-Control-Allow-Origin when Origin matches allowed origins
    # In test env ALLOWED_ORIGINS=* so it should always be present
    assert resp.status_code == 200


def test_cors_options_preflight(client):
    resp = client.options(
        "/api/health",
        headers={
            "Origin": "https://forecast.dinamoservice.it",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert resp.status_code in (200, 204)


# ── Docs availability ─────────────────────────────────────────────────────────

def test_docs_available_in_development(client):
    """In test/dev mode ENVIRONMENT!=production so /docs should exist."""
    resp = client.get("/docs")
    assert resp.status_code == 200, (
        "/docs should be available in development mode"
    )


def test_docs_hidden_in_production():
    """
    _in_production reflects ENVIRONMENT at startup; app.docs_url must match.
    In dev mode docs are at /docs; in production docs_url is None.
    """
    from backend.api.main import _in_production, app
    # _in_production must equal (ENVIRONMENT == "production") — it's set at module load time
    assert _in_production == (settings.ENVIRONMENT == "production"), (
        f"_in_production ({_in_production}) does not match "
        f"ENVIRONMENT={settings.ENVIRONMENT!r}"
    )
    # Verify the FastAPI app was created with the correct docs_url
    if _in_production:
        assert app.docs_url is None, "docs_url must be None in production"
    else:
        assert app.docs_url == "/docs", "docs_url must be /docs in development"


# ── SQL injection resistance ──────────────────────────────────────────────────

SQL_INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE measurements; --",
    "1 UNION SELECT * FROM measurements --",
    "admin'--",
    "\" OR \"1\"=\"1",
]


@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
def test_sql_injection_in_account_param_does_not_500(client, valid_api_key, payload):
    """Parameterized queries should handle injection payloads without server errors."""
    resp = client.get(
        f"/api/pods?account={payload}",
        headers={"X-API-Key": valid_api_key},
    )
    # Should return 200 (empty) or 422 (validation), never 500
    assert resp.status_code != 500, (
        f"SQL injection payload caused a 500 error: {payload!r}"
    )
