"""
Admin routes — ANAGRAFICA upload, loss config CRUD, dispatching config CRUD,
system status.
"""

from __future__ import annotations

import json
import subprocess
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert

from backend.api.auth import Auth, require_admin, require_auth
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

_Auth = Annotated[str, Depends(require_auth)]
_AdminAuth = Annotated[Auth, Depends(require_admin)]


# ── System status ──────────────────────────────────────────────────────────────

class DiskStatus(BaseModel):
    total_gb: float
    used_gb: float
    free_gb: float
    used_pct: int


class ContainerStatus(BaseModel):
    name: str
    status: str
    healthy: bool | None


class SchemaSize(BaseModel):
    schema_name: str
    size_mb: float
    est_rows: int


class SystemStatus(BaseModel):
    disk: DiskStatus
    containers: list[ContainerStatus]
    db_size_gb: float
    db_schemas: list[SchemaSize]


@router.get("/system/status", response_model=SystemStatus, summary="Server & DB health (admin only)")
async def get_system_status(auth: _AdminAuth) -> SystemStatus:
    # Disk usage via df
    disk = DiskStatus(total_gb=0, used_gb=0, free_gb=0, used_pct=0)
    try:
        df = subprocess.run(
            ["df", "-BG", "/"], capture_output=True, text=True, timeout=5
        )
        parts = df.stdout.strip().splitlines()[-1].split()
        # parts: Filesystem 1G-blocks Used Available Use% Mounted
        total = int(parts[1].rstrip("G"))
        used  = int(parts[2].rstrip("G"))
        free  = int(parts[3].rstrip("G"))
        pct   = int(parts[4].rstrip("%"))
        disk  = DiskStatus(total_gb=total, used_gb=used, free_gb=free, used_pct=pct)
    except Exception:
        pass

    # Container statuses via docker ps
    containers: list[ContainerStatus] = []
    try:
        dp = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=10
        )
        for line in dp.stdout.strip().splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            name   = c.get("Names", "")
            state  = c.get("State", "unknown")
            health = c.get("Health", "")
            healthy: bool | None = None
            if health == "healthy":
                healthy = True
            elif health in ("unhealthy", "starting"):
                healthy = False
            containers.append(ContainerStatus(name=name, status=state, healthy=healthy))
    except Exception:
        pass

    # DB total size + per-schema breakdown
    db_size_gb = 0.0
    db_schemas: list[SchemaSize] = []
    try:
        async with get_public_session() as s:
            # Total DB size
            row = (await s.execute(text(
                "SELECT pg_database_size(current_database()) AS sz"
            ))).fetchone()
            if row:
                db_size_gb = round(row[0] / (1024 ** 3), 2)

            # Per-schema sizes (fast — pg_class, no table scan)
            rows = (await s.execute(text("""
                SELECT n.nspname AS schema_name,
                       SUM(pg_total_relation_size(c.oid)) / 1048576.0 AS size_mb,
                       SUM(c.reltuples::bigint) AS est_rows
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
                  AND c.relkind = 'r'
                GROUP BY n.nspname
                ORDER BY SUM(pg_total_relation_size(c.oid)) DESC
            """))).fetchall()
            db_schemas = [
                SchemaSize(
                    schema_name=r[0],
                    size_mb=round(float(r[1]), 1),
                    est_rows=int(r[2]) if r[2] else 0,
                )
                for r in rows
            ]
    except Exception:
        pass

    return SystemStatus(
        disk=disk,
        containers=containers,
        db_size_gb=db_size_gb,
        db_schemas=db_schemas,
    )


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
    _: _Auth,
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
    "/anagrafica/months",
    response_model=list[str],
    summary="List months for which ANAGRAFICA data exists for an account",
)
async def list_anagrafica_months(
    account_id: str,
    _: _Auth,
) -> list[str]:
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        rows = await session.execute(text("""
            SELECT DISTINCT mese_anno FROM anagrafica
            WHERE account_id = :acct
            ORDER BY mese_anno DESC
        """), {"acct": account_id})
        return [r[0] for r in rows.fetchall()]


@router.get(
    "/anagrafica",
    response_model=list[AnagraficaOut],
    summary="List ANAGRAFICA records for an account and month",
)
async def list_anagrafica(
    account_id: str,
    mese_anno: str,
    _: _Auth,
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


@router.delete(
    "/anagrafica",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete all ANAGRAFICA records for an account and month",
)
async def delete_anagrafica(
    account_id: str,
    mese_anno: str,
    _: _Auth,
) -> None:
    schema = schema_for(account_id)
    async with get_session(schema) as session:
        await session.execute(text("""
            DELETE FROM anagrafica
            WHERE account_id = :acct AND mese_anno = :ma
        """), {"acct": account_id, "ma": mese_anno})


# ── Loss config CRUD ──────────────────────────────────────────────────────────

@router.get(
    "/loss-config",
    response_model=list[LossRuleOut],
    summary="List loss config rules (global + account-specific)",
)
async def list_loss_config(
    _: _Auth,
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
    _: _Auth,
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
    _: _Auth,
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
    _: _Auth,
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
    summary="List dispatching weights — global (no account_id) or per-account",
)
async def list_dispatching_config(
    _: _Auth,
    account_id: str | None = None,
    punto_dispacciamento: str | None = None,
) -> list[DispatchingWeightOut]:
    async with get_public_session() as session:
        if account_id is not None:
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
        else:
            # Global weights (account_id IS NULL)
            if punto_dispacciamento:
                rows = await session.execute(text("""
                    SELECT id, account_id, punto_dispacciamento, periodo, pct
                    FROM dispatching_config
                    WHERE account_id IS NULL AND punto_dispacciamento = :pd
                    ORDER BY periodo
                """), {"pd": punto_dispacciamento})
            else:
                rows = await session.execute(text("""
                    SELECT id, account_id, punto_dispacciamento, periodo, pct
                    FROM dispatching_config
                    WHERE account_id IS NULL
                    ORDER BY punto_dispacciamento, periodo
                """))
        return [DispatchingWeightOut.model_validate(dict(r._mapping)) for r in rows.fetchall()]


@router.put(
    "/dispatching-config",
    response_model=dict,
    summary="Set 96 period weights for a dispatching point (global or per-account)",
)
async def set_dispatching_weights(
    body: DispatchingWeightIn,
    _: _Auth,
    account_id: str | None = None,
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
        if account_id is not None:
            await session.execute(text("""
                DELETE FROM dispatching_config
                WHERE account_id = :acct AND punto_dispacciamento = :pd
            """), {"acct": account_id, "pd": body.punto_dispacciamento})
        else:
            await session.execute(text("""
                DELETE FROM dispatching_config
                WHERE account_id IS NULL AND punto_dispacciamento = :pd
            """), {"pd": body.punto_dispacciamento})

        rows = [
            {
                "account_id": account_id,  # None = global
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
    summary="Delete dispatching weights (global or per-account)",
)
async def delete_dispatching_config(
    punto_dispacciamento: str,
    _: _Auth,
    account_id: str | None = None,
) -> None:
    async with get_public_session() as session:
        if account_id is not None:
            await session.execute(text("""
                DELETE FROM dispatching_config
                WHERE account_id = :acct AND punto_dispacciamento = :pd
            """), {"acct": account_id, "pd": punto_dispacciamento})
        else:
            await session.execute(text("""
                DELETE FROM dispatching_config
                WHERE account_id IS NULL AND punto_dispacciamento = :pd
            """), {"pd": punto_dispacciamento})
