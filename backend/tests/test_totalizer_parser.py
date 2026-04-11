"""Tests for backend/parser/totalizer_parser.py"""

import xml.etree.ElementTree as ET
from datetime import date
import pytest
from backend.parser.totalizer_parser import parse_totalizer_file


class TestParseTotalizerFile:
    def test_basic_record_extracted(self, snm2g_xml):
        root = ET.parse(snm2g_xml).getroot()
        records = parse_totalizer_file(root, "sample_snm2g.xml")
        assert len(records) == 1
        r = records[0]
        assert r.pod == "IT001E11222047"
        assert r.data_misura == date(2024, 12, 31)
        assert r.tipo_dato == "E"

    def test_italian_decimal_converted(self, snm2g_xml):
        root = ET.parse(snm2g_xml).getroot()
        records = parse_totalizer_file(root, "sample_snm2g.xml")
        r = records[0]
        assert r.ea_f1 == pytest.approx(30.000)
        assert r.ea_f2 == pytest.approx(15.000)
        assert r.ea_f3 == pytest.approx(24.998)
        assert r.er_f1 == pytest.approx(0.785)
        assert r.pot_f1 == pytest.approx(200.000)

    def test_data_prest_stored(self, snm2g_xml):
        """SNM2G files have DataPrest (switching date) — must be stored."""
        root = ET.parse(snm2g_xml).getroot()
        records = parse_totalizer_file(root, "sample_snm2g.xml")
        assert records[0].data_prest == date(2025, 1, 1)

    def test_trattamento_tensione_from_datipdp(self, snm2g_xml):
        root = ET.parse(snm2g_xml).getroot()
        records = parse_totalizer_file(root, "sample_snm2g.xml")
        assert records[0].trattamento == "F"
        assert records[0].tensione == 400
