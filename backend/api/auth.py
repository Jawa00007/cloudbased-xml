"""
Authentication — two schemes supported:

1. API Key (X-API-Key header) — for machine-to-machine / scheduler calls
2. JWT Bearer token — for browser/dashboard clients

POST /auth/token  →  {username, password} → JWT access token
All other protected endpoints accept either scheme.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select

from backend.core.config import settings

# ── Scheme definitions ─────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Env-based admin hash — populated from env in main.py (backward compat)
_env_admin_hash: str = ""


def set_admin_credentials(username: str, hashed_password: str) -> None:
    """Called at startup to register the env-based admin fallback."""
    global _env_admin_hash
    _env_admin_hash = hashed_password


# ── Auth identity returned by require_auth ─────────────────────────────────────

@dataclass
class Auth:
    username: str
    is_admin: bool = False
    allowed_accounts: list[str] | None = field(default=None)
    # None = unrestricted (all accounts); list = restricted to named accounts only


# ── Account access check ───────────────────────────────────────────────────────

def check_account_access(account_id: str, auth: Auth) -> None:
    """Raise 403 if the authenticated user is not permitted to access this account."""
    if auth.allowed_accounts is None:
        return  # unrestricted
    if account_id.upper() not in [a.upper() for a in auth.allowed_accounts]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access to account '{account_id}' is not permitted for this user.",
        )


# ── Token ──────────────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int   # seconds


class TokenData(BaseModel):
    username: str
    is_admin: bool = False
    allowed_accounts: list[str] | None = None


def create_access_token(username: str, is_admin: bool, allowed_accounts: list[str] | None) -> tuple[str, int]:
    """Return (encoded_jwt, expire_seconds)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": username,
        "exp": expire,
        "is_admin": is_admin,
        "allowed_accounts": allowed_accounts,
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, settings.JWT_EXPIRE_MINUTES * 60


def verify_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid token")
        return TokenData(
            username=username,
            is_admin=bool(payload.get("is_admin", False)),
            allowed_accounts=payload.get("allowed_accounts"),
        )
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Could not validate token")


# ── Dependency — accepts API key OR JWT ───────────────────────────────────────

async def require_auth(
    api_key: Annotated[str | None, Security(_api_key_header)],
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> Auth:
    """
    FastAPI dependency. Returns an Auth object with the authenticated identity.
    API-key callers are treated as unrestricted admins (scheduler/backfill use).
    Raises 401 if neither scheme provides valid credentials.
    """
    # 1. API key — unrestricted, treated as admin for data access
    if api_key and api_key == settings.API_KEY:
        return Auth(username="api-key", is_admin=True, allowed_accounts=None)

    # 2. JWT Bearer
    if bearer:
        td = verify_token(bearer.credentials)
        return Auth(
            username=td.username,
            is_admin=td.is_admin,
            allowed_accounts=td.allowed_accounts,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide X-API-Key header or Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_admin(auth: Annotated[Auth, Depends(require_auth)]) -> Auth:
    """Dependency that additionally requires is_admin=True."""
    if not auth.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Admin access required.")
    return auth


# Type alias for cleaner route signatures
Auth = Auth  # re-export


# ── Login endpoint helper ──────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


async def authenticate_user(username: str, password: str) -> Auth | None:
    """
    Verify username/password.
    1. Check public.users table in DB.
    2. Fall back to env-based admin (backward compat, always available).
    Returns Auth on success, None on failure.
    """
    pw_hash = hashlib.sha256(password.encode()).hexdigest()

    # 1. DB lookup
    try:
        from backend.db.session import get_public_session
        from backend.models.user import User
        async with get_public_session() as s:
            result = await s.execute(
                select(User).where(User.username == username, User.is_active.is_(True))
            )
            user = result.scalar_one_or_none()
        if user and user.password_hash == pw_hash:
            return Auth(
                username=user.username,
                is_admin=user.is_admin,
                allowed_accounts=user.allowed_accounts,
            )
    except Exception:
        # DB unavailable — fall through to env admin
        pass

    # 2. Env-based admin fallback
    if (
        username == settings.ADMIN_USERNAME
        and _env_admin_hash
        and pw_hash == _env_admin_hash
    ):
        return Auth(username=username, is_admin=True, allowed_accounts=None)

    return None
