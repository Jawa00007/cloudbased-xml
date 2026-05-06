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


async def _load_dispatching_weights(
    session: AsyncSession,
    account_id: str,
    punto_dispacciamento: str,
) -> list[float] | None:
    """
    Return 96 period weights for a dispatching point, or None if not configured.
    Account-specific rows take precedence over global (NULL account_id) rows.
    """
    rows = await session.execute(text("""
        SELECT periodo, pct
        FROM public.dispatching_config
        WHERE (account_id = :acct OR account_id IS NULL)
          AND punto_dispacciamento = :pd
        ORDER BY account_id NULLS LAST, periodo
    """), {"acct": account_id, "pd": punto_dispacciamento})
    # If both account-specific and global rows exist, account-specific come first.
    # Build dict — first seen wins (account-specific beats global for the same periodo).
    data: dict[int, float] = {}
    for r in rows.fetchall():
        if r[0] not in data:
            data[r[0]] = float(r[1])
    if len(data) < 96:
        return None
    return [data.get(i, 0.0) for i in range(1, 97)]


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


async def _load_pod_meta(
    session: AsyncSession,
    account_id: str,
    pod: str,
) -> dict | None:
    """Load pod_metadata for loss-rule lookup (tensione, codice_tariffa)."""
    row = await session.execute(text("""
        SELECT tensione, codice_tariffa
        FROM pod_metadata
        WHERE account_id = :acct AND pod = :pod
        ORDER BY valid_from DESC NULLS LAST
        LIMIT 1
    """), {"acct": account_id, "pod": pod})
    r = row.fetchone()
    return {"tensione": r[0], "codice_tariffa": r[1]} if r else None


async def _load_source_daily(
    session: AsyncSession,
    account_id: str,
    pod: str,
    source_mese_anno: str,
) -> dict[date, list[tuple[int, float | None, str]]]:
    """
    Load all 96-period rows for a POD in the source month.
    Returns {date: [(periodo, ea_kwh, source_type), ...]}
    E preferred over S for any given day.
    """
    # Fetch E data
    e_rows = await session.execute(text("""
        SELECT data_misura, periodo, ea_kwh
        FROM measurements
        WHERE account_id = :acct AND pod = :pod AND mese_anno = :ma AND tipo_dato = 'E'
        ORDER BY data_misura, periodo
    """), {"acct": account_id, "pod": pod, "ma": source_mese_anno})

    daily: dict[date, list[tuple[int, float | None, str]]] = {}
    e_dates: set[date] = set()

    for r in e_rows.fetchall():
        d = r[0]
        e_dates.add(d)
        daily.setdefault(d, []).append((r[1], float(r[2]) if r[2] is not None else None, "E"))

    # Fetch S data only for days without E
    s_rows = await session.execute(text("""
        SELECT data_misura, periodo, ea_kwh
        FROM measurements_secondary
        WHERE account_id = :acct AND pod = :pod AND mese_anno = :ma
        ORDER BY data_misura, periodo
    """), {"acct": account_id, "pod": pod, "ma": source_mese_anno})

    for r in s_rows.fetchall():
        d = r[0]
        if d not in e_dates:
            daily.setdefault(d, []).append((r[1], float(r[2]) if r[2] is not None else None, "S"))

    return daily


def _source_mese_anno(forecast_mese_anno: str) -> str:
    """Return the same month one year earlier: '05/2026' → '05/2025'."""
    mm, yyyy = forecast_mese_anno.split("/")
    return f"{mm}/{int(yyyy) - 1}"


# ── Main entry point ──────────────────────────────────────────────────────────

async def generate_forecast(
    session: AsyncSession,
    account_id: str,
    forecast_mese_anno: str,
) -> list[ForecastRow]:
    """
    Generate the full forecast for one account + month.

    Returns a list of ForecastRow (one per POD × 31 days × 96 periods).
    The caller is responsible for upserting into forecast_periods.
    """
    source_month = _source_mese_anno(forecast_mese_anno)
    loss_rules   = await _load_loss_rules(session, account_id)
    ana_pods     = await _load_anagrafica_pods(session, account_id, forecast_mese_anno)

    if not ana_pods:
        log.warning("No ANAGRAFICA data for %s / %s — nothing to forecast", account_id, forecast_mese_anno)
        return []

    all_rows: list[ForecastRow] = []

    for ana in ana_pods:
        pod           = ana["pod"]
        punto         = ana["punto_dispacciamento"]
        consumo_tot   = ana["consumo_tot"]

        # Loss rule lookup: prefer pod_metadata, fall back to anagrafica fields
        meta = await _load_pod_meta(session, account_id, pod)
        tensione       = (meta or {}).get("tensione") or ana.get("tensione")
        codice_tariffa = (meta or {}).get("codice_tariffa") or ana.get("codice_tariffa")
        pod_found      = meta is not None

        loss_pct = calculate_loss_pct(tensione, codice_tariffa, pod_found, loss_rules)

        # Dispatching weights for CONSUMO_TOT estimation
        weights: list[float] | None = None
        if punto:
            weights = await _load_dispatching_weights(session, account_id, punto)

        # Load previous-year source data
        source_daily = await _load_source_daily(session, account_id, pod, source_month)

        # Build 31-day × 96-period filled forecast
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
