"""
Missing data fill logic for the forecast engine.

Three cases (from requirements):
  Case 1 — TipoDato S : already handled by the aggregation engine (E preferred, S fallback).
  Case 2 — Missing day : carry forward the last available day's 96 periods.
  Case 3 — No data at all : estimate daily kWh = CONSUMO_TOT / 365,
                            then distribute across 96 periods using dispatching weights.
                            If no dispatching weights exist, distribute evenly (1/96 each).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


@dataclass
class FilledPeriod:
    forecast_date: date
    source_date: date | None   # None = estimated, no real source day
    periodo: int               # 1–96
    ea_kwh: float | None
    source_type: str           # "E" | "S" | "filled" | "estimated" | "padded"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _flat_periods(daily_map: dict[date, list[tuple[int, float | None, str]]]) -> list[date]:
    """Return sorted list of dates that have at least one period."""
    return sorted(daily_map.keys())


def _uniform_weights(n: int = 96) -> list[float]:
    """Equal distribution across n periods."""
    w = 1.0 / n
    return [w] * n


# ── Public API ────────────────────────────────────────────────────────────────

def build_forecast_month(
    forecast_mese_anno: str,
    source_daily: dict[date, list[tuple[int, float | None, str]]],
    consumo_tot: float | None,
    dispatching_weights: list[float] | None,
) -> list[FilledPeriod]:
    """
    Produce a complete 31-slot × 96-period forecast for one POD in one month.

    Args:
        forecast_mese_anno:  Target month, e.g. "05/2026".
        source_daily:        {source_date: [(periodo, ea_kwh, source_type), ...]}
                             from the previous year (e.g. May 2025 data).
                             Missing = days without measurement data.
        consumo_tot:         Annual kWh total from ANAGRAFICA. Used for Case 3.
        dispatching_weights: 96 floats summing to 1.0. Uniform if None.

    Returns:
        List of FilledPeriod — days_in_month × 96 rows (e.g. 30×96=2 880 for April).
        Short months (April/June/September/November = 30 days, February = 28/29)
        produce fewer rows — non-existent days are skipped entirely to avoid
        duplicate (forecast_date, periodo) pairs that would violate the DB constraint.
    """
    mm, yyyy = forecast_mese_anno.split("/")
    month = int(mm)
    year  = int(yyyy)

    weights = dispatching_weights if dispatching_weights else _uniform_weights()

    # Daily kWh from CONSUMO_TOT estimation (Case 3)
    daily_est_kwh: float | None = None
    if consumo_tot and consumo_tot > 0:
        daily_est_kwh = consumo_tot / 365.0

    sorted_source_dates = _flat_periods(source_daily)

    result: list[FilledPeriod] = []
    last_used_source: date | None = None

    for day_num in range(1, 32):
        # Skip days beyond the real month end (e.g. April 31, Feb 29 in non-leap year).
        # Using the last-day fallback caused duplicate forecast_dates (April 30 appeared
        # twice for day_num=30 and day_num=31), violating the DB unique constraint.
        try:
            f_date = date(year, month, day_num)
        except ValueError:
            continue  # day_num beyond month end — skip rather than reuse last day

        # Determine the corresponding source date (same day in previous year)
        try:
            source_date_target: date | None = date(year - 1, month, day_num)
        except ValueError:
            source_date_target = None  # e.g. Feb 29 in non-leap source year

        # --- Pick source periods ---
        periods_for_day: list[tuple[int, float | None, str]] | None = None
        used_source_date: date | None = None
        source_type_override: str | None = None

        if source_date_target and source_date_target in source_daily:
            # Case 1/E: exact match from previous year
            periods_for_day = source_daily[source_date_target]
            used_source_date = source_date_target

        elif sorted_source_dates:
            # Case 2: carry forward last available day before target
            candidates = [d for d in sorted_source_dates if d <= source_date_target] if source_date_target else sorted_source_dates
            if not candidates:
                candidates = sorted_source_dates  # take earliest if nothing before
            last_used_source = candidates[-1]
            periods_for_day = source_daily[last_used_source]
            used_source_date = last_used_source
            source_type_override = "filled"

        if periods_for_day is not None:
            for (periodo, ea_kwh, base_type) in periods_for_day:
                stype = source_type_override or base_type
                result.append(FilledPeriod(
                    forecast_date=f_date,
                    source_date=used_source_date,
                    periodo=periodo,
                    ea_kwh=float(ea_kwh) if ea_kwh is not None else None,
                    source_type=stype,
                ))
        else:
            # Case 3: no data at all → estimate from CONSUMO_TOT
            for i in range(96):
                periodo = i + 1
                ea_kwh: float | None = None
                if daily_est_kwh is not None and i < len(weights):
                    ea_kwh = daily_est_kwh * weights[i]
                result.append(FilledPeriod(
                    forecast_date=f_date,
                    source_date=None,
                    periodo=periodo,
                    ea_kwh=ea_kwh,
                    source_type="estimated",
                ))

    return result


def _last_day(year: int, month: int) -> int:
    """Return the last calendar day of a given month."""
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day
