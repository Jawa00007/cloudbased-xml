"""
Forecast routes.

POST /forecast/generate                     — start forecast job (returns 202 + job_id immediately)
GET  /forecast/status/{job_id}              — poll job status
GET  /forecast/export                       — download forecast as Excel by dispatching point
GET  /forecast/export/pods                  — download forecast as Excel per-POD wide format (POD|Filename|DAY|P1…P96)
GET  /forecast/export/measurements          — download actual measurements (source data) in same wide format
GET  /forecast/compare                      — year-over-year comparison for ONE pod + date range
GET  /forecast/compare/export               — download single-POD comparison as Excel
GET  /forecast/compare-dp                   — year-over-year comparison aggregated by DP (all / N pods)
GET  /forecast/compare-dp/export            — download compare-dp result as Excel
GET  /forecast/{account_id}/{mese_anno}     — fetch generated forecast periods (catch-all, must be last)
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import uuid
from datetime import date
from typing import Annotated, Any

logger = logging.getLogger(__name__)

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from openpyxl.styles import Alignment, Font, PatternFill

from backend.api.auth import Auth, check_account_access, require_auth
from backend.api.schemas import (
    CompareOut,
    ForecastGenerateIn,
    ForecastGenerateOut,
    ForecastPeriodOut,
)
from backend.db.session import get_session
from backend.db.upsert import delete_forecast_month, insert_forecast_chunk, upsert_forecast_periods
from backend.forecast.engine import (
    compare_dispatching_points,
    compare_partial_month,
    generate_forecast,
    generate_forecast_streaming,
    get_forecast_by_dp,
    get_forecast_ea_matrix,
    get_forecast_periods_by_dp,
)
from backend.ingestion.ingest import schema_for
from sqlalchemy import text

router = APIRouter(prefix="/forecast", tags=["forecast"])

_Auth = Annotated[Auth, Depends(require_auth)]

# In-memory job store — fine for single-process uvicorn
_jobs: dict[str, dict[str, Any]] = {}

_HEADER_COLOR = "1A1A2E"


# ── Excel helpers ─────────────────────────────────────────────────────────────

def _header_cell(ws, row: int, col: int, value: str) -> None:
    c = ws.cell(row=row, column=col, value=value)
    c.fill = PatternFill("solid", fgColor=_HEADER_COLOR)
    c.font = Font(color="FFFFFF", bold=True)
    c.alignment = Alignment(horizontal="center")


# Fixed Italian bidding-zone order (north → south + islands).
# Always present in output regardless of which zones have forecast data.
_ITALIAN_ZONES = ["NORD", "CNOR", "CSUD", "SUD", "SARD", "SICI", "CALA"]


def _make_forecast_excel(account_id: str, mese_anno: str, data: dict) -> bytes:
    """
    Build forecast Excel in SII Ea-row format with a fixed Italian-zone template.

    Structure (repeats for each of the 7 zones):
      [header row: zona | Ea | 1 | 2 | … | 96]
      [zona  |  1  | …96 period values…]   ← day 1
      [zona  |  2  | …96 period values…]   ← day 2
      …
      [zona  | 31  | …96 period values…]   ← day 31 (always, even for 28/30-day months)
      [blank row]

    Zones with no forecast data have empty period cells so the file can be
    copy-pasted directly into a master workbook without structural changes.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Forecast"

    # Build lookup: {(zona, day_of_month): [96 float values]}
    lookup: dict[tuple, list] = {}
    for row in data["rows"]:
        lookup[(row["zona"], row["day"])] = row["values"]

    current_row = 1

    for z_idx, zona in enumerate(_ITALIAN_ZONES):
        # ── Section header ────────────────────────────────────────────────────
        _header_cell(ws, current_row, 1, "zona")
        _header_cell(ws, current_row, 2, "Ea")
        for p in range(1, 97):
            _header_cell(ws, current_row, 2 + p, p)
        current_row += 1

        # ── 31 data rows (fixed length regardless of actual month days) ───────
        for day in range(1, 32):
            ws.cell(row=current_row, column=1, value=zona)
            ws.cell(row=current_row, column=2, value=day)
            values = lookup.get((zona, day))
            if values:
                for p_idx, val in enumerate(values, 3):
                    ws.cell(row=current_row, column=p_idx, value=val)
            # else: leave period cells empty (zone has no data for this day)
            current_row += 1

        # ── Blank separator row between zones ─────────────────────────────────
        if z_idx < len(_ITALIAN_ZONES) - 1:
            current_row += 1  # leave empty row

    # Column widths
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 6
    for col_idx in range(3, 99):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = 10

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


