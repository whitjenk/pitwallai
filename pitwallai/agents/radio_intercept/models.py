"""Pydantic data models for radio intercept decoding."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, field_validator

from pitwallai.agents.radio_intercept.enums import (
    RadioIntent,
    StrategicSignal,
    StreamEventType,
    UrgencyLevel,
)

if TYPE_CHECKING:
    from pitwallai.agents.radio_intercept.vector_store import MockVectorStore


class RadioRawMessage(BaseModel):
    """Raw team radio message as ingested from OpenF1 or test fixtures."""

    model_config = ConfigDict(frozen=True)

    session_key: int
    driver_number: int
    driver_code: str
    team: str
    timestamp: datetime
    raw_transcript: str
    recording_url: str | None = None
    lap_number: int | None = None

    @field_validator("raw_transcript")
    @classmethod
    def validate_non_empty_transcript(cls, value: str) -> str:
        """
        Ensure the transcript contains meaningful content.

        Args:
            value: Raw transcript text.

        Returns:
            Stripped transcript text.

        Raises:
            ValueError: If the transcript is empty after stripping.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("Empty transcript received")
        return stripped


class JargonEntry(BaseModel):
    """A single F1 radio jargon term decoded to plain English."""

    model_config = ConfigDict(frozen=True)

    term: str
    plain_english: str
    confidence: float

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value: float) -> float:
        """
        Clamp confidence into the inclusive range [0.0, 1.0].

        Args:
            value: Raw confidence value.

        Returns:
            Clamped confidence.
        """
        numeric = float(value)
        return max(0.0, min(1.0, numeric))


class CompetitorIntel(BaseModel):
    """Intelligence extracted about a rival team or driver.

    The old three-state confirmation flow (UNCONFIRMED → ACKNOWLEDGED →
    ACTED_ON) collapsed to a single ``verified`` boolean — that state
    machine assumed a user acting on live signals, which the live-race
    product no longer does. Verified means a human (ops or the dashboard)
    has confirmed the intel; everything else is unverified.
    """

    model_config = ConfigDict(frozen=True)

    target_driver_code: str | None
    target_team: str | None
    inferred_action: str
    reliability_score: float
    evidence_transcript: str
    verified: bool = False


class HistoricalRadio(BaseModel):
    """A historical radio transmission retrieved from the vector store."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    raw_transcript: str
    decoded_intent: RadioIntent
    strategic_signal: StrategicSignal
    session_type: str
    lap_number: int | None
    outcome: str | None
    similarity_score: float


class DecodedTransmission(BaseModel):
    """Fully validated structured output from the Radio Intercept Decoder agent."""

    model_config = ConfigDict(frozen=True)

    transmission_id: str | None = None

    session_key: int
    driver_number: int
    driver_code: str
    team: str
    timestamp: datetime
    raw_transcript: str

    decoded_intent: RadioIntent
    jargon_decoded: list[JargonEntry]
    strategic_signal: StrategicSignal
    urgency_level: UrgencyLevel
    confidence_score: float

    competitor_intel: CompetitorIntel | None

    evidence_summary: str | None

    team_color: str | None = None
    lap_number: int | None = None

    context_doc_ids: list[str]
    model_reasoning: str

    decoded_at: datetime | None = None
    processing_latency_ms: float | None = None

    @property
    def is_actionable(self) -> bool:
        """
        Determine whether this transmission warrants immediate strategist attention.

        Returns:
            True when urgency is HIGH or CRITICAL and evidence summary is present.
        """
        return (
            self.urgency_level in (UrgencyLevel.HIGH, UrgencyLevel.CRITICAL)
            and self.evidence_summary is not None
        )


class WebSocketEvent(BaseModel):
    """Envelope for real-time dashboard streaming."""

    model_config = ConfigDict(frozen=True)

    event_type: StreamEventType
    payload: DecodedTransmission | dict[str, Any]
    session_key: int
    emitted_at: datetime


class RehearsalScenario(BaseModel):
    """Scripted replay scenario for pit-wall rehearsal mode."""

    model_config = ConfigDict(frozen=True)

    name: str
    circuit: str
    year: int
    events: list[RadioRawMessage]
    description: str


@dataclass
class AgentDependencies:
    """
    Typed dependency injection container for the Radio Intercept agent.

    Attributes:
        vector_store: Mock vector store for historical context retrieval.
        session_key: Active session identifier for filtering context.
        max_context_results: Maximum historical documents to retrieve per query.
        jargon_glossary: Static term → plain English reference glossary.
        team_colors: Team name → hex color for dashboard rendering.
    """

    vector_store: MockVectorStore
    session_key: int
    jargon_glossary: dict[str, str]
    team_colors: dict[str, str]
    max_context_results: int = 5
