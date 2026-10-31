"""Behaviour snapshot — freezes what the bot currently outputs.

Briefs 002–004 move and delete thousands of lines of fantasy logic. This test
is the safety net: it pins the *outputs* of every user-facing calculation
(picks, grades, scores, chip plans, points tables) so a refactor that changes
an answer is caught, not shipped.

How it works
------------
Each case builds a deterministic input (no network, no clock, no randomness),
runs the real production function, and compares the JSON-serialised result to a
frozen snapshot in ``tests/snapshots/``. Floats are rounded to 3 dp and keys are
sorted so the files are stable and diffable. Anything time- or random-dependent
(``generated_at`` timestamps, chip-plan ``share_token`` UUIDs) is stripped before
comparison.

Snapshots regenerate only with ``UPDATE_SNAPSHOTS=1``. Without it the test
compares and fails with a readable unified diff.

Determinism notes
-----------------
* Picks: prices are pinned to the committed ``fantasy/rules.py`` baseline so a
  local (gitignored) ``prices.live.json`` overlay can't shift the numbers.
* Grading: practice signals are injected via monkeypatch so no OpenF1 call runs.
* Scoring: a fake OpenF1 client returns fixed race results.
* Chips: a fixed, far-future race list is passed so the planner's
  "races from now" filter always includes every race, whatever today is.
"""

from __future__ import annotations

import difflib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from circuits.profiles import get_circuit_profile
from db.models import FantasyTeam
from fantasy import price_catalog as pc
from fantasy.rules import (
    CONSTRUCTOR_PRICES_M,
    DRIVER_PRICES_M,
    constructor_points_race,
    driver_points_qualifying,
    driver_points_race,
    driver_points_sprint,
    transfer_penalty_points,
)
from intelligence import lineup_grader as lg
from intelligence.lineup_grader import perfect_lineup_from_positions
from intelligence.pick_generator import generate_picks
from intelligence.schemas import PickGeneratorInput, PracticeSignal, QualifyingRow
from scheduler.calendar import RaceWeekend

SNAP_DIR = Path(__file__).parent / "snapshots"


# ── Snapshot harness ────────────────────────────────────────────────────────
def _canonical(obj: Any) -> Any:
    """Round every float to 3 dp, recursively; leave everything else alone."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return round(obj, 3)
    if isinstance(obj, dict):
        return {k: _canonical(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    return obj


def _render(data: Any) -> str:
    """Stable JSON: sorted keys, 3-dp floats, pretty-printed."""
    return json.dumps(_canonical(data), sort_keys=True, indent=2, default=str)


def assert_snapshot(name: str, data: Any) -> None:
    """Compare ``data`` to the frozen snapshot, or regenerate it.

    With ``UPDATE_SNAPSHOTS=1`` the snapshot file is (re)written. Otherwise the
    rendered JSON is compared and any difference fails with a unified diff.
    """
    path = SNAP_DIR / f"{name}.json"
    rendered = _render(data)

    if os.getenv("UPDATE_SNAPSHOTS") == "1":
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
        return

    assert path.exists(), (
        f"Missing snapshot '{path.name}'. Generate it with UPDATE_SNAPSHOTS=1."
    )
    expected = path.read_text(encoding="utf-8").strip()
    actual = rendered.strip()
    if expected != actual:
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile=f"{name}.json (saved)",
                tofile=f"{name}.json (now)",
                lineterm="",
            )
        )
        raise AssertionError(
            f"Behaviour snapshot '{name}' changed — a refactor altered an output.\n"
            f"If this change is intended, rerun with UPDATE_SNAPSHOTS=1.\n{diff}"
        )


# ── Fixtures / builders ──────────────────────────────────────────────────────
def _sig(code: str, number: int, *, setup: float, tire: float, pace: float,
         flags: list[str] | None = None) -> PracticeSignal:
    return PracticeSignal(
        driver_number=number,
        driver_code=code,
        session="FP2",
        setup_sentiment=setup,
        tire_confidence=tire,
        mechanical_flags=[],
        pace_satisfaction=pace,
        anomaly_flags=flags or [],
        raw_evidence=[],
    )


def _pin_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the price catalog to the committed rules.py baseline.

    A local, gitignored ``prices.live.json`` overlay would otherwise make the
    personalised picks non-deterministic between machines and CI.
    """
    monkeypatch.setattr(pc, "_driver_prices", dict(DRIVER_PRICES_M), raising=False)
    monkeypatch.setattr(pc, "_constructor_prices", dict(CONSTRUCTOR_PRICES_M), raising=False)
    monkeypatch.setattr(pc, "_loaded", True, raising=False)


