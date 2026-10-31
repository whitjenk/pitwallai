"""Public API for the fantasy core — everything the Slack app calls.

Each function is a thin, documented entry point over the engine in ``core``.
Nothing here touches the database, a chat platform or the old agent layer;
functions that need live timing data take an ``OpenF1Client`` and read it live
(caching is not core's job). See ``core/README.md`` for one-line examples.
"""

from __future__ import annotations

from core.calendar import (
    CALENDAR_2026,
    RaceWeekend,
    get_race_weekend,
    profile_circuit_key,
)
from core.chip_planner import ChipPlan, generate_chip_plan
from core.circuits import CircuitProfile, get_circuit_profile
from core.lap_signals import build_lap_only_signals
from core.lineup_grader import perfect_lineup_from_positions
from core.pick_generator import (
    _constructor_drivers,
    _driver_score,
    _projected_race_points,
    build_qualifying_rows,
    generate_picks,
)
from core.race_key import parse_race_key
from core.rules import CONSTRUCTOR_PRICES_M, driver_points_race
from core.schemas import PickGeneratorInput, PickOutput, PracticeSignal, QualifyingRow
from core.types import Lineup, Team
from openf1.client import OpenF1Client


# ── Calendar & chips (no live data) ───────────────────────────────────────────
def race_calendar() -> list[RaceWeekend]:
    """Return the 2026 race calendar in schedule order.

    >>> race_calendar()[5].display_name
    'Monaco Grand Prix'
    """
    return list(CALENDAR_2026)


def chip_plan(team: Team, races: list[RaceWeekend]) -> ChipPlan:
    """Rank ``races`` for chip windows for ``team`` — observational, never used chips.

    >>> plan = chip_plan(team, race_calendar())
    """
    return generate_chip_plan(team, races)


# ── Live-data helpers (shared by the projection entry points) ─────────────────
class _TeamAdapter:
    """Expose a ``core.types.Team`` with the attribute shape the pick engine
    reads (the legacy ``driver_1..5`` / ``remaining_budget`` / ``constructor_1/2``
    layout), so core needs no db.models import."""

    def __init__(self, team: Team) -> None:
        drivers = (list(team.drivers) + [None] * 5)[:5]
        (self.driver_1, self.driver_2, self.driver_3,
         self.driver_4, self.driver_5) = drivers
        constructors = (list(team.constructors) + [None, None])[:2]
        self.constructor_1, self.constructor_2 = constructors
        self.remaining_budget = team.budget_m
        self.transfers_available = team.transfers_available
        self.chips_used = dict(team.chips_used)
        self.league_size = None
        self.league_mode_enabled = False


async def _practice_signals(
    race_key: str, client: OpenF1Client
) -> dict[str, PracticeSignal]:
    """Lap-only FP1/FP2 practice signals for a weekend, keyed by driver code.

    Live OpenF1 laps only (prefers FP2); empty when the weekend is unknown or
    practice timing hasn't been published yet.
    """
    weekend = get_race_weekend(race_key)
    parsed = parse_race_key(race_key)
    if weekend is None or parsed is None:
        return {}
    year, _ = parsed
    circuit = get_circuit_profile(profile_circuit_key(weekend.circuit_key))
    if circuit is None:
        return {}
    session_keys: dict[str, int] = {}
    for label, name in (("FP1", "Practice 1"), ("FP2", "Practice 2")):
        sk = await client.find_session_key(
            year=year, circuit_short_name=circuit.openf1_circuit_name, session_name=name
        )
        if sk is not None:
            session_keys[label] = sk
    if not session_keys:
        return {}
    by_code: dict[str, PracticeSignal] = {}
    for sig in await build_lap_only_signals(client, session_keys=session_keys):
        if sig.driver_code not in by_code or sig.session == "FP2":
            by_code[sig.driver_code] = sig
    return by_code


