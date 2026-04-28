"""GET /accounts — list all active accounts."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text

from backend.api.auth import require_auth
from backend.api.schemas import AccountOut
from backend.db.session import get_session

router = APIRouter(tags=["accounts"])



@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    _: Annotated[str, Depends(require_auth)],
) -> list[AccountOut]:
    async with get_session("public") as session:
        result = await session.execute(
            text("SELECT account_id, schema_name, display_name, active FROM public.accounts ORDER BY account_id")
        )
        return [
            AccountOut(
                account_id=row[0],
                schema_name=row[1],
                display_name=row[2],
                active=row[3],
            )
            for row in result
        ]
