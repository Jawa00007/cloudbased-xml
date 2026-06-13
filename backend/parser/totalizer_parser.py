"""
SII totalizer parser — Shape 2 (band totals, no quarter-hourly curves).

Real XML structure for totalizer files mirrors curve files but without <Ea>.
Fields in <Misura>: TipoDato, Raccolta, Validato, PotMax, CausaOstativa,
                    EaF1–EaF6, ErF1–ErF6, PotF1–PotF6
Fields in <DatiPdp>: Trattamento, Tensione
Fields in <DatiPod>: Pod, MeseAnno, DataMisura, DataPrest (switching files)

Flusso 2 correction fields (TipoRettifica, Motivazione) appear in <Misura>.
Motivazione=3 (annullamento) → caller must DELETE, not upsert.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date


@dataclass
class TotalizerRecord:
    """One band-total measurement record (one POD, one date)."""
    pod: str
    data_misura: date | None
    data_prest: date | None
    mese_anno: str | None
    tipo_dato: str | None
    raccolta: str | None
    validato: str | None
    tensione: int | None
    trattamento: str | None
    pot_max: float | None
    ea_f1: float | None
    ea_f2: float | None
    ea_f3: float | None
    ea_f4: float | None
    ea_f5: float | None
    ea_f6: float | None
    ea_m: float | None
    er_f1: float | None
    er_f2: float | None
    er_f3: float | None
    pot_f1: float | None
    pot_f2: float | None
    pot_f3: float | None
    er_f4: float | None
    er_f5: float | None
    er_f6: float | None
    pot_f4: float | None
    pot_f5: float | None
    pot_f6: float | None
    erc_f1: float | None
    erc_f2: float | None
    erc_f3: float | None
    erc_f4: float | None
    erc_f5: float | None
    erc_f6: float | None
    eri_f1: float | None
    eri_f2: float | None
    eri_f3: float | None
    eri_f4: float | None
    eri_f5: float | None
    eri_f6: float | None
    tipo_rettifica: str | None
    motivazione: int | None     # 3 = annullamento → caller must delete
    data_rilevazione: date | None


def _parse_italian_float(value: str | None) -> float | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped.replace(",", "."))


def _parse_date_ddmmyyyy(value: str | None) -> date | None:
    if not value:
        return None
    try:
        day, month, year = value.strip().split("/")
        return date(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return None


def extract_totalizer_record(
    dati_pod: ET.Element,
    source_file: str,
) -> TotalizerRecord:
    """
    Extract a TotalizerRecord from a single <DatiPod> block.

    Field locations:
    - Pod, MeseAnno, DataMisura, DataPrest → directly in <DatiPod>
    - Trattamento, Tensione                → in <DatiPdp>
    - TipoDato, Raccolta, Validato,
      PotMax, EaF1-6, ErF1-6, PotF1-6,
      TipoRettifica, Motivazione           → in <Misura>

    Raises:
        ValueError: If the POD identifier is missing.
    """
    pod = (dati_pod.findtext("Pod") or "").strip()
    if not pod:
        raise ValueError(f"Missing <Pod> in DatiPod block in {source_file!r}")

    mese_anno = (dati_pod.findtext("MeseAnno") or "").strip() or None
    data_misura = _parse_date_ddmmyyyy(dati_pod.findtext("DataMisura"))
    data_prest = _parse_date_ddmmyyyy(dati_pod.findtext("DataPrest"))

    # DatiPdp block
    dati_pdp = dati_pod.find("DatiPdp")
    trattamento: str | None = None
    tensione: int | None = None
    if dati_pdp is not None:
        trattamento = (dati_pdp.findtext("Trattamento") or "").strip() or None
        t_text = dati_pdp.findtext("Tensione")
        tensione = int(t_text) if t_text and t_text.strip().isdigit() else None

    # Misura block
    misura = dati_pod.find("Misura")
    if misura is None:
        # Annullamento Flusso 2 — no Misura present, return minimal record
        return TotalizerRecord(
            pod=pod, data_misura=data_misura, data_prest=data_prest,
            mese_anno=mese_anno, tipo_dato=None, raccolta=None, validato=None,
            tensione=tensione, trattamento=trattamento, pot_max=None,
            ea_f1=None, ea_f2=None, ea_f3=None, ea_f4=None, ea_f5=None,
            ea_f6=None, ea_m=None, er_f1=None, er_f2=None, er_f3=None,
            pot_f1=None, pot_f2=None, pot_f3=None,
            er_f4=None, er_f5=None, er_f6=None,
            pot_f4=None, pot_f5=None, pot_f6=None,
            erc_f1=None, erc_f2=None, erc_f3=None, erc_f4=None, erc_f5=None, erc_f6=None,
            eri_f1=None, eri_f2=None, eri_f3=None, eri_f4=None, eri_f5=None, eri_f6=None,
            tipo_rettifica=None, motivazione=3, data_rilevazione=None,
        )

    tipo_dato = (misura.findtext("TipoDato") or "").strip() or None
    raccolta = (misura.findtext("Raccolta") or "").strip() or None
    validato = (misura.findtext("Validato") or "").strip() or None

    motivazione_text = (misura.findtext("Motivazione") or "").strip()
    motivazione = int(motivazione_text) if motivazione_text.isdigit() else None

    data_rilevazione = _parse_date_ddmmyyyy(misura.findtext("DataRilevazione"))

    return TotalizerRecord(
        pod=pod,
        data_misura=data_misura,
        data_prest=data_prest,
        mese_anno=mese_anno,
        tipo_dato=tipo_dato,
        raccolta=raccolta,
        validato=validato,
        tensione=tensione,
        trattamento=trattamento,
        pot_max=_parse_italian_float(misura.findtext("PotMax")),
        ea_f1=_parse_italian_float(misura.findtext("EaF1")),
        ea_f2=_parse_italian_float(misura.findtext("EaF2")),
        ea_f3=_parse_italian_float(misura.findtext("EaF3")),
        ea_f4=_parse_italian_float(misura.findtext("EaF4")),
        ea_f5=_parse_italian_float(misura.findtext("EaF5")),
        ea_f6=_parse_italian_float(misura.findtext("EaF6")),
        ea_m=_parse_italian_float(misura.findtext("EaM")),
        er_f1=_parse_italian_float(misura.findtext("ErF1")),
        er_f2=_parse_italian_float(misura.findtext("ErF2")),
        er_f3=_parse_italian_float(misura.findtext("ErF3")),
        pot_f1=_parse_italian_float(misura.findtext("PotF1")),
        pot_f2=_parse_italian_float(misura.findtext("PotF2")),
        pot_f3=_parse_italian_float(misura.findtext("PotF3")),
        er_f4=_parse_italian_float(misura.findtext("ErF4")),
        er_f5=_parse_italian_float(misura.findtext("ErF5")),
        er_f6=_parse_italian_float(misura.findtext("ErF6")),
        pot_f4=_parse_italian_float(misura.findtext("PotF4")),
        pot_f5=_parse_italian_float(misura.findtext("PotF5")),
        pot_f6=_parse_italian_float(misura.findtext("PotF6")),
        erc_f1=_parse_italian_float(misura.findtext("ErcF1")),
        erc_f2=_parse_italian_float(misura.findtext("ErcF2")),
        erc_f3=_parse_italian_float(misura.findtext("ErcF3")),
        erc_f4=_parse_italian_float(misura.findtext("ErcF4")),
        erc_f5=_parse_italian_float(misura.findtext("ErcF5")),
        erc_f6=_parse_italian_float(misura.findtext("ErcF6")),
        eri_f1=_parse_italian_float(misura.findtext("EriF1")),
        eri_f2=_parse_italian_float(misura.findtext("EriF2")),
        eri_f3=_parse_italian_float(misura.findtext("EriF3")),
        eri_f4=_parse_italian_float(misura.findtext("EriF4")),
        eri_f5=_parse_italian_float(misura.findtext("EriF5")),
        eri_f6=_parse_italian_float(misura.findtext("EriF6")),
        tipo_rettifica=(misura.findtext("TipoRettifica") or "").strip() or None,
        motivazione=motivazione,
        data_rilevazione=data_rilevazione,
    )


def parse_totalizer_file(
    root: ET.Element,
    source_file: str,
) -> list[TotalizerRecord]:
    """
    Parse all <DatiPod> blocks in a totalizer-type XML file.
    A single file can contain multiple PODs — all are returned.
    """
    records: list[TotalizerRecord] = []

    dati_pod_elements = root.findall("DatiPod")
    if not dati_pod_elements:
        raise ValueError(f"No <DatiPod> blocks found in {source_file!r}")

    for dati_pod in dati_pod_elements:
        records.append(extract_totalizer_record(dati_pod, source_file))

    return records