def _projected_grid(
    signals: dict[str, PracticeSignal], circuit: CircuitProfile | None
) -> dict[str, int]:
    """Projected finishing order (code -> position) from practice pace."""
    candidates = set(signals)
    if circuit and candidates:
        ranked = sorted(
            candidates,
            key=lambda c: _driver_score(c, circuit=circuit, signals=signals, grid={}),
            reverse=True,
        )
    else:
        ranked = sorted(candidates, key=lambda c: signals[c].pace_satisfaction, reverse=True)
    return {code: pos for pos, code in enumerate(ranked, start=1)}


# ── Projection, transfers, grade, score (live data) ───────────────────────────
async def project_race(race_key: str, client: OpenF1Client) -> dict:
    """Project a race from live FP1/FP2 pace.

    Returns each driver's projected finishing slot and fantasy points, plus
    PitWallAI's top-5 drivers, top-2 constructors and best captain. ``{}`` when
    no practice timing is available yet.

    >>> await project_race("2026_monaco", client)
    {'race_key': '2026_monaco', 'drivers': {...}, 'top_drivers': [...], ...}
    """
    weekend = get_race_weekend(race_key)
    circuit = (
        get_circuit_profile(profile_circuit_key(weekend.circuit_key)) if weekend else None
    )
    signals = await _practice_signals(race_key, client)
    if not signals:
        return {}
    grid = _projected_grid(signals, circuit)

    def pts(code: str) -> float:
        return _projected_race_points(grid.get(code))

    con_map = _constructor_drivers(set(grid))
    con_scores = {
        con: sum(_projected_race_points(grid.get(d)) for d in con_map.get(con, [])[:2])
        for con in CONSTRUCTOR_PRICES_M
    }
    top_drivers = sorted((c for c in grid), key=pts, reverse=True)[:5]
    return {
        "race_key": race_key,
        "drivers": {
            c: {"projected_grid": grid[c], "projected_points": pts(c)} for c in grid
        },
        "top_drivers": top_drivers,
        "top_constructors": sorted(con_scores, key=lambda c: con_scores[c], reverse=True)[:2],
        "captain": top_drivers[0] if top_drivers else None,
    }


async def suggest_transfers(team: Team, race_key: str, client: OpenF1Client) -> PickOutput:
    """Rank transfer and captain picks for ``team`` at a race, from live data.

    Assembles the pick-engine input (circuit profile, live practice signals, the
    qualifying grid once it's set) and returns the sacred ``PickOutput``.

    >>> out = await suggest_transfers(team, "2026_monza", client)
    >>> out.picks[0].headline
    """
    weekend = get_race_weekend(race_key)
    circuit = (
        get_circuit_profile(profile_circuit_key(weekend.circuit_key)) if weekend else None
    )
    if circuit is None:
        raise ValueError(f"No circuit profile for race_key {race_key!r}")
    signals = list((await _practice_signals(race_key, client)).values())
    qualifying: list[QualifyingRow] = []
    parsed = parse_race_key(race_key)
    if parsed is not None:
        year, _ = parsed
        sk = await client.find_session_key(
            year=year,
            circuit_short_name=circuit.openf1_circuit_name,
            session_name="Qualifying",
        )
        if sk is not None:
            qualifying = await build_qualifying_rows(client, sk)
    ctx = PickGeneratorInput(
        circuit=circuit,
        practice_signals=signals,
        qualifying_result=qualifying,
        weather_forecast=None,
        user_team=_TeamAdapter(team),
        race_key=race_key,
    )
    return generate_picks(ctx)