def _make_forecast_pods_excel(rows: list[dict]) -> bytes:
    """
    Build per-POD wide-format Excel using write_only mode (fast for large datasets).

    Columns: POD | Source | Source File | DAY | 1 | 2 | … | 96
    One row per (pod, forecast_date). Period values are ea_mwh (MWh).
    Source File is the XML filename when source_type is E or S; blank for filled/estimated.
    """
    # Build pivot: {(pod, date_str): {periodo: value, "src": source_type, "src_file": filename}}
    pivot: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["pod"], str(r["forecast_date"]))
        if key not in pivot:
            pivot[key] = {
                "src": r.get("source_type") or "",
                "src_file": r.get("source_file") or "",
            }
        val = r["ea_mwh"]
        if val is not None:
            pivot[key][r["periodo"]] = float(val)

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Forecast PODs")

    ws.append(["POD", "Source", "Source File", "DAY"] + [str(p) for p in range(1, 97)])

    for (pod, date_str) in sorted(pivot.keys()):
        entry = pivot[(pod, date_str)]
        day = int(date_str.split("-")[2]) if date_str and "-" in date_str else ""
        ws.append([pod, entry["src"], entry["src_file"], day] + [entry.get(p) for p in range(1, 97)])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_measurements_wide_excel(rows: list[dict]) -> bytes:
    """
    Build actual-measurements wide Excel using write_only mode.

    Columns: POD | TipoDato | DAY | 1 | 2 | … | 96
    One row per (pod, data_misura). Values are ea_kwh (kWh) from measurements table.
    Preferred tipo_dato=E; S rows are included only when no E row exists for that POD+date.
    """
    # De-duplicate: keep E over S for same (pod, date)
    pivot: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["pod"], str(r["data_misura"]))
        existing = pivot.get(key)
        # E takes priority over S
        if existing is None or (r["tipo_dato"] == "E" and existing.get("tipo_dato") != "E"):
            pivot[key] = {"tipo_dato": r["tipo_dato"]}
        elif existing.get("tipo_dato") == "E" and r["tipo_dato"] != "E":
            continue  # skip S when E already present
        val = r["ea_kwh"]
        if val is not None:
            pivot[key][r["periodo"]] = float(val)
            pivot[key]["tipo_dato"] = r["tipo_dato"] if pivot[key].get("tipo_dato") != "E" else "E"

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Measurements")
    ws.append(["POD", "TipoDato", "DAY"] + [str(p) for p in range(1, 97)])

    for (pod, date_str) in sorted(pivot.keys()):
        entry = pivot[(pod, date_str)]
        day = int(date_str.split("-")[2]) if date_str and "-" in date_str else ""
        ws.append([pod, entry.get("tipo_dato", ""), day] + [entry.get(p) for p in range(1, 97)])

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

async def _run_forecast_job(job_id: str, account_id: str, mese_anno: str, ana_month: str) -> None:
    schema = schema_for(account_id)
    t0 = time.monotonic()
    try:
        # Delete in its own session so the commit is immediate and isolated.
        async with get_session(schema) as del_session:
            await delete_forecast_month(del_session, account_id, mese_anno)

        t1 = time.monotonic()
        n = 0
        got_any = False
        # Read session stays open for the full generator (no mid-stream commits
        # so the connection is never released back to the pool mid-iteration,
        # keeping search_path = schema stable for all source-data queries).
        async with get_session(schema) as read_session:
            async for chunk in generate_forecast_streaming(
                read_session, account_id, mese_anno, ana_month
            ):
                got_any = True
                # Fresh write session per chunk — each new get_session() re-runs
                # SET search_path so inserts always target the right schema,
                # not whatever public.* the pool might hand back after a commit.
                async with get_session(schema) as write_session:
                    n += await insert_forecast_chunk(write_session, chunk, account_id)

            t2 = time.monotonic()
            logger.info("TIMING generate+stream_upsert: %.1fs, rows=%d", t2 - t1, n)

            if not got_any:
                _jobs[job_id] = {
                    "status": "error",
                    "result": None,
                    "error": (
                        f"No ANAGRAFICA data found for {account_id} / {mese_anno}. "
                        "Upload an ANAGRAFICA file first via POST /admin/anagrafica/upload"
                    ),
                }
                return

        logger.info("TIMING total job: %.1fs", time.monotonic() - t0)
        _jobs[job_id] = {
            "status": "done",
            "result": {
                "message": "Forecast generated",
                "account_id": account_id,
                "mese_anno": mese_anno,
                "periods_written": n,
            },
            "error": None,
        }
    except Exception as exc:
        logger.exception("Forecast job %s failed", job_id)
        _jobs[job_id] = {"status": "error", "result": None, "error": str(exc)}


