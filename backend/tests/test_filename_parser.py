"""Tests for backend/parser/filename_parser.py"""

import pytest
from datetime import datetime
from backend.parser.filename_parser import parse_filename


class TestParseFilename:
    def test_standard_filename_with_sm(self):
        name = "05779711000_04393470879_202501_PDO2G_20250118060523_1DP0001_R.xml"
        meta = parse_filename(name)
        assert meta.piva_distributore == "05779711000"
        assert meta.piva_utente == "04393470879"
        assert meta.mese_anno == "01/2025"
        assert meta.cod_flusso == "PDO2G"
        assert meta.file_timestamp == datetime(2025, 1, 18, 6, 5, 23)
        assert meta.progressivo == 1
        assert meta.sm_status == "R"

    def test_sm_status_nr(self):
        name = "05779711000_04393470879_202501_PNO2G_20250118060523_1DP0001_NR.xml"
        meta = parse_filename(name)
        assert meta.sm_status == "NR"
        assert meta.cod_flusso == "PNO2G"

    def test_sm_status_optional(self):
        """Older files (pre-2022) have no _R/_NR suffix — must not raise."""
        name = "05779711000_04393470879_202101_PDO2G_20210118060523_1DP0001.xml"
        meta = parse_filename(name)
        assert meta.sm_status is None
        assert meta.cod_flusso == "PDO2G"

    def test_mese_anno_reformatted(self):
        """AAAAMM=202309 → MM/YYYY=09/2023"""
        name = "05779711000_04393470879_202309_SNM_20230918060523_1DP0001_R.xml"
        meta = parse_filename(name)
        assert meta.mese_anno == "09/2023"

    def test_progressivo_extracted(self):
        """Leading digits from segment like '3DP0001' → progressivo=3"""
        name = "05779711000_04393470879_202501_PDO2G_20250118060523_3DP0001_R.xml"
        meta = parse_filename(name)
        assert meta.progressivo == 3

    def test_f2g_filename(self):
        name = "05779711000_04393470879_202109_F2G_20210825223917_1DP2311.xml"
        meta = parse_filename(name)
        assert meta.cod_flusso == "F2G"
        assert meta.sm_status is None

    def test_invalid_filename_raises(self):
        with pytest.raises(ValueError):
            parse_filename("not_a_valid_sii_filename.xml")
