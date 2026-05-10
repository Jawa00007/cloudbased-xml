"""
Ingestion runner — processes all XML files for one or all accounts.

Usage:
    py -m backend.ingestion.ingest --account=BAT
    py -m backend.ingestion.ingest --all

For each file:
  1. Check if already in files table (skip duplicates)
  2. Parse filename + XML
  3. Upsert records into correct table
  4. Log result in files table
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Callable
from pathlib import Path

# psycopg requires SelectorEventLoop on Windows (not the default ProactorEventLoop)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.config import settings
from backend.db.session import get_session
from backend.db.upsert import (
    delete_annullamento,
    log_correction,
    log_file,
    upsert_curve_records,
    upsert_pod_metadata,
    upsert_totalizer_records,
)
from backend.ingestion.file_walker import walk_account, walk_root
from backend.parser.router import route_file

logger = logging.getLogger(__name__)

# Resolved at runtime so SII_DATA_PATH env var is honoured
DATA_ROOT = Path(settings.SII_DATA_PATH)

# Account folder name → PostgreSQL schema name
# Keys are matched case-insensitively so Italian server uppercase
# folder names (BAT, DINAMO, EGOGREEN …) map correctly.
ACCOUNT_SCHEMA_MAP: dict[str, str] = {
    "BAT": "bat",
    "CH4": "ch4",
    "DINAMO": "dinamo_trade",
    "DINAMO TRADE": "dinamo_trade",
    "EGOGREEN": "egogreen",
    "ENERGETICA": "energetica",
    "ENERGIT": "energit",
    "ENJOY": "enjoy_energy",
    "ENJOY ENERGY": "enjoy_energy",
    "ONDA": "onda_piu",
    "ONDA PIU": "onda_piu",
    "POWER": "power_it",
    "POWER.IT": "power_it",
    "POWERIT": "power_it",
    "ROYAL": "royal_group",
    "ROYAL GROUP": "royal_group",
    "SOS": "sos",
    "TOP": "top_energy",
    "TOP ENERGY": "top_energy",
}


def schema_for(account_id: str) -> str:
    upper = account_id.upper()
    if upper in ACCOUNT_SCHEMA_MAP:
        return ACCOUNT_SCHEMA_MAP[upper]
    # Fallback: normalise name as-is
    return account_id.lower().replace(" ", "_").replace(".", "_").replace("à", "a")


async def already_processed(session, file_name: str) -> bool:
    """Return True if the file was previously processed with status=ok."""
    from sqlalchemy import select, text
    result = await session.execute(
        text("SELECT status FROM files WHERE file_name = :fn"),
        {"fn": file_name},
    )
    row = result.fetchone()
    return row is not None and row[0] == "ok"


async def process_file(account_id: str, file_path: Path, schema: str) -> None:
    """Parse and ingest one XML file, logging result in files table."""
    file_name = file_path.name

    async with get_session(schema) as session:
        # Skip already-processed files
        if await already_processed(session, file_name):
            logger.debug("Skip (already processed): %s", file_name)
            return

        try:
            result = route_file(file_path)
            meta = result.filename_meta

            if result.shape == "f2g":
                count = await upsert_pod_metadata(
                    session,
                    result.f2g_records,
                    account_id=account_id,
                )
                logger.info("%s | pod_metadata: +%d", file_name, count)
                await log_file(
                    session,
                    file_name=file_name,
                    account_id=account_id,
                    cod_flusso=meta.cod_flusso,
                    piva_distributore=meta.piva_distributore,
                    piva_utente=meta.piva_utente,
                    mese_anno=meta.mese_anno,
                    file_timestamp=meta.file_timestamp,
                    progressivo=meta.progressivo,
                    sm_status=meta.sm_status,
                    status="ok",
                )
                return

            # Upsert curve records
            if result.curve_records:
                tipo_dato = result.curve_records[0].tipo_dato if result.curve_records else None
                inserted, skipped = await upsert_curve_records(
                    session,
                    result.curve_records,
                    account_id=account_id,
                    cod_flusso=meta.cod_flusso,
                    mese_anno=meta.mese_anno,
                    file_timestamp=meta.file_timestamp,
                    progressivo=meta.progressivo,
                    source_file=file_name,
                    tipo_dato=tipo_dato,
                )
                logger.info(
                    "%s | curves: +%d skipped:%d", file_name, inserted, skipped
                )

            # Upsert totalizer records
            if result.totalizer_records:
                count = await upsert_totalizer_records(
                    session,
                    result.totalizer_records,
                    account_id=account_id,
                    cod_flusso=meta.cod_flusso,
                    file_timestamp=meta.file_timestamp,
                    progressivo=meta.progressivo,
                    source_file=file_name,
                )
                logger.info("%s | totals: +%d", file_name, count)

            # Handle Flusso 2 annullamento (delete)
            if result.annullamento_pods:
                deleted = await delete_annullamento(
                    session,
                    account_id=account_id,
                    pods=result.annullamento_pods,
                    mese_anno=meta.mese_anno,
                )
                logger.info(
                    "%s | annullamento: deleted %d records for PODs %s",
                    file_name, deleted, result.annullamento_pods,
                )

            # Log Flusso 2 corrections to audit table
            if result.shape == "flusso2":
                for rec in result.curve_records:
                    await log_correction(
                        session,
                        account_id=account_id,
                        pod=rec.pod,
                        mese_anno=meta.mese_anno,
                        tipo_rettifica=None,
                        motivazione=None,
                        data_rilevazione=None,
                        cod_flusso=meta.cod_flusso,
                        source_file=file_name,
                    )

            await log_file(
                session,
                file_name=file_name,
                account_id=account_id,
                cod_flusso=meta.cod_flusso,
                piva_distributore=meta.piva_distributore,
                piva_utente=meta.piva_utente,
                mese_anno=meta.mese_anno,
                file_timestamp=meta.file_timestamp,
                progressivo=meta.progressivo,
                sm_status=meta.sm_status,
                status="ok",
            )

        except Exception as exc:
            logger.error("ERROR %s: %s", file_name, exc)
            try:
                # Attempt to parse filename for the log even on error
                from backend.parser.filename_parser import parse_filename
                try:
                    m = parse_filename(file_name)
                    fmeta = dict(
                        cod_flusso=m.cod_flusso,
                        piva_distributore=m.piva_distributore,
                        piva_utente=m.piva_utente,
                        mese_anno=m.mese_anno,
                        file_timestamp=m.file_timestamp,
                        progressivo=m.progressivo,
                        sm_status=m.sm_status,
                    )
                except Exception:
                    fmeta = dict(
                        cod_flusso=None, piva_distributore=None, piva_utente=None,
                        mese_anno=None, file_timestamp=None, progressivo=None, sm_status=None,
                    )

                async with get_session(schema) as err_session:
                    await log_file(
                        err_session,
                        file_name=file_name,
                        account_id=account_id,
                        status="error",
                        error_message=str(exc),
                        **fmeta,
                    )
            except Exception as log_exc:
                logger.error("Failed to log error for %s: %s", file_name, log_exc)


async def ingest_account(
    account_id: str,
    data_root: Path | None = None,
    on_scan_start: Callable[[], None] | None = None,
    on_files_found: Callable[[int], None] | None = None,
    on_file_done: Callable[[], None] | None = None,
) -> tuple[int, int, int]:
    """Returns (files_ok, files_error, files_skipped)."""
    schema = schema_for(account_id)
    account_root = (data_root or DATA_ROOT) / account_id

    if on_scan_start:
        on_scan_start()
    entries = walk_account(account_root, account_id)

    logger.info(
        "Ingesting %s (%s) — %d files found", account_id, schema, len(entries)
    )
    if on_files_found:
        on_files_found(len(entries))

    ok = error = skipped = 0
    for i, entry in enumerate(entries, 1):
        if i % 500 == 0:
            logger.info("  Progress: %d / %d", i, len(entries))
        try:
            await process_file(account_id, entry.file_path, schema)
            ok += 1
        except Exception as exc:
            logger.error("Unhandled error on %s: %s", entry.file_name, exc)
            error += 1
        if on_file_done:
            on_file_done()

    logger.info("Done %s — ok:%d errors:%d", account_id, ok, error)
    return ok, error, skipped


_ACCOUNT_TIMEOUT_SECONDS = 3600  # 1 hour per account max


async def ingest_all(
    data_root: Path | None = None,
    on_account: Callable[[str], None] | None = None,
    on_account_done: Callable[[str, int, int, int], None] | None = None,
    on_scan_start: Callable[[], None] | None = None,
    on_files_found: Callable[[int], None] | None = None,
    on_file_done: Callable[[], None] | None = None,
) -> None:
    """
    Ingest all accounts found under data_root.

    on_account: called with account name just before processing starts.
    on_account_done: called with (account, files_ok, files_error, files_skipped)
                     after each account completes.
    on_scan_start/on_files_found/on_file_done: file-level progress callbacks.
    """
    root = data_root or DATA_ROOT
    if not root.exists():
        logger.warning("SII_DATA_PATH %r does not exist — skipping ingestion", str(root))
        return
    for account_dir in sorted(root.iterdir()):
        if account_dir.is_dir() and not account_dir.name.startswith("#"):
            acc_name = account_dir.name
            if on_account:
                on_account(acc_name)
            ok = error = skipped = 0
            try:
                ok, error, skipped = await asyncio.wait_for(
                    ingest_account(
                        acc_name,
                        data_root=root,
                        on_scan_start=on_scan_start,
                        on_files_found=on_files_found,
                        on_file_done=on_file_done,
                    ),
                    timeout=_ACCOUNT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Ingestion timeout: %s exceeded %ds — moving to next account",
                    acc_name, _ACCOUNT_TIMEOUT_SECONDS,
                )
            if on_account_done:
                on_account_done(acc_name, ok, error, skipped)


def main() -> None:
    parser = argparse.ArgumentParser(description="SII ingestion runner")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--account", help="Account name, e.g. BAT")
    group.add_argument("--all", action="store_true", help="Ingest all accounts")
    parser.add_argument(
        "--data-path",
        default=None,
        help="Override SII_DATA_PATH — path to synced SII_CLOUD folder",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    data_root = Path(args.data_path) if args.data_path else None

    if args.all:
        asyncio.run(ingest_all(data_root=data_root))
    else:
        asyncio.run(ingest_account(args.account, data_root=data_root))


if __name__ == "__main__":
    main()