def start_forecast_job(
    account_id: str,
    mese_anno: str,
    ana_mese_anno: str | None = None,
) -> str:
    """Create a forecast background job and return its job_id immediately."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "result": None, "error": None}
    asyncio.create_task(_run_forecast_job(job_id, account_id, mese_anno, ana_mese_anno or mese_anno))
    return job_id


@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start forecast generation job (returns immediately — poll /status/{job_id})",
)
async def run_generate_forecast(
    body: ForecastGenerateIn,
    auth: _Auth,
) -> dict:
    """
    Submits the forecast job and returns a job_id immediately.
    The actual engine + DB writes run in the background.
    Poll GET /forecast/status/{job_id} every few seconds until status is 'done' or 'error'.
    """
    check_account_access(body.account_id, auth)
    job_id = start_forecast_job(body.account_id, body.mese_anno, body.anagrafica_mese_anno)
    return {"job_id": job_id, "status": "running"}


@router.get(
    "/status/{job_id}",
    summary="Poll forecast generation job status",
)
async def get_forecast_job_status(job_id: str, auth: _Auth) -> dict:
    """Returns {status, result, error}. status: 'running' | 'done' | 'error'."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get(
    "/export",
    summary="Download forecast as Excel grouped by dispatching point",
)
async def export_forecast(
    account_id: str,
    mese_anno: str,
    auth: _Auth,
) -> StreamingResponse:
    """Download forecast_periods as Excel: one row per (date, period), one column per zone."""
    check_account_access(account_id, auth)
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        data = await get_forecast_ea_matrix(session, account_id, mese_anno)

    if not data["rows"]:
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
    auth: _Auth,
    from_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., description="End date (YYYY-MM-DD)"),
) -> CompareOut:
    check_account_access(account_id, auth)
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
    auth: _Auth,
    from_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., description="End date (YYYY-MM-DD)"),
) -> StreamingResponse:
    """Download current-year vs previous-year daily comparison for a single POD as Excel."""
    check_account_access(account_id, auth)
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
    auth: _Auth,
    from_date: date = Query(..., description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., description="End date (YYYY-MM-DD)"),
    anagrafica_mese_anno: str | None = Query(default=None, description="Registry month MM/YYYY for DP mapping"),
    pods: str | None = Query(default=None, description="Comma-separated POD list; omit for all PODs"),
) -> dict:
    """
    Returns daily MWh by dispatching point for the given date range and the same range
    one year earlier.  POD→DP mapping comes from ANAGRAFICA (defaults to the month of from_date).
    """
    check_account_access(account_id, auth)
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
    auth: _Auth,
    from_date: date = Query(...),
    to_date: date = Query(...),
    anagrafica_mese_anno: str | None = Query(default=None),
    pods: str | None = Query(default=None),
) -> StreamingResponse:
    check_account_access(account_id, auth)
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


@router.get(
    "/export/pods",
    summary="Download forecast as Excel in per-POD wide format (one row per POD+date, 96 period columns)",
)
async def export_forecast_pods(
    account_id: str,
    mese_anno: str,
    auth: _Auth,
) -> StreamingResponse:
    """
    Downloads forecast_periods as Excel wide format:
    POD | Filename | DAY | 1 | 2 | … | 96
    One row per (POD, date). Values are ea_mwh (MWh).
    Filename column contains the source XML file name when available.
    """
    check_account_access(account_id, auth)
    schema = schema_for(account_id)
    t0 = time.monotonic()
    async with get_session(schema) as session:
        result = await session.execute(
            text("""
                SELECT
                    fp.pod,
                    fp.forecast_date,
                    fp.periodo,
                    ROUND(fp.ea_kwh / 1000.0, 6) AS ea_mwh,
                    fp.source_type,
                    COALESCE(me.source_file, ms.source_file) AS source_file
                FROM forecast_periods fp
                LEFT JOIN measurements me
                    ON me.account_id = fp.account_id
                    AND me.pod = fp.pod
                    AND me.data_misura = fp.source_date
                    AND me.periodo = fp.periodo
                    AND me.tipo_dato = 'E'
                LEFT JOIN measurements_secondary ms
                    ON ms.account_id = fp.account_id
                    AND ms.pod = fp.pod
                    AND ms.data_misura = fp.source_date
                    AND ms.periodo = fp.periodo
                    AND ms.tipo_dato = 'S'
                    AND me.id IS NULL
                WHERE fp.account_id = :acct AND fp.mese_anno = :ma
                ORDER BY fp.pod, fp.forecast_date, fp.periodo
            """),
            {"acct": account_id, "ma": mese_anno},
        )
        rows = [dict(r._mapping) for r in result.fetchall()]
    logger.info("export/pods query: %.1fs, %d rows", time.monotonic() - t0, len(rows))

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No forecast data for {account_id} / {mese_anno}. Run POST /forecast/generate first.",
        )

    t1 = time.monotonic()
    xlsx = _make_forecast_pods_excel(rows)
    logger.info("export/pods excel build: %.1fs, %.1fkB", time.monotonic() - t1, len(xlsx) / 1024)
    safe_month = mese_anno.replace("/", "-")
    filename = f"forecast_pods_{account_id.lower()}_{safe_month}.xlsx"

    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get(
    "/measurements/months",
    summary="List months that have measurement data for an account",
)
async def get_measurement_months(account_id: str, auth: _Auth) -> list[str]:
    """Returns distinct mese_anno values from the measurements table, newest first."""
    check_account_access(account_id, auth)
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        result = await session.execute(
            text("""
                SELECT DISTINCT mese_anno
                FROM measurements
                WHERE account_id = :acct AND tipo_dato IN ('E', 'S')
                ORDER BY mese_anno DESC
            """),
            {"acct": account_id},
        )
        return [r[0] for r in result.fetchall()]


