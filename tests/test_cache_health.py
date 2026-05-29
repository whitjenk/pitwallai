"""Signal cache health and dedupe tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from intelligence.cache_health import check_signal_cache_health
from intelligence.repository import load_practice_signals_by_circuit
from intelligence.signal_cache import get_practice_signals, get_radio_signals
from tests.fixtures_signal_cache import make_practice, make_practice_with_radio, make_radio


@pytest.mark.asyncio
async def test_cache_health_ready_when_half_have_signals() -> None:
    async def fake_practice(race_key: str, code: str):
        return make_practice(driver_code=code) if code in {"NOR", "LEC", "PIA", "VER", "HAM"} else None

    async def fake_radio(race_key: str, code: str):
        return make_radio("snippet") if code in {"NOR", "LEC", "PIA"} else make_radio(None)

    with (
        patch("intelligence.practice_cache.get_practice_signals", fake_practice),
        patch("intelligence.radio_cache.get_radio_signals", fake_radio),
    ):
        report = await check_signal_cache_health(
            "2024_monaco",
            ["NOR", "LEC", "PIA", "VER", "HAM", "RUS"],
        )
    assert report.ready_for_explanations
    assert report.practice_hits == 5
    assert report.radio_hits == 3


@pytest.mark.asyncio
async def test_load_practice_by_circuit_dedupes_fp2() -> None:
    rows = [
        make_practice(
            driver_number=1,
            session="FP1",
            setup_sentiment=0.0,
            pace_satisfaction=0.5,
            raw_evidence=["old"],
        ),
        make_practice_with_radio(
            driver_number=1,
            session="FP2",
            setup_sentiment=0.2,
            tire_confidence=0.6,
            pace_satisfaction=0.6,
            snippet="latest",
        ),
    ]

    with patch(
        "intelligence.signal_cache.load_practice_signals_by_circuit",
        AsyncMock(return_value=rows),
    ):
        sig = await get_practice_signals("2026_monaco", "NOR")
        radio = await get_radio_signals("2026_monaco", "NOR")

    assert sig is not None
    assert sig.session == "FP2"
    assert radio == "latest"


@pytest.mark.asyncio
async def test_repository_dedupe_prefers_fp2(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DB returns FP1+FP2 rows, load_practice_signals_by_circuit keeps FP2."""
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime

    from db.models import PracticeSignalRow

    fp1 = PracticeSignalRow(
        session_key=1,
        circuit_key="monaco",
        driver_number=4,
        driver_code="NOR",
        session_label="FP1",
        setup_sentiment=0.0,
        tire_confidence=0.5,
        mechanical_flags=[],
        pace_satisfaction=0.5,
        anomaly_flags=[],
        raw_evidence=["fp1"],
        created_at=datetime(2024, 5, 24, 12, 0, tzinfo=UTC),
    )
    fp2 = PracticeSignalRow(
        session_key=1,
        circuit_key="monaco",
        driver_number=4,
        driver_code="NOR",
        session_label="FP2",
        setup_sentiment=0.1,
        tire_confidence=0.5,
        mechanical_flags=[],
        pace_satisfaction=0.5,
        anomaly_flags=[],
        raw_evidence=["radio: fp2"],
        created_at=datetime(2024, 5, 24, 16, 0, tzinfo=UTC),
    )

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return [fp2, fp1]

    class _Session:
        async def execute(self, _stmt):
            return _Result()

    @asynccontextmanager
    async def _fake_session():
        yield _Session()

    monkeypatch.setattr("intelligence.repository.get_session", _fake_session)
    loaded = await load_practice_signals_by_circuit("monaco")
    assert len(loaded) == 1
    assert loaded[0].session == "FP2"
