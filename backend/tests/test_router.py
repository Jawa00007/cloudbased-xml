"""Tests for backend/parser/router.py — end-to-end routing with real fixture files."""

import pytest
from pathlib import Path
from backend.parser.router import route_file
from backend.tests.conftest import FIXTURES

# Canonical SII filename prefix shared by all fixtures
_PREFIX = "05779711000_04393470879_202501_"
_SUFFIX = "_20250118060523_1DP0001_R.xml"


def _fixture_as_named(fixture_path: Path, cod_flusso: str, tmp_path: Path) -> Path:
    """
    Copy a fixture XML to tmp_path with a valid SII filename so route_file
    can parse the filename metadata.
    """
    dest = tmp_path / f"{_PREFIX}{cod_flusso}{_SUFFIX}"
    dest.write_bytes(fixture_path.read_bytes())
    return dest


class TestRouteFile:
    def test_curve_file_routes_to_curve(self, pdo2g_xml, tmp_path):
        path = _fixture_as_named(pdo2g_xml, "PDO2G", tmp_path)
        result = route_file(path)
        assert result.shape == "curve"
        assert len(result.curve_records) == 96
        assert result.totalizer_records == []
        assert result.f2g_records == []

    def test_totalizer_file_routes_to_totalizer(self, snm2g_xml, tmp_path):
        path = _fixture_as_named(snm2g_xml, "SNM2G", tmp_path)
        result = route_file(path)
        assert result.shape == "totalizer"
        assert len(result.totalizer_records) == 1
        assert result.curve_records == []

    def test_flusso2_file_routes_to_flusso2(self, rfo2g_xml, tmp_path):
        path = _fixture_as_named(rfo2g_xml, "RFO2G", tmp_path)
        result = route_file(path)
        assert result.shape == "flusso2"
        assert len(result.curve_records) == 96

    def test_f2g_file_routes_to_f2g(self, f2g_xml, tmp_path):
        # F2G filenames have no _SM suffix
        dest = tmp_path / "05779711000_04393470879_202109_F2G_20210825223917_1DP2311.xml"
        dest.write_bytes(f2g_xml.read_bytes())
        result = route_file(dest)
        assert result.shape == "f2g"
        assert len(result.f2g_records) == 2
        assert result.curve_records == []

    def test_filename_meta_populated(self, pdo2g_xml, tmp_path):
        path = _fixture_as_named(pdo2g_xml, "PDO2G", tmp_path)
        result = route_file(path)
        assert result.filename_meta.cod_flusso == "PDO2G"
        assert result.filename_meta.mese_anno == "01/2025"
        assert result.filename_meta.sm_status == "R"
