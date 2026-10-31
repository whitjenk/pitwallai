"""Practice Analyst — FP1/FP2 signals built from lap/pace data.

OpenF1 never publishes team-radio transcripts, so practice signals come purely
from real lap times via ``intelligence.lap_signals.build_lap_only_signals``.
"""

from __future__ import annotations

from loguru import logger

from circuits.profiles import CircuitProfile
from intelligence.lap_signals import build_lap_only_signals
from intelligence.repository import save_practice_signals
from intelligence.schemas import PracticeSignal
from openf1.client import OpenF1Client

_PRACTICE_SESSION_NAMES = ("Practice 1", "Practice 2")


def _best_lap_by_driver(laps: list) -> dict[int, float]:
    """Return best lap duration per driver."""
    best: dict[int, float] = {}
    for lap in laps:
        if lap.lap_duration is None or lap.is_pit_out_lap:
            continue
        current = best.get(lap.driver_number)
        if current is None or lap.lap_duration < current:
            best[lap.driver_number] = lap.lap_duration
    return best


def _teammate_pairs(driver_numbers: set[int]) -> list[tuple[int, int]]:
    """Approximate teammate pairs by team (hardcoded 2025)."""
    teams: dict[str, list[int]] = {
        "RBR": [1, 11],
        "FER": [16, 55],
        "MCL": [4, 81],
        "MER": [44, 63],
        "AM": [14, 18],
        "ALP": [10, 31],
        "WIL": [23, 2],
        "RB": [22, 3],
        "HAA": [27, 20],
        "SAU": [77, 24],
    }
    pairs: list[tuple[int, int]] = []
    for members in teams.values():
        present = [d for d in members if d in driver_numbers]
        if len(present) == 2:
            pairs.append((present[0], present[1]))
    return pairs


async def analyze_practice_weekend(
    *,
    client: OpenF1Client,
    circuit: CircuitProfile,
    year: int,
    persist: bool = True,
) -> list[PracticeSignal]:
    """
    Build FP1 and FP2 PracticeSignals from real lap data.

    Args:
        client: OpenF1 client.
        circuit: Injected circuit profile.
        year: Championship year.
        persist: Save signals to the practice-signal store.

    Returns:
        PracticeSignal list for FP1 and FP2 combined (empty if no laps found).
    """
    session_keys: dict[str, int] = {}
    for name in _PRACTICE_SESSION_NAMES:
        sk = await client.find_session_key(
            year=year,
            circuit_short_name=circuit.openf1_circuit_name,
            session_name=name,
        )
        if sk is None:
            logger.warning("Practice session not found: {} {}", circuit.display_name, name)
            continue
        label = "FP1" if "1" in name else "FP2"
        session_keys[label] = sk

    if not session_keys:
        return []

    signals = await build_lap_only_signals(client, session_keys=session_keys)
    if not signals:
        return []

    if persist:
        primary_key = next(iter(session_keys.values()))
        await save_practice_signals(primary_key, circuit.circuit_key, signals)

    logger.bind(circuit=circuit.circuit_key, signals=len(signals)).info(
        "Practice analysis complete (lap-only)"
    )
    return signals
