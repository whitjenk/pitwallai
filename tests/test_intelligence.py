"""Unit tests for Phase 3 intelligence layer."""

from __future__ import annotations

from circuits.profiles import get_circuit_profile, load_circuit_profiles
from db.models import FantasyTeam
from fantasy.rules import driver_points_qualifying
from intelligence.context import init_orchestrator_context
from intelligence.pick_generator import generate_picks
from intelligence.schemas import PickGeneratorInput, QualifyingRow


def test_circuit_profiles_load_24() -> None:
    profiles = load_circuit_profiles()
    assert len(profiles) == 24
    monaco = get_circuit_profile("monaco")
    monza = get_circuit_profile("monza")
    assert monaco is not None and monza is not None
    assert monaco.overtaking_difficulty > monza.overtaking_difficulty
    assert monaco.positions_gained_ceiling < monza.positions_gained_ceiling


def test_generic_pick_generator() -> None:
    ctx = init_orchestrator_context()
    monaco = ctx.get_circuit("monaco")
    assert monaco is not None
    output = generate_picks(
        PickGeneratorInput(
            circuit=monaco,
            practice_signals=[],
            qualifying_result=[
                QualifyingRow(
                    driver_number=16,
                    driver_code="LEC",
                    grid_position=1,
                    session_key=1,
                )
            ],
            weather_forecast=None,
            user_team=None,
            race_key="2026_monaco",
            generated_by="rules",
        )
    )
    assert not output.personalized
    assert len(output.picks) == 3
    assert "TEAM" in output.confidence_note


def test_personalized_swap_expected_delta_uses_quali_points() -> None:
    """Pre-lock swap scoring must use qualifying points, not race finish scale."""
    ctx = init_orchestrator_context()
    monaco = ctx.get_circuit("monaco")
    assert monaco is not None
    team = FantasyTeam(
        phone="+15550000001",
        driver_1="VER",
        driver_2="NOR",
        driver_3="LEC",
        driver_4="ALB",
        driver_5="HAM",
        remaining_budget=25.0,
        transfers_available=2,
        chips_used={},
    )
    qualifying = [
        QualifyingRow(driver_number=1, driver_code="LEC", grid_position=1, session_key=1),
        QualifyingRow(driver_number=2, driver_code="VER", grid_position=2, session_key=1),
        QualifyingRow(driver_number=3, driver_code="NOR", grid_position=3, session_key=1),
        QualifyingRow(driver_number=4, driver_code="HAM", grid_position=5, session_key=1),
        QualifyingRow(driver_number=5, driver_code="ALB", grid_position=10, session_key=1),
        QualifyingRow(driver_number=6, driver_code="SAR", grid_position=8, session_key=1),
    ]
    output = generate_picks(
        PickGeneratorInput(
            circuit=monaco,
            practice_signals=[],
            qualifying_result=qualifying,
            weather_forecast=None,
            user_team=team,
            race_key="2026_monaco",
            generated_by="rules",
        )
    )
    assert output.personalized
    assert output.picks
    sar_swap = next(
        (p for p in output.picks if p.transfer_in == "SAR" and p.transfer_out == "ALB"),
        None,
    )
    assert sar_swap is not None
    assert sar_swap.predicted_points_delta is not None
    expected = float(
        driver_points_qualifying(8) - driver_points_qualifying(10)
    )
    assert sar_swap.predicted_points_delta == expected
