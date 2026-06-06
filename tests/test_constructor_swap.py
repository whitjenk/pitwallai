"""Constructor swap recommendation + projection-safety."""

from __future__ import annotations

from db.models import FantasyTeam
from circuits.profiles import get_circuit_profile
from intelligence import pick_generator as pg
from intelligence.schemas import PracticeSignal


def test_projected_race_points_never_applies_dnf_penalty() -> None:
    # Top-10 score on the F1 scale; everything else is 0 — never a DNF penalty,
    # so a driver merely slow in practice cannot create a huge negative swing.
    assert pg._projected_race_points(1) == 25.0
    assert pg._projected_race_points(10) == 1.0
    assert pg._projected_race_points(11) == 0.0
    assert pg._projected_race_points(22) == 0.0  # would be -20 via driver_points_race
    assert pg._projected_race_points(None) == 0.0


def _sig(code: str, pace: float) -> PracticeSignal:
    return PracticeSignal(
        driver_number=0,
        driver_code=code,
        session="FP2",
        setup_sentiment=0.0,
        tire_confidence=0.5,
        mechanical_flags=[],
        pace_satisfaction=pace,
        anomaly_flags=[],
        raw_evidence=[],
    )


def test_constructor_swap_delta_is_bounded_and_sane() -> None:
    circuit = get_circuit_profile("monaco")
    # Ferrari pair (LEC/HAM) fast, McLaren pair (NOR/PIA) slow on practice pace.
    signals = {
        "HAM": _sig("HAM", 1.0), "LEC": _sig("LEC", 0.95),
        "NOR": _sig("NOR", 0.2), "PIA": _sig("PIA", 0.25),
        "RUS": _sig("RUS", 0.8), "ANT": _sig("ANT", 0.75),
    }
    team = FantasyTeam(
        phone="x", constructor_1="MCL", constructor_2="MER",
        remaining_budget=20.0, transfers_available=2, driver_1="ANT",
    )
    opt = pg._best_constructor_swap(team, circuit=circuit, signals=signals, grid={})
    assert opt is not None
    # A single constructor's projected points cannot exceed two P1 finishes (43),
    # so the swing is bounded — never the old +57 DNF-penalty artifact.
    assert -43.0 <= opt.expected_delta <= 43.0
    assert opt.out_code in {"MCL", "MER"}
    assert opt.in_code not in {"MCL", "MER"}
