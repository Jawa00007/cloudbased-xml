"""
ANAGRAFICA parser — master POD register from ZIP/CSV files.

File naming convention:
    ANAGRAFICA_YYYYMM_<PIvaUtente>_<PuntoDispacciamento>.zip
    (or .csv directly)

CSV rules:
  - Filter: only rows where the "filter" column = "O" (case-insensitive)
  - POD normalization: use only first 14 characters
  - Italian decimal separator (comma → period) for CONSUMO_TOT

Column detection:
  The parser first looks for recognized column header names (case-insensitive).
  If headers are not found, it falls back to positional column index mapping
  defined in COLUMN_INDEX_MAP.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


# ── Data record ────────────────────────────────────────────────────────────────

@dataclass
class AnagraficaRecord:
    piva_utente: str | None
    piva_distributore: str | None
    pod: str                        # 14-char normalized
    pod_raw: str                    # original value before normalization
    punto_dispacciamento: str | None
    tipo_misuratore: str | None
    trattamento: str | None
    tensione: int | None
    codice_tariffa: str | None
    consumo_tot: float | None
    included: bool                  # True = col filter = "O"
    mese_anno: str                  # MM/YYYY derived from filename
    source_file: str


# ── Column name aliases (case-insensitive) ────────────────────────────────────

_COL_ALIASES: dict[str, list[str]] = {
    "piva_utente":          ["pivautente", "piva_utente", "partitaivautente", "piva utente"],
    "piva_distributore":    ["pivadistributore", "piva_distributore", "partitaivadistributore"],
    "pod":                  ["pod", "codicepod", "codice_pod"],
    "punto_dispacciamento": ["puntodispacciamento", "punto_dispac", "puntodispacc", "dispatchingpoint"],
    "tipo_misuratore":      ["tipomisuratore", "tipo_mis", "tipomis"],
    "trattamento":          ["trattamento"],
    "tensione":             ["tensione"],
    "codice_tariffa":       ["codicetariffa", "codice_tariffa", "cod_tariffa", "codtariffa"],
    "consumo_tot":          ["consumo_tot", "consumotot", "consumo tot", "annualkwh"],
    "filter_col":           ["f", "filtro", "filter", "includi", "flag"],
}

# Positional fallback (0-based column indices) — adjust to match your CSV layout
# Column F in Excel = index 5
_COL_INDEX_FALLBACK: dict[str, int] = {
    "piva_utente":          0,
    "piva_distributore":    1,
    "pod":                  3,
    "punto_dispacciamento": 6,
    "tipo_misuratore":      7,
    "trattamento":          8,
    "tensione":             9,
    "codice_tariffa":       10,
    "consumo_tot":          11,
    "filter_col":           5,     # Column F = index 5
}


# ── Filename parser ────────────────────────────────────────────────────────────

_FILENAME_RE = re.compile(
    r"ANAGRAFICA[_-](\d{6})[_-]([^_.-]+)[_-]([^.]+)",
    re.IGNORECASE,
)


def parse_anagrafica_filename(filename: str) -> dict[str, str]:
    """
    Extract metadata from an ANAGRAFICA filename.

    Pattern: ANAGRAFICA_YYYYMM_PIvaUtente_PuntoDisp[.zip|.csv]

    Returns dict with keys: mese_anno, piva_utente, punto_dispacciamento
    """
    stem = Path(filename).stem
    m = _FILENAME_RE.match(stem)
    if not m:
        return {"mese_anno": "", "piva_utente": "", "punto_dispacciamento": ""}
    yyyymm, piva, punto = m.group(1), m.group(2), m.group(3)
    mese_anno = f"{yyyymm[4:6]}/{yyyymm[:4]}"   # YYYYMM → MM/YYYY
    return {"mese_anno": mese_anno, "piva_utente": piva, "punto_dispacciamento": punto}


# ── CSV reader ────────────────────────────────────────────────────────────────

def _resolve_columns(headers: list[str]) -> dict[str, int | None]:
    """
    Map logical field names → column indices using header names.
    Falls back to positional mapping for any field not found by name.
    """
    normalized = [h.lower().strip().replace(" ", "_") for h in headers]
    mapping: dict[str, int | None] = {}

    for field_name, aliases in _COL_ALIASES.items():
        idx: int | None = None
        for alias in aliases:
            try:
                idx = normalized.index(alias.replace(" ", "_"))
                break
            except ValueError:
                continue
        if idx is None:
            idx = _COL_INDEX_FALLBACK.get(field_name)
        mapping[field_name] = idx

    return mapping


def _safe_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _safe_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def _cell(row: list[str], idx: int | None) -> str | None:
    if idx is None or idx >= len(row):
        return None
    v = row[idx].strip()
    return v or None


def _parse_csv_rows(
    reader: csv.reader,
    mese_anno: str,
    source_file: str,
    piva_utente_from_filename: str | None = None,
) -> list[AnagraficaRecord]:
    records: list[AnagraficaRecord] = []
    col_map: dict[str, int | None] | None = None

    for i, row in enumerate(reader):
        if not row:
            continue

        # First non-empty row → detect headers
        if col_map is None:
            col_map = _resolve_columns(row)
            continue

        # Filter: only include rows where filter_col = "O"
        filter_val = (_cell(row, col_map["filter_col"]) or "").upper()
        included = filter_val == "O"
        if not included:
            continue  # skip excluded rows entirely

        pod_raw = _cell(row, col_map["pod"]) or ""
        pod_normalized = pod_raw[:14].strip()
        if not pod_normalized:
            continue  # skip rows with no POD

        piva_utente = _cell(row, col_map["piva_utente"]) or piva_utente_from_filename
        piva_dist   = _cell(row, col_map["piva_distributore"])
        punto       = _cell(row, col_map["punto_dispacciamento"])
        tipo_mis    = _cell(row, col_map["tipo_misuratore"])
        trattamento = _cell(row, col_map["trattamento"])
        tensione    = _safe_int(_cell(row, col_map["tensione"]))
        cod_tar     = _cell(row, col_map["codice_tariffa"])
        consumo_raw = _cell(row, col_map["consumo_tot"])
        consumo_tot = _safe_float(consumo_raw)

        records.append(AnagraficaRecord(
            piva_utente=piva_utente,
            piva_distributore=piva_dist,
            pod=pod_normalized,
            pod_raw=pod_raw,
            punto_dispacciamento=punto,
            tipo_misuratore=tipo_mis,
            trattamento=trattamento,
            tensione=tensione,
            codice_tariffa=cod_tar,
            consumo_tot=consumo_tot,
            included=True,
            mese_anno=mese_anno,
            source_file=source_file,
        ))

    return records


# ── Public API ────────────────────────────────────────────────────────────────

def parse_anagrafica_bytes(
    data: bytes,
    filename: str,
    account_id: str,
) -> list[AnagraficaRecord]:
    """
    Parse ANAGRAFICA data from raw bytes (ZIP or CSV).

    Accepts:
      - A ZIP file containing one or more CSV files
      - A raw CSV file

    Returns a list of AnagraficaRecord for rows where filter column = "O".
    """
    meta = parse_anagrafica_filename(filename)
    mese_anno = meta["mese_anno"]
    piva_utente_fn = meta["piva_utente"] or None

    all_records: list[AnagraficaRecord] = []

    # Detect ZIP vs CSV
    if filename.lower().endswith(".zip") or data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                for csv_name in csv_names:
                    raw = zf.read(csv_name).decode("utf-8-sig", errors="replace")
                    reader = csv.reader(io.StringIO(raw), delimiter=";")
                    all_records.extend(
                        _parse_csv_rows(reader, mese_anno, csv_name, piva_utente_fn)
                    )
        except zipfile.BadZipFile:
            # Treat as raw CSV
            raw = data.decode("utf-8-sig", errors="replace")
            reader = csv.reader(io.StringIO(raw), delimiter=";")
            all_records.extend(
                _parse_csv_rows(reader, mese_anno, filename, piva_utente_fn)
            )
    else:
        raw = data.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(raw), delimiter=";")
        all_records.extend(
            _parse_csv_rows(reader, mese_anno, filename, piva_utente_fn)
        )

    return all_records


def parse_anagrafica_file(path: str | Path, account_id: str) -> list[AnagraficaRecord]:
    """Parse an ANAGRAFICA ZIP/CSV from disk."""
    p = Path(path)
    return parse_anagrafica_bytes(p.read_bytes(), p.name, account_id)
