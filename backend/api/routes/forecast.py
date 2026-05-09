"""
Forecast routes.

POST /forecast/generate                     — run forecast engine for one account + month
GET  /forecast/export                       — download forecast as Excel by dispatching point
GET  /forecast/compare                      — year-over-year comparison for ONE pod + date range
GET  /forecast/compare-dp                   — year-over-year comparison aggregated by DP (all / N pods)
GET  /forecast/compare-dp/export            — download compare-dp result as Excel
GET  /forecast/{account_id}/{mese_anno}     — fetch generated forecast periods (catch-all, must be last)
"""

from __future__ import annotations

import io
from datetime import date
from typing import Annotated

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from openpyxl.styles import Alignment, Font, PatternFill

from backend.api.auth import require_auth
from backend.api.schemas import (
    CompareOut,
    ForecastGenerateIn,
    ForecastGenerateOut,
    ForecastPeriodOut,
)
from backend.db.session import get_session
from backend.db.upsert import upsert_forecast_periods
from backend.forecast.engine import (
    compare_dispatching_points,
    compare_partial_month,
    generate_forecast,
    get_forecast_by_dp,
)
from backend.ingestion.ingest import schema_for
from sqlalchemy import text

router = APIRouter(prefix="/forecast", tags=["forecast"])

Auth = Annotated[str, Depends(require_auth)]

_HEADER_COLOR = "1A1A2E"


# ── Excel helpers ─────────────────────────────────────────────────────────────

def _header_cell(ws, row: int, col: int, value: str) -> None:
    c = ws.cell(row=row, column=col, value=value)
    c.fill = PatternFill("solid", fgColor=_HEADER_COLOR)
    c.font = Font(color="FFFFFF", bold=True)
    c.alignment = Alignment(horizontal="center")


