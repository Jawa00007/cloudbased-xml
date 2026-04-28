"""GET /accounts — list all active accounts."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.api.auth import require_auth
from backend.api.schemas import AccountOut
from backend.db.session import get_session

router = APIRouter(tags=["accounts"])


@router.get("/db-test", tags=["debug"])
async def db_test() -> JSONResponse:
    """Temporary: test DB connectivity and return raw error if any."""
    try:
        async with get_session("public") as session:
            result = await session.execute(text("SELECT 1"))
            r1 = result.scalar()
            result2 = await session.execute(text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='accounts'"
            ))
            has_table = result2.scalar()
            return JSONResponse({"db": "ok", "ping": r1, "accounts_table_exists": has_table})
    except Exception as e:
        return JSONResponse({"db": "error", "detail": str(e)}, status_code=200)


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
