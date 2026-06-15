"""
Forecast engine — generates the monthly forecast dataset for one account.

Pipeline per POD:
  1. Load ANAGRAFICA for the forecast month (filter col = "O")
  2. For each POD, determine the source month (same month, previous year)
  3. Fetch all available 96-period data for the source month (E preferred, S fallback)
  4. Apply missing-data fill:
       - Missing day  → carry forward last available day  (source_type = "filled")
       - No data at all → CONSUMO_TOT / 365 × dispatching weights (source_type = "estimated")
       - Pad to 31 days → repeat last day (source_type = "padded")
  5. Apply grid-loss adjustment (result stored in kWh for full precision)
  6. Upsert into forecast_periods table
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from dataclasses import dataclass
from calendar import monthrange
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.forecast.loss_calculator import (
    DEFAULT_RULES,
    LossRule,
    apply_loss,
    calculate_loss_pct,
)
from backend.forecast.missing_data import FilledPeriod, build_forecast_month

log = logging.getLogger(__name__)


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class ForecastRow:
    account_id: str
    pod: str
    mese_anno: str
    punto_dispacciamento: str | None
    forecast_date: date
    source_date: date | None
    periodo: int
    ea_kwh: float | None
    ea_kwh_with_loss: float | None
    loss_pct: float
    source_type: str


# ── Private helpers ────────────────────────────────────────────────────────────

async def _load_loss_rules(session: AsyncSession, account_id: str) -> list[LossRule]:
    """Load loss_config rows for account (or global). Falls back to DEFAULT_RULES."""
    rows = await session.execute(text("""
        SELECT condition_type, condition_value, loss_pct, priority
        FROM public.loss_config
        WHERE account_id = :acct OR account_id IS NULL
        ORDER BY priority ASC
    """), {"acct": account_id})
    rules = [
        LossRule(
            condition_type=r[0],
            condition_value=r[1],
            loss_pct=float(r[2]),
            priority=r[3],
        )
        for r in rows.fetchall()
    ]
    return rules if rules else DEFAULT_RULES


async def _load_pod_metadata_batch(
    session: AsyncSession,
    account_id: str,
    pods: list[str],
) -> dict[str, dict]:
    """Load pod_metadata tensione for all PODs in one query (latest record per pod).
    codice_tariffa is not in pod_metadata — it comes from anagrafica instead."""
    if not pods:
        return {}
    rows = await session.execute(text("""
        SELECT DISTINCT ON (pod) pod, tensione
        FROM pod_metadata
        WHERE account_id = :acct AND pod = ANY(:pods)
        ORDER BY pod, valid_from DESC NULLS LAST
    """), {"acct": account_id, "pods": pods})
    return {r[0]: {"tensione": r[1], "codice_tariffa": None} for r in rows.fetchall()}


async def _load_dispatching_weights_batch(
    session: AsyncSession,
    account_id: str,
    puntos: list[str],
) -> dict[str, list[float] | None]:
    """
    Load dispatching weights for all relevant puntos.
    Two-step: account-specific first, then global (account_id IS NULL) for any
    puntos not covered by account-specific rows.  Global weights therefore work
    as a shared fallback — enter them once in "All accounts" mode and all
    accounts will use them automatically unless they have account-specific overrides.
    Returns {punto_dispacciamento: [96 floats summing to 1.0] or None}.
    """
    if not puntos:
        return {}

    def _collect(rows_iter) -> dict[str, dict[int, float]]:
        by_punto: dict[str, dict[int, float]] = {}
        for r in rows_iter:
            pd, periodo, pct = r[0], r[1], float(r[2])
            by_punto.setdefault(pd, {})[periodo] = pct
        return by_punto

    # Step 1 — account-specific weights
    acct_rows = await session.execute(text("""
        SELECT punto_dispacciamento, periodo, pct
        FROM public.dispatching_config
        WHERE account_id = :acct AND punto_dispacciamento = ANY(:puntos)
        ORDER BY punto_dispacciamento, periodo
    """), {"acct": account_id, "puntos": puntos})
    by_punto = _collect(acct_rows.fetchall())

    # Step 2 — global fallback for any puntos not covered above
    missing = [p for p in puntos if p not in by_punto]
    if missing:
        global_rows = await session.execute(text("""
            SELECT punto_dispacciamento, periodo, pct
            FROM public.dispatching_config
            WHERE account_id IS NULL AND punto_dispacciamento = ANY(:puntos)
            ORDER BY punto_dispacciamento, periodo
        """), {"puntos": missing})
        by_punto.update(_collect(global_rows.fetchall()))

    return {
        pd: ([data.get(i, 0.0) for i in range(1, 97)] if len(data) >= 96 else None)
        for pd, data in by_punto.items()
    }


async def _load_source_daily_batch(
    session: AsyncSession,
    account_id: str,
    pods: list[str],
    source_mese_anno: str,
) -> dict[str, dict[date, list[tuple[int, float | None, str]]]]:
    """
    Load source-month measurement data for ALL pods in 2 queries instead of 2×N.
    Returns {pod: {date: [(periodo, ea_kwh, source_type), ...]}}
    E preferred over S for any given (pod, date).
    """
    mm, yyyy = source_mese_anno.split("/")
    y, m = int(yyyy), int(mm)
    start = date(y, m, 1)
    end = date(y, m, monthrange(y, m)[1])

    result: dict[str, dict[date, list[tuple[int, float | None, str]]]] = {p: {} for p in pods}
    e_dates: dict[str, set[date]] = {p: set() for p in pods}

    e_rows = await session.execute(text("""
        SELECT pod, data_misura, periodo, ea_kwh
        FROM measurements
        WHERE account_id = :acct AND pod = ANY(:pods)
          AND data_misura >= :start AND data_misura <= :end AND tipo_dato = 'E'
        ORDER BY pod, data_misura, periodo
    """), {"acct": account_id, "pods": pods, "start": start, "end": end})
    for r in e_rows.fetchall():
        pod, d, periodo, ea = r[0], r[1], r[2], r[3]
        e_dates[pod].add(d)
        result[pod].setdefault(d, []).append((periodo, float(ea) if ea is not None else None, "E"))

    s_rows = await session.execute(text("""
        SELECT pod, data_misura, periodo, ea_kwh
        FROM measurements_secondary
        WHERE account_id = :acct AND pod = ANY(:pods)
          AND data_misura >= :start AND data_misura <= :end
        ORDER BY pod, data_misura, periodo
    """), {"acct": account_id, "pods": pods, "start": start, "end": end})
    for r in s_rows.fetchall():
        pod, d, periodo, ea = r[0], r[1], r[2], r[3]
        if d not in e_dates[pod]:
            result[pod].setdefault(d, []).append((periodo, float(ea) if ea is not None else None, "S"))

    return result


async def _load_anagrafica_pods(
    session: AsyncSession,
    account_id: str,
    mese_anno: str,
) -> list[dict]:
    """Return included ANAGRAFICA rows for the forecast month."""
    rows = await session.execute(text("""
        SELECT pod, punto_dispacciamento, tensione, codice_tariffa, consumo_tot
        FROM anagrafica
        WHERE account_id = :acct AND mese_anno = :ma AND included = TRUE
        ORDER BY pod
    """), {"acct": account_id, "ma": mese_anno})
    return [
        {
            "pod": r[0],
            "punto_dispacciamento": r[1],
            "tensione": r[2],
            "codice_tariffa": r[3],
            "consumo_tot": float(r[4]) if r[4] is not None else None,
        }
        for r in rows.fetchall()
    ]


def _source_mese_anno(forecast_mese_anno: str) -> str:
    """Return the same month one year earlier: '05/2026' → '05/2025'."""
    mm, yyyy = forecast_mese_anno.split("/")
    return f"{mm}/{int(yyyy) - 1}"


async def _resolve_source_month(
    session: AsyncSession,
    account_id: str,
    target_source: str,
) -> str:
    """
    Return the nearest month that actually has measurement data.

    Tries target_source first. If no rows exist for that month, queries all
    available months (via data_misura date column) and returns the one closest
    in calendar distance to target_source. Falls back to target_source itself
    (CONSUMO_TOT path) only when the measurements table is empty.
    """
    mm, yyyy = target_source.split("/")
    y, m = int(yyyy), int(mm)
    start = date(y, m, 1)
    end = date(y, m, monthrange(y, m)[1])

    row = await session.execute(
        text("""
            SELECT 1 FROM measurements
            WHERE account_id = :acct AND data_misura >= :s AND data_misura <= :e
            UNION ALL
            SELECT 1 FROM measurements_secondary
            WHERE account_id = :acct AND data_misura >= :s AND data_misura <= :e
            LIMIT 1
        """),
        {"acct": account_id, "s": start, "e": end},
    )
    if row.first() is not None:
        return target_source  # data exists — no fallback needed

    # No data for the target month; find the nearest available month across both tables
    available = await session.execute(
        text("""
            SELECT DISTINCT DATE_TRUNC('month', data_misura)::date AS m
            FROM (
                SELECT data_misura FROM measurements WHERE account_id = :acct
                UNION ALL
                SELECT data_misura FROM measurements_secondary WHERE account_id = :acct
            ) combined
            ORDER BY m
        """),
        {"acct": account_id},
    )
    months = [r[0] for r in available.fetchall()]  # list of date(YYYY, MM, 1)
    if not months:
        log.warning(
            "%s: no measurements at all — source month %s will fall back to CONSUMO_TOT",
            account_id, target_source,
        )
        return target_source

    target_date = date(y, m, 1)
    nearest = min(months, key=lambda d: abs((d - target_date).days))
    fallback = f"{nearest.month:02d}/{nearest.year}"
    log.warning(
        "%s: no data for source month %s — using nearest available %s",
        account_id, target_source, fallback,
    )
    return fallback


# ── Main entry point ──────────────────────────────────────────────────────────

async def generate_forecast_streaming(
    session: AsyncSession,
    account_id: str,
    forecast_mese_anno: str,
    anagrafica_mese_anno: str | None = None,
    pods_per_chunk: int = 50,
):
    """
    Async-generator — yields list[ForecastRow] in chunks of `pods_per_chunk` PODs.

    Both the DB data loading AND the output are chunked so peak RAM is bounded
    to ~50 pods at a time regardless of account size (CH4 has 3,449 PODs).
    The big cost was _load_source_daily_batch which fetched ALL pods' measurements
    at once (~500 MB for CH4); now it only fetches 50 pods per iteration.
    """
    ana_month    = anagrafica_mese_anno or forecast_mese_anno
    source_month = await _resolve_source_month(
        session, account_id, _source_mese_anno(forecast_mese_anno)
    )
    loss_rules   = await _load_loss_rules(session, account_id)
    ana_pods     = await _load_anagrafica_pods(session, account_id, ana_month)

    log.info(
        "Forecast(stream) %s target=%s registry=%s source=%s pods=%d",
        account_id, forecast_mese_anno, ana_month, source_month, len(ana_pods),
    )
    if not ana_pods:
        log.warning("No ANAGRAFICA data for %s / %s", account_id, forecast_mese_anno)
        return

    seen_pods: set[str] = set()
    unique_ana: list[dict] = []
    for a in ana_pods:
        if a["pod"] not in seen_pods:
            seen_pods.add(a["pod"])
            unique_ana.append(a)
    if len(unique_ana) < len(ana_pods):
        log.warning("Deduplicated %d duplicate PODs from ANAGRAFICA", len(ana_pods) - len(unique_ana))
    ana_pods = unique_ana

    # Dispatching weights are small (7 zones × 96 periods) — load once upfront
    puntos = list({a["punto_dispacciamento"] for a in ana_pods if a["punto_dispacciamento"]})
    dispatch_map = await _load_dispatching_weights_batch(session, account_id, puntos)

    total_chunks = (len(ana_pods) + pods_per_chunk - 1) // pods_per_chunk

    # Process pods in chunks; load pod_meta and source_daily per chunk only
    # so peak RAM ~ pods_per_chunk × 30 days × 96 periods × ~50 bytes ≈ 7 MB/chunk
    for chunk_start in range(0, len(ana_pods), pods_per_chunk):
        chunk_num = chunk_start // pods_per_chunk + 1
        chunk_anas = ana_pods[chunk_start : chunk_start + pods_per_chunk]
        chunk_pods = [a["pod"] for a in chunk_anas]

        _tc = _time.monotonic()
        pod_meta_map = await _load_pod_metadata_batch(session, account_id, chunk_pods)
        _t1 = _time.monotonic()
        source_daily_map = await _load_source_daily_batch(session, account_id, chunk_pods, source_month)
        _t2 = _time.monotonic()
        log.info(
            "Forecast %s chunk %d/%d: meta=%.2fs source=%.2fs pods=%d",
            account_id, chunk_num, total_chunks, _t1 - _tc, _t2 - _t1, len(chunk_pods),
        )

        rows: list[ForecastRow] = []
        for ana in chunk_anas:
            pod         = ana["pod"]
            punto       = ana["punto_dispacciamento"]
            consumo_tot = ana["consumo_tot"]

            meta           = pod_meta_map.get(pod)
            tensione       = (meta or {}).get("tensione") or ana.get("tensione")
            codice_tariffa = (meta or {}).get("codice_tariffa") or ana.get("codice_tariffa")
            pod_found      = meta is not None

            loss_pct = calculate_loss_pct(tensione, codice_tariffa, pod_found, loss_rules)

            weights: list[float] | None = dispatch_map.get(punto) if punto else None
            if punto and weights is None:
                log.warning(
                    "Forecast %s %s pod=%s: no dispatching weights for punto='%s' — "
                    "falling back to uniform distribution. "
                    "Add weights in Admin > Dispatching Weights using exactly this name.",
                    account_id, forecast_mese_anno, pod, punto,
                )
            source_daily = source_daily_map.get(pod, {})

            filled: list[FilledPeriod] = build_forecast_month(
                forecast_mese_anno=forecast_mese_anno,
                source_daily=source_daily,
                consumo_tot=consumo_tot,
                dispatching_weights=weights,
                source_mese_anno=source_month,
            )

            for fp in filled:
                rows.append(ForecastRow(
                    account_id=account_id,
                    pod=pod,
                    mese_anno=forecast_mese_anno,
                    punto_dispacciamento=punto,
                    forecast_date=fp.forecast_date,
                    source_date=fp.source_date,
                    periodo=fp.periodo,
                    ea_kwh=fp.ea_kwh,
                    ea_kwh_with_loss=apply_loss(fp.ea_kwh, loss_pct),
                    loss_pct=loss_pct,
                    source_type=fp.source_type,
                ))

        yield rows
        # Yield to the event loop between chunks so health checks stay responsive
        await asyncio.sleep(0)


async def generate_forecast(
    session: AsyncSession,
    account_id: str,
    forecast_mese_anno: str,
    anagrafica_mese_anno: str | None = None,
) -> list[ForecastRow]:
    """
    Generate the full forecast for one account + month.

    anagrafica_mese_anno: which registry (ANAGRAFICA) to use for the POD list.
      Defaults to forecast_mese_anno when not provided. Decoupling the two lets
      you, e.g., forecast 04/2026 using the 04/2026 registry but draw historical
      consumption from 04/2025.

    Returns a list of ForecastRow (one per POD × 31 days × 96 periods).
    The caller is responsible for upserting into forecast_periods.

    All supporting data is batch-loaded in a small fixed number of queries
    (regardless of POD count) to avoid per-POD round-trips.
    """
    ana_month    = anagrafica_mese_anno or forecast_mese_anno
    source_month = await _resolve_source_month(
        session, account_id, _source_mese_anno(forecast_mese_anno)
    )
    loss_rules   = await _load_loss_rules(session, account_id)
    ana_pods     = await _load_anagrafica_pods(session, account_id, ana_month)

    log.info(
        "Forecast %s target=%s registry=%s source=%s",
        account_id, forecast_mese_anno, ana_month, source_month,
    )

    if not ana_pods:
        log.warning("No ANAGRAFICA data for %s / %s — nothing to forecast", account_id, forecast_mese_anno)
        return []

    # Deduplicate by pod — anagrafica should be unique per pod but guard against
    # duplicate uploads that slip past the unique constraint (e.g. same pod,
    # different source_file). Keep first occurrence.
    seen_pods: set[str] = set()
    unique_ana: list[dict] = []
    for a in ana_pods:
        if a["pod"] not in seen_pods:
            seen_pods.add(a["pod"])
            unique_ana.append(a)
    if len(unique_ana) < len(ana_pods):
        log.warning("Deduplicated %d duplicate PODs from ANAGRAFICA", len(ana_pods) - len(unique_ana))
    ana_pods = unique_ana

    pods   = [a["pod"] for a in ana_pods]
    puntos = list({a["punto_dispacciamento"] for a in ana_pods if a["punto_dispacciamento"]})

    # Batch-load all supporting data in 4 queries total (not 3×N)
    pod_meta_map    = await _load_pod_metadata_batch(session, account_id, pods)
    dispatch_map    = await _load_dispatching_weights_batch(session, account_id, puntos)
    source_daily_map = await _load_source_daily_batch(session, account_id, pods, source_month)

    all_rows: list[ForecastRow] = []

    for ana in ana_pods:
        pod         = ana["pod"]
        punto       = ana["punto_dispacciamento"]
        consumo_tot = ana["consumo_tot"]

        meta           = pod_meta_map.get(pod)
        tensione       = (meta or {}).get("tensione") or ana.get("tensione")
        codice_tariffa = (meta or {}).get("codice_tariffa") or ana.get("codice_tariffa")
        pod_found      = meta is not None

        loss_pct = calculate_loss_pct(tensione, codice_tariffa, pod_found, loss_rules)

        weights: list[float] | None = dispatch_map.get(punto) if punto else None
        if punto and weights is None:
            log.warning(
                "Forecast %s %s pod=%s: no dispatching weights for punto='%s' — falling back to uniform distribution. "
                "Add weights in Admin > Dispatching Weights using exactly this name.",
                account_id, forecast_mese_anno, pod, punto,
            )
        source_daily = source_daily_map.get(pod, {})

        filled: list[FilledPeriod] = build_forecast_month(
            forecast_mese_anno=forecast_mese_anno,
            source_daily=source_daily,
            consumo_tot=consumo_tot,
            dispatching_weights=weights,
            source_mese_anno=source_month,
        )

        for fp in filled:
            ea_kwh_with_loss = apply_loss(fp.ea_kwh, loss_pct)

            all_rows.append(ForecastRow(
                account_id=account_id,
                pod=pod,
                mese_anno=forecast_mese_anno,
                punto_dispacciamento=punto,
                forecast_date=fp.forecast_date,
                source_date=fp.source_date,
                periodo=fp.periodo,
                ea_kwh=fp.ea_kwh,
                ea_kwh_with_loss=ea_kwh_with_loss,
                loss_pct=loss_pct,
                source_type=fp.source_type,
            ))

        log.info(
            "Forecast %s %s pod=%s: %d periods, loss=%.1f%%, source_month=%s",
            account_id, forecast_mese_anno, pod, len(filled), loss_pct * 100, source_month,
        )

    return all_rows


async def get_forecast_by_dp(
    session: AsyncSession,
    account_id: str,
    mese_anno: str,
) -> dict:
    """Return daily forecast totals grouped by dispatching point (for Excel export)."""
    rows = await session.execute(text("""
        SELECT forecast_date,
               COALESCE(punto_dispacciamento, 'Unknown') AS dp,
               ROUND(SUM(ea_kwh_with_loss) / 1000.0, 3) AS daily_mwh
        FROM forecast_periods
        WHERE account_id = :acct AND mese_anno = :ma
        GROUP BY forecast_date, dp
        ORDER BY forecast_date, dp
    """), {"acct": account_id, "ma": mese_anno})

    all_rows = rows.fetchall()
    if not all_rows:
        return {"dispatching_points": [], "daily": [], "total_mwh": 0.0}

    dp_set = sorted(set(r[1] for r in all_rows))
    dates  = sorted(set(r[0] for r in all_rows))

    dp_daily: dict = {}
    for r in all_rows:
        dp_daily[(r[0], r[1])] = float(r[2]) if r[2] else 0.0

    daily = []
    for d in dates:
        row: dict = {"date": d.isoformat()}
        total = 0.0
        for dp in dp_set:
            mwh = round(dp_daily.get((d, dp), 0.0), 4)
            row[dp] = mwh
            total += mwh
        row["total"] = round(total, 4)
        daily.append(row)

    return {
        "mese_anno": mese_anno,
        "dispatching_points": dp_set,
        "daily": daily,
        "total_mwh": round(sum(r["total"] for r in daily), 3),
    }


async def get_forecast_periods_by_dp(
    session: AsyncSession,
    account_id: str,
    mese_anno: str,
) -> dict:
    """Return period-level (96 per day) forecast totals grouped by dispatching point."""
    rows = await session.execute(text("""
        SELECT forecast_date,
               periodo,
               COALESCE(punto_dispacciamento, 'Unknown') AS dp,
               ROUND(SUM(ea_kwh_with_loss) / 1000.0, 6) AS period_mwh
        FROM forecast_periods
        WHERE account_id = :acct AND mese_anno = :ma
        GROUP BY forecast_date, periodo, dp
        ORDER BY forecast_date, periodo, dp
    """), {"acct": account_id, "ma": mese_anno})

    all_rows = rows.fetchall()
    if not all_rows:
        return {"dispatching_points": [], "periods": [], "total_mwh": 0.0}

    dp_set = sorted(set(r[2] for r in all_rows))
    date_period_pairs = sorted(set((r[0], r[1]) for r in all_rows))

    lookup: dict = {}
    for r in all_rows:
        lookup[(r[0], r[1], r[2])] = float(r[3]) if r[3] else 0.0

    periods = []
    for (d, p) in date_period_pairs:
        row: dict = {"date": d.isoformat(), "periodo": p}
        total = 0.0
        for dp in dp_set:
            mwh = round(lookup.get((d, p, dp), 0.0), 6)
            row[dp] = mwh
            total += mwh
        row["total"] = round(total, 6)
        periods.append(row)

    return {
        "mese_anno": mese_anno,
        "dispatching_points": dp_set,
        "periods": periods,
        "total_mwh": round(sum(r["total"] for r in periods), 3),
    }


async def get_forecast_ea_matrix(
    session: AsyncSession,
    account_id: str,
    mese_anno: str,
) -> dict:
    """
    Return forecast data in SII Ea-row format:
    one row per (zona, day-of-month) with 96 period columns.

    Maps to the classic SII XML structure:
      <Ea E1="..." E2="..." ... E96="...">DD</Ea>
    """
    rows = await session.execute(text("""
        SELECT COALESCE(punto_dispacciamento, 'Unknown') AS zona,
               forecast_date,
               periodo,
               ROUND(SUM(ea_kwh_with_loss) / 1000.0, 6) AS value
        FROM forecast_periods
        WHERE account_id = :acct AND mese_anno = :ma
        GROUP BY zona, forecast_date, periodo
        ORDER BY zona, forecast_date, periodo
    """), {"acct": account_id, "ma": mese_anno})

    all_rows = rows.fetchall()
    if not all_rows:
        return {"zones": [], "rows": []}

    # Build {(zona, date): {periodo: value}}
    lookup: dict = {}
    zones_set: set = set()
    dates_by_zone: dict = {}

    for r in all_rows:
        zona, d, periodo, value = r[0], r[1], r[2], float(r[3]) if r[3] else 0.0
        zones_set.add(zona)
        dates_by_zone.setdefault(zona, set()).add(d)
        lookup.setdefault((zona, d), {})[periodo] = value

    zones = sorted(zones_set)

    result_rows = []
    for zona in zones:
        for d in sorted(dates_by_zone[zona]):
            period_vals = lookup.get((zona, d), {})
            result_rows.append({
                "zona": zona,
                "day": d.day,          # day-of-month integer (1–31)
                "values": [round(period_vals.get(p, 0.0), 6) for p in range(1, 97)],
            })

    return {"zones": zones, "rows": result_rows}


async def compare_dispatching_points(
    session: AsyncSession,
    account_id: str,
    from_date: date,
    to_date: date,
    anagrafica_mese_anno: str | None = None,
    pods: list[str] | None = None,
) -> dict:
    """Year-over-year comparison aggregated by dispatching point."""
    prev_from = date(from_date.year - 1, from_date.month, from_date.day)
    prev_to   = date(to_date.year   - 1, to_date.month,   to_date.day)

    ana_month = anagrafica_mese_anno or f"{from_date.month:02d}/{from_date.year}"

    ana_filter = "AND pod = ANY(:pods)" if pods else ""
    ana_params: dict = {"acct": account_id, "ma": ana_month}
    if pods:
        ana_params["pods"] = pods

    pod_dp_rows = await session.execute(text(f"""
        SELECT pod, COALESCE(punto_dispacciamento, 'Unknown') AS dp
        FROM anagrafica
        WHERE account_id = :acct AND mese_anno = :ma AND included = TRUE
        {ana_filter}
    """), ana_params)
    pod_dp_map: dict[str, str] = {r[0]: r[1] for r in pod_dp_rows.fetchall()}

    _empty: dict = {
        "account_id": account_id,
        "anagrafica_month": ana_month,
        "current_period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
        "previous_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        "dispatching_points": [],
        "current_daily": [],
        "previous_daily": [],
        "current_total_mwh": 0.0,
        "previous_total_mwh": 0.0,
    }
    if not pod_dp_map:
        return _empty

    all_pods = list(pod_dp_map.keys())
    dp_set = sorted(set(pod_dp_map.values()))

    async def _fetch(fd: date, td: date) -> list[dict]:
        e_rows = await session.execute(text("""
            SELECT pod, data_misura, SUM(ea_kwh) AS kwh
            FROM measurements
            WHERE account_id = :acct AND pod = ANY(:pods)
              AND data_misura >= :fd AND data_misura <= :td
              AND tipo_dato = 'E'
            GROUP BY pod, data_misura
        """), {"acct": account_id, "pods": all_pods, "fd": fd, "td": td})

        combined: dict[tuple, float] = {}
        e_by_pod: dict[str, set] = {}
        for r in e_rows.fetchall():
            pod, d, kwh = r[0], r[1], float(r[2]) if r[2] else 0.0
            combined[(pod, d)] = kwh
            e_by_pod.setdefault(pod, set()).add(d)

        s_rows = await session.execute(text("""
            SELECT pod, data_misura, SUM(ea_kwh) AS kwh
            FROM measurements_secondary
            WHERE account_id = :acct AND pod = ANY(:pods)
              AND data_misura >= :fd AND data_misura <= :td
            GROUP BY pod, data_misura
        """), {"acct": account_id, "pods": all_pods, "fd": fd, "td": td})

        for r in s_rows.fetchall():
            pod, d, kwh = r[0], r[1], float(r[2]) if r[2] else 0.0
            if d not in e_by_pod.get(pod, set()):
                combined[(pod, d)] = kwh

        dp_daily: dict[tuple, float] = {}
        for (pod, d), kwh in combined.items():
            dp = pod_dp_map.get(pod, "Unknown")
            key = (d, dp)
            dp_daily[key] = dp_daily.get(key, 0.0) + kwh

        result = []
        for d in sorted(set(k[0] for k in dp_daily)):
            row: dict = {"date": d.isoformat()}
            total = 0.0
            for dp in dp_set:
                mwh = round(dp_daily.get((d, dp), 0.0) / 1000, 4)
                row[dp] = mwh
                total += mwh
            row["total"] = round(total, 4)
            result.append(row)
        return result

    current_daily  = await _fetch(from_date, to_date)
    previous_daily = await _fetch(prev_from, prev_to)

    return {
        "account_id": account_id,
        "anagrafica_month": ana_month,
        "current_period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
        "previous_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        "dispatching_points": dp_set,
        "current_daily": current_daily,
        "previous_daily": previous_daily,
        "current_total_mwh": round(sum(r.get("total", 0) for r in current_daily), 3),
        "previous_total_mwh": round(sum(r.get("total", 0) for r in previous_daily), 3),
    }


async def compare_partial_month(
    session: AsyncSession,
    account_id: str,
    pod: str,
    from_date: date,
    to_date: date,
) -> dict:
    """
    Year-over-year comparison for a partial date range.

    Returns dict with:
      current_year: list of {date, periodo, ea_mwh}
      previous_year: list of {date, periodo, ea_mwh}
    """
    prev_from = date(from_date.year - 1, from_date.month, from_date.day)
    prev_to   = date(to_date.year   - 1, to_date.month,   to_date.day)

    async def _fetch(table: str, fd: date, td: date, tipo: str | None = None) -> list[dict]:
        tipo_filter = "AND tipo_dato = :tipo" if tipo else ""
        params: dict = {"acct": account_id, "pod": pod, "fd": fd, "td": td}
        if tipo:
            params["tipo"] = tipo
        rows = await session.execute(text(f"""
            SELECT data_misura, periodo, ea_kwh
            FROM {table}
            WHERE account_id = :acct AND pod = :pod
              AND data_misura >= :fd AND data_misura <= :td
              {tipo_filter}
            ORDER BY data_misura, periodo
        """), params)
        return [
            {
                "date": r[0].isoformat(),
                "periodo": r[1],
                "ea_mwh": round(float(r[2]) / 1000, 3) if r[2] is not None else None,
            }
            for r in rows.fetchall()
        ]

    # Current year: E first, fill gaps with S
    cur_e = await _fetch("measurements", from_date, to_date, "E")
    cur_e_dates = {r["date"] for r in cur_e}
    cur_s = [r for r in await _fetch("measurements_secondary", from_date, to_date) if r["date"] not in cur_e_dates]
    current = sorted(cur_e + cur_s, key=lambda r: (r["date"], r["periodo"]))

    # Previous year: same logic
    prev_e = await _fetch("measurements", prev_from, prev_to, "E")
    prev_e_dates = {r["date"] for r in prev_e}
    prev_s = [r for r in await _fetch("measurements_secondary", prev_from, prev_to) if r["date"] not in prev_e_dates]
    previous = sorted(prev_e + prev_s, key=lambda r: (r["date"], r["periodo"]))

    return {
        "account_id": account_id,
        "pod": pod,
        "current_period": {"from": from_date.isoformat(), "to": to_date.isoformat(), "data": current},
        "previous_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat(), "data": previous},
        "current_total_mwh": round(sum(r["ea_mwh"] or 0 for r in current), 3),
        "previous_total_mwh": round(sum(r["ea_mwh"] or 0 for r in previous), 3),
    }
