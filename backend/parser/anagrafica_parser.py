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
    "piva_utente":          ["pivautente", "piva_utente", "partitaivautente", "piva utente", "piva"],
    "piva_distributore":    ["pivadistributore", "piva_distributore", "partitaivadistributore"],
    "pod":                  ["pod", "codicepod", "codice_pod"],
    "punto_dispacciamento": ["puntodispacciamento", "punto_dispac", "puntodispacc", "dispatchingpoint", "codice_dp"],
    "tipo_misuratore":      ["tipomisuratore", "tipo_mis", "tipomis", "tipo_misuratore"],
    "trattamento":          ["trattamento", "trattamento_03"],
    "tensione":             ["tensione"],
    "codice_tariffa":       ["codicetariffa", "codice_tariffa", "cod_tariffa", "codtariffa"],
    "consumo_tot":          ["consumo_tot", "consumotot", "consumo tot", "annualkwh"],
    # trattamento_04 = Excel column F = the filter column in E-Distribuzione files
    "filter_col":           ["f", "filtro", "filter", "includi", "flag", "trattamento_04"],
}

# Positional fallback (0-based column indices) for when header names are not recognised.
# Matches the E-Distribuzione ANAGRAFICA CSV layout:
#   0=POD, 1=CF, 2=PIVA, 3=Tipo_Misuratore, 4=Trattamento_03, 5=Trattamento_04, 6+=CRPP…
_COL_INDEX_FALLBACK: dict[str, int] = {
    "piva_utente":          2,
    "piva_distributore":    -1,   # not present — will return None safely
    "pod":                  0,
    "punto_dispacciamento": -1,   # not present — taken from filename
    "tipo_misuratore":      3,
    "trattamento":          4,
    "tensione":             -1,
    "codice_tariffa":       -1,
    "consumo_tot":          -1,   # found by name; positional varies with CRPP column count
    "filter_col":           5,    # Trattamento_04 = Excel column F
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
    if idx is None or idx is not None and idx < 0:
        return None
    if idx >= len(row):
        return None
    v = row[idx].strip()
    return v or None


_YYMM_RE = re.compile(r"^(\d{2})(\d{2})$")


def _extract_mese_anno_from_metadata(row: list[str]) -> str | None:
    """
    E-Distribuzione files have a metadata first line like:
      E-DISTRIBUZIONE S.P.A.;CALA;DP2788;2604;05779711000
    Index 3 is a YYMM code: '2604' → YY=26, MM=04 → '04/2026'.
    """
    for cell in row:
        m = _YYMM_RE.match(cell.strip())
        if m:
            yy, mm = int(m.group(1)), int(m.group(2))
            if 1 <= mm <= 12:
                return f"{mm:02d}/{2000 + yy}"
    return None


def _is_header_row(row: list[str]) -> bool:
    """Return True if this row contains 'POD' as a column header."""
    return any(c.strip().upper() == "POD" for c in row)


def _parse_csv_rows(
    reader: csv.reader,
    mese_anno: str,
    source_file: str,
    piva_utente_from_filename: str | None = None,
    punto_dispacciamento_from_filename: str | None = None,
) -> list[AnagraficaRecord]:
    records: list[AnagraficaRecord] = []
    col_map: dict[str, int | None] | None = None
    resolved_mese_anno = mese_anno

    for row in reader:
        if not row:
            continue

        if col_map is None:
            # Keep scanning until we find the real header row (contains "POD")
            if _is_header_row(row):
                col_map = _resolve_columns(row)
            else:
                # Try to extract mese_anno from metadata lines (e.g. YYMM code)
                found = _extract_mese_anno_from_metadata(row)
                if found:
                    resolved_mese_anno = found
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
        punto       = _cell(row, col_map["punto_dispacciamento"]) or punto_dispacciamento_from_filename
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
            mese_anno=resolved_mese_anno,
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
    punto_fn = meta["punto_dispacciamento"] or None

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
                        _parse_csv_rows(reader, mese_anno, csv_name, piva_utente_fn, punto_fn)
                    )
        except zipfile.BadZipFile:
            # Treat as raw CSV
            raw = data.decode("utf-8-sig", errors="replace")
            reader = csv.reader(io.StringIO(raw), delimiter=";")
            all_records.extend(
                _parse_csv_rows(reader, mese_anno, filename, piva_utente_fn, punto_fn)
            )
    else:
        raw = data.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(raw), delimiter=";")
        all_records.extend(
            _parse_csv_rows(reader, mese_anno, filename, piva_utente_fn, punto_fn)
        )

    return all_records


def parse_anagrafica_file(path: str | Path, account_id: str) -> list[AnagraficaRecord]:
    """Parse an ANAGRAFICA ZIP/CSV from disk."""
    p = Path(path)
    return parse_anagrafica_bytes(p.read_bytes(), p.name, account_id)
