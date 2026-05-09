"""
Query count and performance tests.

Uses a counting mock session to verify that batch-rewritten functions do NOT
exhibit N+1 query patterns. No real database is needed.

Key invariants tested:
  - get_monthly_totals_all_pods: ≤ 2 DB calls regardless of POD count
  - get_yearly_totals: ≤ 2 DB calls regardless of month count
  - upsert_forecast_periods: exactly ceil(N/5900) INSERT calls for N rows

Run: pytest backend/tests/test_performance_queries.py -v
"""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Counting session mock ──────────────────────────────────────────────────────

class _CountingSession:
    """
    Wraps session.execute and counts how many times it's called.
    Returns configurable results so the code under test can proceed normally.
    """
    def __init__(self, results: list[list] | None = None):
        self.call_count = 0
        self._results = results or []
        self._call_index = 0

    async def execute(self, stmt, params=None):
        self.call_count += 1
        if self._call_index < len(self._results):
            rows = self._results[self._call_index]
            self._call_index += 1
        else:
            rows = []
        mock_result = MagicMock()
        mock_result.__iter__ = lambda s: iter(rows)
        mock_result.fetchall.return_value = rows
        return mock_result

    async def commit(self):
        pass

    async def rollback(self):
        pass


# ── Fake ForecastRow ───────────────────────────────────────────────────────────

@dataclass
class _FRow:
    pod: str
    mese_anno: str
    punto_dispacciamento: str | None
    forecast_date: date
    source_date: date | None
    periodo: int
    ea_mwh: float
    ea_mwh_with_loss: float
    loss_pct: float
    source_type: str


# ── get_monthly_totals_all_pods ────────────────────────────────────────────────

@pytest.mark.anyio
async def test_monthly_totals_all_pods_uses_single_batch_query():
    """
    get_monthly_totals_all_pods must use at most 2 DB calls regardless of POD count
    (previously it used 1 + N*3 calls).
    """
    from backend.aggregation.engine import get_monthly_totals_all_pods

    # Simulate 10 PODs with E data returned by the batch UNION ALL
    fake_rows = [
        (f"IT001E{i:06d}0000000000X", date(2024, 4, d), Decimal("100"), Decimal("10"), "E")
        for i in range(10)
        for d in range(1, 6)
    ]

    session = _CountingSession(results=[fake_rows])
    result = await get_monthly_totals_all_pods(session, "ch4", "04/2024")

    assert session.call_count <= 2, (
        f"get_monthly_totals_all_pods made {session.call_count} DB calls for 10 PODs — "
        f"expected ≤ 2 (batch query). Old N+1 pattern would have used {1 + 10*3} calls."
    )
    assert len(result) == 10


@pytest.mark.anyio
async def test_monthly_totals_all_pods_empty_month():
    """Empty month returns empty list without extra queries."""
    from backend.aggregation.engine import get_monthly_totals_all_pods

    session = _CountingSession(results=[[]])
    result = await get_monthly_totals_all_pods(session, "ch4", "04/2024")

    assert result == []
    assert session.call_count <= 2


@pytest.mark.anyio
async def test_monthly_totals_prefers_e_over_s():
    """E source rows must be preferred; mixed days show source='mixed'."""
    from backend.aggregation.engine import get_monthly_totals_all_pods

    pod = "IT001E000001"
    rows = [
        (pod, date(2024, 4, 1), Decimal("100"), Decimal("5"), "E"),
        (pod, date(2024, 4, 2), Decimal("80"),  Decimal("4"), "S"),
    ]
    session = _CountingSession(results=[rows])
    result = await get_monthly_totals_all_pods(session, "ch4", "04/2024")

    assert len(result) == 1
    assert result[0].source == "mixed"
    assert result[0].monthly_kwh == Decimal("180")


# ── get_yearly_totals ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_yearly_totals_uses_single_batch_query():
    """
    get_yearly_totals must use ≤ 2 DB calls for a full year
    (previously it used 12 * 3 = 36 calls).
    """
    from backend.aggregation.engine import get_yearly_totals

    pod = "IT001E000001"
    fake_rows = [
        (f"{m:02d}/2024", date(2024, m, d), Decimal("100"), Decimal("5"), "E")
        for m in range(1, 13)
        for d in range(1, 4)  # 3 days per month
    ]

    session = _CountingSession(results=[fake_rows])
    result = await get_yearly_totals(session, "ch4", pod, 2024)

    assert session.call_count <= 2, (
        f"get_yearly_totals made {session.call_count} DB calls for 12 months — "
        f"expected ≤ 2 (batch query). Old pattern used {12*3} calls."
    )
    assert len(result) == 12


