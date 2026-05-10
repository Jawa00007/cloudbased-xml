"""
SII parser router — top-level entry point for processing a single XML file.

Ties together:
  - filename_parser  → FilenameMetadata
  - shape_detector   → DataShape
  - curve_parser     → list[CurveRecord]
  - totalizer_parser → list[TotalizerRecord]

Returns a ParseResult that the ingestion pipeline hands off to the DB layer.
VNO2G dual files produce both curve and totalizer records in one result.

route_file() accepts either:
  - route_file(file_path)                       — read from disk (tests / CLI)
  - route_file(xml_bytes=b"...", file_name="x") — parse from in-memory bytes
                                                   (production: no temp file)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .curve_parser import CurveRecord, parse_curve_file
from .f2g_parser import F2GRecord, parse_f2g_file
from .filename_parser import FilenameMetadata, parse_filename
from .shape_detector import DataShape, detect_shape, is_vno2g_dual
from .totalizer_parser import TotalizerRecord, parse_totalizer_file


@dataclass
class ParseResult:
    """
    Output of routing and parsing one SII XML file.

    Exactly one of curve_records / totalizer_records / f2g_records will be
    populated per shape — except VNO2G which populates both curve and totalizer.
    """
    filename_meta: FilenameMetadata
    shape: DataShape
    curve_records: list[CurveRecord] = field(default_factory=list)
    totalizer_records: list[TotalizerRecord] = field(default_factory=list)
    f2g_records: list[F2GRecord] = field(default_factory=list)
    # Flusso 2: annullamento PODs that must be DELETED (not upserted)
    annullamento_pods: list[str] = field(default_factory=list)


def route_file(
    file_path: Path | None = None,
    *,
    xml_bytes: bytes | None = None,
    file_name: str | None = None,
) -> ParseResult:
    """
    Parse a single SII XML file.

    Two calling conventions:
      route_file(Path("/app/data/..."))               — reads from disk
      route_file(xml_bytes=b"...", file_name="x.xml") — parses from memory

    Steps:
      1. Parse filename metadata
      2. Parse XML (from disk or from bytes)
      3. Detect shape
      4. Dispatch to correct parser
      5. Handle VNO2G dual output and Flusso 2 annullamento

    Raises:
        ValueError: On filename pattern mismatch, missing required fields,
                    or invalid period counts. Caller must catch and log to
                    the `files` table — never silently discard.
    """
    if xml_bytes is not None:
        # In-memory path — no disk read, no temp file
        _file_name = file_name or ""
        root = ET.fromstring(xml_bytes)
    elif file_path is not None:
        # Disk path — used by tests and CLI
        _file_name = file_path.name
        root = ET.parse(file_path).getroot()
    else:
        raise ValueError("route_file requires either file_path or xml_bytes")

    filename_meta = parse_filename(_file_name)
    cod_flusso = filename_meta.cod_flusso
    mese_anno = filename_meta.mese_anno
    source_file = _file_name

    shape = detect_shape(cod_flusso, root)

    result = ParseResult(filename_meta=filename_meta, shape=shape)

    if shape == "f2g":
        result.f2g_records = parse_f2g_file(root, source_file)
        return result

    if shape == "curve" or shape == "flusso2":
        result.curve_records = parse_curve_file(root, mese_anno, source_file)

        # Flusso 2: collect annullamento PODs (Motivazione=3 → delete)
        if shape == "flusso2":
            result.annullamento_pods = _collect_annullamento_pods(root)

        # VNO2G dual: also extract totalizer bands from the same file
        if is_vno2g_dual(cod_flusso, root):
            result.totalizer_records = parse_totalizer_file(root, source_file)

        return result

    if shape == "totalizer":
        result.totalizer_records = parse_totalizer_file(root, source_file)
        return result

    # Unreachable — detect_shape always returns a known value
    raise RuntimeError(f"Unknown shape {shape!r} for {source_file!r}")  # pragma: no cover


def _collect_annullamento_pods(root: ET.Element) -> list[str]:
    """
    For Flusso 2 files, return PODs where Motivazione=3 (annullamento).
    These records must be DELETED from measurements, not upserted.
    The <Misura> section is absent for these PODs.
    """
    pods: list[str] = []
    for dati_pod in root.findall(".//DatiPod"):
        motivazione = (dati_pod.findtext("Motivazione") or "").strip()
        if motivazione == "3":
            pod = (dati_pod.findtext("Pod") or "").strip()
            if pod:
                pods.append(pod)
    return pods