def _far_future_weekend(circuit_key: str, display_name: str, *, is_sprint: bool) -> RaceWeekend:
    """Build a race weekend with a fixed, far-future date.

    The date sits far enough ahead that the chip planner's "future races only"
    filter keeps it no matter when the test runs — so the snapshot is stable.
    """
    t = datetime(2099, 6, 1, 13, 0, tzinfo=UTC)
    return RaceWeekend(
        race_key=f"2099_{circuit_key}",
        circuit_key=circuit_key,
        display_name=display_name,
        fp1_utc=t,
        fp2_utc=t,
        fp3_utc=t,
        qualifying_utc=t,
        race_utc=t,
        fantasy_lock_utc=t,
        is_sprint=is_sprint,
    )


# ── 1. Generic picks (no team) ────────────────────────────────────────────────
def test_snapshot_picks_generic() -> None:
    monaco = get_circuit_profile("monaco")
    assert monaco is not None
    signals = [
        _sig("LEC", 16, setup=0.8, tire=0.7, pace=0.9),
        _sig("VER", 1, setup=0.6, tire=0.8, pace=0.85),
        _sig("NOR", 4, setup=0.4, tire=0.6, pace=0.7),
        _sig("HAM", 44, setup=0.2, tire=0.5, pace=0.55, flags=["balance", "overheat"]),
        _sig("PIA", 81, setup=0.5, tire=0.65, pace=0.75),
    ]
    quali = [
        QualifyingRow(driver_number=16, driver_code="LEC", grid_position=1, session_key=1),
        QualifyingRow(driver_number=1, driver_code="VER", grid_position=2, session_key=1),
        QualifyingRow(driver_number=4, driver_code="NOR", grid_position=3, session_key=1),
        QualifyingRow(driver_number=81, driver_code="PIA", grid_position=4, session_key=1),
        QualifyingRow(driver_number=44, driver_code="HAM", grid_position=5, session_key=1),
    ]
    out = generate_picks(
        PickGeneratorInput(
            circuit=monaco,
            practice_signals=signals,
            qualifying_result=quali,
            weather_forecast=None,
            user_team=None,
            race_key="2026_monaco",
            generated_by="rules",
        )
    )
    assert not out.personalized
    assert_snapshot("picks_generic_monaco", out.model_dump(mode="json"))


# ── 2. Personalised picks with a real budget constraint ───────────────────────
def test_snapshot_picks_personalized_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PITWALL_PRICES_VERIFIED", "1")
    _pin_prices(monkeypatch)

    monza = get_circuit_profile("monza")
    assert monza is not None
    # Tight budget ($4M): only near-cost-neutral swaps are legal, so the budget
    # genuinely constrains what the engine can recommend.
    team = FantasyTeam(
        phone="+15550000123",
        driver_1="VER",
        driver_2="NOR",
        driver_3="LEC",
        driver_4="ALB",
        driver_5="HAM",
        constructor_1="MER",
        constructor_2="HAA",
        remaining_budget=4.0,
        transfers_available=2,
        chips_used={},
    )
    quali = [
        QualifyingRow(driver_number=16, driver_code="LEC", grid_position=1, session_key=1),
        QualifyingRow(driver_number=1, driver_code="VER", grid_position=2, session_key=1),
        QualifyingRow(driver_number=4, driver_code="NOR", grid_position=3, session_key=1),
        QualifyingRow(driver_number=44, driver_code="HAM", grid_position=4, session_key=1),
        QualifyingRow(driver_number=23, driver_code="ALB", grid_position=12, session_key=1),
        QualifyingRow(driver_number=6, driver_code="COL", grid_position=6, session_key=1),
        QualifyingRow(driver_number=14, driver_code="ALO", grid_position=7, session_key=1),
        QualifyingRow(driver_number=31, driver_code="OCO", grid_position=8, session_key=1),
    ]
    out = generate_picks(
        PickGeneratorInput(
            circuit=monza,
            practice_signals=[],
            qualifying_result=quali,
            weather_forecast=None,
            user_team=team,
            race_key="2026_monza",
            generated_by="rules",
        )
    )
    assert out.personalized
    assert_snapshot("picks_personalized_budget_monza", out.model_dump(mode="json"))