def _make_forecast_excel(account_id: str, mese_anno: str, data: dict) -> bytes:
    """Build forecast Excel: one row per date, one column per dispatching point."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Forecast"

    dps = data["dispatching_points"]
    headers = ["Date"] + dps + ["Total MWh"]

    for col_idx, h in enumerate(headers, 1):
        _header_cell(ws, 1, col_idx, h)

    for row_idx, row in enumerate(data["daily"], 2):
        ws.cell(row=row_idx, column=1, value=row["date"])
        for j, dp in enumerate(dps, 2):
            ws.cell(row=row_idx, column=j, value=round(row.get(dp, 0.0), 4))
        ws.cell(row=row_idx, column=len(headers), value=round(row.get("total", 0.0), 4))

    tr = len(data["daily"]) + 2
    bold = Font(bold=True)
    ws.cell(row=tr, column=1, value="TOTAL").font = bold
    for j, dp in enumerate(dps, 2):
        ws.cell(row=tr, column=j, value=round(sum(r.get(dp, 0) for r in data["daily"]), 4)).font = bold
    ws.cell(row=tr, column=len(headers), value=round(data["total_mwh"], 4)).font = bold

    ws.column_dimensions["A"].width = 13
    for col_idx in range(2, len(headers) + 1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = 16

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_compare_pod_excel(data: dict) -> bytes:
    """Build single-POD comparison Excel: daily sums, current vs previous year."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Comparison"

    headers = [
        "Date (current year)", "MWh current",
        "Date (previous year)", "MWh previous",
        "Delta MWh", "Change %",
    ]
    for col_idx, h in enumerate(headers, 1):
        _header_cell(ws, 1, col_idx, h)

    # Build daily sums from period data
    def _daily(rows: list[dict]) -> dict[str, float]:
        d: dict[str, float] = {}
        for r in rows:
            if r["ea_mwh"] is not None:
                d[r["date"]] = d.get(r["date"], 0.0) + r["ea_mwh"]
        return d

    curr_daily = _daily(data["current_period"]["data"])
    prev_daily = _daily(data["previous_period"]["data"])

    curr_dates = sorted(curr_daily.keys())
    prev_dates = sorted(prev_daily.keys())

    for row_idx, curr_d in enumerate(curr_dates, 2):
        prev_d = prev_dates[row_idx - 2] if row_idx - 2 < len(prev_dates) else None
        cv = round(curr_daily[curr_d], 4)
        pv = round(prev_daily.get(prev_d, 0.0), 4) if prev_d else 0.0
        delta = round(cv - pv, 4)
        pct = round((delta / pv) * 100, 2) if pv else None

        ws.cell(row=row_idx, column=1, value=curr_d)
        ws.cell(row=row_idx, column=2, value=cv)
        ws.cell(row=row_idx, column=3, value=prev_d or "")
        ws.cell(row=row_idx, column=4, value=pv)
        ws.cell(row=row_idx, column=5, value=delta)
        ws.cell(row=row_idx, column=6, value=pct)

    tr = len(curr_dates) + 2
    bold = Font(bold=True)
    ws.cell(row=tr, column=1, value="TOTAL").font = bold
    ws.cell(row=tr, column=2, value=round(data["current_total_mwh"], 4)).font = bold
    ws.cell(row=tr, column=3, value="").font = bold
    ws.cell(row=tr, column=4, value=round(data["previous_total_mwh"], 4)).font = bold
    delta_tot = round(data["current_total_mwh"] - data["previous_total_mwh"], 4)
    ws.cell(row=tr, column=5, value=delta_tot).font = bold
    pct_tot = round((delta_tot / data["previous_total_mwh"]) * 100, 2) if data["previous_total_mwh"] else None
    ws.cell(row=tr, column=6, value=pct_tot).font = bold

    widths = [20, 14, 20, 14, 14, 12]
    for col_idx, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_compare_dp_excel(data: dict) -> bytes:
    """Build compare Excel: current vs previous year, one column group per DP."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Comparison"

    dps = data["dispatching_points"]
    headers = ["Date (Current)"]
    for dp in dps:
        headers += [f"{dp} Curr", f"{dp} Prev", f"{dp} Δ"]
    headers += ["Total Curr", "Total Prev", "Total Δ"]

    for col_idx, h in enumerate(headers, 1):
        _header_cell(ws, 1, col_idx, h)

    curr_by_date = {r["date"]: r for r in data["current_daily"]}
    prev_by_date = {r["date"]: r for r in data["previous_daily"]}
    curr_dates = sorted(curr_by_date.keys())
    prev_dates = sorted(prev_by_date.keys())

    for row_idx, curr_d in enumerate(curr_dates, 2):
        curr = curr_by_date[curr_d]
        prev_d = prev_dates[row_idx - 2] if row_idx - 2 < len(prev_dates) else None
        prev = prev_by_date.get(prev_d, {}) if prev_d else {}

        ws.cell(row=row_idx, column=1, value=curr_d)
        col = 2
        for dp in dps:
            cv = round(curr.get(dp, 0.0), 4)
            pv = round(prev.get(dp, 0.0), 4)
            ws.cell(row=row_idx, column=col, value=cv); col += 1
            ws.cell(row=row_idx, column=col, value=pv); col += 1
            ws.cell(row=row_idx, column=col, value=round(cv - pv, 4)); col += 1
        ct = round(curr.get("total", 0.0), 4)
        pt = round(prev.get("total", 0.0), 4)
        ws.cell(row=row_idx, column=col, value=ct); col += 1
        ws.cell(row=row_idx, column=col, value=pt); col += 1
        ws.cell(row=row_idx, column=col, value=round(ct - pt, 4))

    tr = len(curr_dates) + 2
    bold = Font(bold=True)
    ws.cell(row=tr, column=1, value="TOTAL").font = bold
    col = 2
    for dp in dps:
        cv = round(sum(r.get(dp, 0) for r in data["current_daily"]), 4)
        pv = round(sum(r.get(dp, 0) for r in data["previous_daily"]), 4)
        ws.cell(row=tr, column=col, value=cv).font = bold; col += 1
        ws.cell(row=tr, column=col, value=pv).font = bold; col += 1
        ws.cell(row=tr, column=col, value=round(cv - pv, 4)).font = bold; col += 1
    ct_tot = round(data["current_total_mwh"], 4)
    pt_tot = round(data["previous_total_mwh"], 4)
    ws.cell(row=tr, column=col, value=ct_tot).font = bold; col += 1
    ws.cell(row=tr, column=col, value=pt_tot).font = bold; col += 1
    ws.cell(row=tr, column=col, value=round(ct_tot - pt_tot, 4)).font = bold

    ws.column_dimensions["A"].width = 15
    for col_idx in range(2, len(headers) + 1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = 14

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Routes — fixed paths first (before catch-all) ───────────────────────────

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
    "/export",
    summary="Download forecast as Excel grouped by dispatching point",
)
async def export_forecast(
    account_id: str,
    mese_anno: str,
    _: Auth,
) -> StreamingResponse:
    """Download forecast_periods as Excel, aggregated by dispatching point (one row per date)."""
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        data = await get_forecast_by_dp(session, account_id, mese_anno)

    if not data["dispatching_points"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No forecast data for {account_id} / {mese_anno}. Run POST /forecast/generate first.",
        )

    xlsx = _make_forecast_excel(account_id, mese_anno, data)
    safe_month = mese_anno.replace("/", "-")
    filename = f"forecast_{account_id.lower()}_{safe_month}.xlsx"

    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get(
    "/compare",
    response_model=CompareOut,
    summary="Year-over-year comparison for a single POD over a date range",
)
async def get_forecast_compare(
    account_id: str,
    pod: str,
    _: Auth,
    from_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., description="End date (YYYY-MM-DD)"),
) -> CompareOut:
    if from_date > to_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="from_date must be <= to_date")
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        result = await compare_partial_month(session, account_id, pod, from_date, to_date)
    return CompareOut(**result)


@router.get(
    "/compare/export",
    summary="Download single-POD comparison as Excel",
)
async def export_compare_pod(
    account_id: str,
    pod: str,
    _: Auth,
    from_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., description="End date (YYYY-MM-DD)"),
) -> StreamingResponse:
    """Download current-year vs previous-year daily comparison for a single POD as Excel."""
    if from_date > to_date:
        raise HTTPException(422, "from_date must be <= to_date")

    schema = schema_for(account_id)
    async with get_session(schema) as session:
        result = await compare_partial_month(session, account_id, pod, from_date, to_date)

    xlsx = _make_compare_pod_excel(result)
    safe_pod = pod.replace("/", "_")
    filename = f"compare_{account_id.lower()}_{safe_pod}_{from_date}_{to_date}.xlsx"

    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get(
    "/compare-dp",
    summary="Year-over-year comparison aggregated by dispatching point",
)
async def get_compare_dp(
    account_id: str,
    _: Auth,
    from_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    anagrafica_mese_anno: str | None = Query(default=None, description="Registry month MM/YYYY for DP mapping"),
    pods: str | None = Query(default=None, description="Comma-separated POD list; omit for all PODs"),
) -> dict:
    """
    Returns daily MWh by dispatching point for the given date range and the same range
    one year earlier.  POD→DP mapping comes from ANAGRAFICA (defaults to the month of from_date).
    """
    if from_date > to_date:
        raise HTTPException(422, "from_date must be <= to_date")

    pod_list = [p.strip() for p in pods.split(",") if p.strip()] if pods else None
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        result = await compare_dispatching_points(
            session, account_id, from_date, to_date, anagrafica_mese_anno, pod_list
        )
    return result


@router.get(
    "/compare-dp/export",
    summary="Download dispatching-point comparison as Excel",
)
async def export_compare_dp(
    account_id: str,
    _: Auth,
    from_date: date = Query(...),
    to_date: date = Query(...),
    anagrafica_mese_anno: str | None = Query(default=None),
    pods: str | None = Query(default=None),
) -> StreamingResponse:
    if from_date > to_date:
        raise HTTPException(422, "from_date must be <= to_date")

    pod_list = [p.strip() for p in pods.split(",") if p.strip()] if pods else None
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        data = await compare_dispatching_points(
            session, account_id, from_date, to_date, anagrafica_mese_anno, pod_list
        )

    if not data["dispatching_points"]:
        raise HTTPException(
            404,
            f"No ANAGRAFICA data found for {account_id} / {anagrafica_mese_anno or f'{from_date.month:02d}/{from_date.year}'}. "
            "Upload an ANAGRAFICA file or specify a valid anagrafica_mese_anno.",
        )

    xlsx = _make_compare_dp_excel(data)
    filename = f"compare_{account_id.lower()}_{from_date}_{to_date}.xlsx"

    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Catch-all — must come last ────────────────────────────────────────────────

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
