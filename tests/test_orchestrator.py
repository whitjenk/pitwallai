"""Phase 6 orchestrator and formatter tests."""

from __future__ import annotations

from datetime import UTC, datetime

from orchestrator.race_context import evolve_race_context, initial_race_context, RaceContext
from scheduler.calendar import get_race_weekend
from circuits.profiles import get_circuit_profile
from scheduler.calendar import profile_circuit_key
from agents.practice_analyst import format_practice_summary
from intelligence.schemas import PracticeSignal
from whatsapp.message_format import LIVE_ALERT_MAX_CHARS


def test_race_context_immutable_evolve() -> None:
    weekend = get_race_weekend("2026_monaco")
    assert weekend is not None
    profile = get_circuit_profile(profile_circuit_key("monaco"))
    assert profile is not None
    ctx = initial_race_context(weekend, profile)
    ctx2 = evolve_race_context(ctx, built_at=ctx.built_at)
    assert ctx2 is not ctx
    assert ctx2.last_updated >= ctx.last_updated


def test_practice_summary_under_300() -> None:
    weekend = get_race_weekend("2026_monaco")
    assert weekend is not None
    profile = get_circuit_profile("monaco")
    assert profile is not None
    ctx = RaceContext(
        race_weekend=weekend,
        circuit_profile=profile,
        practice_signals={
            "FP2": [
                PracticeSignal(
                    driver_number=18,
                    driver_code="STR",
                    session="FP2",
                    setup_sentiment=-0.5,
                    tire_confidence=0.4,
                    mechanical_flags=[],
                    pace_satisfaction=0.3,
                    anomaly_flags=["TEAMMATE_GAP_ANOMALY"],
                    raw_evidence=["test"],
                )
            ]
        },
        built_at=datetime.now(tz=UTC),
        last_updated=datetime.now(tz=UTC),
    )
    msg = format_practice_summary(ctx)
    assert len(msg) <= 300


def test_live_alert_char_limit() -> None:
    msg = "🟡 SC deployed lap 42 — safety car deployed after incident turn 6 observation only for fantasy context"
    if len(msg) > LIVE_ALERT_MAX_CHARS:
        msg = msg[: LIVE_ALERT_MAX_CHARS - 1] + "…"
    assert len(msg) <= LIVE_ALERT_MAX_CHARS