# ── 3 & 4. Lineup grading (chip + captain) ────────────────────────────────────
def _grade_signals() -> dict[str, PracticeSignal]:
    return {
        "HAM": _sig("HAM", 44, setup=0.9, tire=0.8, pace=1.0),
        "LEC": _sig("LEC", 16, setup=0.8, tire=0.75, pace=0.95),
        "VER": _sig("VER", 1, setup=0.7, tire=0.7, pace=0.9),
        "RUS": _sig("RUS", 63, setup=0.6, tire=0.65, pace=0.85),
        "ANT": _sig("ANT", 12, setup=0.5, tire=0.6, pace=0.8),
        "NOR": _sig("NOR", 4, setup=0.2, tire=0.4, pace=0.4),
        "PIA": _sig("PIA", 81, setup=0.15, tire=0.35, pace=0.3),
    }


@pytest.mark.asyncio
async def test_snapshot_grade_limitless_with_captain(monkeypatch: pytest.MonkeyPatch) -> None:
    signals = _grade_signals()

    async def _loader(_ck: str) -> dict[str, PracticeSignal]:
        return signals

    monkeypatch.setattr(lg, "load_practice_by_driver", _loader)
    monkeypatch.setattr(lg, "circuit_key_for_race", lambda _rk: "monaco")

    msg = await lg.grade_lineup(
        "2026_monaco",
        ["HAM", "LEC", "ANT", "RUS", "VER"],
        ["FER", "MER"],
        "limitless",
        captain="HAM",
    )
    assert_snapshot("grade_limitless_captain_monaco", {"message_lines": msg.split("\n")})


@pytest.mark.asyncio
async def test_snapshot_grade_extra_drs_no_captain(monkeypatch: pytest.MonkeyPatch) -> None:
    signals = _grade_signals()

    async def _loader(_ck: str) -> dict[str, PracticeSignal]:
        return signals

    monkeypatch.setattr(lg, "load_practice_by_driver", _loader)
    monkeypatch.setattr(lg, "circuit_key_for_race", lambda _rk: "monaco")

    # DRS Boost triples (3x) the best driver; no captain stated.
    msg = await lg.grade_lineup(
        "2026_monaco",
        ["LEC", "VER", "RUS", "ANT", "NOR"],
        ["FER"],
        "extra_drs",
    )
    assert_snapshot("grade_extra_drs_no_captain_monaco", {"message_lines": msg.split("\n")})


# ── 5. Scoring a lineup against an actual race result ─────────────────────────
class _FakeResultRow:
    def __init__(self, number: int, position: int | None, *, dnf: bool = False) -> None:
        self.driver_number = number
        self.position = position
        self.dnf = dnf
        self.dns = False
        self.dsq = False


class _FakeDriverRow:
    def __init__(self, number: int, code: str) -> None:
        self.driver_number = number
        self.name_acronym = code


class _FakeOpenF1Client:
    """Returns a fixed Monaco race classification — no network."""

    _RESULTS = [
        _FakeResultRow(16, 1),    # LEC  P1
        _FakeResultRow(44, 2),    # HAM  P2
        _FakeResultRow(1, 3),     # VER  P3
        _FakeResultRow(63, 6),    # RUS  P6
        _FakeResultRow(4, None, dnf=True),  # NOR  DNF
    ]
    _ROSTER = [
        _FakeDriverRow(16, "LEC"),
        _FakeDriverRow(44, "HAM"),
        _FakeDriverRow(1, "VER"),
        _FakeDriverRow(63, "RUS"),
        _FakeDriverRow(4, "NOR"),
    ]

    async def find_session_key(self, **_kwargs: Any) -> int:
        return 999

    async def get_session_results(self, _sk: int) -> list[Any]:
        return list(self._RESULTS)

    async def get_drivers(self, _sk: int) -> list[Any]:
        return list(self._ROSTER)


