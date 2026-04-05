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

This module intentionally mirrors the interface the WebDAV client will use
later — swapping local for cloud requires only replacing this module.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SubfolderMeta:
    """Metadata parsed from a subfolder name like 2G_05779711000_04393470879."""
    meter_type: str          # "2G" or "TME"
    piva_distributore: str
    piva_utente: str
    raw_name: str


@dataclass
class FileEntry:
    """A single XML file ready for parsing."""
    account_id: str
    subfolder: SubfolderMeta
    file_path: Path          # absolute path to the extracted .xml file
    file_name: str           # bare .xml filename (without .zip)


def _parse_subfolder(name: str) -> SubfolderMeta | None:
    """
    Parse a subfolder name into components.
    Returns None for unrecognised names (PDFs, #recycle, etc.).
    """
    parts = name.split("_", 2)
    if len(parts) != 3:
        return None
    meter_type, piva_dist, piva_utente = parts
    if meter_type not in {"2G", "TME"}:
        return None
    return SubfolderMeta(
        meter_type=meter_type,
        piva_distributore=piva_dist,
        piva_utente=piva_utente,
        raw_name=name,
    )


def _extract_xml_from_zip(zip_path: Path) -> Path:
    """
    Extract the XML file from a .xml.zip archive.
    Extracts into a sibling _extracted/ directory; skips if already present.

    Returns the path to the extracted .xml file.
    """
    extract_dir = zip_path.parent / "_extracted"
    extract_dir.mkdir(exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        xml_entries = [e for e in zf.namelist() if e.lower().endswith(".xml")]
        if not xml_entries:
            raise ValueError(f"No XML file found inside {zip_path.name!r}")

        entry_name = xml_entries[0]
        dest = extract_dir / Path(entry_name).name

        if not dest.exists():
            dest.write_bytes(zf.read(entry_name))

    return dest


def _iter_date_folder(date_folder: Path) -> list[Path]:
    """
    Return extracted XML paths from all .xml.zip files in a MMDD folder.
    Non-zip files (txt reports, etc.) are silently skipped.
    """
    xml_paths: list[Path] = []
    for entry in sorted(date_folder.iterdir()):
        name_lower = entry.name.lower()
        if name_lower.endswith(".xml.zip") or name_lower.endswith(".zip"):
            xml_paths.append(_extract_xml_from_zip(entry))
        elif name_lower.endswith(".xml"):
            xml_paths.append(entry)
        # skip .txt and other files
    return xml_paths


def walk_account(account_root: Path, account_id: str) -> list[FileEntry]:
    """
    Walk all subfolders under an account directory and return FileEntry
    objects for every XML file found.

    Traversal: account_root/<subfolder>/<year>/<MMDD>/*.xml.zip

    Args:
        account_root: Path to the account folder, e.g. data/BAT/
        account_id:   Account identifier string, e.g. "BAT"
    """
    entries: list[FileEntry] = []

    if not account_root.exists():
        raise FileNotFoundError(f"Account root not found: {account_root}")

    for subfolder_dir in sorted(account_root.iterdir()):
        if not subfolder_dir.is_dir():
            continue  # skip PDFs and other loose files

        meta = _parse_subfolder(subfolder_dir.name)
        if meta is None:
            continue

        # Walk year/ subdirectories
        for year_dir in sorted(subfolder_dir.iterdir()):
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue

            # Walk MMDD/ subdirectories
            for date_dir in sorted(year_dir.iterdir()):
                if not date_dir.is_dir():
                    continue

                for xml_path in _iter_date_folder(date_dir):
                    entries.append(FileEntry(
                        account_id=account_id,
                        subfolder=meta,
                        file_path=xml_path,
                        file_name=xml_path.name,
                    ))

    return entries


def walk_root(data_root: Path) -> list[FileEntry]:
    """
    Walk all account folders under the Cloud_SII data root.
    The account_id is taken from the top-level folder name.
    """
    all_entries: list[FileEntry] = []

    for account_dir in sorted(data_root.iterdir()):
        if not account_dir.is_dir():
            continue
        if account_dir.name.startswith("#"):
            continue
        all_entries.extend(walk_account(account_dir, account_dir.name))

    return all_entries
