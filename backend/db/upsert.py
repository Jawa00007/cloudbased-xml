"""
Upsert functions for all measurement tables.

Deduplication rule (both tables):
  Priority 1: higher file_timestamp wins
  Priority 2: if equal timestamp → higher progressivo wins

All upserts use PostgreSQL ON CONFLICT DO UPDATE with a WHERE clause that
enforces the priority — no application-level read-then-write loops.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.anagrafica import Anagrafica
from backend.models.corrections import Correction
from backend.models.files import FileLog
from backend.models.forecast import ForecastPeriod
from backend.models.measurements import (
    Measurement,
    MeasurementSecondary,
    MeasurementTotalizer,
)
from backend.models.pod_metadata import PodMetadata
from backend.parser.anagrafica_parser import AnagraficaRecord
from backend.parser.curve_parser import CurveRecord
from backend.parser.f2g_parser import F2GRecord
from backend.parser.totalizer_parser import TotalizerRecord


# ── Curve records ──────────────────────────────────────────────────────────────

# 19 columns per curve row → 65535 / 19 = 3449; use 3400 to stay safely under.
_CURVE_CHUNK = 3_400


async def upsert_curve_records(
    session: AsyncSession,
    records: list[CurveRecord],
    account_id: str,
    cod_flusso: str,
    mese_anno: str,
    file_timestamp: datetime,
    progressivo: int,
    source_file: str,
    tipo_dato: str | None,
) -> tuple[int, int]:
    """
    Upsert a batch of CurveRecord rows into measurements or measurements_secondary.

    Routes to the correct table based on tipo_dato:
      E or None (Flusso 2) → measurements
      S                    → measurements_secondary

    Returns:
        (inserted_count, skipped_count) — skipped = existing record won by priority
    """
    if not records:
        return 0, 0

    target = MeasurementSecondary if tipo_dato == "S" else Measurement
    table = target.__table__

    # Deduplicate within this batch — a single XML may contain duplicate
    # (pod, data_misura, periodo, tipo_dato) rows (CardinalityViolation).
    # Keep the row with the highest (file_timestamp, progressivo).
    seen: dict[tuple, dict] = {}
    for r in records:
        key = (r.pod, r.data_misura, r.periodo, r.tipo_dato)
        row = {
            "account_id": account_id,
            "pod": r.pod,
            "data_misura": r.data_misura,
            "periodo": r.periodo,
            "ea_kwh": r.ea_kwh,
            "er_kvarh": r.er_kvarh,
            "dst": r.dst,
            "tipo_dato": r.tipo_dato,
            "raccolta": r.raccolta,
            "validato": r.validato,
            "tensione": r.tensione,
            "trattamento": r.trattamento,
            "pot_max": r.pot_max,
            "causa_ostativa": r.causa_ostativa,
            "cod_flusso": cod_flusso,
            "mese_anno": mese_anno,
            "file_timestamp": file_timestamp,
            "progressivo": progressivo,
            "source_file": source_file,
        }
        if key not in seen:
            seen[key] = row
        else:
            existing = seen[key]
            # Replace if new row has higher priority
            new_ts = file_timestamp or datetime.min
            old_ts = existing["file_timestamp"] or datetime.min
            if new_ts > old_ts or (new_ts == old_ts and progressivo > (existing["progressivo"] or 0)):
                seen[key] = row

    rows = list(seen.values())

    def _make_stmt(chunk: list[dict]):
        return (
            insert(table)
            .values(chunk)
            .on_conflict_do_update(
                # Use index_elements instead of constraint name — the DB may have
                # created the constraint with a schema-prefixed name (e.g.
                # uq_bat_measurements_key) which differs from the model's name.
                index_elements=["account_id", "pod", "data_misura", "periodo", "tipo_dato"],
                set_={
                    "ea_kwh": insert(table).excluded.ea_kwh,
                    "er_kvarh": insert(table).excluded.er_kvarh,
                    "dst": insert(table).excluded.dst,
                    "raccolta": insert(table).excluded.raccolta,
                    "validato": insert(table).excluded.validato,
                    "pot_max": insert(table).excluded.pot_max,
                    "causa_ostativa": insert(table).excluded.causa_ostativa,
                    "cod_flusso": insert(table).excluded.cod_flusso,
                    "file_timestamp": insert(table).excluded.file_timestamp,
                    "progressivo": insert(table).excluded.progressivo,
                    "source_file": insert(table).excluded.source_file,
                },
                where=(
                    (insert(table).excluded.file_timestamp > table.c.file_timestamp)
                    | (
                        (insert(table).excluded.file_timestamp == table.c.file_timestamp)
                        & (insert(table).excluded.progressivo > table.c.progressivo)
                    )
                ),
            )
        )

    total_affected = 0
    for i in range(0, len(rows), _CURVE_CHUNK):
        chunk = rows[i : i + _CURVE_CHUNK]
        result = await session.execute(_make_stmt(chunk))
        total_affected += result.rowcount

    skipped = len(rows) - total_affected
    return total_affected, skipped


# ── Totalizer records ──────────────────────────────────────────────────────────

async def upsert_totalizer_records(
    session: AsyncSession,
    records: list[TotalizerRecord],
    account_id: str,
    cod_flusso: str,
    file_timestamp: datetime,
    progressivo: int,
    source_file: str,
) -> int:
    """
    Insert totalizer records. No deduplication key is defined for totalizters
    (they don't have a periodo), so we do a simple insert and ignore conflicts
    on (account_id, pod, data_misura, cod_flusso) if the same file is replayed.
    """
    if not records:
        return 0

    table = MeasurementTotalizer.__table__

    rows = [
        {
            "account_id": account_id,
            "pod": r.pod,
            "data_misura": r.data_misura,
            "data_prest": r.data_prest,
            "mese_anno": r.mese_anno,
            "tipo_dato": r.tipo_dato,
            "raccolta": r.raccolta,
            "validato": r.validato,
            "tensione": r.tensione,
            "trattamento": r.trattamento,
            "pot_max": r.pot_max,
            "ea_f1": r.ea_f1,
            "ea_f2": r.ea_f2,
            "ea_f3": r.ea_f3,
            "ea_f4": r.ea_f4,
            "ea_f5": r.ea_f5,
            "ea_f6": r.ea_f6,
            "ea_m": r.ea_m,
            "er_f1": r.er_f1,
            "er_f2": r.er_f2,
            "er_f3": r.er_f3,
            "pot_f1": r.pot_f1,
            "pot_f2": r.pot_f2,
            "pot_f3": r.pot_f3,
            "er_f4": r.er_f4,
            "er_f5": r.er_f5,
            "er_f6": r.er_f6,
            "pot_f4": r.pot_f4,
            "pot_f5": r.pot_f5,
            "pot_f6": r.pot_f6,
            "erc_f1": r.erc_f1,
            "erc_f2": r.erc_f2,
            "erc_f3": r.erc_f3,
            "erc_f4": r.erc_f4,
            "erc_f5": r.erc_f5,
            "erc_f6": r.erc_f6,
            "eri_f1": r.eri_f1,
            "eri_f2": r.eri_f2,
            "eri_f3": r.eri_f3,
            "eri_f4": r.eri_f4,
            "eri_f5": r.eri_f5,
            "eri_f6": r.eri_f6,
            "tipo_rettifica": r.tipo_rettifica,
            "motivazione": r.motivazione,
            "data_rilevazione": r.data_rilevazione,
            "cod_flusso": cod_flusso,
            "file_timestamp": file_timestamp,
            "progressivo": progressivo,
            "source_file": source_file,
        }
        for r in records
    ]

    stmt = insert(table).values(rows).on_conflict_do_nothing()
    result = await session.execute(stmt)
    return result.rowcount


# ── Annullamento (Flusso 2 delete) ────────────────────────────────────────────

async def delete_annullamento(
    session: AsyncSession,
    account_id: str,
    pods: list[str],
    mese_anno: str,
) -> int:
    """
    Delete measurements for Motivazione=3 (annullamento) PODs.
    Deletes from both measurements and measurements_secondary.
    """
    if not pods:
        return 0

    deleted = 0
    for table in (Measurement.__table__, MeasurementSecondary.__table__):
        stmt = (
            delete(table)
            .where(table.c.account_id == account_id)
            .where(table.c.pod.in_(pods))
            .where(table.c.mese_anno == mese_anno)
        )
        result = await session.execute(stmt)
        deleted += result.rowcount

    return deleted


# ── Corrections audit log ──────────────────────────────────────────────────────

async def log_correction(
    session: AsyncSession,
    account_id: str,
    pod: str,
    mese_anno: str,
    tipo_rettifica: str | None,
    motivazione: int | None,
    data_rilevazione: date | None,
    cod_flusso: str,
    source_file: str,
) -> None:
    """Insert one row into the corrections audit table."""
    session.add(Correction(
        account_id=account_id,
        pod=pod,
        mese_anno=mese_anno,
        tipo_rettifica=tipo_rettifica,
        motivazione=motivazione,
        data_rilevazione=data_rilevazione,
        cod_flusso=cod_flusso,
        source_file=source_file,
    ))


# ── Pod metadata (F2G) ────────────────────────────────────────────────────────

async def upsert_pod_metadata(
    session: AsyncSession,
    records: list[F2GRecord],
    account_id: str,
) -> int:
    """
    Upsert F2G dispatching-point records into pod_metadata.

    Conflict key: (account_id, pod, valid_from).
    On conflict, always update — newer F2G file is authoritative.
    """
    if not records:
        return 0

    table = PodMetadata.__table__

    rows = [
        {
            "account_id": account_id,
            "pod": r.pod,
            "codice_dp": r.codice_dp,
            "tensione": r.tensione,
            "trattamento": r.trattamento,
            "piva_utente": getattr(r, "piva_utente", None),
            "piva_distributore": getattr(r, "piva_distributore", None),
            "punto_dispacciamento": getattr(r, "punto_dispacciamento", None),
            "tipo_misuratore": getattr(r, "tipo_misuratore", None),
            "codice_tariffa": getattr(r, "codice_tariffa", None),
            "valid_from": r.valid_from,
            "valid_to": r.valid_to,
            "source_file": r.source_file,
        }
        for r in records
    ]

    stmt = (
        insert(table)
        .values(rows)
        .on_conflict_do_update(
            constraint="uq_pod_metadata_key",
            set_={
                "codice_dp": insert(table).excluded.codice_dp,
                "tensione": insert(table).excluded.tensione,
                "trattamento": insert(table).excluded.trattamento,
                "piva_utente": insert(table).excluded.piva_utente,
                "piva_distributore": insert(table).excluded.piva_distributore,
                "punto_dispacciamento": insert(table).excluded.punto_dispacciamento,
                "tipo_misuratore": insert(table).excluded.tipo_misuratore,
                "codice_tariffa": insert(table).excluded.codice_tariffa,
                "valid_to": insert(table).excluded.valid_to,
                "source_file": insert(table).excluded.source_file,
            },
        )
    )

    result = await session.execute(stmt)
    return result.rowcount


# ── Anagrafica (master POD register) ──────────────────────────────────────────

async def upsert_anagrafica(
    session: AsyncSession,
    records: list[AnagraficaRecord],
    account_id: str,
) -> int:
    """
    Upsert ANAGRAFICA records into the anagrafica table.

    Conflict key: (account_id, pod, mese_anno).
    On conflict, always update — a re-uploaded file is authoritative.
    """
    if not records:
        return 0

    table = Anagrafica.__table__

    rows = [
        {
            "account_id": account_id,
            "mese_anno": r.mese_anno,
            "piva_utente": r.piva_utente,
            "piva_distributore": r.piva_distributore,
            "pod": r.pod,
            "pod_raw": r.pod_raw,
            "punto_dispacciamento": r.punto_dispacciamento,
            "tipo_misuratore": r.tipo_misuratore,
            "trattamento": r.trattamento,
            "tensione": r.tensione,
            "codice_tariffa": r.codice_tariffa,
            "consumo_tot": r.consumo_tot,
            "included": r.included,
            "source_file": r.source_file,
        }
        for r in records
    ]

    # 14 columns per row; psycopg3 limit is 65535 params → max 4681 rows per statement
    _ANA_CHUNK = 4_500

    def _make_stmt(chunk: list[dict]):
        return (
            insert(table)
            .values(chunk)
            .on_conflict_do_update(
                constraint="uq_anagrafica_key",
                set_={
                    "piva_utente": insert(table).excluded.piva_utente,
                    "piva_distributore": insert(table).excluded.piva_distributore,
                    "pod_raw": insert(table).excluded.pod_raw,
                    "punto_dispacciamento": insert(table).excluded.punto_dispacciamento,
                    "tipo_misuratore": insert(table).excluded.tipo_misuratore,
                    "trattamento": insert(table).excluded.trattamento,
                    "tensione": insert(table).excluded.tensione,
                    "codice_tariffa": insert(table).excluded.codice_tariffa,
                    "consumo_tot": insert(table).excluded.consumo_tot,
                    "included": insert(table).excluded.included,
                    "source_file": insert(table).excluded.source_file,
                },
            )
        )

    for i in range(0, len(rows), _ANA_CHUNK):
        await session.execute(_make_stmt(rows[i : i + _ANA_CHUNK]))

    return len(records)   # rowcount is unreliable for batch ON CONFLICT upserts


# ── Forecast periods ───────────────────────────────────────────────────────────

# psycopg3 extended-query limit: 65535 params per statement.
# 11 columns per row → max 5957 rows; use 5900 to stay safely under.
_CHUNK = 5_900


async def drop_forecast_unique_idx(session: AsyncSession) -> None:
    """Drop the unique constraint/index on forecast_periods before a bulk insert.
    Handles both the legacy named CONSTRAINT form and the newer standalone INDEX form."""
    await session.execute(text("""
        DO $$ BEGIN
            ALTER TABLE forecast_periods DROP CONSTRAINT IF EXISTS uq_forecast_period_key;
        EXCEPTION WHEN OTHERS THEN NULL; END $$
    """))
    await session.execute(text("DROP INDEX IF EXISTS uq_forecast_period_key"))


async def create_forecast_unique_idx(session: AsyncSession) -> None:
    """Recreate the unique index on forecast_periods after a bulk insert.
    Uses CREATE UNIQUE INDEX IF NOT EXISTS to tolerate concurrent forecast jobs."""
    await session.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_period_key "
        "ON forecast_periods (account_id, pod, forecast_date, periodo)"
    ))


async def delete_forecast_month(
    session: AsyncSession,
    account_id: str,
    mese_anno: str,
) -> None:
    """Delete all forecast rows for an account+month. Called once before streaming inserts."""
    await session.execute(
        text("DELETE FROM forecast_periods WHERE account_id = :acct AND mese_anno = :ma"),
        {"acct": account_id, "ma": mese_anno},
    )


async def insert_forecast_chunk(
    session: AsyncSession,
    rows: list,
    account_id: str,
) -> int:
    """Insert a batch of forecast rows without DELETE (caller manages deletion)."""
    if not rows:
        return 0
    table = ForecastPeriod.__table__
    values = [
        {
            "account_id": account_id,
            "pod": r.pod,
            "mese_anno": r.mese_anno,
            "punto_dispacciamento": r.punto_dispacciamento,
            "forecast_date": r.forecast_date,
            "source_date": r.source_date,
            "periodo": r.periodo,
            "ea_kwh": r.ea_kwh,
            "ea_kwh_with_loss": r.ea_kwh_with_loss,
            "loss_pct": r.loss_pct,
            "source_type": r.source_type,
        }
        for r in rows
    ]
    total = 0
    for i in range(0, len(values), _CHUNK):
        await session.execute(insert(table).values(values[i : i + _CHUNK]))
        total += len(values[i : i + _CHUNK])
    return total


async def upsert_forecast_periods(
    session: AsyncSession,
    rows: list,  # list[ForecastRow] from engine — avoid circular import
    account_id: str,
) -> int:
    """
    Replace forecast rows for one account + month.

    Strategy: DELETE existing month data (fast via index), then INSERT all rows
    in chunks using ORM insert().values(chunk) which uses psycopg3 binary protocol
    (~1.75s per 5900-row chunk, 8-10x faster than unnest text serialization).
    """
    if not rows:
        return 0

    table = ForecastPeriod.__table__
    mese_anno = rows[0].mese_anno

    # Fast DELETE via index on (account_id, mese_anno)
    await session.execute(
        text("DELETE FROM forecast_periods WHERE account_id = :acct AND mese_anno = :ma"),
        {"acct": account_id, "ma": mese_anno},
    )

    seen: set[tuple] = set()
    values: list[dict] = []
    for r in rows:
        key = (account_id, r.pod, r.forecast_date, r.periodo)
        if key in seen:
            continue
        seen.add(key)
        values.append({
            "account_id": account_id,
            "pod": r.pod,
            "mese_anno": r.mese_anno,
            "punto_dispacciamento": r.punto_dispacciamento,
            "forecast_date": r.forecast_date,
            "source_date": r.source_date,
            "periodo": r.periodo,
            "ea_kwh": r.ea_kwh,
            "ea_kwh_with_loss": r.ea_kwh_with_loss,
            "loss_pct": r.loss_pct,
            "source_type": r.source_type,
        })

    total = 0
    for i in range(0, len(values), _CHUNK):
        chunk = values[i : i + _CHUNK]
        await session.execute(insert(table).values(chunk))
        total += len(chunk)
    return total


# ── File log ───────────────────────────────────────────────────────────────────

async def log_file(
    session: AsyncSession,
    *,
    file_name: str,
    account_id: str,
    cod_flusso: str | None,
    piva_distributore: str | None,
    piva_utente: str | None,
    mese_anno: str | None,
    file_timestamp: datetime | None,
    progressivo: int | None,
    sm_status: str | None,
    status: str,
    error_message: str | None = None,
) -> None:
    """
    Log the result of processing one file into the files table.
    Uses INSERT ... ON CONFLICT DO NOTHING so replaying a file is safe.
    """
    stmt = (
        insert(FileLog.__table__)
        .values(
            file_name=file_name,
            account_id=account_id,
            cod_flusso=cod_flusso,
            piva_distributore=piva_distributore,
            piva_utente=piva_utente,
            mese_anno=mese_anno,
            file_timestamp=file_timestamp,
            progressivo=progressivo,
            sm_status=sm_status,
            status=status,
            error_message=error_message,
        )
        .on_conflict_do_update(
            index_elements=["file_name"],
            set_={"status": status, "error_message": error_message},
        )
    )
    await session.execute(stmt)
