"""Shared decode post-processing and validation helpers."""

from __future__ import annotations

import re
import time
import uuid
from datetime import UTC, datetime

from pitwallai.agents.radio_intercept.enums import ConfirmationState
from pitwallai.agents.radio_intercept.models import (
    AgentDependencies,
    CompetitorIntel,
    DecodedTransmission,
    RadioRawMessage,
)

_DRIVER_CODE_RE = re.compile(r"^[A-Z]{3}$")
_TEAM_RE = re.compile(r"^[\w\s\-\.]{1,64}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_LAP_RE = re.compile(r"\blap\s*(\d{1,2})\b", re.IGNORECASE)


def sanitize_driver_code(code: str) -> str:
    """
    Normalize and validate a driver code.

    Args:
        code: Raw driver code.

    Returns:
        Uppercase three-letter code or 'UNK' if invalid.
    """
    normalized = code.strip().upper()[:3]
    return normalized if _DRIVER_CODE_RE.match(normalized) else "UNK"


def sanitize_team(team: str) -> str:
    """
    Normalize team name and reject unexpected characters.

    Args:
        team: Raw team string.

    Returns:
        Sanitized team name.
    """
    cleaned = team.strip()[:64]
    return cleaned if _TEAM_RE.match(cleaned) else "Unknown"


def extract_lap_number(message: RadioRawMessage, transcript: str) -> int | None:
    """
    Resolve lap number from message metadata or transcript text.

    Args:
        message: Raw radio message.
        transcript: Transcript text.

    Returns:
        Lap number if found.
    """
    if message.lap_number is not None:
        return message.lap_number
    match = _LAP_RE.search(transcript)
    return int(match.group(1)) if match else None


def infer_competitor_intel(transcript: str) -> CompetitorIntel | None:
    """
    Derive competitor intel from explicit rival references in the transcript.

    Args:
        transcript: Lowercased or mixed-case transcript.

    Returns:
        CompetitorIntel when patterns match, else None.
    """
    lowered = transcript.lower()
    if "ferrari pit crew" in lowered or "leclerc boxing" in lowered:
        return CompetitorIntel(
            target_driver_code="LEC",
            target_team="Ferrari",
            inferred_action="Imminent pit stop — Ferrari undercut window opening",
            reliability_score=0.85,
            evidence_transcript=transcript,
            confirmation_state=ConfirmationState.UNCONFIRMED,
        )
    if "norris pitting" in lowered or "nor boxing" in lowered:
        return CompetitorIntel(
            target_driver_code="NOR",
            target_team="McLaren",
            inferred_action="Rival pit stop imminent — track position under threat",
            reliability_score=0.75,
            evidence_transcript=transcript,
            confirmation_state=ConfirmationState.UNCONFIRMED,
        )
    if "verstappen" in lowered and ("box" in lowered or "pit" in lowered):
        return CompetitorIntel(
            target_driver_code="VER",
            target_team="Red Bull Racing",
            inferred_action="Red Bull pit activity detected on competitor radio",
            reliability_score=0.7,
            evidence_transcript=transcript,
            confirmation_state=ConfirmationState.UNCONFIRMED,
        )
    return None


def finalize_transmission(
    output: DecodedTransmission,
    message: RadioRawMessage,
    deps: AgentDependencies,
    started_at: float,
) -> DecodedTransmission:
    """
    Apply deterministic post-decode fields shared by all backends.

    Args:
        output: Decoder output before metadata injection.
        message: Source raw message.
        deps: Agent dependencies.
        started_at: perf_counter() start time.

    Returns:
        Completed DecodedTransmission.
    """
    processing_latency_ms = (time.perf_counter() - started_at) * 1000
    team_color = deps.team_colors.get(message.team, "#FFFFFF")
    lap_number = output.lap_number if output.lap_number is not None else extract_lap_number(
        message, message.raw_transcript
    )
    competitor_intel = output.competitor_intel or infer_competitor_intel(message.raw_transcript)

    return output.model_copy(
        update={
            "transmission_id": str(uuid.uuid4()),
            "driver_code": sanitize_driver_code(message.driver_code),
            "team": sanitize_team(message.team),
            "decoded_at": datetime.now(tz=UTC),
            "processing_latency_ms": processing_latency_ms,
            "team_color": team_color,
            "exceeds_latency_target": processing_latency_ms > 800.0,
            "lap_number": lap_number,
            "competitor_intel": competitor_intel,
        }
    )


def is_valid_transmission_id(transmission_id: str) -> bool:
    """
    Validate transmission_id format.

    Args:
        transmission_id: Client-supplied identifier.

    Returns:
        True if a valid UUID string.
    """
    return bool(_UUID_RE.match(transmission_id))
