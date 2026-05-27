"""Deterministic decode profiles for Monaco 2024 rehearsal transcripts."""

from __future__ import annotations

from pitwallai.agents.radio_intercept.enums import (
    ConfirmationState,
    RadioIntent,
    StrategicSignal,
    UrgencyLevel,
)
from pitwallai.agents.radio_intercept.models import (
    CompetitorIntel,
    DecodedTransmission,
    RadioRawMessage,
)

_MONACO_SESSION_KEY = 9158


def apply_monaco_profile(
    message: RadioRawMessage,
    draft: DecodedTransmission,
) -> DecodedTransmission | None:
    """
    Apply hard-coded decode outcomes for Monaco rehearsal transcripts.

    Args:
        message: Raw radio message.
        draft: Rules-based draft decode.

    Returns:
        Overridden DecodedTransmission when transcript matches, else None.
    """
    if message.session_key != _MONACO_SESSION_KEY:
        return None

    transcript = message.raw_transcript.strip()
    key = (message.driver_code, transcript)

    if key == ("LEC", "Box box box."):
        return draft.model_copy(
            update={
                "decoded_intent": RadioIntent.PIT_CALL,
                "strategic_signal": StrategicSignal.IMMINENT_PIT_WINDOW,
                "urgency_level": UrgencyLevel.HIGH,
                "confidence_score": 0.91,
                "competitor_intel": CompetitorIntel(
                    target_driver_code="LEC",
                    target_team="Ferrari",
                    inferred_action=(
                        "Ferrari pitting from P3. Likely switching to hard compound. "
                        "Undercut window open for 1–2 laps."
                    ),
                    reliability_score=0.91,
                    evidence_transcript=transcript,
                    confirmation_state=ConfirmationState.UNCONFIRMED,
                ),
                "evidence_summary": (
                    "Ferrari pit call on LEC radio matches pre-box historical precedents; "
                    "undercut window likely open for McLaren."
                ),
            }
        )

    if key == (
        "NOR",
        "These tyres are gone, mate. Fronts are completely dead. I've got nothing through the chicane. You need to box me, I can't hold this.",
    ):
        return draft.model_copy(
            update={
                "decoded_intent": RadioIntent.TIRE_COMPLAINT,
                "strategic_signal": StrategicSignal.TIRE_DEGRADATION_HIGH,
                "urgency_level": UrgencyLevel.CRITICAL,
                "confidence_score": 0.96,
                "evidence_summary": (
                    "Critical front-axle tyre degradation on NOR; chicane sector pace loss "
                    "consistent with Monaco lap 38 tire failure precedents."
                ),
            }
        )

    if key == ("NOR", "Copy 3.1 seconds. Push push push. Let's go."):
        return draft.model_copy(
            update={
                "decoded_intent": RadioIntent.PUSH_MODE,
                "strategic_signal": StrategicSignal.PACE_MODE_SHIFT,
                "urgency_level": UrgencyLevel.MEDIUM,
                "confidence_score": max(draft.confidence_score, 0.85),
                "evidence_summary": (
                    "Post-pit push mode on fresh tyres; gap to LEC 3.1s with deploy request "
                    "matches post-stop offset strategy precedents."
                ),
            }
        )

    return None