@pytest.mark.anyio
async def test_yearly_totals_partial_year():
    """Only months with data are returned."""
    from backend.aggregation.engine import get_yearly_totals

    pod = "IT001E000001"
    fake_rows = [
        ("01/2024", date(2024, 1, 1), Decimal("100"), Decimal("5"), "E"),
        ("03/2024", date(2024, 3, 1), Decimal("200"), Decimal("8"), "E"),
    ]

    session = _CountingSession(results=[fake_rows])
    result = await get_yearly_totals(session, "ch4", pod, 2024)

    assert len(result) == 2
    months = [r.mese_anno for r in result]
    assert "01/2024" in months
    assert "03/2024" in months


# ── upsert_forecast_periods chunking ──────────────────────────────────────────

@pytest.mark.anyio
async def test_upsert_forecast_chunks_correctly_small():
    """Small batch (< 5900 rows) → exactly 1 DELETE + 1 INSERT."""
    from backend.db.upsert import upsert_forecast_periods

    rows = [
        _FRow("POD1", "04/2024", "SICI", date(2024, 4, d), None, p, 0.1, 0.102, 1.8, "historical")
        for d in range(1, 4)
        for p in range(1, 97)
    ]  # 3 days × 96 = 288 rows

    session = _CountingSession()
    # The DELETE uses text(), the INSERT uses insert(table).values(chunk)
    count = await upsert_forecast_periods(session, rows, "ch4")

    assert count == 288
    # 1 DELETE + 1 INSERT chunk
    assert session.call_count == 2, (
        f"Expected 2 DB calls (1 DELETE + 1 INSERT) for 288 rows, got {session.call_count}"
    )


@pytest.mark.anyio
async def test_upsert_forecast_chunks_correctly_large():
    """
    Large batch (> 5900 rows) → exactly 1 DELETE + ceil(N/5900) INSERT calls.
    """
    from backend.db.upsert import upsert_forecast_periods

    N = 12_000
    # Use unique pod per row to guarantee all keys are distinct after deduplication
    rows = [
        _FRow(f"POD{i:05d}", "04/2024", "SICI", date(2024, 4, 1), None, i % 96 + 1,
              0.1, 0.102, 1.8, "historical")
        for i in range(N)
    ]

    session = _CountingSession()
    _CHUNK = 5_900
    expected_inserts = math.ceil(N / _CHUNK)

    count = await upsert_forecast_periods(session, rows, "ch4")

    # 1 DELETE + expected_inserts INSERT calls
    expected_calls = 1 + expected_inserts
    assert session.call_count == expected_calls, (
        f"Expected {expected_calls} DB calls (1 DELETE + {expected_inserts} INSERT chunks) "
        f"for {N} rows, got {session.call_count}"
    )


@pytest.mark.anyio
async def test_upsert_forecast_deduplicates_rows():
    """Duplicate (pod, forecast_date, periodo) keys are deduplicated before insert."""
    from backend.db.upsert import upsert_forecast_periods

    base = _FRow("POD1", "04/2024", "SICI", date(2024, 4, 1), None, 1, 0.1, 0.102, 1.8, "historical")
    rows = [base, base, base]  # 3 identical rows

    session = _CountingSession()
    count = await upsert_forecast_periods(session, rows, "ch4")

    assert count == 1, "Duplicate rows must be deduplicated — only 1 unique row"


@pytest.mark.anyio
async def test_upsert_forecast_empty_noop():
    """Empty input must return 0 without any DB calls."""
    from backend.db.upsert import upsert_forecast_periods

    session = _CountingSession()
    count = await upsert_forecast_periods(session, [], "ch4")

    assert count == 0
    assert session.call_count == 0, "Empty input must not touch the database"


# ── get_daily_totals query count ──────────────────────────────────────────────

@pytest.mark.anyio
async def test_daily_totals_single_pod_bounded_queries():
    """
    get_daily_totals for a single POD must use ≤ 3 DB calls
    (1 for E-days, 1 for E data, 1 for S fallback).
    """
    from backend.aggregation.engine import get_daily_totals

    e_days_result = [("2024-04-01",), ("2024-04-02",)]
    e_data_result = [
        ("POD1", date(2024, 4, 1), Decimal("100"), Decimal("5"), 96),
        ("POD1", date(2024, 4, 2), Decimal("90"),  Decimal("4"), 96),
    ]
    s_data_result = []

    session = _CountingSession(results=[e_days_result, e_data_result, s_data_result])
    result = await get_daily_totals(session, "ch4", "POD1", "04/2024")

    assert session.call_count <= 3, (
        f"get_daily_totals used {session.call_count} queries — expected ≤ 3"
    )
    assert len(result) == 2
