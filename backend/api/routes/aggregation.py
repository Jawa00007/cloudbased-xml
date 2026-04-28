"""
Aggregation endpoints:

  GET /aggregation/daily    — daily kWh totals for a POD+month
  GET /aggregation/monthly  — monthly kWh totals per POD for a year
  GET /aggregation/summary  — all PODs monthly totals for a given month
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.aggregation.engine import (
    get_daily_totals,
    get_monthly_total,
    get_monthly_totals_all_pods,
    get_yearly_totals,
)
from backend.api.auth import require_auth
from backend.api.schemas import DailyTotalOut, MonthlyTotalOut
from backend.db.session import get_session
from backend.ingestion.ingest import schema_for

router = APIRouter(prefix="/aggregation", tags=["aggregation"])


@router.get("/daily", response_model=list[DailyTotalOut])
async def daily_totals(
    account: Annotated[str, Query()],
    pod: Annotated[str, Query()],
    mese_anno: Annotated[str, Query(description="MM/YYYY")],
    _: Annotated[str, Depends(require_auth)],
) -> list[DailyTotalOut]:
    schema = schema_for(account)
    async with get_session(schema) as session:
        rows = await get_daily_totals(session, account, pod, mese_anno)
    return [DailyTotalOut(
        pod=r.pod, data_misura=r.data_misura,
        daily_kwh=r.daily_kwh, daily_kvarh=r.daily_kvarh,
        source=r.source, periods=r.periods,
    ) for r in rows]


@router.get("/monthly", response_model=list[MonthlyTotalOut])
async def monthly_totals(
    account: Annotated[str, Query()],
    pod: Annotated[str, Query()],
    year: Annotated[int, Query(ge=2000, le=2100)],
    _: Annotated[str, Depends(require_auth)],
) -> list[MonthlyTotalOut]:
    schema = schema_for(account)
    async with get_session(schema) as session:
        rows = await get_yearly_totals(session, account, pod, year)
    return [MonthlyTotalOut(
        pod=r.pod, mese_anno=r.mese_anno,
        monthly_kwh=r.monthly_kwh, monthly_kvarh=r.monthly_kvarh,
        days=r.days, source=r.source,
    ) for r in rows]


@router.get("/summary", response_model=list[MonthlyTotalOut])
async def monthly_summary(
    account: Annotated[str, Query()],
    mese_anno: Annotated[str, Query(description="MM/YYYY")],
    _: Annotated[str, Depends(require_auth)],
) -> list[MonthlyTotalOut]:
    """Monthly totals for ALL PODs in an account for a given month."""
    schema = schema_for(account)
    async with get_session(schema) as session:
        rows = await get_monthly_totals_all_pods(session, account, mese_anno)
    return [MonthlyTotalOut(
        pod=r.pod, mese_anno=r.mese_anno,
        monthly_kwh=r.monthly_kwh, monthly_kvarh=r.monthly_kvarh,
        days=r.days, source=r.source,
    ) for r in rows]
