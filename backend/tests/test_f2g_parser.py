"""Tests for backend/parser/f2g_parser.py"""

import xml.etree.ElementTree as ET
from datetime import date
import pytest
from backend.parser.f2g_parser import parse_f2g_file


class TestParseF2GFile:
    def test_records_extracted(self, f2g_xml):
        root = ET.parse(f2g_xml).getroot()
        records = parse_f2g_file(root, "sample_f2g.xml")
        assert len(records) == 2

    def test_pod_extracted(self, f2g_xml):
        root = ET.parse(f2g_xml).getroot()
        records = parse_f2g_file(root, "sample_f2g.xml")
        assert records[0].pod == "IT001E95381966"
        assert records[1].pod == "IT001E94653083"

    def test_codice_dp_shared_from_header(self, f2g_xml):
        """CodContrDisp lives in IdentificativiFlusso, shared across all PODs."""
        root = ET.parse(f2g_xml).getroot()
        records = parse_f2g_file(root, "sample_f2g.xml")
        assert records[0].codice_dp == "DP2311"
        assert records[1].codice_dp == "DP2311"

    def test_valid_from_parsed(self, f2g_xml):
        root = ET.parse(f2g_xml).getroot()
        records = parse_f2g_file(root, "sample_f2g.xml")
        assert records[0].valid_from == date(2021, 9, 1)
        assert records[1].valid_from == date(2022, 1, 1)

    def test_valid_to_none_when_absent(self, f2g_xml):
        root = ET.parse(f2g_xml).getroot()
        records = parse_f2g_file(root, "sample_f2g.xml")
        assert records[0].valid_to is None

    def test_tensione_from_datipdp(self, f2g_xml):
        root = ET.parse(f2g_xml).getroot()
        records = parse_f2g_file(root, "sample_f2g.xml")
        assert records[0].tensione == 220
        assert records[1].tensione == 380

    def test_trattamento_from_datipdp(self, f2g_xml):
        root = ET.parse(f2g_xml).getroot()
        records = parse_f2g_file(root, "sample_f2g.xml")
        assert records[0].trattamento == "O"
        assert records[1].trattamento == "F"

    def test_source_file_stored(self, f2g_xml):
        root = ET.parse(f2g_xml).getroot()
        records = parse_f2g_file(root, "sample_f2g.xml")
        assert records[0].source_file == "sample_f2g.xml"

    def test_empty_file_raises(self):
        root = ET.fromstring("<FlussoMisure CodFlusso='F2G'><IdentificativiFlusso/></FlussoMisure>")
        with pytest.raises(ValueError, match="no <DatiPod>"):
            parse_f2g_file(root, "empty.xml")
