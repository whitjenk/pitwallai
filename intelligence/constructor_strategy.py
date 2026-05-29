"""
Constructor strategy profiles from OpenF1 pit history (data science + one LLM sentence).

OpenF1 team_name → constructor_code mapping is maintained here; update when teams
rebrand (e.g. Sauber → Audi, Alpine naming). Verify against GET /v1/drivers team_name.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from circuits.profiles import CircuitProfile, all_circuit_keys, get_circuit_profile
from intelligence.drivers import constructor_code_for_driver, driver_code_for
from openf1.client import OpenF1Client
from openf1.models import DriverSessionRow, LapRecord, PitStop, PositionSample, RaceControlMessage

# Fantasy / OpenF1 constructor codes used by seeder (2022–2026 grid).
CONSTRUCTOR_CODES: tuple[str, ...] = (
    "FER",
    "MCL",
    "MER",
    "RBR",
    "AMR",
    "WIL",
    "HAA",
    "SAU",
    "VCA",
    "RBT",
)

MIN_SAMPLE_RACES = 3
MIN_OWNERSHIP_GROUP = 5
MIN_ATTACK_SUBSCRIBERS = 3

# Legacy quali thresholds (old ConstructorStrategyRow path).
MIN_LEAD_WINDOW_SAMPLES = 5
MIN_UNDERCUT_ATTEMPTS = 3
PACE_COMPETITIVE_GAP_S = 2.0


# OpenF1 team_name substrings → constructor_code (update on rebrand).
_OPENF1_TEAM_TO_CONSTRUCTOR: tuple[tuple[str, str], ...] = (
    ("racing bulls", "RBT"),
    ("vcarb", "RBT"),
    ("visa cash app rb", "RBT"),
    ("red bull racing", "RBR"),
    ("red bull", "RBR"),
    ("ferrari", "FER"),
    ("mercedes", "MER"),
    ("mclaren", "MCL"),
    ("aston martin", "AMR"),
    ("williams", "WIL"),
    ("haas", "HAA"),
    ("kick sauber", "SAU"),
    ("sauber", "SAU"),
    ("audi", "SAU"),
    ("alpine", "VCA"),
    ("cadillac", "CAD"),
)


def openf1_team_to_constructor(team_name: str | None) -> str | None:
    """Map OpenF1 drivers.team_name to constructor_code."""
    if not team_name:
        return None
    lower = team_name.strip().lower()
    for needle, code in _OPENF1_TEAM_TO_CONSTRUCTOR:
        if needle in lower:
            return code
    return None


@dataclass(frozen=True, slots=True)
class PitEvent:
    """One pit stop in a race weekend sample."""

    year: int
    race_key: str
    driver_number: int
    constructor_code: str
    lap_number: int
    pit_duration: float
    race_total_laps: int
    position_at_pit: int | None
    position_after_pit: int | None
    was_under_sc: bool
    was_double_stack: bool
    stint_number: int


class ConstructorStrategyProfileData(BaseModel):
    """Calculated profile (not persisted until upsert)."""

    model_config = ConfigDict(frozen=True)

    constructor_code: str
    circuit_key: str
    sample_size: int
    early_box_rate: float = Field(ge=0.0, le=1.0)
    undercut_attempt_rate: float | None = None
    overcut_rate: float = Field(ge=0.0, le=1.0)
    avg_pit_window_open_lap: float = Field(ge=0.0, le=1.0)
    double_stack_rate: float = Field(ge=0.0, le=1.0)
    safety_car_opportunist: float = Field(ge=0.0, le=1.0)
    championship_pressure_modifier: float = Field(ge=-1.0, le=1.0)
    fantasy_tendency: str = Field(max_length=120)
    data_quality: str
    source_race_keys: list[str] = Field(default_factory=list)


# --- Legacy in-memory profile (context_builder / tests) ---


@dataclass(frozen=True, slots=True)
class ConstructorStrategyProfileLegacy:
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


def _session_driver_codes(drivers: list[DriverSessionRow]) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in drivers:
        acronym = (row.name_acronym or "").strip().upper()
        if acronym:
            out[row.driver_number] = acronym
    return out


def _driver_constructor_map(
    drivers: list[DriverSessionRow],
    session_numbers: dict[int, str],
) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for row in drivers:
        code = openf1_team_to_constructor(row.team_name)
        if code is None:
            code = constructor_code_for_driver(
                session_numbers.get(row.driver_number, driver_code_for(row.driver_number))
            )
        mapping[row.driver_number] = code
    return mapping


def _sc_laps(messages: list[RaceControlMessage]) -> set[int]:
    laps: set[int] = set()
    for msg in messages:
        text = (msg.message or "").upper()
        if "SAFETY CAR" in text or "VIRTUAL SAFETY CAR" in text or " VSC" in text:
            if msg.lap_number is not None:
                laps.add(int(msg.lap_number))
    return laps


def _position_at_lap(
    positions: list[PositionSample],
    driver_number: int,
    lap_number: int,
) -> int | None:
    """Best-effort position on lap (OpenF1 position may lack lap — use last known)."""
    best: int | None = None
    for sample in positions:
        if sample.driver_number != driver_number or sample.position is None:
            continue
        best = int(sample.position)
    return best


async def fetch_pit_history(
    circuit_key: str,
    constructor_code: str,
    *,
    years: list[int] | None = None,
    client: OpenF1Client | None = None,
) -> list[PitEvent]:
    """
    Fetch pit history for one constructor at a circuit across years.

    Rate-limited via OpenF1Client (4 req/s). Returns [] if <2 years of data.
    """
    circuit = get_circuit_profile(circuit_key)
    if circuit is None:
        logger.warning("fetch_pit_history: unknown circuit_key={}", circuit_key)
        return []

    year_list = years or [2022, 2023, 2024, 2025]
    client = client or OpenF1Client()
    events: list[PitEvent] = []
    years_with_data = 0

    for year in year_list:
        session_key = await client.find_session_key(
            year=year,
            circuit_short_name=circuit.openf1_circuit_name,
            session_name="Race",
        )
        if session_key is None:
            continue

        drivers, pits, laps, race_control, positions, results = await asyncio.gather(
            client.get_drivers(session_key),
            client.get_pit_stops(session_key),
            client.get_laps(session_key),
            client.get_race_control(session_key),
            client.get_positions(session_key),
            client.get_session_results(session_key),
        )
        session_numbers = _session_driver_codes(drivers)
        team_map = _driver_constructor_map(drivers, session_numbers)
        race_laps = [lap.lap_number for lap in laps if lap.lap_number and lap.lap_number > 0]
        race_total = max(race_laps) if race_laps else 58
        sc_laps = _sc_laps(race_control)
        race_key = f"{year}_{circuit_key}"

        final_pos = {
            row.driver_number: int(row.position)
            for row in results
            if row.position is not None
        }

        pits_by_driver: dict[int, list[PitStop]] = defaultdict(list)
        for pit in pits:
            if pit.lap_number is None:
                continue
            if team_map.get(pit.driver_number) != constructor_code:
                continue
            pits_by_driver[pit.driver_number].append(pit)

        if not pits_by_driver:
            continue

        years_with_data += 1
        for driver_number, driver_pits in pits_by_driver.items():
            driver_pits.sort(key=lambda p: p.lap_number or 0)
            for stint_idx, pit in enumerate(driver_pits, start=1):
                lap = int(pit.lap_number or 0)
                pos_at = _position_at_lap(positions, driver_number, lap)
                events.append(
                    PitEvent(
                        year=year,
                        race_key=race_key,
                        driver_number=driver_number,
                        constructor_code=constructor_code,
                        lap_number=lap,
                        pit_duration=float(pit.pit_duration or 0.0),
                        race_total_laps=race_total,
                        position_at_pit=pos_at,
                        position_after_pit=final_pos.get(driver_number),
                        was_under_sc=lap in sc_laps,
                        was_double_stack=False,
                        stint_number=stint_idx,
                    )
                )

        race_event_indices = [
            i
            for i, e in enumerate(events)
            if e.race_key == race_key and e.constructor_code == constructor_code
        ]
        first_pits = [
            (dn, min(p.lap_number for p in ps if p.lap_number))
            for dn, ps in pits_by_driver.items()
        ]
        double_stack_drivers: set[int] = set()
        if len(first_pits) >= 2:
            first_pits.sort(key=lambda x: x[1])
            for i in range(len(first_pits) - 1):
                if first_pits[i + 1][1] - first_pits[i][1] <= 2:
                    double_stack_drivers.add(first_pits[i][0])
                    double_stack_drivers.add(first_pits[i + 1][0])
        if double_stack_drivers:
            rebuilt: list[PitEvent] = []
            for idx, e in enumerate(events):
                if idx in race_event_indices and e.driver_number in double_stack_drivers:
                    rebuilt.append(
                        PitEvent(
                            year=e.year,
                            race_key=e.race_key,
                            driver_number=e.driver_number,
                            constructor_code=e.constructor_code,
                            lap_number=e.lap_number,
                            pit_duration=e.pit_duration,
                            race_total_laps=e.race_total_laps,
                            position_at_pit=e.position_at_pit,
                            position_after_pit=e.position_after_pit,
                            was_under_sc=e.was_under_sc,
                            was_double_stack=True,
                            stint_number=e.stint_number,
                        )
                    )
                else:
                    rebuilt.append(e)
            events = rebuilt

    if years_with_data < 2:
        logger.warning(
            "fetch_pit_history: LOW data circuit={} constructor={} years={}",
            circuit_key,
            constructor_code,
            years_with_data,
        )
    return events


def _dedupe_events(events: list[PitEvent]) -> list[PitEvent]:
    seen: set[tuple[str, int, int, int]] = set()
    out: list[PitEvent] = []
    for event in events:
        key = (event.race_key, event.driver_number, event.lap_number, event.stint_number)
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return out


def _data_quality_label(sample_size: int, _undercut_available: bool = True) -> str:
    if sample_size >= 5:
        return "HIGH"
    if sample_size >= 3:
        return "MEDIUM"
    return "LOW"


def _fallback_fantasy_tendency(
    profile: ConstructorStrategyProfileData,
    constructor_code: str,
    circuit: CircuitProfile,
) -> str:
    parts: list[str] = []
    if profile.early_box_rate > 0.6:
        parts.append("often boxes early")
    if profile.undercut_attempt_rate and profile.undercut_attempt_rate > 0.5:
        parts.append("active undercut timing")
    if profile.safety_car_opportunist > 0.6:
        parts.append("uses SC pit windows")
    if not parts:
        parts.append("mixed pit strategy")
    text = (
        f"{constructor_code} at {circuit.display_name}: "
        + ", ".join(parts)
        + f" ({profile.sample_size} races sampled)"
    )
    return text[:120]


async def _generate_fantasy_tendency(
    profile: ConstructorStrategyProfileData,
    constructor_code: str,
    circuit: CircuitProfile,
) -> str:
    """One LLM sentence per profile at seed time; sanitised evidence-only."""
    from pitwallai.agents.radio_intercept.decoder_factory import _sanitise_evidence_summary
    from pitwallai.agents.radio_intercept.model_factory import get_model, resolve_api_key
    from pitwallai.agents.radio_intercept.config import PitWallSettings

    settings = PitWallSettings.from_env()
    provider = (settings.llm_provider or "gemini").strip().lower()
    undercut = profile.undercut_attempt_rate
    prompt = (
        f"Given these F1 strategy stats for {constructor_code} at {circuit.display_name}: "
        f"early_box_rate={profile.early_box_rate:.2f}, "
        f"undercut_rate={undercut if undercut is not None else 'n/a'}, "
        f"sc_opportunist={profile.safety_car_opportunist:.2f}, "
        f"sample_size={profile.sample_size}. "
        "Write one sentence (under 120 chars) describing fantasy implications for a "
        "driver owner. Focus on position gains or losses vs grid slot. "
        "Observation only, no directives."
    )
    try:
        from pydantic_ai import Agent

        model = get_model(provider, resolve_api_key(provider))
        agent = Agent(
            model,
            system_prompt=(
                "You write factual F1 fantasy observations only. Never instruct the reader."
            ),
        )
        result = await agent.run(prompt)
        raw = str(result.output).strip()[:120]
        cleaned = _sanitise_evidence_summary(raw)
        if cleaned:
            return cleaned[:120]
    except Exception as exc:
        logger.debug("fantasy_tendency LLM skipped: {}", exc)
    return _fallback_fantasy_tendency(profile, constructor_code, circuit)


def calculate_strategy_profile(
    pit_events: list[PitEvent],
    constructor_code: str,
    circuit_key: str,
    *,
    fantasy_tendency: str = "",
) -> ConstructorStrategyProfileData:
    """Compute metrics from pit events synchronously (no LLM; for tests)."""
    return _compute_profile_metrics(
        pit_events,
        constructor_code,
        circuit_key,
        fantasy_tendency=fantasy_tendency,
    )


def _compute_profile_metrics(
    pit_events: list[PitEvent],
    constructor_code: str,
    circuit_key: str,
    *,
    fantasy_tendency: str = "",
) -> ConstructorStrategyProfileData:
    circuit = get_circuit_profile(circuit_key)
    if circuit is None:
        raise ValueError(f"Unknown circuit_key: {circuit_key}")

    events = _dedupe_events(pit_events)
    race_keys = sorted({e.race_key for e in events})
    sample_size = len(race_keys)

    by_race: dict[str, list[PitEvent]] = defaultdict(list)
    for event in events:
        by_race[event.race_key].append(event)

    early_box_races = 0
    overcut_races = 0
    double_stack_races = 0
    sc_top5_opportunities = 0
    sc_top5_pitted = 0
    stint1_norm_laps: list[float] = []
    undercut_attempts = 0
    undercut_races_total = 0
    pressure_early: list[float] = []
    relaxed_early: list[float] = []

    for race_key, race_events in by_race.items():
        stint1 = [e for e in race_events if e.stint_number == 1]
        if not stint1:
            continue
        first_lap = min(e.lap_number for e in stint1)
        total = stint1[0].race_total_laps or 58
        norm = first_lap / total
        stint1_norm_laps.append(norm)
        if norm < 0.4:
            early_box_races += 1

        pos = next((e.position_at_pit for e in stint1 if e.position_at_pit), None)
        if pos is not None and pos <= 3:
            pressure_early.append(norm)
        elif pos is not None and pos > 10:
            relaxed_early.append(norm)

        if any(e.was_double_stack for e in race_events):
            double_stack_races += 1

        if any(e.was_under_sc for e in race_events):
            sc_top5_opportunities += 1
            if any(e.was_under_sc and (e.position_at_pit or 99) <= 5 for e in race_events):
                sc_top5_pitted += 1

        team_first = min(e.lap_number for e in stint1)
        other_firsts = sorted(
            {
                e.lap_number
                for e in events
                if e.race_key == race_key and e.constructor_code != constructor_code
            }
        )
        if other_firsts:
            undercut_races_total += 1
            rival_first = other_firsts[0]
            if team_first <= rival_first + 2 and team_first > rival_first:
                undercut_attempts += 1
            if team_first >= rival_first + 5:
                overcut_races += 1

    early_box_rate = early_box_races / sample_size if sample_size else 0.0
    overcut_rate = overcut_races / sample_size if sample_size else 0.0
    double_stack_rate = double_stack_races / sample_size if sample_size else 0.0
    safety_car_opportunist = (
        sc_top5_pitted / sc_top5_opportunities if sc_top5_opportunities else 0.0
    )
    avg_pit_window = (
        sum(stint1_norm_laps) / len(stint1_norm_laps) if stint1_norm_laps else 0.0
    )

    undercut_rate_val: float | None = None
    if undercut_races_total >= MIN_OWNERSHIP_GROUP:
        undercut_rate_val = undercut_attempts / undercut_races_total

    champ_mod = 0.0
    if len(pressure_early) >= 3 and relaxed_early:
        champ_mod = round(
            max(-1.0, min(1.0, (median(relaxed_early) - median(pressure_early)) * 2.0)),
            3,
        )

    quality = _data_quality_label(sample_size, undercut_rate_val is not None)
    tendency = fantasy_tendency or _fallback_fantasy_tendency(
        ConstructorStrategyProfileData(
            constructor_code=constructor_code,
            circuit_key=circuit_key,
            sample_size=sample_size,
            early_box_rate=round(early_box_rate, 3),
            undercut_attempt_rate=undercut_rate_val,
            overcut_rate=round(overcut_rate, 3),
            avg_pit_window_open_lap=round(avg_pit_window, 3),
            double_stack_rate=round(double_stack_rate, 3),
            safety_car_opportunist=round(safety_car_opportunist, 3),
            championship_pressure_modifier=champ_mod,
            fantasy_tendency="",
            data_quality=quality,
            source_race_keys=race_keys,
        ),
        constructor_code,
        circuit,
    )

    return ConstructorStrategyProfileData(
        constructor_code=constructor_code,
        circuit_key=circuit_key,
        sample_size=sample_size,
        early_box_rate=round(early_box_rate, 3),
        undercut_attempt_rate=(
            round(undercut_rate_val, 3) if undercut_rate_val is not None else None
        ),
        overcut_rate=round(overcut_rate, 3),
        avg_pit_window_open_lap=round(avg_pit_window, 3),
        double_stack_rate=round(double_stack_rate, 3),
        safety_car_opportunist=round(safety_car_opportunist, 3),
        championship_pressure_modifier=champ_mod,
        fantasy_tendency=tendency[:120],
        data_quality=quality,
        source_race_keys=race_keys,
    )


async def calculate_strategy_profile_async(
    pit_events: list[PitEvent],
    constructor_code: str,
    circuit_key: str,
    *,
    generate_tendency: bool = True,
) -> ConstructorStrategyProfileData:
    """Async profile calculation with optional LLM fantasy_tendency."""
    circuit = get_circuit_profile(circuit_key)
    if circuit is None:
        raise ValueError(f"Unknown circuit_key: {circuit_key}")

    profile = calculate_strategy_profile(
        pit_events,
        constructor_code,
        circuit_key,
        fantasy_tendency="",
    )
    if not generate_tendency or profile.data_quality == "LOW":
        return profile.model_copy(
            update={
                "fantasy_tendency": _fallback_fantasy_tendency(
                    profile, constructor_code, circuit
                )
            }
        )
    tendency = await _generate_fantasy_tendency(profile, constructor_code, circuit)
    return profile.model_copy(update={"fantasy_tendency": tendency})


async def get_constructor_context(
    circuit_key: str,
) -> dict[str, ConstructorStrategyProfileData]:
    """Load persisted profiles for a circuit (empty if none)."""
    from intelligence.repository import load_constructor_strategy_profiles

    return await load_constructor_strategy_profiles(circuit_key)


async def seed_constructor_profiles() -> int:
    """
    One-time background seed from OpenF1 (skips if table already has rows).

    Returns number of profiles upserted.
    """
    from intelligence.repository import (
        count_constructor_strategy_profiles,
        upsert_constructor_strategy_profile,
    )

    existing = await count_constructor_strategy_profiles()
    if existing > 0:
        logger.info("constructor profiles already seeded ({} rows) — skipping", existing)
        return 0

    client = OpenF1Client()
    upserted = 0
    for circuit_key in all_circuit_keys():
        for constructor_code in CONSTRUCTOR_CODES:
            await asyncio.sleep(1.0)
            events = await fetch_pit_history(
                circuit_key, constructor_code, client=client
            )
            if not events:
                continue
            profile = await calculate_strategy_profile_async(
                events,
                constructor_code,
                circuit_key,
                generate_tendency=True,
            )
            await upsert_constructor_strategy_profile(profile)
            upserted += 1
    logger.info("Seeded {} constructor/circuit profiles", upserted)
    return upserted


async def update_constructor_profile(
    constructor_code: str,
    circuit_key: str,
    new_pit_events: list[PitEvent],
) -> None:
    """
    Rolling refresh after each race (last 4 years). Idempotent per race_key.

    Skips LOW-quality profiles with no new events. Never double-counts race_key.
    """
    from intelligence.repository import (
        load_constructor_strategy_profile,
        upsert_constructor_strategy_profile,
    )

    if not new_pit_events:
        return

    new_race_keys = {e.race_key for e in new_pit_events}
    existing = await load_constructor_strategy_profile(constructor_code, circuit_key)
    if existing is not None:
        known = set(existing.source_race_keys)
        if new_race_keys.issubset(known):
            logger.warning(
                "update_constructor_profile idempotent skip {} {} keys={}",
                constructor_code,
                circuit_key,
                new_race_keys,
            )
            return
        if existing.data_quality == "LOW" and not (new_race_keys - known):
            logger.warning(
                "update_constructor_profile skipped LOW profile {} {} — no new events",
                constructor_code,
                circuit_key,
            )
            return

    years = sorted({e.year for e in new_pit_events})
    if not years:
        years = [datetime.now(tz=UTC).year]
    year_hi = max(years)
    rolling_years = list(range(year_hi - 3, year_hi + 1))

    all_events = await fetch_pit_history(
        circuit_key, constructor_code, years=rolling_years
    )
    all_events = _dedupe_events(all_events)
    if not all_events:
        return

    profile = await calculate_strategy_profile_async(
        all_events,
        constructor_code,
        circuit_key,
        generate_tendency=existing is None or existing.data_quality != "LOW",
    )
    await upsert_constructor_strategy_profile(profile)


# --- Legacy API (tests + context_builder backward compat) ---

from openf1.models import SessionResultRow  # noqa: E402


def driver_code_from_session(
    driver_number: int,
    session_numbers: dict[int, str],
) -> str:
    return session_numbers.get(driver_number, driver_code_for(driver_number))


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
    """Legacy per-race counters (unit tests)."""
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
) -> list[ConstructorStrategyProfileLegacy]:
    """Legacy aggregate for context_builder until DB seed completes."""
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

    profiles: list[ConstructorStrategyProfileLegacy] = []
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
            ConstructorStrategyProfileLegacy(
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
