"""Tests for chip window confidence bands."""

from __future__ import annotations

from datetime import UTC, datetime

from circuits.profiles import CircuitProfile
from intelligence.chip_conviction import (
    ConfidenceTier,
    assess_chip_conviction,
)
from scheduler.calendar import RaceWeekend


def _profile(
    *,
    weather: float = 0.1,
    safety_car: float = 0.3,
) -> CircuitProfile:
    return CircuitProfile(
        circuit_key="test",
        display_name="Test Circuit",
        overtaking_difficulty=0.5,
        tire_deg_rate=0.5,
        weather_sensitivity=weather,
        safety_car_probability=safety_car,
        positions_gained_ceiling=8,
        sector_characteristics=["test"],
        notes="test",
        openf1_circuit_name="Test",
    )


def _weekend(*, is_sprint: bool = False) -> RaceWeekend:
    t = datetime(2026, 6, 1, 13, 0, tzinfo=UTC)
    return RaceWeekend(
        race_key="2026_test",
        circuit_key="test",
        display_name="Test GP",
        fp1_utc=t,
        fp2_utc=t,
        fp3_utc=t,
        qualifying_utc=t,
        race_utc=t,
        fantasy_lock_utc=t,
        is_sprint=is_sprint,
    )


def test_high_confidence_strong_signal_stable_circuit_near_term() -> None:
    result = assess_chip_conviction(
        score=0.85,
        circuit=_profile(),
        weekend=_weekend(),
        championship_week=2,
    )
    assert result.tier == ConfidenceTier.HIGH


def test_low_confidence_far_out_chaotic_weather_weak_signal() -> None:
    result = assess_chip_conviction(
        score=0.40,
        circuit=_profile(weather=0.9, safety_car=0.8),
        weekend=_weekend(),
        championship_week=10,
    )
    assert result.tier == ConfidenceTier.LOW
    assert any("weather" in r for r in result.reasons)
    assert any("weekends out" in r for r in result.reasons)


def test_medium_when_only_one_demotion_applies() -> None:
    result = assess_chip_conviction(
        score=0.85,
        circuit=_profile(),
        weekend=_weekend(),
        championship_week=8,  # only "far out" trips
    )
    assert result.tier == ConfidenceTier.MEDIUM


def test_sprint_format_drives_confidence_down() -> None:
    base = assess_chip_conviction(
        score=0.80,
        circuit=_profile(),
        weekend=_weekend(is_sprint=False),
        championship_week=2,
    )
    sprint = assess_chip_conviction(
        score=0.80,
        circuit=_profile(),
        weekend=_weekend(is_sprint=True),
        championship_week=2,
    )
    assert base.tier == ConfidenceTier.HIGH
    assert sprint.tier == ConfidenceTier.MEDIUM
    assert any("sprint" in r for r in sprint.reasons)


def test_planner_drops_low_conviction_window_from_sequence() -> None:
    """If every chip window for the season is Low conviction, the
    recommended_sequence should not anchor a chip there."""
    from db.models import FantasyTeam
    from intelligence.chip_planner import ChipWindow, generate_chip_plan
    from unittest.mock import patch

    team = FantasyTeam(
        phone="+10000000099",
        driver_1="VER", driver_2="NOR", driver_3="LEC",
        driver_4="PIA", driver_5="RUS",
        constructor_1="FER", constructor_2="MCL",
        remaining_budget=2.0,
        transfers_available=2,
        chips_used={},
        league_mode_enabled=False,
        league_size=None,
        league_strategy=None,
        opponent_profiles=[],
        updated_at=datetime.now(tz=UTC),
    )

    plan = generate_chip_plan(team, [])
    # Empty remaining races → no sequence, no crash.
    assert plan.recommended_sequence == []
    assert plan.windows == []

    # And with windows: a Low-tier window must not appear in sequence.
    real_plan = generate_chip_plan(team, list(__import__(
        "scheduler.calendar", fromlist=["CALENDAR_2026"]).CALENDAR_2026))
    low_race_keys = {
        w.race_key for w in real_plan.windows
        if w.confidence_tier == ConfidenceTier.LOW
    }
    for _chip, race_key in real_plan.recommended_sequence:
        assert race_key not in low_race_keys
