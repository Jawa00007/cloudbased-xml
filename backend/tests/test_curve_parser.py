"""Tests for backend/parser/curve_parser.py"""

import xml.etree.ElementTree as ET
from datetime import date
import pytest
from backend.parser.curve_parser import parse_curve_file
from backend.parser.curve_parser import _parse_italian_float as parse_italian_float


class TestParseItalianFloat:
    def test_comma_decimal(self):
        assert parse_italian_float("1,740") == pytest.approx(1.740)

    def test_integer_value(self):
        assert parse_italian_float("200") == pytest.approx(200.0)

    def test_none_returns_none(self):
        assert parse_italian_float(None) is None

    def test_empty_string_returns_none(self):
        assert parse_italian_float("") is None


class TestParseCurveFile:
    def test_valid_file_96_periods_tipo_e(self, pdo2g_xml):
        root = ET.parse(pdo2g_xml).getroot()
        records = parse_curve_file(root, "01/2025", "sample_pdo2g.xml")
        # 1 day × 96 periods
        assert len(records) == 96
        r = records[0]
        assert r.pod == "IT001E11222047"
        assert r.data_misura == date(2025, 1, 1)
        assert r.periodo == 1
        assert r.tipo_dato == "E"
        assert r.dst == 0
        assert r.ea_kwh == pytest.approx(1.740)

    def test_italian_decimal_converted(self, pdo2g_xml):
        root = ET.parse(pdo2g_xml).getroot()
        records = parse_curve_file(root, "01/2025", "sample_pdo2g.xml")
        # E96 = "2,070" → 2.070
        assert records[95].ea_kwh == pytest.approx(2.070)

    def test_tipo_dato_s_routes_to_secondary(self, pdo2g_secondary_xml):
        root = ET.parse(pdo2g_secondary_xml).getroot()
        records = parse_curve_file(root, "01/2025", "sample_pdo2g_secondary.xml")
        assert len(records) == 96
        assert all(r.tipo_dato == "S" for r in records)

    def test_dst_spring_forward_accepted(self, pdo2g_dst_spring_xml):
        """Dst=1 day has fewer than 96 Ea attributes — must NOT raise.
        Parser still emits 96 records but missing periods (E9-E12) have ea_kwh=None."""
        root = ET.parse(pdo2g_dst_spring_xml).getroot()
        records = parse_curve_file(root, "03/2025", "sample_dst_spring.xml")
        dst0 = [r for r in records if r.dst == 0]
        dst1 = [r for r in records if r.dst == 1]
        assert len(dst0) == 96
        assert len(dst1) == 96
        # Missing periods (E9–E12) should be None, not a hard error
        missing = [r for r in dst1 if r.ea_kwh is None]
        assert len(missing) > 0

    def test_dst_stored_per_record(self, pdo2g_dst_spring_xml):
        root = ET.parse(pdo2g_dst_spring_xml).getroot()
        records = parse_curve_file(root, "03/2025", "sample_dst_spring.xml")
        assert any(r.dst == 1 for r in records)

    def test_wrong_period_count_dst0_raises(self):
        """Dst=0 day with 95 attributes must raise ValueError."""
        # Build a minimal XML with only 95 E attributes on a Dst=0 day
        attrs = " ".join(f'E{i}="1,000"' for i in range(1, 96))  # only E1–E95
        xml_str = f"""<FlussoMisure>
          <IdentificativiFlusso><MeseAnno>01/2025</MeseAnno></IdentificativiFlusso>
          <DatiPod>
            <Pod>IT001E00000001</Pod>
            <DatiPdp><Trattamento>O</Trattamento><Tensione>230</Tensione></DatiPdp>
            <Misura>
              <TipoDato>E</TipoDato>
              <Raccolta>P</Raccolta>
              <Validato>S</Validato>
              <Ea Dst="0" {attrs}>01</Ea>
            </Misura>
          </DatiPod>
        </FlussoMisure>"""
        root = ET.fromstring(xml_str)
        with pytest.raises(ValueError, match="96"):
            parse_curve_file(root, "01/2025", "bad_periods.xml")

    def test_flusso2_missing_tipo_dato_accepted(self, rfo2g_xml):
        """Flusso 2 files have no <TipoDato> — must not raise, tipo_dato=None or 'E'."""
        root = ET.parse(rfo2g_xml).getroot()
        records = parse_curve_file(root, "01/2025", "sample_rfo2g.xml")
        assert len(records) == 96
        # TipoDato absent → treated as None/E for measurement routing
        assert records[0].tipo_dato is None or records[0].tipo_dato == "E"

    def test_causa_ostativa_converted_to_bool(self, pdo2g_xml):
        root = ET.parse(pdo2g_xml).getroot()
        records = parse_curve_file(root, "01/2025", "sample_pdo2g.xml")
        assert records[0].causa_ostativa is False  # "NO" → False

    def test_tensione_and_trattamento_from_datipdp(self, pdo2g_xml):
        root = ET.parse(pdo2g_xml).getroot()
        records = parse_curve_file(root, "01/2025", "sample_pdo2g.xml")
        assert records[0].tensione == 230
        assert records[0].trattamento == "O"