@pytest.mark.asyncio
async def test_snapshot_score_against_result(monkeypatch: pytest.MonkeyPatch) -> None:
    import openf1.client as oc

    monkeypatch.setattr(oc, "OpenF1Client", _FakeOpenF1Client)

    result = await lg.score_against_result(
        "2026_monaco",
        ["LEC", "HAM", "VER", "RUS", "NOR"],
        ["FER", "MER"],
        "extra_drs",
        captain="LEC",
    )
    assert result is not None
    assert_snapshot("score_against_result_monaco", result)


# ── 6. Hindsight-perfect lineup from race positions ───────────────────────────
def test_snapshot_perfect_lineup() -> None:
    positions: dict[str, int | None] = {
        "VER": 1,
        "LEC": 2,
        "HAM": 3,
        "RUS": 4,
        "NOR": 5,
        "PIA": 6,
        "SAI": 7,
        "ALO": 8,
        "ALB": 9,
        "COL": None,  # DNF
    }
    out = perfect_lineup_from_positions(positions)
    assert_snapshot("perfect_lineup_from_positions", out)


# ── 7. Season chip plan over a fixed race list ────────────────────────────────
def test_snapshot_chip_plan() -> None:
    team = FantasyTeam(
        phone="+15550000777",
        driver_1="VER",
        driver_2="NOR",
        driver_3="LEC",
        driver_4="PIA",
        driver_5="RUS",
        constructor_1="FER",
        constructor_2="MCL",
        remaining_budget=2.0,
        transfers_available=2,
        chips_used={},
        league_mode_enabled=False,
        league_size=None,
    )
    races = [
        _far_future_weekend("monaco", "Monaco Grand Prix", is_sprint=False),
        _far_future_weekend("monza", "Italian Grand Prix", is_sprint=False),
        _far_future_weekend("spa", "Belgian Grand Prix", is_sprint=False),
        _far_future_weekend("marina_bay", "Singapore Grand Prix", is_sprint=False),
        _far_future_weekend("austin", "United States Grand Prix", is_sprint=True),
    ]
    from intelligence.chip_planner import generate_chip_plan

    plan = generate_chip_plan(team, races).model_dump(mode="json")
    # Strip the time- and random-dependent fields.
    plan.pop("generated_at", None)
    plan.pop("share_token", None)
    assert_snapshot("chip_plan_fixed_races", plan)


# ── 8. Fantasy points scales (every position 1–22 + DNF) ──────────────────────
def test_snapshot_points_rules() -> None:
    def scale(fn) -> dict[str, int]:
        table = {str(pos): fn(pos) for pos in range(1, 23)}
        table["DNF"] = fn(None, classified=False)
        return table

    constructor_cases = {
        "clean_p1_p2": constructor_points_race([25, 18]),
        "with_fastest_pit": constructor_points_race([25, 18], has_fastest_pit_in_race=True),
        "world_record_pit": constructor_points_race(
            [25, 18], pit_stop_duration_s=1.7, pit_world_record=True
        ),
        "pit_tier_2_5s": constructor_points_race([10, 8], pit_stop_duration_s=2.3),
        "one_driver_dsq": constructor_points_race([12, 0], drivers_dsq=1),
        "midfield_no_pit": constructor_points_race([6, 2]),
    }

    transfer_cases = {
        f"used_{used}_free_{free}": transfer_penalty_points(used, free)
        for free in range(0, 4)
        for used in range(0, 6)
    }

    data = {
        "driver_points_race": scale(driver_points_race),
        "driver_points_sprint": scale(driver_points_sprint),
        "driver_points_qualifying": {
            **{str(pos): driver_points_qualifying(pos) for pos in range(1, 23)},
            "DNF": driver_points_qualifying(None, classified=False),
        },
        "constructor_points_race": constructor_cases,
        "transfer_penalty_points": transfer_cases,
    }
    assert_snapshot("points_rules", data)
