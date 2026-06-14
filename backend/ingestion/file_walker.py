"""
Local file walker for SII XML ingestion.

Real folder structure (confirmed from BAT account):

  <root>/
    <account_id>/                          e.g. BAT/
      <MeterType>_<PIVAdist>_<PIVAutente>/ e.g. 2G_05779711000_04393470879/
        <year>/                            e.g. 2025/
          <MMDD>/                          e.g. 0101/
            <filename>.xml.zip
            ElencoFileGiornalieri<HH>.txt
            ReportAmmissibilità*.txt

Files are always ZIP-compressed with a double extension: <name>.xml.zip
The ZIP contains a single entry with the bare .xml filename.

Design notes:
- walk_account() is a generator — yields one FileEntry at a time without
  loading the whole list into memory.  Callers can start processing immediately
  while the walk continues.
- No ZIP is opened during the scan.  FileEntry.xml_name is derived by stripping
  the trailing .zip suffix from the archive name (e.g. "foo.xml.zip" → "foo.xml").
- Extraction to disk has been removed entirely.  Callers read XML bytes from the
  ZIP in-memory using zipfile.ZipFile + ZipFile.read().
- count_account_files() does a fast directory-listing-only count (no ZIP open)
  so callers can report an accurate total before processing begins.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SubfolderMeta:
    """Metadata parsed from a subfolder name like 2G_05779711000_04393470879."""
    meter_type: str          # "2G" or "TME"
    piva_distributore: str
    piva_utente: str
    raw_name: str


@dataclass
class FileEntry:
    """A single XML-ZIP file ready for in-memory extraction and parsing."""
    account_id: str
    subfolder: SubfolderMeta
    zip_path: Path    # absolute path to the .xml.zip archive
    xml_name: str     # bare .xml filename inside the archive (zip_path.stem)


def _parse_subfolder(name: str) -> SubfolderMeta | None:
    """
    Parse a subfolder name into components.
    Returns None for unrecognised names (PDFs, #recycle, etc.).
    """
    parts = name.split("_", 2)
    if len(parts) != 3:
        logger.debug("Skipping subfolder %r: expected 3 underscore-parts, got %d", name, len(parts))
        return None
    meter_type, piva_dist, piva_utente = parts
    if meter_type not in {"2G", "TME"}:
        logger.debug("Skipping subfolder %r: MeterType %r not in {'2G', 'TME'}", name, meter_type)
        return None
    return SubfolderMeta(
        meter_type=meter_type,
        piva_distributore=piva_dist,
        piva_utente=piva_utente,
        raw_name=name,
    )


def _iter_date_folder(date_folder: Path) -> Iterator[Path]:
    """
    Yield ZIP paths from a MMDD folder — no ZIP opening, no extraction.
    Non-zip files (txt reports, bare .xml files) are handled as fallback.
    """
    for entry in sorted(date_folder.iterdir()):
        n = entry.name.lower()
        if n.endswith(".zip"):
            yield entry
        elif n.endswith(".xml") and not entry.is_dir():
            # Bare XML (not inside a ZIP) — treat zip_path == file itself,
            # xml_name == file.name so the rest of the pipeline is unchanged.
            yield entry


def walk_account(account_root: Path, account_id: str) -> Iterator[FileEntry]:
    """
    Yield FileEntry objects for every XML-ZIP under an account directory.

    This is a generator — processing can begin on the first file while the
    directory walk continues.  No ZIP is opened; no file is extracted to disk.

    Traversal: account_root/<subfolder>/<year>/<MMDD>/*.xml.zip
    """
    if not account_root.exists():
        raise FileNotFoundError(f"Account root not found: {account_root}")

    for subfolder_dir in sorted(account_root.iterdir()):
        if not subfolder_dir.is_dir():
            continue

        meta = _parse_subfolder(subfolder_dir.name)
        if meta is None:
            continue

        for year_dir in sorted(subfolder_dir.iterdir()):
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue

            for date_dir in sorted(year_dir.iterdir()):
                if not date_dir.is_dir():
                    continue

                for zip_path in _iter_date_folder(date_dir):
                    # For .xml.zip: stem gives "foo.xml" — correct.
                    # For plain .zip (S2G, SOS, SOF): stem gives "foo" — append ".xml"
                    # so parse_filename() and deduplication keys are consistent.
                    # For bare .xml files: use file.name directly.
                    if zip_path.name.lower().endswith(".zip"):
                        stem = zip_path.stem
                        xml_name = stem if stem.lower().endswith(".xml") else stem + ".xml"
                    else:
                        xml_name = zip_path.name
                    yield FileEntry(
                        account_id=account_id,
                        subfolder=meta,
                        zip_path=zip_path,
                        xml_name=xml_name,
                    )


def count_account_files(account_root: Path) -> int:
    """
    Fast count of processable files under account_root.

    Does directory listing only — no ZIP is opened.  Used to seed the
    progress bar total before the generator walk begins.
    """
    if not account_root.exists():
        return 0
    count = 0
    for subfolder_dir in account_root.iterdir():
        if not subfolder_dir.is_dir():
            continue
        if _parse_subfolder(subfolder_dir.name) is None:
            continue
        for year_dir in subfolder_dir.iterdir():
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue
            for date_dir in year_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                count += sum(
                    1 for e in date_dir.iterdir()
                    if not e.is_dir() and (
                        e.name.lower().endswith(".zip")
                        or e.name.lower().endswith(".xml")
                    )
                )
    return count


def walk_root(data_root: Path) -> Iterator[FileEntry]:
    """
    Yield all FileEntry objects under the Cloud_SII data root (all accounts).
    The account_id is taken from the top-level folder name.
    """
    for account_dir in sorted(data_root.iterdir()):
        if not account_dir.is_dir():
            continue
        if account_dir.name.startswith("#"):
            continue
        yield from walk_account(account_dir, account_dir.name)
