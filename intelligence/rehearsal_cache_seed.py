"""Seed practice_signals for Monaco rehearsal when DB is empty (local smoke tests)."""

from __future__ import annotations

from loguru import logger

from fantasy.rules import DRIVER_PRICES_M
from intelligence.repository import load_practice_signals_by_circuit, save_practice_signals
from intelligence.schemas import PracticeSignal
from onboarding.monaco_calendar import MONACO_SESSION_KEY


async def seed_rehearsal_practice_signals_if_needed() -> int:
    """
    Idempotently persist demo FP2 signals for Monaco when coverage is low.

    Returns number of drivers seeded (0 if skipped or already warm).
    """
    import os

    if not os.environ.get("DATABASE_URL", "").strip():
        return 0

    circuit_key = "monaco"
    existing = await load_practice_signals_by_circuit(circuit_key)
    if len(existing) >= len(DRIVER_PRICES_M) // 2:
        return 0

    signals: list[PracticeSignal] = []
    for idx, code in enumerate(sorted(DRIVER_PRICES_M.keys())):
        signals.append(
            PracticeSignal(
                driver_number=10 + idx,
                driver_code=code,
                session="FP2",
                setup_sentiment=0.1,
                tire_confidence=0.5,
                mechanical_flags=[],
                pace_satisfaction=0.4,
                anomaly_flags=[],
                raw_evidence=(
                    [f"radio: {code} happy with balance on the soft"]
                    if idx % 2 == 0
                    else ["Long run pace looked stable in traffic"]
                ),
            )
        )
    await save_practice_signals(MONACO_SESSION_KEY, circuit_key, signals)
    logger.info(
        "Rehearsal practice cache seeded circuit={} drivers={}",
        circuit_key,
        len(signals),
    )
    return len(signals)
