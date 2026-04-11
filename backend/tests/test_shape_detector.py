"""Tests for backend/parser/shape_detector.py"""

import xml.etree.ElementTree as ET
import pytest
from backend.parser.shape_detector import detect_shape, is_vno2g_dual


def _xml(body: str) -> ET.Element:
    return ET.fromstring(f"<Root>{body}</Root>")


class TestDetectShape:
    def test_f2g_always_routes_first(self):
        root = _xml("<DatiPod><Ea E1='1,000'>01</Ea></DatiPod>")
        assert detect_shape("F2G", root) == "f2g"

    def test_flusso2_code(self):
        root = _xml("<DatiPod><Misura><Ea E1='1,000'>01</Ea></Misura></DatiPod>")
        assert detect_shape("RFO2G", root) == "flusso2"

    def test_all_flusso2_codes_route_correctly(self):
        from backend.parser.shape_detector import FLUSSO2_CODES
        root = _xml("<DatiPod></DatiPod>")
        for code in FLUSSO2_CODES:
            assert detect_shape(code, root) == "flusso2"

    def test_curve_when_ea_present(self):
        root = _xml("<DatiPod><Misura><Ea E1='1,000'>01</Ea></Misura></DatiPod>")
        assert detect_shape("PDO2G", root) == "curve"

    def test_totalizer_when_no_ea(self):
        root = _xml("<DatiPod><Misura><EaF1>30,000</EaF1></Misura></DatiPod>")
        assert detect_shape("SNM2G", root) == "totalizer"


class TestIsVno2gDual:
    def test_vno2g_with_both_ea_and_eaf1(self):
        root = _xml("<DatiPod><Misura><Ea E1='1,000'>01</Ea><EaF1>10,000</EaF1></Misura></DatiPod>")
        assert is_vno2g_dual("VNO2G", root) is True

    def test_vno2g_curve_only(self):
        root = _xml("<DatiPod><Misura><Ea E1='1,000'>01</Ea></Misura></DatiPod>")
        assert is_vno2g_dual("VNO2G", root) is False

    def test_non_vno2g(self):
        root = _xml("<DatiPod><Misura><Ea E1='1,000'>01</Ea><EaF1>10,000</EaF1></Misura></DatiPod>")
        assert is_vno2g_dual("PDO2G", root) is False