async def grade_lineup(lineup: Lineup, race_key: str, client: OpenF1Client) -> dict:
    """Grade a stated lineup against PitWallAI's projection from live pace.

    Returns projected points for the stated drivers and constructors, the best
    captain and bonus, the projected total, and which of the model's top picks
    the lineup matches. ``{}`` when no practice timing is available yet.

    >>> await grade_lineup(lineup, "2026_monaco", client)
    """
    weekend = get_race_weekend(race_key)
    circuit = (
        get_circuit_profile(profile_circuit_key(weekend.circuit_key)) if weekend else None
    )
    signals = await _practice_signals(race_key, client)
    if not signals:
        return {}
    grid = _projected_grid(signals, circuit)

    def pts(code: str) -> float:
        return _projected_race_points(grid.get(code.upper()))

    con_map = _constructor_drivers(set(grid))

    def con_pts(con: str) -> float:
        return sum(_projected_race_points(grid.get(d)) for d in con_map.get(con.upper(), [])[:2])

    drivers = [d.upper() for d in lineup.drivers]
    multiplier = 3 if lineup.chip == "extra_drs" else 2
    best_cap = max(drivers, key=pts) if drivers else None
    captain = lineup.captain.upper() if lineup.captain else best_cap
    cap_bonus = pts(captain) * (multiplier - 1) if captain else 0.0
    driver_points = {d: pts(d) for d in drivers}
    constructor_points = {c.upper(): con_pts(c) for c in lineup.constructors}
    top_drivers = sorted((c for c in grid), key=pts, reverse=True)[:5]
    return {
        "race_key": race_key,
        "driver_points": driver_points,
        "constructor_points": constructor_points,
        "captain": captain,
        "captain_bonus": cap_bonus,
        "projected_total": sum(driver_points.values())
        + sum(constructor_points.values())
        + cap_bonus,
        "model_top_drivers": top_drivers,
        "drivers_matching_model": [d for d in drivers if d in top_drivers],
    }


async def score_lineup(lineup: Lineup, race_key: str, client: OpenF1Client) -> dict | None:
    """Actual fantasy points for a lineup from the finished race, or ``None``.

    ``None`` when the race hasn't been classified yet (no result from OpenF1).
    Also returns the race's finishing ``positions`` (code -> finishing slot, or
    ``None`` for a DNF/DNS/DSQ) and the hindsight-``perfect`` lineup for the
    race, so a caller can show a lineup against the best that was on the table.

    >>> await score_lineup(lineup, "2026_monaco", client)
    {'race_key': '2026_monaco', 'total': 112, 'perfect': {...}, ...}
    """
    weekend = get_race_weekend(race_key)
    parsed = parse_race_key(race_key)
    if weekend is None or parsed is None:
        return None
    year, _ = parsed
    circuit = get_circuit_profile(profile_circuit_key(weekend.circuit_key))
    if circuit is None:
        return None
    sk = await client.find_session_key(
        year=year, circuit_short_name=circuit.openf1_circuit_name, session_name="Race"
    )
    if sk is None:
        return None
    rows = await client.get_session_results(sk)
    if not rows:
        return None
    roster = {r.driver_number: (r.name_acronym or "") for r in await client.get_drivers(sk)}
    pos_by_code: dict[str, int | None] = {}
    for r in rows:
        code = roster.get(r.driver_number, "").upper()
        if not code:
            continue
        pos_by_code[code] = None if (r.dnf or r.dns or r.dsq) else r.position

    def d_pts(code: str) -> int:
        if code not in pos_by_code:
            return 0
        pos = pos_by_code[code]
        return driver_points_race(pos, classified=pos is not None)

    con_map = _constructor_drivers(set(pos_by_code))
    multiplier = 3 if lineup.chip == "extra_drs" else 2
    drivers = [d.upper() for d in lineup.drivers]
    captain = (
        lineup.captain.upper()
        if lineup.captain
        else (max(drivers, key=d_pts) if drivers else None)
    )
    driver_points = {d: d_pts(d) for d in drivers}
    cap_bonus = driver_points.get(captain, 0) * (multiplier - 1) if captain else 0
    constructor_points = {
        c.upper(): sum(d_pts(x) for x in con_map.get(c.upper(), [])[:2])
        for c in lineup.constructors
    }
    return {
        "race_key": race_key,
        "total": sum(driver_points.values()) + sum(constructor_points.values()) + cap_bonus,
        "driver_points": driver_points,
        "constructor_points": constructor_points,
        "captain": captain,
        "captain_bonus": cap_bonus,
        "positions": pos_by_code,
        "perfect": perfect_lineup_from_positions(pos_by_code),
    }
