"""
Constructor strategy tendency model from historical OpenF1 pit/lap data.

Signals are observational proxies — not live strategy predictions:

- *Pace-competitive stop*: constructor's first pitter was within 2s of the field's
  fastest lap time on the lap before their stop (not gap to race leader).
- *Early pit (field-relative)*: first stop lap ≤ median first-stop lap in that race.
- *Cross-team undercut attempt*: constructor pits before another constructor's first
  stop by 1–3 laps (team-level timing, not wheel-to-wheel).
- *Undercut success (proxy)*: first-stopping driver finishes ahead of the rival
  constructor's best classified finisher (finish-order proxy, not on-track undercut).
- *Hedge*: teammates' first stops are ≥5 laps apart.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from circuits.profiles import CircuitProfile
from intelligence.drivers import constructor_code_for_driver, driver_code_for
from openf1.client import OpenF1Client
from openf1.models import DriverSessionRow, LapRecord, PitStop, SessionResultRow

# Minimum evidence before quali strategist / WhatsApp surface tendencies.
MIN_SAMPLE_RACES = 3
MIN_LEAD_WINDOW_SAMPLES = 5
MIN_UNDERCUT_ATTEMPTS = 3
PACE_COMPETITIVE_GAP_S = 2.0


@dataclass(frozen=True, slots=True)
class ConstructorStrategyProfile:
    constructor_code: str
    sample_races: int
    lead_window_samples: int
    early_pit_count: int
    early_pit_rate: float
    undercut_attempts: int
    undercut_successes: int
    undercut_success_rate: float
    hedge_events: int
    hedge_rate: float


def driver_code_from_session(
    driver_number: int,
    session_numbers: dict[int, str],
) -> str:
    """Resolve driver code from session roster, else static fallback."""
    return session_numbers.get(driver_number, driver_code_for(driver_number))


def _session_driver_codes(drivers: list[DriverSessionRow]) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in drivers:
        acronym = (row.name_acronym or "").strip().upper()
        if acronym:
            out[row.driver_number] = acronym
    return out


def _lap_durations_by_driver(
    laps: list[LapRecord],
    session_numbers: dict[int, str],
) -> dict[str, dict[int, float]]:
    by_driver: dict[str, dict[int, float]] = defaultdict(dict)
    for lap in laps:
        if lap.lap_number <= 0 or lap.lap_duration is None:
            continue
        code = driver_code_from_session(lap.driver_number, session_numbers)
        by_driver[code][lap.lap_number] = float(lap.lap_duration)
    return by_driver


def _first_pit_laps(
    pits: list[PitStop],
    session_numbers: dict[int, str],
) -> dict[str, int]:
    first: dict[str, int] = {}
    for stop in sorted(pits, key=lambda p: ((p.lap_number or 9999), p.driver_number)):
        if stop.lap_number is None:
            continue
        code = driver_code_from_session(stop.driver_number, session_numbers)
        first.setdefault(code, int(stop.lap_number))
    return first


def _result_positions(
    results: list[SessionResultRow],
    session_numbers: dict[int, str],
) -> dict[str, int]:
    pos: dict[str, int] = {}
    for row in results:
        if row.position is None:
            continue
        pos[driver_code_from_session(row.driver_number, session_numbers)] = int(row.position)
    return pos


def _pace_delta_vs_field_best_on_lap(
    driver_code: str,
    lap_number: int,
    by_driver_laps: dict[str, dict[int, float]],
) -> float | None:
    """Seconds slower than the fastest lap time on this lap (field best)."""
    my = by_driver_laps.get(driver_code, {}).get(lap_number)
    if my is None:
        return None
    lap_values = [d.get(lap_number) for d in by_driver_laps.values()]
    lap_values = [v for v in lap_values if v is not None]
    if not lap_values:
        return None
    return float(my - min(lap_values))


def _build_from_single_race(
    pits: list[PitStop],
    laps: list[LapRecord],
    results: list[SessionResultRow],
    session_numbers: dict[int, str],
) -> dict[str, dict[str, float]]:
    """Build per-constructor strategy event counters for one race."""
    by_driver_laps = _lap_durations_by_driver(laps, session_numbers)
    first_pit = _first_pit_laps(pits, session_numbers)
    positions = _result_positions(results, session_numbers)

    by_constructor: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for code, lap in first_pit.items():
        constructor = constructor_code_for_driver(code)
        if constructor == "UNK":
            continue
        by_constructor[constructor].append((code, lap))

    if not by_constructor:
        return {}

    all_first_pits = sorted([lap for _, lap in first_pit.items()])
    early_threshold = int(median(all_first_pits))

    out: dict[str, dict[str, float]] = {}
    for constructor, entries in by_constructor.items():
        entries.sort(key=lambda x: x[1])
        first_driver, first_lap = entries[0]
        row = {
            "sample_races": 1.0,
            "lead_window_samples": 0.0,
            "early_pit_count": 0.0,
            "undercut_attempts": 0.0,
            "undercut_successes": 0.0,
            "hedge_events": 0.0,
        }

        gap = _pace_delta_vs_field_best_on_lap(
            first_driver,
            max(1, first_lap - 1),
            by_driver_laps,
        )
        if gap is not None and gap <= PACE_COMPETITIVE_GAP_S:
            row["lead_window_samples"] += 1.0
            if first_lap <= early_threshold:
                row["early_pit_count"] += 1.0

        first_lap_by_constructor = {
            c: min(lap for _, lap in vals) for c, vals in by_constructor.items()
        }
        my_pos = positions.get(first_driver)
        for other_constructor, other_first_lap in first_lap_by_constructor.items():
            if other_constructor == constructor:
                continue
            if first_lap < other_first_lap <= first_lap + 3:
                row["undercut_attempts"] += 1.0
                if my_pos is None:
                    continue
                rival_drivers = [d for d, _ in by_constructor[other_constructor]]
                rival_positions = [
                    positions.get(d) for d in rival_drivers if positions.get(d) is not None
                ]
                if rival_positions and my_pos < min(rival_positions):
                    row["undercut_successes"] += 1.0

        if len(entries) >= 2 and abs(entries[1][1] - entries[0][1]) >= 5:
            row["hedge_events"] += 1.0

        out[constructor] = row
    return out


async def build_constructor_strategy_profiles(
    client: OpenF1Client,
    circuit: CircuitProfile,
    *,
    years: range = range(2021, 2026),
) -> list[ConstructorStrategyProfile]:
    """Aggregate per-constructor strategy tendencies for a circuit (2021–2025 races)."""
    agg: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for year in years:
        session_key = await client.find_session_key(
            year=year,
            circuit_short_name=circuit.openf1_circuit_name,
            session_name="Race",
        )
        if session_key is None:
            continue
        drivers, pits, laps, results = await asyncio.gather(
            client.get_drivers(session_key),
            client.get_pit_stops(session_key),
            client.get_laps(session_key),
            client.get_session_results(session_key),
        )
        session_numbers = _session_driver_codes(drivers)
        race_rows = _build_from_single_race(pits, laps, results, session_numbers)
        for constructor, counters in race_rows.items():
            for key, value in counters.items():
                agg[constructor][key] += value

    profiles: list[ConstructorStrategyProfile] = []
    for constructor, c in agg.items():
        samples = int(c["sample_races"])
        lead_samples = int(c["lead_window_samples"])
        early_count = int(c["early_pit_count"])
        undercut_attempts = int(c["undercut_attempts"])
        undercut_successes = int(c["undercut_successes"])
        hedge_events = int(c["hedge_events"])

        early_rate = (early_count / lead_samples) if lead_samples else 0.0
        undercut_rate = (undercut_successes / undercut_attempts) if undercut_attempts else 0.0
        hedge_rate = (hedge_events / samples) if samples else 0.0
        profiles.append(
            ConstructorStrategyProfile(
                constructor_code=constructor,
                sample_races=samples,
                lead_window_samples=lead_samples,
                early_pit_count=early_count,
                early_pit_rate=round(early_rate, 3),
                undercut_attempts=undercut_attempts,
                undercut_successes=undercut_successes,
                undercut_success_rate=round(undercut_rate, 3),
                hedge_events=hedge_events,
                hedge_rate=round(hedge_rate, 3),
            )
        )
    profiles.sort(key=lambda p: p.constructor_code)
    return profiles
