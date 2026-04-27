"""
Aggregation engine — daily and monthly rollups.

Query rule (enforced at SQL level):
  Use measurements (TipoDato=E) if records exist for that POD+date.
  Fall back to measurements_secondary (TipoDato=S) only when no E record exists.

All functions return plain dicts — the API layer wraps them in Pydantic response models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ── Result types ───────────────────────────────────────────────────────────────

@dataclass
class DailyTotal:
    pod: str
    data_misura: date
    daily_kwh: Decimal | None
    daily_kvarh: Decimal | None
    source: str          # "E" or "S"
    periods: int         # number of non-null periods summed


@dataclass
class MonthlyTotal:
    pod: str
    mese_anno: str
    monthly_kwh: Decimal | None
    monthly_kvarh: Decimal | None
    days: int
    source: str          # "E", "S", or "mixed"


@dataclass
class PeriodRow:
    pod: str
    data_misura: date
    periodo: int
    ea_kwh: Decimal | None
    er_kvarh: Decimal | None
    tipo_dato: str | None
    dst: int


# ── Daily aggregation ──────────────────────────────────────────────────────────

async def get_daily_totals(
    session: AsyncSession,
    account_id: str,
    pod: str,
    mese_anno: str,
) -> list[DailyTotal]:
    """
    Sum ea_kwh per day for a POD+month, preferring E over S data.

    Returns one DailyTotal per day that has data.
    """
    # Step 1: days that have E data
    e_days_result = await session.execute(text("""
        SELECT DISTINCT data_misura
        FROM measurements
        WHERE account_id = :account_id
          AND pod        = :pod
          AND mese_anno  = :mese_anno
          AND tipo_dato  = 'E'
    """), {"account_id": account_id, "pod": pod, "mese_anno": mese_anno})
    e_days = {row[0] for row in e_days_result}

    results: list[DailyTotal] = []

    # Step 2: E data for those days
    if e_days:
        e_result = await session.execute(text("""
            SELECT
                pod,
                data_misura,
                SUM(ea_kwh)   AS daily_kwh,
                SUM(er_kvarh) AS daily_kvarh,
                COUNT(ea_kwh) AS periods
            FROM measurements
            WHERE account_id = :account_id
              AND pod        = :pod
              AND mese_anno  = :mese_anno
              AND tipo_dato  = 'E'
            GROUP BY pod, data_misura
            ORDER BY data_misura
        """), {"account_id": account_id, "pod": pod, "mese_anno": mese_anno})

        for row in e_result:
            results.append(DailyTotal(
                pod=row[0],
                data_misura=row[1],
                daily_kwh=row[2],
                daily_kvarh=row[3],
                source="E",
                periods=row[4],
            ))

    # Step 3: S fallback for days with NO E data
    s_result = await session.execute(text("""
        SELECT
            pod,
            data_misura,
            SUM(ea_kwh)   AS daily_kwh,
            SUM(er_kvarh) AS daily_kvarh,
            COUNT(ea_kwh) AS periods
        FROM measurements_secondary
        WHERE account_id = :account_id
          AND pod        = :pod
          AND mese_anno  = :mese_anno
          AND tipo_dato  = 'S'
        GROUP BY pod, data_misura
        ORDER BY data_misura
    """), {"account_id": account_id, "pod": pod, "mese_anno": mese_anno})

    for row in s_result:
        if row[1] not in e_days:
            results.append(DailyTotal(
                pod=row[0],
                data_misura=row[1],
                daily_kwh=row[2],
                daily_kvarh=row[3],
                source="S",
                periods=row[4],
            ))

    results.sort(key=lambda r: r.data_misura)
    return results


# ── Monthly aggregation ────────────────────────────────────────────────────────

async def get_monthly_total(
    session: AsyncSession,
    account_id: str,
    pod: str,
    mese_anno: str,
) -> MonthlyTotal | None:
    """
    Sum ea_kwh across all days in a month for a POD, using E-over-S rule.
    """
    daily = await get_daily_totals(session, account_id, pod, mese_anno)
    if not daily:
        return None

    total_kwh = sum((d.daily_kwh or Decimal(0)) for d in daily)
    total_kvarh = sum((d.daily_kvarh or Decimal(0)) for d in daily)
    sources = {d.source for d in daily}
    source = "E" if sources == {"E"} else "S" if sources == {"S"} else "mixed"

    return MonthlyTotal(
        pod=pod,
        mese_anno=mese_anno,
        monthly_kwh=total_kwh,
        monthly_kvarh=total_kvarh,
        days=len(daily),
        source=source,
    )


async def get_monthly_totals_all_pods(
    session: AsyncSession,
    account_id: str,
    mese_anno: str,
) -> list[MonthlyTotal]:
    """Monthly totals for every POD in an account+month."""
    pod_result = await session.execute(text("""
        SELECT DISTINCT pod FROM (
            SELECT pod FROM measurements
            WHERE account_id = :account_id AND mese_anno = :mese_anno
            UNION
            SELECT pod FROM measurements_secondary
            WHERE account_id = :account_id AND mese_anno = :mese_anno
        ) pods ORDER BY pod
    """), {"account_id": account_id, "mese_anno": mese_anno})

    pods = [row[0] for row in pod_result]
    results = []
    for pod in pods:
        mt = await get_monthly_total(session, account_id, pod, mese_anno)
        if mt:
            results.append(mt)
    return results


async def get_yearly_totals(
    session: AsyncSession,
    account_id: str,
    pod: str,
    year: int,
) -> list[MonthlyTotal]:
    """Monthly totals for each month of a year for a given POD."""
    months = [f"{m:02d}/{year}" for m in range(1, 13)]
    results = []
    for mese_anno in months:
        mt = await get_monthly_total(session, account_id, pod, mese_anno)
        if mt:
            results.append(mt)
    return results


# ── Raw period data ────────────────────────────────────────────────────────────

async def get_period_data(
    session: AsyncSession,
    account_id: str,
    pod: str,
    data_misura: date,
) -> list[PeriodRow]:
    """
    All 96 quarter-hourly periods for a POD+date.
    Prefers E data; falls back to S if no E exists for that date.
    """
    e_result = await session.execute(text("""
        SELECT pod, data_misura, periodo, ea_kwh, er_kvarh, tipo_dato, dst
        FROM measurements
        WHERE account_id  = :account_id
          AND pod         = :pod
          AND data_misura = :data_misura
          AND tipo_dato   = 'E'
        ORDER BY periodo
    """), {"account_id": account_id, "pod": pod, "data_misura": data_misura})

    rows = e_result.fetchall()
    if rows:
        return [PeriodRow(*r) for r in rows]

    # Fallback to secondary
    s_result = await session.execute(text("""
        SELECT pod, data_misura, periodo, ea_kwh, er_kvarh, tipo_dato, dst
        FROM measurements_secondary
        WHERE account_id  = :account_id
          AND pod         = :pod
          AND data_misura = :data_misura
        ORDER BY periodo
    """), {"account_id": account_id, "pod": pod, "data_misura": data_misura})

    return [PeriodRow(*r) for r in s_result.fetchall()]


# ── Missing periods ────────────────────────────────────────────────────────────

@dataclass
class MissingPeriodRow:
    pod: str
    data_misura: date
    periods_found: int
    source: str   # E or S


async def get_missing_periods(
    session: AsyncSession,
    account_id: str,
    mese_anno: str,
) -> list[MissingPeriodRow]:
    """
    Return all POD+day combinations in a month where fewer than 96 periods
    were recorded (DST days are excluded — only Dst=0 days counted).
    """
    result = await session.execute(text("""
        SELECT pod, data_misura, COUNT(*) AS periods_found, 'E' AS source
        FROM measurements
        WHERE account_id = :account_id
          AND mese_anno  = :mese_anno
          AND tipo_dato  = 'E'
          AND dst        = 0
        GROUP BY pod, data_misura
        HAVING COUNT(*) < 96
        UNION ALL
        SELECT pod, data_misura, COUNT(*) AS periods_found, 'S' AS source
        FROM measurements_secondary
        WHERE account_id = :account_id
          AND mese_anno  = :mese_anno
          AND dst        = 0
          AND data_misura NOT IN (
              SELECT DISTINCT data_misura
              FROM measurements
              WHERE account_id = :account_id AND mese_anno = :mese_anno
          )
        GROUP BY pod, data_misura
        HAVING COUNT(*) < 96
        ORDER BY pod, data_misura
    """), {"account_id": account_id, "mese_anno": mese_anno})

    return [
        MissingPeriodRow(pod=r[0], data_misura=r[1], periods_found=r[2], source=r[3])
        for r in result.fetchall()
    ]


# ── Period range ────────────────────────────────────────────────────────────────

async def get_period_range(
    session: AsyncSession,
    account_id: str,
    pod: str,
    from_date: date,
    to_date: date,
    tipo_dato: str | None = None,
) -> list[PeriodRow]:
    """
    Quarter-hourly periods for a POD across a date range (max 31 days).
    tipo_dato=None returns both E and S (E preferred per day).
    """
    params = {"account_id": account_id, "pod": pod,
               "from_date": from_date, "to_date": to_date}

    td_filter = "AND tipo_dato = :tipo_dato" if tipo_dato else ""
    if tipo_dato:
        params["tipo_dato"] = tipo_dato

    result = await session.execute(text(f"""
        SELECT pod, data_misura, periodo, ea_kwh, er_kvarh, tipo_dato, dst
        FROM measurements
        WHERE account_id  = :account_id
          AND pod         = :pod
          AND data_misura >= :from_date
          AND data_misura <= :to_date
          {td_filter}
        UNION ALL
        SELECT pod, data_misura, periodo, ea_kwh, er_kvarh, tipo_dato, dst
        FROM measurements_secondary
        WHERE account_id  = :account_id
          AND pod         = :pod
          AND data_misura >= :from_date
          AND data_misura <= :to_date
          {td_filter}
          AND data_misura NOT IN (
              SELECT DISTINCT data_misura FROM measurements
              WHERE account_id = :account_id AND pod = :pod
                AND data_misura >= :from_date AND data_misura <= :to_date
          )
        ORDER BY data_misura, periodo
    """), params)

    return [PeriodRow(*r) for r in result.fetchall()]


# ── Corrections summary ─────────────────────────────────────────────────────────

@dataclass
class CorrectionSummaryRow:
    pod: str
    mese_anno: str
    cod_flusso: str
    count: int


async def get_corrections_summary(
    session: AsyncSession,
    account_id: str,
    mese_anno: str | None = None,
) -> list[CorrectionSummaryRow]:
    """Correction file counts grouped by POD + month + flow code."""
    params: dict = {"account_id": account_id}
    mese_filter = "AND mese_anno = :mese_anno" if mese_anno else ""
    if mese_anno:
        params["mese_anno"] = mese_anno

    result = await session.execute(text(f"""
        SELECT pod, mese_anno, cod_flusso, COUNT(*) AS cnt
        FROM corrections
        WHERE account_id = :account_id
          {mese_filter}
        GROUP BY pod, mese_anno, cod_flusso
        ORDER BY mese_anno DESC, pod
    """), params)

    return [
        CorrectionSummaryRow(pod=r[0], mese_anno=r[1], cod_flusso=r[2], count=r[3])
        for r in result.fetchall()
    ]


# ── POD list ───────────────────────────────────────────────────────────────────

async def get_pods(
    session: AsyncSession,
    account_id: str,
) -> list[str]:
    """All distinct PODs that have any measurement data for an account."""
    result = await session.execute(text("""
        SELECT DISTINCT pod FROM (
            SELECT pod FROM measurements         WHERE account_id = :account_id
            UNION
            SELECT pod FROM measurements_secondary WHERE account_id = :account_id
            UNION
            SELECT pod FROM measurements_totalizer WHERE account_id = :account_id
        ) p ORDER BY pod
    """), {"account_id": account_id})
    return [row[0] for row in result]
