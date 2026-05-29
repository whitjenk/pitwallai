"""Resolve practice and radio signals for a race_key + driver (DB / circuit store)."""

from __future__ import annotations

from collections import defaultdict

from intelligence.explanation_builder import _radio_snippet
from intelligence.repository import load_practice_signals_by_circuit
from intelligence.schemas import PracticeSignal
from orchestrator.race_context import RaceContext, evolve_race_context
from scheduler.calendar import get_race_weekend, profile_circuit_key
from utils.race_key import parse_race_key


def circuit_key_for_race(race_key: str) -> str | None:
    """Profile circuit key used by practice_signals rows for this weekend."""
    weekend = get_race_weekend(race_key)
    if weekend is not None:
        return profile_circuit_key(weekend.circuit_key)
    parsed = parse_race_key(race_key)
    if parsed is None:
        return None
    _year, circuit = parsed
    return profile_circuit_key(circuit)


async def load_practice_by_driver(circuit_key: str) -> dict[str, PracticeSignal]:
    """Latest practice signal per driver for a circuit (FP2 preferred over FP1)."""
    rows = await load_practice_signals_by_circuit(circuit_key)
    merged: dict[str, PracticeSignal] = {}
    priority = {"FP2": 2, "FP1": 1}
    for sig in rows:
        code = sig.driver_code.upper()
        existing = merged.get(code)
        if existing is None:
            merged[code] = sig
            continue
        if priority.get(sig.session, 0) > priority.get(existing.session, 0):
            merged[code] = sig
    return merged


async def get_practice_signals(race_key: str, driver_code: str) -> PracticeSignal | None:
    """Return persisted practice signal for driver, or None."""
    circuit_key = circuit_key_for_race(race_key)
    if circuit_key is None:
        return None
    by_driver = await load_practice_by_driver(circuit_key)
    return by_driver.get(driver_code.upper())


async def get_radio_signals(race_key: str, driver_code: str) -> str | None:
    """
    Return decoded radio snippet for driver if present in practice raw_evidence.

    Radio is not stored separately — FP1/FP2 decode writes into PracticeSignal.raw_evidence.
    """
    practice = await get_practice_signals(race_key, driver_code)
    if practice is None:
        return None
    return _radio_snippet(practice)


async def hydrate_practice_signals_for_context(ctx: RaceContext) -> RaceContext:
    """Load practice_signals from DB into context when Agent 2 did not run in-process."""
    if ctx.practice_signals:
        return ctx
    circuit_key = profile_circuit_key(ctx.race_weekend.circuit_key)
    by_driver = await load_practice_by_driver(circuit_key)
    if not by_driver:
        return ctx
    by_session: dict[str, list[PracticeSignal]] = defaultdict(list)
    for sig in by_driver.values():
        by_session[sig.session].append(sig)
    return evolve_race_context(ctx, practice_signals=dict(by_session))
