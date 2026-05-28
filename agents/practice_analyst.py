"""Agent 2 — Practice Anomaly Detector (post-FP2)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean

from loguru import logger

from agents.base import AgentRunDependencies
from circuits.profiles import get_circuit_profile
from intelligence.drivers import driver_code_for
from intelligence.practice_analyst import analyze_practice_weekend
from intelligence.repository import list_active_subscribers
from intelligence.schemas import PracticeSignal
from openf1.client import OpenF1Client
from orchestrator.race_context import CadencePreference, evolve_race_context, RaceContext
from scheduler.calendar import profile_circuit_key
from whatsapp.message_format import PRACTICE_SUMMARY_MAX_CHARS
from whatsapp.sender import mask_phone, send_message

_TEAMMATE_GAP_ANOMALY = 0.5
_TEAMMATE_GAP_PRIOR = 0.2
_SESSION_REGRESSION_S = 0.3
_LONG_RUN_MIN = 5


def _best_laps(laps: list) -> dict[int, float]:
    best: dict[int, float] = {}
    for lap in laps:
        if lap.lap_duration is None or lap.is_pit_out_lap:
            continue
        d = lap.driver_number
        if d not in best or lap.lap_duration < best[d]:
            best[d] = lap.lap_duration
    return best


def _long_run_counts(laps: list) -> dict[int, int]:
    by_driver: dict[int, int] = defaultdict(int)
    for lap in laps:
        if lap.lap_duration is not None and not lap.is_pit_out_lap:
            by_driver[lap.driver_number] += 1
    return {d: c for d, c in by_driver.items() if c >= _LONG_RUN_MIN}


def _teammate_pairs(drivers: set[int]) -> list[tuple[int, int]]:
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
        present = [d for d in members if d in drivers]
        if len(present) == 2:
            pairs.append((present[0], present[1]))
    return pairs


async def _extended_anomalies(
    client: OpenF1Client,
    signals: list[PracticeSignal],
    *,
    circuit_key: str,
    openf1_name: str,
    fp1_key: int | None,
    fp2_key: int | None,
) -> list[PracticeSignal]:
    """Apply Phase 6 anomaly rules on top of Phase 3 signals."""
    by_key: dict[tuple[int, str], PracticeSignal] = {
        (s.driver_number, s.session): s for s in signals
    }

    # Session regression FP1 vs FP2
    fp1_best = _best_laps(await client.get_laps(fp1_key)) if fp1_key else {}
    fp2_best = _best_laps(await client.get_laps(fp2_key)) if fp2_key else {}
    for driver, fp1_time in fp1_best.items():
        fp2_time = fp2_best.get(driver)
        if fp2_time is None:
            continue
        if fp2_time - fp1_time > _SESSION_REGRESSION_S:
            key = (driver, "FP2")
            if key in by_key:
                sig = by_key[key]
                flags = list(sig.anomaly_flags) + ["SESSION_REGRESSION"]
                by_key[key] = sig.model_copy(update={"anomaly_flags": flags})

    # Teammate + long run on FP2
    if fp2_key:
        laps = await client.get_laps(fp2_key)
        best = _best_laps(laps)
        long_runs = _long_run_counts(laps)

        prior_sk = await client.find_session_key(
            year=2025,
            circuit_short_name=openf1_name,
            session_name="Practice 2",
        )
        prior_best: dict[int, float] = {}
        if prior_sk:
            prior_best = _best_laps(await client.get_laps(prior_sk))

        for d1, d2 in _teammate_pairs(set(best.keys())):
            gap = abs(best[d1] - best[d2])
            if gap > _TEAMMATE_GAP_ANOMALY:
                pair = (min(d1, d2), max(d1, d2))
                prior_gap = abs(prior_best.get(d1, 0) - prior_best.get(d2, 0)) if prior_best else 999.0
                if prior_gap < _TEAMMATE_GAP_PRIOR:
                    for driver in (d1, d2):
                        key = (driver, "FP2")
                        if key in by_key:
                            sig = by_key[key]
                            flags = list(sig.anomaly_flags) + ["TEAMMATE_GAP_ANOMALY"]
                            by_key[key] = sig.model_copy(update={"anomaly_flags": flags})

        if long_runs:
            max_lr = max(long_runs.values())
            for driver, count in long_runs.items():
                if count < max_lr * 0.5:
                    key = (driver, "FP2")
                    if key in by_key:
                        sig = by_key[key]
                        flags = list(sig.anomaly_flags) + ["LOW_LONG_RUN_COUNT"]
                        by_key[key] = sig.model_copy(update={"anomaly_flags": flags})

    return list(by_key.values())


def format_practice_summary(ctx: RaceContext) -> str:
    """Build Thursday evening practice summary (<=300 chars)."""
    signals = ctx.practice_signals or {}
    fp2 = signals.get("FP2", [])
    if not fp2:
        return "Clean practice sessions. Quali tomorrow will be the signal."

    watch: list[str] = []
    note: list[str] = []
    strong: list[str] = []

    for sig in fp2:
        code = sig.driver_code
        if any("TEAMMATE_GAP" in f or "SESSION_REGRESSION" in f for f in sig.anomaly_flags):
            watch.append(f"{code} — {sig.anomaly_flags[0].replace('_', ' ').lower()}")
        elif sig.setup_sentiment < -0.3:
            watch.append(f"{code} — setup concerns on radio")
        elif len(sig.anomaly_flags) >= 1:
            note.append(f"{code} — {sig.anomaly_flags[0].replace('_', ' ').lower()}")
        elif sig.setup_sentiment > 0.5 and sig.pace_satisfaction > 0.6:
            strong.append(f"{code} — positive radio and pace")

    lines = [f"📻 {ctx.race_weekend.display_name} practice summary", ""]
    if watch:
        lines.append(f"🔴 Watch: {watch[0]}")
    if note:
        lines.append(f"🟡 Note: {note[0]}")
    if strong:
        lines.append(f"🟢 Strong: {strong[0]}")
    if len(lines) <= 2:
        return "Clean practice sessions. Quali tomorrow will be the signal."
    lines.extend(["", "Full picks Saturday after quali · Reply HELP"])
    msg = "\n".join(lines)
    if len(msg) > PRACTICE_SUMMARY_MAX_CHARS:
        msg = msg[: PRACTICE_SUMMARY_MAX_CHARS - 1] + "…"
    assert len(msg) <= PRACTICE_SUMMARY_MAX_CHARS
    return msg


async def _broadcast_practice_summary(ctx: RaceContext, message: str) -> int:
    """Send practice summary to FULL cadence subscribers only."""
    subs = await list_active_subscribers()
    sent = 0
    for sub in subs:
        if sub.cadence_preference != CadencePreference.FULL.value:
            continue
        try:
            await send_message(sub.phone, message)
            sent += 1
        except Exception as exc:
            logger.error("Practice summary failed phone={}: {}", mask_phone(sub.phone), exc)
    return sent


async def run_practice_analyst(
    ctx: RaceContext,
    deps: AgentRunDependencies,
) -> RaceContext:
    """Run radio extraction + Phase 6 anomalies; update context; notify FULL subs."""
    profile_key = profile_circuit_key(ctx.race_weekend.circuit_key)
    circuit = get_circuit_profile(profile_key)
    if circuit is None:
        logger.error("No circuit profile for {}", profile_key)
        return ctx

    client = deps.openf1_client
    base_signals = await analyze_practice_weekend(
        client=client,
        agent=deps.radio_agent,
        vector_store=deps.vector_store,
        circuit=circuit,
        year=2026,
        persist=True,
    )

    fp1_key = await client.find_session_key(
        year=2026,
        circuit_short_name=circuit.openf1_circuit_name,
        session_name="Practice 1",
    )
    fp2_key = await client.find_session_key(
        year=2026,
        circuit_short_name=circuit.openf1_circuit_name,
        session_name="Practice 2",
    )

    enhanced = await _extended_anomalies(
        client,
        base_signals,
        circuit_key=profile_key,
        openf1_name=circuit.openf1_circuit_name,
        fp1_key=fp1_key,
        fp2_key=fp2_key,
    )

    by_session: dict[str, list[PracticeSignal]] = defaultdict(list)
    for sig in enhanced:
        by_session[sig.session].append(sig)

    new_ctx = evolve_race_context(ctx, practice_signals=dict(by_session))

    summary = format_practice_summary(new_ctx)
    await _broadcast_practice_summary(new_ctx, summary)

    return new_ctx
