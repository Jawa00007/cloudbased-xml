"""
Monitoring endpoints:
  GET /monitoring/missing      — POD+days with < 96 periods for a month
  GET /monitoring/corrections  — correction file counts by POD+month
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.aggregation.engine import get_corrections_summary, get_missing_periods
from backend.api.auth import require_auth
from backend.api.schemas import CorrectionSummaryOut, MissingPeriodOut
from backend.db.session import get_session
from backend.ingestion.ingest import schema_for

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/missing", response_model=list[MissingPeriodOut])
async def missing_readings(
    account: Annotated[str, Query()],
    mese_anno: Annotated[str, Query(description="MM/YYYY")],
    _: Annotated[str, Depends(require_auth)] = None,
) -> list[MissingPeriodOut]:
    schema = schema_for(account)
    async with get_session(schema) as session:
        rows = await get_missing_periods(session, account, mese_anno)
    return [
        MissingPeriodOut(
            pod=r.pod,
            data_misura=r.data_misura,
            periods_found=r.periods_found,
            missing=96 - r.periods_found,
            source=r.source,
        )
        for r in rows
    ]


@router.get("/corrections", response_model=list[CorrectionSummaryOut])
async def corrections_summary(
    account: Annotated[str, Query()],
    mese_anno: Annotated[str | None, Query(description="MM/YYYY")] = None,
    _: Annotated[str, Depends(require_auth)] = None,
) -> list[CorrectionSummaryOut]:
    schema = schema_for(account)
    async with get_session(schema) as session:
        rows = await get_corrections_summary(session, account, mese_anno)
    return [
        CorrectionSummaryOut(
            pod=r.pod, mese_anno=r.mese_anno,
            cod_flusso=r.cod_flusso, count=r.count,
        )
        for r in rows
    ]
