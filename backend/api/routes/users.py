"""
Admin-only user management endpoints.

GET    /admin/users          — list all users
POST   /admin/users          — create a user
PUT    /admin/users/{id}     — update a user (password optional)
DELETE /admin/users/{id}     — deactivate a user (soft delete)
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from backend.api.auth import Auth, require_admin
from backend.db.session import get_public_session
from backend.models.user import User

router = APIRouter(prefix="/admin/users", tags=["users"])

AdminAuth = Annotated[Auth, Depends(require_admin)]


# ── Schemas ────────────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
    allowed_accounts: list[str] | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    allowed_accounts: list[str] | None = None  # None = all accounts

    @field_validator("username")
    @classmethod
    def username_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("username must not be empty")
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("password must be at least 6 characters")
        return v


class UserUpdate(BaseModel):
    password: str | None = None          # None = no change
    is_admin: bool | None = None
    allowed_accounts: list[str] | None = None
    is_active: bool | None = None


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[UserOut])
async def list_users(auth: AdminAuth) -> list[UserOut]:
    async with get_public_session() as s:
        rows = (await s.execute(select(User).order_by(User.id))).scalars().all()
    return [UserOut.model_validate(u) for u in rows]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, auth: AdminAuth) -> UserOut:
    pw_hash = hashlib.sha256(body.password.encode()).hexdigest()
    async with get_public_session() as s:
        existing = (await s.execute(
            select(User).where(User.username == body.username)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail=f"Username '{body.username}' already exists.")
        user = User(
            username=body.username,
            password_hash=pw_hash,
            is_admin=body.is_admin,
            allowed_accounts=body.allowed_accounts,
            is_active=True,
        )
        s.add(user)
        await s.flush()
        await s.refresh(user)
        return UserOut.model_validate(user)


@router.put("/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserUpdate, auth: AdminAuth) -> UserOut:
    async with get_public_session() as s:
        user = (await s.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found.")

        if body.password is not None:
            if len(body.password) < 6:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    detail="Password must be at least 6 characters.")
            user.password_hash = hashlib.sha256(body.password.encode()).hexdigest()
        if body.is_admin is not None:
            user.is_admin = body.is_admin
        if body.allowed_accounts is not None or "allowed_accounts" in body.model_fields_set:
            user.allowed_accounts = body.allowed_accounts
        if body.is_active is not None:
            user.is_active = body.is_active

        await s.flush()
        await s.refresh(user)
        return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, auth: AdminAuth) -> None:
    if auth.username != "api-key":  # prevent self-delete for JWT users
        async with get_public_session() as s:
            user = (await s.execute(
                select(User).where(User.id == user_id)
            )).scalar_one_or_none()
            if not user:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found.")
            if user.username == auth.username:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    detail="Cannot deactivate your own account.")
            user.is_active = False
