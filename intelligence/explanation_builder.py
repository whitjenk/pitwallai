"""
Generate PickExplanation cards from existing agent output.

Reads practice signals, quali grid, circuit profile, and pick metadata only —
no external APIs and no LLM calls at send time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from circuits.profiles import CircuitProfile
from fantasy.rules import DRIVER_PRICES_M, driver_price_m
from intelligence.drivers import team_for_driver
from intelligence.schemas import PickRecommendation, PracticeSignal
from models.pick_explanation import PickExplanation, SignalSource

_TEAMMATE_GAP_RE = re.compile(r"teammate_gap_([\d.]+)s")


@dataclass(slots=True)
class ExplanationBuildContext:
    """Pre-computed signals for explanation cards (one race weekend)."""

    race_key: str
    circuit_key: str
    circuit: CircuitProfile | None = None
    practice_by_driver: dict[str, PracticeSignal] = field(default_factory=dict)
    quali_grid: dict[str, int] = field(default_factory=dict)


def _target_driver_code(pick: PickRecommendation) -> str:
    return (pick.transfer_in or pick.driver_code).upper()


def _expected_quali_slot(driver_code: str) -> int:
    """Price-rank proxy for expected quali position (1 = favourite)."""
    ranked = sorted(DRIVER_PRICES_M.keys(), key=lambda c: driver_price_m(c), reverse=True)
    try:
        return ranked.index(driver_code) + 1
    except ValueError:
        return 11


def _teammate_gap_seconds(anomaly_flags: list[str]) -> float | None:
    for flag in anomaly_flags:
        match = _TEAMMATE_GAP_RE.search(flag)
        if match:
            return float(match.group(1))
    return None


def _radio_snippet(practice: PracticeSignal | None) -> str | None:
    if practice is None:
        return None
    for bit in practice.raw_evidence:
        text = bit.strip()
        if not text or len(text) < 12:
            continue
        if text.lower().startswith("radio:"):
            return text[6:].strip()[:100]
        if len(text) < 180 and not text.startswith("["):
            return text[:100]
    return None


def _select_primary_signal(
    pick: PickRecommendation,
    practice: PracticeSignal | None,
    *,
    quali_position: int | None,
    driver_code: str,
) -> tuple[str, SignalSource] | None:
    snippet = _radio_snippet(practice)
    if snippet:
        return f"Team radio: {snippet}", SignalSource.RADIO

    if practice is not None:
        gap = _teammate_gap_seconds(practice.anomaly_flags)
        if gap is not None and gap >= 0.3:
            session = practice.session or "FP2"
            return (
                f"{session}: {gap:.2f}s gap vs teammate on comparable runs.",
                SignalSource.PRACTICE,
            )
        if practice.setup_sentiment >= 0.35 and practice.tire_confidence >= 0.55:
            session = practice.session or "Practice"
            return (
                f"{session}: setup sentiment {practice.setup_sentiment:+.2f}, "
                f"tyre confidence {practice.tire_confidence:.0%}.",
                SignalSource.PRACTICE,
            )
        if practice.raw_evidence and practice.setup_sentiment > 0.2:
            ev = practice.raw_evidence[0][:100]
            return f"{practice.session or 'Practice'}: {ev}", SignalSource.PRACTICE

    if quali_position is not None:
        expected = _expected_quali_slot(driver_code)
        gap = expected - quali_position
        if gap >= 2:
            return (
                f"Qualified P{quali_position}, {gap} places above price-rank expectation (P{expected}).",
                SignalSource.QUALI,
            )
        if quali_position <= 3 and pick.confidence >= 60:
            return (
                f"Front-row quali P{quali_position} ({int(pick.confidence)}% model confidence).",
                SignalSource.QUALI,
            )

    price_m = driver_price_m(driver_code)
    if pick.confidence > 65 and price_m < 18.0:
        return (
            f"Value signal: {int(pick.confidence)}% confidence at ${price_m:.1f}M.",
            SignalSource.PRICE,
        )
    if pick.price_direction == "UP" and (pick.price_confidence or 0) > 0.6:
        mag = pick.price_magnitude or 0.0
        return (
            f"Price model flags UP (${mag:.1f}M move, {pick.price_confidence:.0%} conf).",
            SignalSource.PRICE,
        )

    return None


def _build_risk_note(
    pick: PickRecommendation,
    practice: PracticeSignal | None,
    circuit: CircuitProfile | None,
    driver_code: str,
) -> str:
    if practice and practice.mechanical_flags:
        flags = ", ".join(practice.mechanical_flags[:2])
        return f"Practice flagged {flags} — reliability watch."

    if practice and len(practice.anomaly_flags) >= 2:
        return f"{len(practice.anomaly_flags)} practice anomaly flags — setup uncertainty."

    if circuit is not None:
        if "street_circuit" in circuit.sector_characteristics and circuit.overtaking_difficulty >= 0.55:
            team = team_for_driver(driver_code)
            return (
                f"Street circuit ({circuit.display_name.split()[0]}): "
                f"limited overtaking — {team} history mixed here."
            )[:100]
        if circuit.weather_sensitivity >= 0.45:
            return f"{circuit.display_name}: high weather variance this weekend."[:100]

    if pick.confidence < 55:
        return f"Moderate confidence ({int(pick.confidence)}%) — incomplete signal mix."

    return "Limited downside at this price point."


def _build_league_angle(pick: PickRecommendation) -> str | None:
    tier = (pick.ownership_tier or "UNKNOWN").upper()
    is_contrarian = bool(pick.is_contrarian)

    if tier == "HIGH":
        return "Consensus pick — safe floor, limited upside vs field."
    if tier == "LOW" and is_contrarian:
        return "Contrarian — upside if rivals play chalk this weekend."
    if tier == "LOW":
        return "Low ownership — differentiator if confidence holds."
    if tier == "MEDIUM":
        return "Mixed field — differentiator in smaller leagues."
    return None


def build_explanation(
    pick: PickRecommendation,
    ctx: ExplanationBuildContext,
) -> PickExplanation | None:
    """
    Build an explanation card from cached agent outputs.

    Returns None when no signal path yields grounded evidence.
    """
    driver_code = _target_driver_code(pick)
    practice = ctx.practice_by_driver.get(driver_code)
    quali_position = ctx.quali_grid.get(driver_code)

    selected = _select_primary_signal(
        pick,
        practice,
        quali_position=quali_position,
        driver_code=driver_code,
    )
    if selected is None:
        if ctx.circuit is not None and ctx.circuit.notes:
            note = ctx.circuit.notes[:100]
            selected = (f"Circuit prior: {note}", SignalSource.CIRCUIT)
        else:
            return None

    primary_signal, source = selected
    league_angle = _build_league_angle(pick)

    return PickExplanation(
        driver_code=driver_code,
        primary_signal=primary_signal,
        signal_source=source,
        risk_note=_build_risk_note(pick, practice, ctx.circuit, driver_code),
        league_angle=league_angle,
    )
