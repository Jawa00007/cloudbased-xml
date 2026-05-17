"""POST /auth/token — issue JWT from username+password."""

from fastapi import APIRouter, HTTPException, status

from backend.api.auth import (
    LoginRequest,
    Token,
    authenticate_user,
    create_access_token,
)
from backend.api.schemas import TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    auth = await authenticate_user(body.username, body.password)
    if not auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    token, expires_in = create_access_token(
        username=auth.username,
        is_admin=auth.is_admin,
        allowed_accounts=auth.allowed_accounts,
    )
    return TokenResponse(access_token=token, expires_in=expires_in)
