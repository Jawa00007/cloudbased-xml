"""
SII XML data shape detector.

Determines which parser to use based on CodFlusso and XML content.
Shape detection always reads the XML — never inferred from CodFlusso alone,
because the same CodFlusso (e.g. PNO2G) can appear in both curve and
totalizer form depending on the SM flag.

Routing order (MUST be respected):
  1. F2G                    → "f2g"       (pod_metadata table)
  2. Flusso 2 correction    → "flusso2"   (measurements table via upsert)
  3. <Ea> present in XML    → "curve"     (measurements / measurements_secondary)
  4. No <Ea>                → "totalizer" (measurements_totalizer)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Literal

DataShape = Literal["f2g", "flusso2", "curve", "totalizer"]

# Flusso 2 correction flow codes (do not hardcode as if/elif — use set membership)
FLUSSO2_CODES: frozenset[str] = frozenset({
    "RFO", "RFO2G",
    "RNO", "RNO2G",
    "RSN", "RSN2G",
    "RNV", "RNV2G",
    "RIN", "RIN2G",
    "SMR", "SMR2G",
    "RTR", "RTR2G",
    "DSR", "DSR2G",
    "AVR", "AVR2G",
    "VPR", "VPR2G",
    "INTR",
})


def detect_shape(cod_flusso: str, root: ET.Element) -> DataShape:
    """
    Determine the data shape for a parsed XML document.

    Args:
        cod_flusso: Upper-cased flow code from the filename (e.g. "PDO2G").
        root:       Parsed XML root element.

    Returns:
        One of: "f2g", "flusso2", "curve", "totalizer"
    """
    # 1. F2G — completely different tag structure, must be caught first
    if cod_flusso == "F2G":
        return "f2g"

    # 2. Flusso 2 corrections — upsert into measurements with audit log
    if cod_flusso in FLUSSO2_CODES:
        return "flusso2"

    # 3. Detect from XML content — presence of any <Ea> element
    #    Search recursively; <Ea> can be nested inside <DatiPod> / <Misura>
    if root.find(".//Ea") is not None:
        return "curve"

    # 4. No <Ea> found — totalizer (band totals only)
    return "totalizer"


def has_ea_curves(root: ET.Element) -> bool:
    """Return True if the XML contains at least one <Ea> element."""
    return root.find(".//Ea") is not None


def is_vno2g_dual(cod_flusso: str, root: ET.Element) -> bool:
    """
    VNO2G files contain BOTH <Ea> curves AND <EaF1-4> totalizer fields.
    They need two separate write operations.
    """
    if cod_flusso != "VNO2G":
        return False
    return (
        root.find(".//Ea") is not None
        and root.find(".//EaF1") is not None
    )
