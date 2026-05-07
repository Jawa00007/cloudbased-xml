"""
Forecast routes.

POST /forecast/generate                — run forecast engine for one account + month
GET  /forecast/{account_id}/{mese_anno} — fetch generated forecast periods
GET  /forecast/compare                  — year-over-year comparison for a POD + date range
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.auth import require_auth
from backend.api.schemas import (
    CompareOut,
    ForecastGenerateIn,
    ForecastGenerateOut,
    ForecastPeriodOut,
)
from backend.db.session import get_session
from backend.db.upsert import upsert_forecast_periods
from backend.forecast.engine import compare_partial_month, generate_forecast
from backend.ingestion.ingest import schema_for
from sqlalchemy import text

router = APIRouter(prefix="/forecast", tags=["forecast"])

Auth = Annotated[str, Depends(require_auth)]


@router.post(
    "/generate",
    response_model=ForecastGenerateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Generate forecast for one account and month",
)
async def run_generate_forecast(
    body: ForecastGenerateIn,
    _: Auth,
) -> ForecastGenerateOut:
    """
    Runs the full forecast pipeline:
      1. Load ANAGRAFICA for the forecast month
      2. For each POD: fetch previous-year data, apply missing-data fill
      3. Apply grid-loss adjustment, convert kWh → MWh
      4. Upsert all rows into forecast_periods table
    """
    ana_month = body.anagrafica_mese_anno or body.mese_anno
    schema = schema_for(body.account_id)
    async with get_session(schema) as session:
        rows = await generate_forecast(session, body.account_id, body.mese_anno, ana_month)
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"No ANAGRAFICA data found for {body.account_id} / {body.mese_anno}. "
                    "Upload an ANAGRAFICA file first via POST /admin/anagrafica/upload"
                ),
            )
        n = await upsert_forecast_periods(session, rows, body.account_id)

    return ForecastGenerateOut(
        message="Forecast generated",
        account_id=body.account_id,
        mese_anno=body.mese_anno,
        periods_written=n,
    )


@router.get(
    "/compare",
    response_model=CompareOut,
    summary="Year-over-year comparison for a POD over a date range",
)
async def get_forecast_compare(
    account_id: str,
    pod: str,
    _: Auth,
    from_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., description="End date (YYYY-MM-DD)"),
) -> CompareOut:
    """
    Returns current-year vs previous-year measurement data for the given date range.
    Prefers TipoDato=E; falls back to measurements_secondary.
    """
    if from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from_date must be <= to_date",
        )

    schema = schema_for(account_id)
    async with get_session(schema) as session:
        result = await compare_partial_month(session, account_id, pod, from_date, to_date)
    return CompareOut(**result)


@router.get(
    "/{account_id}/{mese_anno:path}",
    response_model=list[ForecastPeriodOut],
    summary="Fetch generated forecast periods for an account and month",
)
async def get_forecast(
    account_id: str,
    mese_anno: str,
    _: Auth,
    pod: str | None = Query(default=None, description="Filter to a specific POD"),
) -> list[ForecastPeriodOut]:
    """
    Returns all generated forecast periods.
    Optionally filtered to a single POD.
    Results ordered by pod, forecast_date, periodo.
    """
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        if pod:
            rows = await session.execute(text("""
                SELECT pod, mese_anno, punto_dispacciamento, forecast_date, source_date,
                       periodo, ea_mwh, ea_mwh_with_loss, loss_pct, source_type
                FROM forecast_periods
                WHERE account_id = :acct AND mese_anno = :ma AND pod = :pod
                ORDER BY forecast_date, periodo
            """), {"acct": account_id, "ma": mese_anno, "pod": pod})
        else:
            rows = await session.execute(text("""
                SELECT pod, mese_anno, punto_dispacciamento, forecast_date, source_date,
                       periodo, ea_mwh, ea_mwh_with_loss, loss_pct, source_type
                FROM forecast_periods
                WHERE account_id = :acct AND mese_anno = :ma
                ORDER BY pod, forecast_date, periodo
            """), {"acct": account_id, "ma": mese_anno})

        result = rows.fetchall()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No forecast data for {account_id} / {mese_anno}. Run POST /forecast/generate first.",
        )

    return [ForecastPeriodOut.model_validate(dict(r._mapping)) for r in result]
