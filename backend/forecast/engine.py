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
  5. Apply grid-loss adjustment and convert kWh → MWh (÷1000, round 3dp)
  6. Upsert into forecast_periods table
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.forecast.loss_calculator import (
    DEFAULT_RULES,
    LossRule,
    apply_loss,
    calculate_loss_pct,
    kwh_to_mwh,
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
    ea_mwh: float | None
    ea_mwh_with_loss: float | None
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
    Load dispatching weights for all relevant puntos in one query.
    Account-specific rows take precedence over global (NULL account_id).
    Returns {punto_dispacciamento: [96 weights] or None}.
    """
    if not puntos:
        return {}
    rows = await session.execute(text("""
        SELECT punto_dispacciamento, periodo, pct
        FROM public.dispatching_config
        WHERE (account_id = :acct OR account_id IS NULL)
          AND punto_dispacciamento = ANY(:puntos)
        ORDER BY account_id NULLS LAST, punto_dispacciamento, periodo
    """), {"acct": account_id, "puntos": puntos})
    by_punto: dict[str, dict[int, float]] = {}
    for r in rows.fetchall():
        pd, periodo, pct = r[0], r[1], float(r[2])
        by_punto.setdefault(pd, {})
        if periodo not in by_punto[pd]:  # first-seen wins: account-specific before global
            by_punto[pd][periodo] = pct
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
    result: dict[str, dict[date, list[tuple[int, float | None, str]]]] = {p: {} for p in pods}
    e_dates: dict[str, set[date]] = {p: set() for p in pods}

    e_rows = await session.execute(text("""
        SELECT pod, data_misura, periodo, ea_kwh
        FROM measurements
        WHERE account_id = :acct AND pod = ANY(:pods) AND mese_anno = :ma AND tipo_dato = 'E'
        ORDER BY pod, data_misura, periodo
    """), {"acct": account_id, "pods": pods, "ma": source_mese_anno})
    for r in e_rows.fetchall():
        pod, d, periodo, ea = r[0], r[1], r[2], r[3]
        e_dates[pod].add(d)
        result[pod].setdefault(d, []).append((periodo, float(ea) if ea is not None else None, "E"))

    s_rows = await session.execute(text("""
        SELECT pod, data_misura, periodo, ea_kwh
        FROM measurements_secondary
        WHERE account_id = :acct AND pod = ANY(:pods) AND mese_anno = :ma
        ORDER BY pod, data_misura, periodo
    """), {"acct": account_id, "pods": pods, "ma": source_mese_anno})
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


# ── Main entry point ──────────────────────────────────────────────────────────

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
    source_month = _source_mese_anno(forecast_mese_anno)
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
        source_daily = source_daily_map.get(pod, {})

        filled: list[FilledPeriod] = build_forecast_month(
            forecast_mese_anno=forecast_mese_anno,
            source_daily=source_daily,
            consumo_tot=consumo_tot,
            dispatching_weights=weights,
        )

        for fp in filled:
            ea_mwh           = kwh_to_mwh(fp.ea_kwh)
            ea_kwh_with_loss = apply_loss(fp.ea_kwh, loss_pct)
            ea_mwh_with_loss = kwh_to_mwh(ea_kwh_with_loss)

            all_rows.append(ForecastRow(
                account_id=account_id,
                pod=pod,
                mese_anno=forecast_mese_anno,
                punto_dispacciamento=punto,
                forecast_date=fp.forecast_date,
                source_date=fp.source_date,
                periodo=fp.periodo,
                ea_mwh=ea_mwh,
                ea_mwh_with_loss=ea_mwh_with_loss,
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
               SUM(ea_mwh_with_loss) AS daily_mwh
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
               SUM(ea_mwh_with_loss) AS period_mwh
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
