"""
Authentication — two schemes supported:

1. API Key (X-API-Key header) — for machine-to-machine / scheduler calls
2. JWT Bearer token — for browser/dashboard clients

POST /auth/token  →  {username, password} → JWT access token
All other protected endpoints accept either scheme.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
from jose import JWTError, jwt
from pydantic import BaseModel

from backend.core.config import settings

# ── Scheme definitions ─────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# In-memory "user" store — single admin user for now.
# In production, replace with a DB lookup or OAuth provider.
_USERS: dict[str, str] = {}  # populated from env in main.py


def set_admin_credentials(username: str, hashed_password: str) -> None:
    _USERS[username] = hashed_password


# ── Token ──────────────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int   # seconds


class TokenData(BaseModel):
    username: str


def create_access_token(username: str) -> tuple[str, int]:
    """Return (encoded_jwt, expire_seconds)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {"sub": username, "exp": expire}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, settings.JWT_EXPIRE_MINUTES * 60


def verify_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid token")
        return TokenData(username=username)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Could not validate token")


# ── Dependency — accepts API key OR JWT ───────────────────────────────────────

async def require_auth(
    api_key: Annotated[str | None, Security(_api_key_header)],
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> str:
    """
    FastAPI dependency. Returns the authenticated identity (username or "api-key").
    Raises 401 if neither scheme provides valid credentials.
    """
    # 1. API key check
    if api_key and api_key == settings.API_KEY:
        return "api-key"

    # 2. JWT check
    if bearer:
        token_data = verify_token(bearer.credentials)
        return token_data.username

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide X-API-Key header or Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ── Login endpoint helper ──────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


def authenticate_user(username: str, password: str) -> bool:
    """Verify username/password against the in-memory store."""
    import hashlib
    stored = _USERS.get(username)
    if not stored:
        return False
    # Compare SHA-256 hash
    hashed = hashlib.sha256(password.encode()).hexdigest()
    return hashed == stored
