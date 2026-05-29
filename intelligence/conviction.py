"""Low-conviction detection — the brand-defining "I don't know" mode.

Not every race weekend produces a real signal. Wet practice, FP1-only
running, late FIA technical directives, missing radio, sparse telemetry —
the honest play is to tell the user to hold transfers, not invent three
HIGH-conviction picks. This module is the detector that flips that switch.
"""

from __future__ import annotations

from dataclasses import dataclass

from intelligence.schemas import PickRecommendation, PracticeSignal


@dataclass(frozen=True, slots=True)
class ConvictionAssessment:
    """Why the weekend is (or isn't) low-conviction. Kept for log lines."""

    is_low_conviction: bool
    reasons: tuple[str, ...]


# Tunable thresholds — bump when calibration data tells us to.
_MIN_PICKS = 3
_MIN_AVG_CONFIDENCE = 55.0
_MIN_PRACTICE_DRIVERS = 8       # < this many drivers in practice = sparse
_MAX_HIGH_CONFIDENCE_SPREAD = 25 # if conf range across top-3 is huge, model is uncertain


def assess_conviction(
    picks: list[PickRecommendation],
    practice_signals: dict[str, PracticeSignal] | None = None,
) -> ConvictionAssessment:
    """Return whether to switch the Saturday broadcast to low-conviction mode."""
    reasons: list[str] = []

    if len(picks) < _MIN_PICKS:
        reasons.append(f"only {len(picks)} viable pick(s)")

    if picks:
        confidences = [p.confidence for p in picks[:3]]
        avg = sum(confidences) / len(confidences)
        if avg < _MIN_AVG_CONFIDENCE:
            reasons.append(f"avg top-3 confidence {avg:.0f}% < {_MIN_AVG_CONFIDENCE:.0f}%")
        spread = max(confidences) - min(confidences)
        if spread > _MAX_HIGH_CONFIDENCE_SPREAD:
            reasons.append(f"top-3 confidence spread {spread:.0f}pp suggests model uncertainty")

    if practice_signals is not None and len(practice_signals) < _MIN_PRACTICE_DRIVERS:
        reasons.append(f"practice signals on only {len(practice_signals)} drivers — sparse")

    return ConvictionAssessment(
        is_low_conviction=bool(reasons),
        reasons=tuple(reasons),
    )


def low_conviction_message(assessment: ConvictionAssessment, race_label: str) -> str:
    """The "holding is reasonable" Saturday message. Brand-defining tone.

    Plain language, no fake authority. Names *why* honestly. This is the
    message that earns trust on the HIGH-conviction weekends.
    """
    if not assessment.reasons:
        primary = "signals are mixed"
    else:
        primary = assessment.reasons[0]

    body = (
        f"🏎  *{race_label} — low conviction*\n\n"
        f"PitWallAI doesn't have a strong call this weekend ({primary}). "
        "Holding transfers is a reasonable play.\n\n"
        "I'll send a fresh read if anything changes before lock.\n\n"
        "──────────────────\n"
        "PitWallAI · Not financial advice"
    )
    return body
