"""
Ingestion runner — processes all XML files for one or all accounts.

Usage:
    py -m backend.ingestion.ingest --account=BAT
    py -m backend.ingestion.ingest --all

Pipeline per file:
  1. Fast count of files (directory listing only — no ZIP opening)
  2. Pre-load all already-processed filenames in ONE DB query per account
  3. Walk files as a generator (no full list materialisation)
  4. For each new file: read ZIP bytes in-memory, parse, upsert, log
  5. Process _CONCURRENCY files concurrently (asyncio semaphore)
     in chunks of _CHUNK to keep memory bounded

No temp files are ever written to disk — ZIP bytes are read directly
into memory and discarded after parsing.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import zipfile
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
from backend.ingestion.file_walker import FileEntry, count_account_files, walk_account, walk_root
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

# Concurrency controls
_CONCURRENCY = 5    # files processed simultaneously (bounded by DB pool_size=10)
_CHUNK_SIZE = 100   # max FileEntry objects held in memory at once


def schema_for(account_id: str) -> str:
    upper = account_id.upper()
    if upper in ACCOUNT_SCHEMA_MAP:
        return ACCOUNT_SCHEMA_MAP[upper]
    # Fallback: normalise name as-is
    return account_id.lower().replace(" ", "_").replace(".", "_").replace("à", "a")


async def _load_processed_names(session) -> set[str]:
    """Load all file_names with status='ok' in a single query."""
    from sqlalchemy import text
    result = await session.execute(
        text("SELECT file_name FROM files WHERE status = 'ok'")
    )
    return {row[0] for row in result}


def _read_xml_from_zip(zip_path: Path, xml_name: str) -> bytes:
    """
    Read the XML entry from a ZIP archive entirely in memory.
    Returns raw XML bytes — no file is written to disk.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        xml_entries = [e for e in zf.namelist() if e.lower().endswith(".xml")]
        if not xml_entries:
            raise ValueError(f"No XML file found inside {zip_path.name!r}")
        # Use xml_name as hint; fall back to first entry
        target = xml_name if xml_name in zf.namelist() else xml_entries[0]
        return zf.read(target)


async def process_file(account_id: str, entry: FileEntry, schema: str) -> None:
    """Parse and ingest one XML file, logging result in files table."""
    xml_name = entry.xml_name
    zip_path = entry.zip_path

    async with get_session(schema) as session:
        try:
            # Read ZIP in-memory — no extraction to disk
            if zip_path.name.lower().endswith(".zip"):
                xml_bytes = _read_xml_from_zip(zip_path, xml_name)
                result = route_file(xml_bytes=xml_bytes, file_name=xml_name)
            else:
                # Bare .xml file (rare, legacy)
                result = route_file(zip_path)

            meta = result.filename_meta

            if result.shape == "f2g":
                count = await upsert_pod_metadata(
                    session,
                    result.f2g_records,
                    account_id=account_id,
                )
                logger.info("%s | pod_metadata: +%d", xml_name, count)
                await log_file(
                    session,
                    file_name=xml_name,
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
                    source_file=xml_name,
                    tipo_dato=tipo_dato,
                )
                logger.info(
                    "%s | curves: +%d skipped:%d", xml_name, inserted, skipped
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
                    source_file=xml_name,
                )
                logger.info("%s | totals: +%d", xml_name, count)

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
                    xml_name, deleted, result.annullamento_pods,
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
                        source_file=xml_name,
                    )

            await log_file(
                session,
                file_name=xml_name,
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
            logger.error("ERROR %s: %s", xml_name, exc)
            try:
                from backend.parser.filename_parser import parse_filename
                try:
                    m = parse_filename(xml_name)
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
                        file_name=xml_name,
                        account_id=account_id,
                        status="error",
                        error_message=str(exc),
                        **fmeta,
                    )
            except Exception as log_exc:
                logger.error("Failed to log error for %s: %s", xml_name, log_exc)
            raise  # re-raise so caller can distinguish ok vs error and skip ZIP deletion


_ACCOUNT_TIMEOUT_SECONDS = 3600  # 1 hour per account max


async def ingest_account(
    account_id: str,
    data_root: Path | None = None,
    on_scan_start: Callable[[], None] | None = None,
    on_files_found: Callable[[int], None] | None = None,
    on_file_done: Callable[[], None] | None = None,
) -> tuple[int, int, int]:
    """
    Ingest all new XML files for one account.

    Returns (files_ok, files_error, files_skipped).

    Strategy:
      1. Fast count (directory listing, no ZIP open) → report total to UI
      2. Pre-load processed filenames set (one DB query)
      3. Generator walk — yields entries lazily
      4. Process in chunks of _CHUNK_SIZE with _CONCURRENCY semaphore
    """
    schema = schema_for(account_id)
    account_root = (data_root or DATA_ROOT) / account_id

    if not account_root.exists():
        logger.warning("Account root not found: %s — skipping", account_root)
        return 0, 0, 0

    # 1. Fast count (no ZIP opening)
    if on_scan_start:
        on_scan_start()
    total = count_account_files(account_root)
    logger.info("Ingesting %s (%s) — %d files on disk", account_id, schema, total)
    if on_files_found:
        on_files_found(total)

    # 2. Pre-load already-processed filenames in ONE query
    async with get_session(schema) as s:
        processed = await _load_processed_names(s)
    logger.info("%s: %d already processed (will skip)", account_id, len(processed))

    # 3. Walk as generator + semaphore concurrency
    sem = asyncio.Semaphore(_CONCURRENCY)
    ok = error = skipped = 0

    async def _run_one(entry: FileEntry) -> str:
        """Returns 'ok' | 'error' | 'skip'."""
        if entry.xml_name in processed:
            # Already committed ok in DB — source ZIP no longer needed
            entry.zip_path.unlink(missing_ok=True)
            return "skip"
        async with sem:
            try:
                await process_file(account_id, entry, schema)
                # DB commit succeeded → flow: sync→parse→validate→mark→delete
                entry.zip_path.unlink(missing_ok=True)
                return "ok"
            except Exception as exc:
                logger.error("Unhandled error on %s: %s", entry.xml_name, exc)
                return "error"  # keep ZIP — will retry on next run

    chunk: list[FileEntry] = []

    async def _flush_chunk() -> None:
        nonlocal ok, error, skipped
        if not chunk:
            return
        results = await asyncio.gather(*[_run_one(e) for e in chunk])
        for r in results:
            if r == "ok":
                ok += 1
            elif r == "error":
                error += 1
            else:
                skipped += 1
            if on_file_done:
                on_file_done()
        chunk.clear()

    i = 0
    for entry in walk_account(account_root, account_id):
        chunk.append(entry)
        i += 1
        if i % 500 == 0:
            logger.info("  Progress: %d queued / %d total", i, total)
        if len(chunk) >= _CHUNK_SIZE:
            await _flush_chunk()

    await _flush_chunk()  # remainder

    logger.info("Done %s — ok:%d errors:%d skipped:%d", account_id, ok, error, skipped)
    return ok, error, skipped


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
    # Suppress SQLAlchemy internal SQL statement logging — engine.echo=False alone
    # does not silence the sqlalchemy.engine logger when basicConfig sets root to INFO
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    data_root = Path(args.data_path) if args.data_path else None

    if args.all:
        asyncio.run(ingest_all(data_root=data_root))
    else:
        asyncio.run(ingest_account(args.account, data_root=data_root))


if __name__ == "__main__":
    main()
