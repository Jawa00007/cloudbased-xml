"""
Measurement endpoints:

  GET /pods                    — list PODs for an account
  GET /measurements            — 96 periods for a POD+date
  GET /measurements/month      — all periods for a POD+month
  GET /totals                  — totalizer band records for a POD+month
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text

from backend.aggregation.engine import get_period_data, get_pods
from backend.api.auth import require_auth
from backend.api.schemas import MeasurementOut, PeriodOut, TotalizerOut
from backend.db.session import get_session
from backend.ingestion.ingest import schema_for

router = APIRouter(tags=["measurements"])


def _resolve_schema(account: str) -> str:
    return schema_for(account)


@router.get("/pods", response_model=list[str])
async def list_pods(
    account: Annotated[str, Query(description="Account name, e.g. BAT")],
    _: Annotated[str, Depends(require_auth)],
) -> list[str]:
    schema = _resolve_schema(account)
    async with get_session(schema) as session:
        return await get_pods(session, account)


@router.get("/measurements", response_model=list[PeriodOut])
async def get_measurements(
    account: Annotated[str, Query()],
    pod: Annotated[str, Query()],
    date_: Annotated[date, Query(alias="date", description="YYYY-MM-DD")],
    _: Annotated[str, Depends(require_auth)],
) -> list[PeriodOut]:
    schema = _resolve_schema(account)
    async with get_session(schema) as session:
        rows = await get_period_data(session, account, pod, date_)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No measurements for {pod} on {date_}")
    return [PeriodOut(
        pod=r.pod,
        data_misura=r.data_misura,
        periodo=r.periodo,
        ea_kwh=r.ea_kwh,
        er_kvarh=r.er_kvarh,
        tipo_dato=r.tipo_dato,
        dst=r.dst,
    ) for r in rows]


@router.get("/measurements/month", response_model=list[MeasurementOut])
async def get_measurements_month(
    account: Annotated[str, Query()],
    pod: Annotated[str, Query()],
    mese_anno: Annotated[str, Query(description="MM/YYYY")],
    _: Annotated[str, Depends(require_auth)],
) -> list[MeasurementOut]:
    schema = _resolve_schema(account)
    async with get_session(schema) as session:
        # Prefer E; include S only for days missing E
        result = await session.execute(text("""
            SELECT
                pod, data_misura, periodo, ea_kwh, er_kvarh, tipo_dato,
                raccolta, validato, tensione, trattamento, pot_max, dst,
                cod_flusso, mese_anno, source_file
            FROM measurements
            WHERE account_id = :account_id
              AND pod        = :pod
              AND mese_anno  = :mese_anno
              AND tipo_dato  = 'E'
            UNION ALL
            SELECT
                pod, data_misura, periodo, ea_kwh, er_kvarh, tipo_dato,
                raccolta, validato, tensione, trattamento, pot_max, dst,
                cod_flusso, mese_anno, source_file
            FROM measurements_secondary
            WHERE account_id = :account_id
              AND pod        = :pod
              AND mese_anno  = :mese_anno
              AND data_misura NOT IN (
                  SELECT DISTINCT data_misura
                  FROM measurements
                  WHERE account_id = :account_id AND pod = :pod AND mese_anno = :mese_anno
              )
            ORDER BY data_misura, periodo
        """), {"account_id": account, "pod": pod, "mese_anno": mese_anno})

        rows = result.fetchall()

    return [MeasurementOut(
        pod=r[0], data_misura=r[1], periodo=r[2], ea_kwh=r[3], er_kvarh=r[4],
        tipo_dato=r[5], raccolta=r[6], validato=r[7], tensione=r[8],
        trattamento=r[9], pot_max=r[10], dst=r[11],
        cod_flusso=r[12], mese_anno=r[13], source_file=r[14],
    ) for r in rows]


@router.get("/totals", response_model=list[TotalizerOut])
async def get_totals(
    account: Annotated[str, Query()],
    pod: Annotated[str, Query()],
    mese_anno: Annotated[str, Query(description="MM/YYYY")],
    _: Annotated[str, Depends(require_auth)],
) -> list[TotalizerOut]:
    schema = _resolve_schema(account)
    async with get_session(schema) as session:
        result = await session.execute(text("""
            SELECT
                pod, data_misura, mese_anno, tipo_dato,
                ea_f1, ea_f2, ea_f3, ea_f4, ea_f5, ea_f6, ea_m,
                er_f1, er_f2, er_f3,
                pot_f1, pot_f2, pot_f3,
                cod_flusso, source_file
            FROM measurements_totalizer
            WHERE account_id = :account_id
              AND pod        = :pod
              AND mese_anno  = :mese_anno
            ORDER BY data_misura
        """), {"account_id": account, "pod": pod, "mese_anno": mese_anno})

        rows = result.fetchall()

    return [TotalizerOut(
        pod=r[0], data_misura=r[1], mese_anno=r[2], tipo_dato=r[3],
        ea_f1=r[4], ea_f2=r[5], ea_f3=r[6], ea_f4=r[7],
        ea_f5=r[8], ea_f6=r[9], ea_m=r[10],
        er_f1=r[11], er_f2=r[12], er_f3=r[13],
        pot_f1=r[14], pot_f2=r[15], pot_f3=r[16],
        cod_flusso=r[17], source_file=r[18],
    ) for r in rows]
