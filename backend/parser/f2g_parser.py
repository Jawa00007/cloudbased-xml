"""
F2G parser — enriched dispatching point (DatiPod) metadata.

F2G files have a completely different structure from all other SII flows:
  - No <Misura> block
  - No <Ea> curves or band totals
  - <CodContrDisp> lives in <IdentificativiFlusso> (shared across all PODs)
  - Each <DatiPod> has <DataInizio> (valid_from) and optional <DataFine> (valid_to)
  - <Trattamento> and <Tensione> are in <DatiPdp>
  - PIvaUtente / PIvaDistributore may appear in <IdentificativiFlusso>

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
    # Extended fields
    piva_utente: str | None
    piva_distributore: str | None
    punto_dispacciamento: str | None
    tipo_misuratore: str | None
    codice_tariffa: str | None
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


def _text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    raw = el.findtext(path)
    return raw.strip() or None if raw else None


def parse_f2g_file(
    root: ET.Element,
    source_file: str,
    piva_utente_from_filename: str | None = None,
    piva_distributore_from_filename: str | None = None,
) -> list[F2GRecord]:
    """
    Extract all POD dispatching-point records from an F2G XML root.

    Args:
        root:                          Parsed XML root element of an F2G file.
        source_file:                   Filename (for traceability).
        piva_utente_from_filename:     PIva extracted from the filename (fallback).
        piva_distributore_from_filename: PIva distributore from the filename.

    Returns:
        List of F2GRecord — one per <DatiPod> block.
    """
    ident = root.find("IdentificativiFlusso")

    codice_dp = _text(ident, "CodContrDisp")

    # PIva values — try XML first, fall back to filename-parsed values
    piva_utente = _text(ident, "PIvaUtente") or _text(ident, "PIVAUtente") or piva_utente_from_filename
    piva_distributore = (
        _text(ident, "PIvaDistributore")
        or _text(ident, "PIVADistributore")
        or piva_distributore_from_filename
    )

    records: list[F2GRecord] = []

    for dati_pod in root.findall(".//DatiPod"):
        pod = (dati_pod.findtext("Pod") or "").strip()
        if not pod:
            continue

        valid_from = _parse_italian_date(dati_pod.findtext("DataInizio"))
        valid_to   = _parse_italian_date(dati_pod.findtext("DataFine"))

        dati_pdp = dati_pod.find("DatiPdp")
        tensione_raw = _text(dati_pdp, "Tensione")
        trattamento  = _text(dati_pdp, "Trattamento")
        codice_tariffa = _text(dati_pdp, "CodiceTariffa") or _text(dati_pdp, "CodTariffa")
        tipo_misuratore = _text(dati_pdp, "TipoMisuratore") or _text(dati_pdp, "TipoMis")

        # PuntoDispacciamento may be on each DatiPod or shared in IdentificativiFlusso
        punto_disp = (
            _text(dati_pod, "PuntoDispacciamento")
            or _text(dati_pod, "CodContrDisp")
            or _text(ident, "PuntoDispacciamento")
        )

        tensione: int | None = None
        if tensione_raw:
            try:
                tensione = int(tensione_raw)
            except ValueError:
                pass

        records.append(F2GRecord(
            pod=pod,
            codice_dp=codice_dp,
            tensione=tensione,
            trattamento=trattamento,
            valid_from=valid_from,
            valid_to=valid_to,
            piva_utente=piva_utente,
            piva_distributore=piva_distributore,
            punto_dispacciamento=punto_disp,
            tipo_misuratore=tipo_misuratore,
            codice_tariffa=codice_tariffa,
            source_file=source_file,
        ))

    if not records:
        raise ValueError(f"F2G file {source_file!r} contains no <DatiPod> blocks")

    return records
