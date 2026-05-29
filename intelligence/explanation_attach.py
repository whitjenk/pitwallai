"""Attach explanation cards to pick output (Saturday broadcast only)."""

from __future__ import annotations

from loguru import logger

from intelligence.explanation_builder import ExplanationBuildContext, build_explanation
from intelligence.schemas import PickOutput, PracticeSignal
from models.pick_explanation import PickExplanation
from pitwallai.agents.radio_intercept.config import PitWallSettings


def practice_map_from_sessions(
    practice_signals: dict[str, list[PracticeSignal]] | None,
) -> dict[str, PracticeSignal]:
    """Merge session lists into one signal per driver (latest session wins)."""
    merged: dict[str, PracticeSignal] = {}
    if not practice_signals:
        return merged
    for signals in practice_signals.values():
        for sig in signals:
            merged[sig.driver_code.upper()] = sig
    return merged


def attach_explanations(
    output: PickOutput,
    ctx: ExplanationBuildContext,
    *,
    enabled: bool,
) -> PickOutput:
    """
    Return PickOutput with explanation cards on each pick (best-effort).

    Never raises — failures omit cards for that pick only.
    """
    if not enabled:
        return output

    patched = []
    for pick in output.picks:
        try:
            explanation = build_explanation(pick, ctx)
        except Exception as exc:
            logger.warning(
                "explanation_build_failed driver={} race={}: {}",
                pick.driver_code,
                ctx.race_key,
                exc,
            )
            explanation = None
        patched.append(
            pick.model_copy(update={"explanation": explanation})
            if explanation
            else pick
        )
    return output.model_copy(update={"picks": patched})


async def attach_explanations_from_db(
    output: PickOutput,
    *,
    circuit_key: str,
    race_key: str,
    circuit,
    practice_signals: dict[str, list[PracticeSignal]] | None,
    quali_grid: dict[str, int],
    settings: PitWallSettings,
) -> PickOutput:
    """Load practice from DB if in-memory map is empty."""
    practice_by_driver = practice_map_from_sessions(practice_signals)
    if not practice_by_driver:
        from intelligence.repository import load_practice_signals_by_circuit
        from scheduler.calendar import profile_circuit_key

        profile_key = profile_circuit_key(circuit_key)
        rows = await load_practice_signals_by_circuit(profile_key)
        for sig in rows:
            code = sig.driver_code.upper()
            practice_by_driver[code] = sig

    build_ctx = ExplanationBuildContext(
        race_key=race_key,
        circuit_key=circuit_key,
        circuit=circuit,
        practice_by_driver=practice_by_driver,
        quali_grid=quali_grid,
    )
    return attach_explanations(
        output,
        build_ctx,
        enabled=settings.explanation_cards_enabled,
    )
