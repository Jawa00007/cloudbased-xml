"""Shared fixtures for the SII parser test suite."""

from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def pdo2g_xml() -> Path:
    return FIXTURES / "sample_pdo2g.xml"


@pytest.fixture
def pdo2g_secondary_xml() -> Path:
    return FIXTURES / "sample_pdo2g_secondary.xml"


@pytest.fixture
def pdo2g_dst_spring_xml() -> Path:
    return FIXTURES / "sample_pdo2g_dst_spring.xml"


@pytest.fixture
def snm2g_xml() -> Path:
    return FIXTURES / "sample_snm2g.xml"


@pytest.fixture
def rfo2g_xml() -> Path:
    return FIXTURES / "sample_rfo2g.xml"


@pytest.fixture
def f2g_xml() -> Path:
    return FIXTURES / "sample_f2g.xml"
