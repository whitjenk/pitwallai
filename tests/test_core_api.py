"""Cover every core.api function with no network — a fake OpenF1 client only."""

from __future__ import annotations

from typing import Any

import pytest

from core import api
from core.schemas import PickOutput
from core.types import Lineup, Team

# Session keys the fake hands back per session name.
_SK = {"Practice 1": 1, "Practice 2": 2, "Qualifying": 3, "Race": 4}

# (number, code, team) — real 2026 numbers/codes so the constructor mapping works.
_ROSTER = [
    (1, "NOR", "McLaren"),
    (81, "PIA", "McLaren"),
    (16, "LEC", "Ferrari"),
    (44, "HAM", "Ferrari"),
    (63, "RUS", "Mercedes"),
    (12, "ANT", "Mercedes"),
    (3, "VER", "Red Bull Racing"),
    (23, "ALB", "Williams"),
]

# Best practice lap per driver (seconds) — ordering drives the projection.
_BEST_LAP = {1: 90.1, 81: 90.4, 16: 90.2, 44: 90.9, 63: 90.6, 12: 91.2, 3: 90.3, 23: 91.5}

# Finishing positions for the fake race result (COL-style DNF via None).
_RACE_POS = {1: 1, 16: 2, 3: 3, 81: 4, 63: 5, 44: 6, 12: 7, 23: None}


class _Lap:
    def __init__(self, number: int, duration: float) -> None:
        self.driver_number = number
        self.lap_duration = duration
        self.is_pit_out_lap = False


class _DriverRow:
    def __init__(self, number: int, code: str, team: str) -> None:
        self.driver_number = number
        self.name_acronym = code
        self.team_name = team


class _ResultRow:
    def __init__(self, number: int, position: int | None) -> None:
        self.driver_number = number
        self.position = position
        self.dnf = position is None
        self.dns = False
        self.dsq = False


class FakeClient:
    """Implements only the OpenF1 methods core.api touches — no network."""

    async def find_session_key(self, **kwargs: Any) -> int | None:
        return _SK.get(kwargs.get("session_name"))

    async def get_laps(self, session_key: int) -> list[_Lap]:
        # A couple of timed laps each; FP2 (sk=2) a touch quicker than FP1.
        bump = 0.0 if session_key == _SK["Practice 2"] else 0.2
        laps: list[_Lap] = []
        for number, best in _BEST_LAP.items():
            laps.append(_Lap(number, best + bump))
            laps.append(_Lap(number, best + bump + 0.3))
        return laps

    async def get_drivers(self, session_key: int) -> list[_DriverRow]:
        return [_DriverRow(n, c, t) for n, c, t in _ROSTER]

    async def get_session_results(self, session_key: int) -> list[_ResultRow]:
        if session_key == _SK["Qualifying"]:
            # A clean grid (position by best practice lap), no DNFs.
            order = sorted(_BEST_LAP, key=lambda n: _BEST_LAP[n])
            return [_ResultRow(n, pos) for pos, n in enumerate(order, start=1)]
        if session_key == _SK["Race"]:
            return [_ResultRow(n, pos) for n, pos in _RACE_POS.items()]
        return []


RACE_KEY = "2026_monaco"


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def team() -> Team:
    return Team(
        drivers=["VER", "NOR", "LEC", "ALB", "HAM"],
        constructors=["MER", "HAA"],
        budget_m=4.0,
        transfers_available=2,
        chips_used={},
    )


@pytest.fixture
def lineup() -> Lineup:
    return Lineup(
        drivers=["NOR", "LEC", "VER", "RUS", "PIA"],
        constructors=["MCL", "FER"],
        chip="limitless",
        captain="NOR",
    )


def test_race_calendar() -> None:
    cal = api.race_calendar()
    assert len(cal) == 22
    assert cal[5].display_name == "Monaco Grand Prix"


def test_chip_plan(team: Team) -> None:
    plan = api.chip_plan(team, api.race_calendar())
    # Every window is a real calendar race; no used chip is ever recommended.
    assert plan.windows
    assert all(w.race_key for w in plan.windows)


async def test_project_race(client: FakeClient) -> None:
    out = await api.project_race(RACE_KEY, client)
    assert out["race_key"] == RACE_KEY
    assert out["top_drivers"] and out["captain"] == out["top_drivers"][0]
    # NOR set the quickest lap, so projects P1 and is the captain pick.
    assert out["captain"] == "NOR"
    assert out["top_constructors"]
    assert out["drivers"]["NOR"]["projected_grid"] == 1


async def test_project_race_unknown_weekend(client: FakeClient) -> None:
    assert await api.project_race("1999_nowhere", client) == {}


async def test_suggest_transfers(team: Team, client: FakeClient) -> None:
    out = await api.suggest_transfers(team, RACE_KEY, client)
    assert isinstance(out, PickOutput)
    assert out.picks  # up to three ranked recommendations
    assert len(out.picks) <= 3


async def test_grade_lineup(lineup: Lineup, client: FakeClient) -> None:
    graded = await api.grade_lineup(lineup, RACE_KEY, client)
    assert graded["race_key"] == RACE_KEY
    assert set(graded["driver_points"]) == set(lineup.drivers)
    assert graded["captain"] == "NOR"
    # Limitless captain doubles (not triples) the captain's projected points.
    assert graded["captain_bonus"] == pytest.approx(graded["driver_points"]["NOR"])
    assert graded["projected_total"] >= sum(graded["driver_points"].values())


async def test_score_lineup(lineup: Lineup, client: FakeClient) -> None:
    scored = await api.score_lineup(lineup, RACE_KEY, client)
    assert scored is not None
    assert scored["race_key"] == RACE_KEY
    # NOR finished P1; captain bonus equals NOR's race points (limitless = 2x).
    assert scored["captain"] == "NOR"
    assert scored["captain_bonus"] == scored["driver_points"]["NOR"]
    assert scored["total"] > 0


async def test_score_lineup_before_race(lineup: Lineup) -> None:
    class _NoResult(FakeClient):
        async def get_session_results(self, session_key: int) -> list[_ResultRow]:
            return []

    assert await api.score_lineup(lineup, RACE_KEY, _NoResult()) is None
