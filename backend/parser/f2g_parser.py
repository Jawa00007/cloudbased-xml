"""
F2G parser — dispatching point (DatiPod) metadata.

F2G files have a completely different structure from all other SII flows:
  - No <Misura> block
  - No <Ea> curves or band totals
  - <CodContrDisp> lives in <IdentificativiFlusso> (shared across all PODs)
  - Each <DatiPod> has <DataInizio> (valid_from) and optional <DataFine> (valid_to)
  - <Trattamento> and <Tensione> are in <DatiPdp>

Target table: pod_metadata
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date


@dataclass
class F2GRecord:
    pod: str
    codice_dp: str | None
    tensione: int | None
    trattamento: str | None
    valid_from: date | None
    valid_to: date | None
    source_file: str


def _parse_italian_date(value: str | None) -> date | None:
    """Parse DD/MM/YYYY → date. Returns None if missing or malformed."""
    if not value:
        return None
    try:
        day, month, year = value.strip().split("/")
        return date(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return None


def parse_f2g_file(root: ET.Element, source_file: str) -> list[F2GRecord]:
    """
    Extract all POD dispatching-point records from an F2G XML root.

    Args:
        root:        Parsed XML root element of an F2G file.
        source_file: Filename (for traceability — stored in pod_metadata.source_file).

    Returns:
        List of F2GRecord — one per <DatiPod> block.

    Raises:
        ValueError: If no <DatiPod> blocks are found (malformed file).
    """
    # CodContrDisp is shared across all PODs in the file
    codice_dp = (root.findtext("IdentificativiFlusso/CodContrDisp") or "").strip() or None

    records: list[F2GRecord] = []

    for dati_pod in root.findall(".//DatiPod"):
        pod = (dati_pod.findtext("Pod") or "").strip()
        if not pod:
            continue

        valid_from = _parse_italian_date(dati_pod.findtext("DataInizio"))
        valid_to = _parse_italian_date(dati_pod.findtext("DataFine"))

        dati_pdp = dati_pod.find("DatiPdp")
        tensione_raw = dati_pdp.findtext("Tensione") if dati_pdp is not None else None
        trattamento = (dati_pdp.findtext("Trattamento") or "").strip() or None if dati_pdp is not None else None

        tensione: int | None = None
        if tensione_raw:
            try:
                tensione = int(tensione_raw.strip())
            except ValueError:
                pass

        records.append(F2GRecord(
            pod=pod,
            codice_dp=codice_dp,
            tensione=tensione,
            trattamento=trattamento,
            valid_from=valid_from,
            valid_to=valid_to,
            source_file=source_file,
        ))

    if not records:
        raise ValueError(f"F2G file {source_file!r} contains no <DatiPod> blocks")

    return records
