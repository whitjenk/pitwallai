"""Pick explanation card schema for Saturday WhatsApp broadcasts."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignalSource(str, Enum):
    """Which agent output grounded the primary signal line."""

    PRACTICE = "practice"
    QUALI = "quali"
    RADIO = "radio"
    PRICE = "price"
    CIRCUIT = "circuit"


class PickExplanation(BaseModel):
    """
    Human-readable explanation card for a single driver pick.

    Attached to PickRecommendation before WhatsApp formatting.
    """

    model_config = ConfigDict(frozen=True)

    driver_code: str
    primary_signal: str = Field(
        description=(
            "One sentence — strongest evidence for this pick. "
            "Must reference a specific data point. Max 120 chars."
        ),
    )
    signal_source: SignalSource
    risk_note: str = Field(
        description="One sentence honest downside. Max 100 chars.",
    )
    field_angle: str | None = Field(
        default=None,
        description=(
            "Field-level framing (consensus vs contrarian vs differentiator). "
            "Heuristic only — not user-specific league context. None when tier UNKNOWN."
        ),
    )

    @field_validator("primary_signal")
    @classmethod
    def _cap_primary(cls, value: str) -> str:
        text = value.strip()
        if len(text) > 120:
            return text[:119] + "…"
        return text

    @field_validator("risk_note")
    @classmethod
    def _cap_risk(cls, value: str) -> str:
        text = value.strip()
        if len(text) > 100:
            return text[:99] + "…"
        return text

    @field_validator("field_angle")
    @classmethod
    def _cap_field_angle(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        text = value.strip()
        if len(text) > 100:
            return text[:99] + "…"
        return text
