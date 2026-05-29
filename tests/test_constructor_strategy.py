"""Tests for constructor strategy profiles (Task 47)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.quali_strategist import generate_quali_picks
from circuits.profiles import get_circuit_profile
from intelligence.constructor_strategy import (
    ConstructorStrategyProfileData,
    PitEvent,
    _build_from_single_race,
    _data_quality_label,
    calculate_strategy_profile,
    seed_constructor_profiles,
)
from intelligence.schemas import PickRecommendation
from openf1.models import LapRecord, PitStop, SessionResultRow
from orchestrator.race_context import RaceContext
from scheduler.calendar import get_race_weekend
from whatsapp.message_format import format_personalized_picks


def _pit_event(
    *,
    race_key: str,
    lap: int,
    total_laps: int = 50,
    year: int = 2024,
) -> PitEvent:
    return PitEvent(
        year=year,
        race_key=race_key,
        driver_number=16,
        constructor_code="FER",
        lap_number=lap,
        pit_duration=22.0,
        race_total_laps=total_laps,
        position_at_pit=3,
        position_after_pit=4,
        was_under_sc=False,
        was_double_stack=False,
        stint_number=1,
    )


def test_calculate_early_box_rate() -> None:
    events = [
        _pit_event(race_key="2024_monaco", lap=15, total_laps=50),  # 30% — early
        _pit_event(race_key="2023_monaco", lap=16, total_laps=50),
        _pit_event(race_key="2022_monaco", lap=14, total_laps=50),
        _pit_event(race_key="2021_monaco", lap=28, total_laps=50),  # 56% — not early
        _pit_event(race_key="2020_monaco", lap=30, total_laps=50),
    ]
    profile = calculate_strategy_profile(events, "FER", "monaco")
    assert profile.early_box_rate == pytest.approx(0.6, abs=0.01)
    assert profile.sample_size == 5


def test_data_quality_thresholds() -> None:
    assert _data_quality_label(6) == "HIGH"
    assert _data_quality_label(3) == "MEDIUM"
    assert _data_quality_label(1) == "LOW"


@pytest.mark.asyncio
async def test_no_profile_does_not_block_picks() -> None:
    weekend = get_race_weekend("2026_monaco")
    circuit = get_circuit_profile("monaco")
    assert weekend is not None
    assert circuit is not None
    ctx = RaceContext(
        race_weekend=weekend,
        circuit_profile=circuit,
        built_at=weekend.race_utc,
        last_updated=weekend.race_utc,
    )
    with (
        patch(
            "agents.quali_strategist.get_constructor_context",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "agents.quali_strategist.get_price_prediction_map",
            new=AsyncMock(return_value={}),
        ),
    ):
        output = await generate_quali_picks(ctx, user_team=None, generated_by="test")
    assert output.picks
    for pick in output.picks:
        assert pick.constructor_tendency_note is None
        assert pick.constructor_data_quality is None


@pytest.mark.asyncio
async def test_low_quality_not_surfaced() -> None:
    weekend = get_race_weekend("2026_monaco")
    circuit = get_circuit_profile("monaco")
    assert weekend is not None
    assert circuit is not None
    low_profile = ConstructorStrategyProfileData(
        constructor_code="FER",
        circuit_key="monaco",
        sample_size=2,
        early_box_rate=0.9,
        undercut_attempt_rate=0.8,
        overcut_rate=0.1,
        avg_pit_window_open_lap=0.3,
        double_stack_rate=0.0,
        safety_car_opportunist=0.9,
        championship_pressure_modifier=0.5,
        fantasy_tendency="Should not appear to users.",
        data_quality="LOW",
        source_race_keys=["2024_monaco", "2023_monaco"],
    )
    ctx = RaceContext(
        race_weekend=weekend,
        circuit_profile=circuit,
        built_at=weekend.race_utc,
        last_updated=weekend.race_utc,
    )
    with (
        patch(
            "agents.quali_strategist.get_constructor_context",
            new=AsyncMock(return_value={"FER": low_profile}),
        ),
        patch(
            "agents.quali_strategist.get_price_prediction_map",
            new=AsyncMock(return_value={}),
        ),
    ):
        output = await generate_quali_picks(ctx, user_team=None, generated_by="test")
    lec_pick = next((p for p in output.picks if p.driver_code == "LEC"), None)
    assert lec_pick is not None
    assert lec_pick.constructor_tendency_note is None
    assert lec_pick.constructor_data_quality is None

    high_pick = PickRecommendation(
        rank=1,
        headline="Swap VER → LEC",
        confidence=70.0,
        reasoning="Practice strong.",
        driver_code="LEC",
        transfer_out="VER",
        transfer_in="LEC",
        predicted_points_delta=12.0,
        constructor_tendency_note="Hidden low quality",
        constructor_data_quality="LOW",
    )
    output_low = type(output)(
        picks=[high_pick],
        personalized=True,
        circuit_note="Monaco",
        confidence_note="ok",
        generated_by="test",
    )
    msg = format_personalized_picks(weekend, output_low, timezone="UTC")
    assert "🏭" not in msg


@pytest.mark.asyncio
async def test_seeder_skips_if_populated() -> None:
    with (
        patch(
            "intelligence.repository.count_constructor_strategy_profiles",
            new=AsyncMock(return_value=5),
        ),
        patch(
            "intelligence.constructor_strategy.fetch_pit_history",
            new=AsyncMock(),
        ) as fetch_mock,
    ):
        result = await seed_constructor_profiles()
    assert result == 0
    fetch_mock.assert_not_called()


def test_build_from_single_race_detects_early_pit_window() -> None:
    session_numbers = {16: "LEC", 1: "VER"}
    pits = [
        PitStop(session_key=1, driver_number=16, lap_number=10),
        PitStop(session_key=1, driver_number=1, lap_number=12),
    ]
    laps = [
        LapRecord(session_key=1, driver_number=16, lap_number=9, lap_duration=90.8),
        LapRecord(session_key=1, driver_number=1, lap_number=9, lap_duration=90.0),
    ]
    results = [
        SessionResultRow(session_key=1, driver_number=16, position=2),
        SessionResultRow(session_key=1, driver_number=1, position=1),
    ]
    out = _build_from_single_race(pits, laps, results, session_numbers)
    fer = out["FER"]
    assert fer["sample_races"] == 1.0
    assert fer["lead_window_samples"] == 1.0
    assert fer["early_pit_count"] == 1.0
