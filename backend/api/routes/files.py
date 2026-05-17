"""GET /files — file ingestion log with optional status filter."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from backend.api.auth import Auth, check_account_access, require_auth
from backend.api.schemas import FileLogOut
from backend.db.session import get_session
from backend.ingestion.ingest import schema_for

router = APIRouter(tags=["files"])


@router.get("/files", response_model=list[FileLogOut])
async def list_files(
    account: Annotated[str, Query()],
    status: Annotated[str | None, Query(description="ok | error | skipped")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    auth: Annotated[Auth, Depends(require_auth)] = None,
) -> list[FileLogOut]:
    check_account_access(account, auth)
    schema = schema_for(account)
    async with get_session(schema) as session:
        if status:
            result = await session.execute(text("""
                SELECT file_id, file_name, account_id, cod_flusso, mese_anno,
                       file_timestamp, progressivo, sm_status, processed_at,
                       status, error_message
                FROM files
                WHERE status = :status
                ORDER BY processed_at DESC
                LIMIT :limit OFFSET :offset
            """), {"status": status, "limit": limit, "offset": offset})
        else:
            result = await session.execute(text("""
                SELECT file_id, file_name, account_id, cod_flusso, mese_anno,
                       file_timestamp, progressivo, sm_status, processed_at,
                       status, error_message
                FROM files
                ORDER BY processed_at DESC
                LIMIT :limit OFFSET :offset
            """), {"limit": limit, "offset": offset})

        rows = result.fetchall()

    return [FileLogOut(
        file_id=r[0], file_name=r[1], account_id=r[2], cod_flusso=r[3],
        mese_anno=r[4], file_timestamp=r[5], progressivo=r[6], sm_status=r[7],
        processed_at=r[8], status=r[9], error_message=r[10],
    ) for r in rows]