@router.get(
    "/export/measurements",
    summary="Download actual measurements (source data) in per-POD wide format",
)
async def export_measurements_wide(
    account_id: str,
    mese_anno: str,
    auth: _Auth,
) -> StreamingResponse:
    """
    Downloads actual measured ea_kwh values from the measurements table in wide format:
    POD | TipoDato | DAY | 1 | 2 | … | 96

    This is the source data the forecast engine uses (tipo_dato E preferred, S as fallback).
    To see what April 2026 forecast is based on, request mese_anno=04/2025.
    """
    check_account_access(account_id, auth)
    schema = schema_for(account_id)
    t0 = time.monotonic()
    async with get_session(schema) as session:
        result = await session.execute(
            text("""
                SELECT pod, data_misura, periodo, ea_kwh, tipo_dato
                FROM measurements
                WHERE account_id = :acct AND mese_anno = :ma
                  AND tipo_dato IN ('E', 'S')
                ORDER BY pod, data_misura, tipo_dato DESC, periodo
            """),
            {"acct": account_id, "ma": mese_anno},
        )
        rows = [dict(r._mapping) for r in result.fetchall()]
    logger.info("export/measurements query: %.1fs, %d rows", time.monotonic() - t0, len(rows))

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No measurement data for {account_id} / {mese_anno}.",
        )

    t1 = time.monotonic()
    xlsx = _make_measurements_wide_excel(rows)
    logger.info("export/measurements excel: %.1fs, %.1fkB", time.monotonic() - t1, len(xlsx) / 1024)

    safe_month = mese_anno.replace("/", "-")
    filename = f"measurements_{account_id.lower()}_{safe_month}.xlsx"
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
    auth: _Auth,
    pod: str | None = Query(default=None, description="Filter to a specific POD"),
    limit: int = Query(default=2976, ge=1, le=10000, description="Max rows (default 2976 = 1 POD × 31 days × 96)"),
    offset: int = Query(default=0, ge=0, description="Row offset for pagination"),
) -> list[ForecastPeriodOut]:
    check_account_access(account_id, auth)
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        if pod:
            rows = await session.execute(text("""
                SELECT pod, mese_anno, punto_dispacciamento, forecast_date, source_date,
                       periodo,
                       ROUND(ea_kwh / 1000.0, 6) AS ea_mwh,
                       ROUND(ea_kwh_with_loss / 1000.0, 6) AS ea_mwh_with_loss,
                       loss_pct, source_type
                FROM forecast_periods
                WHERE account_id = :acct AND mese_anno = :ma AND pod = :pod
                ORDER BY forecast_date, periodo
                LIMIT :lim OFFSET :off
            """), {"acct": account_id, "ma": mese_anno, "pod": pod, "lim": limit, "off": offset})
        else:
            rows = await session.execute(text("""
                SELECT pod, mese_anno, punto_dispacciamento, forecast_date, source_date,
                       periodo,
                       ROUND(ea_kwh / 1000.0, 6) AS ea_mwh,
                       ROUND(ea_kwh_with_loss / 1000.0, 6) AS ea_mwh_with_loss,
                       loss_pct, source_type
                FROM forecast_periods
                WHERE account_id = :acct AND mese_anno = :ma
                ORDER BY pod, forecast_date, periodo
                LIMIT :lim OFFSET :off
            """), {"acct": account_id, "ma": mese_anno, "lim": limit, "off": offset})

        result = rows.fetchall()

    return [ForecastPeriodOut.model_validate(dict(r._mapping)) for r in result]
