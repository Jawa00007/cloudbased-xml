"""
Admin routes — ANAGRAFICA upload, loss config CRUD, dispatching config CRUD.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert

from backend.api.auth import require_auth
from backend.api.schemas import (
    AnagraficaOut,
    AnagraficaUploadOut,
    DispatchingWeightIn,
    DispatchingWeightOut,
    LossRuleIn,
    LossRuleOut,
)
from backend.db.session import get_public_session, get_session
from backend.db.upsert import upsert_anagrafica
from backend.ingestion.ingest import schema_for
from backend.models.config import DispatchingConfig, LossConfig
from backend.parser.anagrafica_parser import parse_anagrafica_bytes

router = APIRouter(prefix="/admin", tags=["admin"])

Auth = Annotated[str, Depends(require_auth)]


# ── ANAGRAFICA upload ─────────────────────────────────────────────────────────

@router.post(
    "/anagrafica/upload",
    response_model=AnagraficaUploadOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an ANAGRAFICA ZIP or CSV file for a given account",
)
async def upload_anagrafica(
    account_id: str,
    file: UploadFile,
    _: Auth,
) -> AnagraficaUploadOut:
    data = await file.read()
    filename = file.filename or "upload.csv"

    records = parse_anagrafica_bytes(data, filename, account_id)
    if not records:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid ANAGRAFICA rows found (filter column = 'O' required)",
        )

    schema = schema_for(account_id)
    async with get_session(schema) as session:
        n = await upsert_anagrafica(session, records, account_id)

    mese_anno = records[0].mese_anno if records else ""
    return AnagraficaUploadOut(
        message="ANAGRAFICA uploaded",
        account_id=account_id,
        mese_anno=mese_anno,
        records_upserted=n,
    )


@router.get(
    "/anagrafica",
    response_model=list[AnagraficaOut],
    summary="List ANAGRAFICA records for an account and month",
)
async def list_anagrafica(
    account_id: str,
    mese_anno: str,
    _: Auth,
) -> list[AnagraficaOut]:
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        rows = await session.execute(text("""
            SELECT pod, mese_anno, piva_utente, punto_dispacciamento, tipo_misuratore,
                   trattamento, tensione, codice_tariffa, consumo_tot, included, source_file
            FROM anagrafica
            WHERE account_id = :acct AND mese_anno = :ma AND included = TRUE
            ORDER BY pod
        """), {"acct": account_id, "ma": mese_anno})
        return [AnagraficaOut.model_validate(dict(r._mapping)) for r in rows.fetchall()]


# ── Loss config CRUD ──────────────────────────────────────────────────────────

@router.get(
    "/loss-config",
    response_model=list[LossRuleOut],
    summary="List loss config rules (global + account-specific)",
)
async def list_loss_config(
    _: Auth,
    account_id: str | None = None,
) -> list[LossRuleOut]:
    async with get_public_session() as session:
        if account_id:
            rows = await session.execute(text("""
                SELECT id, account_id, name, condition_type, condition_value,
                       loss_pct, priority, description
                FROM loss_config
                WHERE account_id = :acct OR account_id IS NULL
                ORDER BY priority
            """), {"acct": account_id})
        else:
            rows = await session.execute(text("""
                SELECT id, account_id, name, condition_type, condition_value,
                       loss_pct, priority, description
                FROM loss_config
                ORDER BY priority
            """))
        return [LossRuleOut.model_validate(dict(r._mapping)) for r in rows.fetchall()]


@router.post(
    "/loss-config",
    response_model=LossRuleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a loss config rule",
)
async def create_loss_rule(
    body: LossRuleIn,
    _: Auth,
) -> LossRuleOut:
    table = LossConfig.__table__
    async with get_public_session() as session:
        stmt = (
            insert(table)
            .values(
                account_id=body.account_id,
                name=body.name,
                condition_type=body.condition_type,
                condition_value=body.condition_value,
                loss_pct=body.loss_pct,
                priority=body.priority,
                description=body.description,
            )
            .returning(
                table.c.id, table.c.account_id, table.c.name, table.c.condition_type,
                table.c.condition_value, table.c.loss_pct, table.c.priority, table.c.description,
            )
        )
        row = (await session.execute(stmt)).fetchone()
    return LossRuleOut.model_validate(dict(row._mapping))


@router.put(
    "/loss-config/{rule_id}",
    response_model=LossRuleOut,
    summary="Update a loss config rule",
)
async def update_loss_rule(
    rule_id: int,
    body: LossRuleIn,
    _: Auth,
) -> LossRuleOut:
    async with get_public_session() as session:
        rows = await session.execute(text("""
            UPDATE loss_config
            SET account_id = :acct, name = :name, condition_type = :ct,
                condition_value = :cv, loss_pct = :lp, priority = :pr,
                description = :desc
            WHERE id = :id
            RETURNING id, account_id, name, condition_type, condition_value,
                      loss_pct, priority, description
        """), {
            "id": rule_id,
            "acct": body.account_id,
            "name": body.name,
            "ct": body.condition_type,
            "cv": body.condition_value,
            "lp": body.loss_pct,
            "pr": body.priority,
            "desc": body.description,
        })
        row = rows.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Loss rule not found")
    return LossRuleOut.model_validate(dict(row._mapping))


@router.delete(
    "/loss-config/{rule_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a loss config rule",
)
async def delete_loss_rule(
    rule_id: int,
    _: Auth,
) -> None:
    async with get_public_session() as session:
        result = await session.execute(
            delete(LossConfig.__table__).where(LossConfig.__table__.c.id == rule_id)
        )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Loss rule not found")


# ── Dispatching config CRUD ───────────────────────────────────────────────────

@router.get(
    "/dispatching-config",
    response_model=list[DispatchingWeightOut],
    summary="List dispatching weights for an account",
)
async def list_dispatching_config(
    account_id: str,
    _: Auth,
    punto_dispacciamento: str | None = None,
) -> list[DispatchingWeightOut]:
    async with get_public_session() as session:
        if punto_dispacciamento:
            rows = await session.execute(text("""
                SELECT id, account_id, punto_dispacciamento, periodo, pct
                FROM dispatching_config
                WHERE account_id = :acct AND punto_dispacciamento = :pd
                ORDER BY periodo
            """), {"acct": account_id, "pd": punto_dispacciamento})
        else:
            rows = await session.execute(text("""
                SELECT id, account_id, punto_dispacciamento, periodo, pct
                FROM dispatching_config
                WHERE account_id = :acct
                ORDER BY punto_dispacciamento, periodo
            """), {"acct": account_id})
        return [DispatchingWeightOut.model_validate(dict(r._mapping)) for r in rows.fetchall()]


@router.put(
    "/dispatching-config",
    response_model=dict,
    summary="Set all 96 period weights for a dispatching point (replaces existing)",
)
async def set_dispatching_weights(
    account_id: str,
    body: DispatchingWeightIn,
    _: Auth,
) -> dict:
    if len(body.weights) != 96:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Expected 96 weights, got {len(body.weights)}",
        )
    total = sum(body.weights)
    if not (0.999 <= total <= 1.001):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Weights must sum to 1.0, got {total:.6f}",
        )

    table = DispatchingConfig.__table__
    async with get_public_session() as session:
        await session.execute(text("""
            DELETE FROM dispatching_config
            WHERE account_id = :acct AND punto_dispacciamento = :pd
        """), {"acct": account_id, "pd": body.punto_dispacciamento})

        rows = [
            {
                "account_id": account_id,
                "punto_dispacciamento": body.punto_dispacciamento,
                "periodo": i + 1,
                "pct": body.weights[i],
            }
            for i in range(96)
        ]
        await session.execute(insert(table).values(rows))

    return {
        "message": "Dispatching weights saved",
        "account_id": account_id,
        "punto_dispacciamento": body.punto_dispacciamento,
        "periods": 96,
    }


@router.delete(
    "/dispatching-config",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete dispatching weights for an account + dispatching point",
)
async def delete_dispatching_config(
    account_id: str,
    punto_dispacciamento: str,
    _: Auth,
) -> None:
    async with get_public_session() as session:
        await session.execute(text("""
            DELETE FROM dispatching_config
            WHERE account_id = :acct AND punto_dispacciamento = :pd
        """), {"acct": account_id, "pd": punto_dispacciamento})
