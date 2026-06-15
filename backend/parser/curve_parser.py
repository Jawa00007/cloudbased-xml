"""
SII curve parser — Shape 1 (quarter-hourly time series).

Real XML structure (confirmed from BAT/PDO2G files):

  <DatiPod>
    <Pod>IT001E91742250</Pod>
    <MeseAnno>12/2024</MeseAnno>
    <DatiPdp>
      <Trattamento>O</Trattamento>
      <Tensione>380</Tensione>
    </DatiPdp>
    <Misura>
      <Raccolta>P</Raccolta>
      <TipoDato>E</TipoDato>
      <CausaOstativa>NO</CausaOstativa>
      <Validato>S</Validato>
      <PotMax>7,924</PotMax>
      <Ea Dst="0" E1="0,046" ... E96="0,047">31</Ea>
      <Er Dst="0" E1="0,005" ... E96="0,006">31</Er>
      <EaF1>7802,489</EaF1>   ← monthly band totals also present in PDO2G
      ...
    </Misura>
  </DatiPod>
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date


@dataclass
class CurveRecord:
    """One quarter-hourly measurement period."""
    pod: str
    data_misura: date
    periodo: int            # 1–96
    ea_kwh: float | None
    er_kvarh: float | None
    dst: int                # 0=normal, 1=spring-fwd, 2=fall-back part1, 3=fall-back part2
    tipo_dato: str | None   # E, S, A — None for Flusso 2 corrections
    raccolta: str | None
    validato: str | None
    tensione: int | None
    trattamento: str | None
    pot_max: float | None
    causa_ostativa: bool | None


def _parse_italian_float(value: str | None) -> float | None:
    """Convert Italian comma-decimal string to float. Returns None if absent/empty."""
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped.replace(",", "."))


def _parse_date(day_number: str, mese_anno: str) -> date:
    """
    Build a date from a day-of-month string and MeseAnno.

    Args:
        day_number: Text content of <Ea>, e.g. "01", "31"
        mese_anno:  MM/YYYY e.g. "01/2013"
    """
    month_str, year_str = mese_anno.split("/")
    return date(int(year_str), int(month_str), int(day_number.strip()))


def _validate_periods(ea_element: ET.Element, dst: int) -> None:
    """
    Validate period count. Only enforced for Dst=0 days.
    Raises ValueError if Dst=0 and period count != 96.
    """
    if dst != 0:
        return
    count = sum(1 for k in ea_element.attrib if k.startswith("E") and k[1:].isdigit())
    if count != 96:
        raise ValueError(
            f"Expected 96 Ea periods for Dst=0 day, found {count}"
        )


def extract_curve_records(
    dati_pod: ET.Element,
    mese_anno_fallback: str,
    source_file: str,
) -> list[CurveRecord]:
    """
    Extract all CurveRecord objects from a single <DatiPod> block.

    Field locations in the real XML:
    - Pod, MeseAnno              → directly in <DatiPod>
    - Trattamento, Tensione      → in <DatiPdp>
    - TipoDato, Raccolta,
      Validato, PotMax,
      CausaOstativa, Ea, Er      → in <Misura>

    Args:
        dati_pod:          A <DatiPod> XML element.
        mese_anno_fallback: MM/YYYY from filename — used if XML lacks <MeseAnno>.
        source_file:       Original filename for error messages.

    Returns:
        List of CurveRecord — one per (day, periodo) combination.

    Raises:
        ValueError: If POD is missing, or Dst=0 day has wrong period count.
    """
    pod = (dati_pod.findtext("Pod") or "").strip()
    if not pod:
        raise ValueError(f"Missing <Pod> in DatiPod block in {source_file!r}")

    # DatiPdp block
    dati_pdp = dati_pod.find("DatiPdp")
    trattamento: str | None = None
    tensione: int | None = None
    if dati_pdp is not None:
        trattamento = (dati_pdp.findtext("Trattamento") or "").strip() or None
        t_text = dati_pdp.findtext("Tensione")
        tensione = int(t_text) if t_text and t_text.strip().isdigit() else None

    # Misura block — all measurement fields live here
    # SOS/S2G files use <Consumo> instead of <Misura> for the measurement block
    misura = dati_pod.find("Misura") or dati_pod.find("Consumo")
    if misura is None:
        # Flusso 2 annullamento (Motivazione=3) has no <Misura> or <Consumo>; caller handles
        return []

    # MeseAnno: check DatiPod direct child first, then inside Misura/Consumo (S2G/SOS
    # files carry <MeseAnno> inside <Consumo>, not as a direct <DatiPod> child), then
    # fall back to the filename AAAAMM.
    mese_anno = (
        dati_pod.findtext("MeseAnno")
        or misura.findtext("MeseAnno")
        or mese_anno_fallback
    ).strip()

    # TipoDato is absent in Flusso 2 correction files — default to None
    tipo_dato = (misura.findtext("TipoDato") or "").strip() or None

    raccolta = (misura.findtext("Raccolta") or "").strip() or None
    validato = (misura.findtext("Validato") or "").strip() or None
    pot_max = _parse_italian_float(misura.findtext("PotMax"))

    causa_text = (misura.findtext("CausaOstativa") or "").strip().upper()
    causa_ostativa: bool | None = None
    if causa_text in ("SI", "S"):
        causa_ostativa = True
    elif causa_text in ("NO", "N"):
        causa_ostativa = False

    # Normalise TipoDato: absent in Flusso 2 corrections → default to E
    # (corrections target existing E records; None would violate NOT NULL)
    effective_tipo_dato = tipo_dato or "E"
    if tipo_dato == "A" and validato and validato.upper() == "S":
        effective_tipo_dato = "E"

    # Update CurveRecord type hint to allow None
    # (Flusso 2 corrections don't carry TipoDato)

    records: list[CurveRecord] = []

    for ea_el in misura.findall("Ea"):
        day_str = (ea_el.text or "").strip()
        if not day_str:
            continue

        dst = int(ea_el.get("Dst", "0"))

        try:
            _validate_periods(ea_el, dst)
            data_misura = _parse_date(day_str, mese_anno)
        except ValueError as exc:
            raise ValueError(
                f"POD {pod!r} day {day_str!r} in {source_file!r}: {exc}"
            ) from exc

        # <Er> element mirrors <Ea> structure — same day, same periods
        er_el = misura.find(f"Er[@Dst='{dst}']") or misura.find("Er")

        for i in range(1, 97):
            attr = f"E{i}"
            ea_kwh = _parse_italian_float(ea_el.get(attr))
            er_kvarh = _parse_italian_float(er_el.get(attr)) if er_el is not None else None

            records.append(CurveRecord(
                pod=pod,
                data_misura=data_misura,
                periodo=i,
                ea_kwh=ea_kwh,
                er_kvarh=er_kvarh,
                dst=dst,
                tipo_dato=effective_tipo_dato,
                raccolta=raccolta,
                validato=validato,
                tensione=tensione,
                trattamento=trattamento,
                pot_max=pot_max,
                causa_ostativa=causa_ostativa,
            ))

    return records


def parse_curve_file(
    root: ET.Element,
    mese_anno_fallback: str,
    source_file: str,
) -> list[CurveRecord]:
    """
    Parse all <DatiPod> blocks in a curve-type XML file.
    A single file can contain multiple PODs — all are returned.
    """
    # Some file types (e.g. SOS, S2G) put MeseAnno at the root level inside
    # <IdentificativiFlusso> rather than inside each <DatiPod>. Extract it
    # once here so extract_curve_records() can use it as a fallback before
    # resorting to the filename-derived AAAAMM.
    root_mese_anno = (root.findtext("IdentificativiFlusso/MeseAnno") or "").strip()
    effective_fallback = root_mese_anno if root_mese_anno else mese_anno_fallback

    all_records: list[CurveRecord] = []

    dati_pod_elements = root.findall("DatiPod")
    if not dati_pod_elements:
        raise ValueError(f"No <DatiPod> blocks found in {source_file!r}")

    for dati_pod in dati_pod_elements:
        all_records.extend(
            extract_curve_records(dati_pod, effective_fallback, source_file)
        )

    return all_records
