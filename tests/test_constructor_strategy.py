"""Tests for constructor strategy tendency modeling."""

from __future__ import annotations

from intelligence.constructor_strategy import _build_from_single_race
from openf1.models import LapRecord, PitStop, SessionResultRow


def test_build_from_single_race_detects_early_pit_window() -> None:
    # Two constructors in contention; Ferrari pits first while within 2s of best lap.
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
    out = _build_from_single_race(pits, laps, results)
    fer = out["FER"]
    assert fer["sample_races"] == 1.0
    assert fer["lead_window_samples"] == 1.0
    assert fer["early_pit_count"] == 1.0


def test_build_from_single_race_detects_hedge_split() -> None:
    pits = [
        PitStop(session_key=1, driver_number=16, lap_number=9),
        PitStop(session_key=1, driver_number=55, lap_number=16),
    ]
    laps = [
        LapRecord(session_key=1, driver_number=16, lap_number=8, lap_duration=90.5),
        LapRecord(session_key=1, driver_number=55, lap_number=8, lap_duration=91.0),
    ]
    results = [
        SessionResultRow(session_key=1, driver_number=16, position=3),
        SessionResultRow(session_key=1, driver_number=55, position=5),
    ]
    out = _build_from_single_race(pits, laps, results)
    assert out["FER"]["hedge_events"] == 1.0
