"""Immutable shared race weekend context for multi-agent orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from circuits.profiles import CircuitProfile
from intelligence.schemas import PracticeSignal, QualifyingRow, WeatherForecast
from scheduler.calendar import RaceWeekend


class CadencePreference(str, Enum):
    """Subscriber notification cadence."""

    FULL = "FULL"
    RACE_DAY_ONLY = "RACE_DAY_ONLY"


class ChampionshipRow(BaseModel):
    """Driver championship standing snapshot."""

    model_config = ConfigDict(frozen=True)

    driver_code: str
    position: int
    points: float
    championship_pressure: float = Field(ge=0.0, le=1.0)


class SignalQualityEntry(BaseModel):
    """Rolling accuracy for a signal type at a circuit."""

    model_config = ConfigDict(frozen=True)

    circuit_key: str
    signal_type: str
    sample_size: int
    hit_rate: float
    weight_multiplier: float = 1.0


class SignalQuality(BaseModel):
    """Agent 5 feedback weights consumed by downstream agents."""

    model_config = ConfigDict(frozen=True)

    entries: dict[str, SignalQualityEntry] = Field(default_factory=dict)
    practice_sentiment_accuracy: float | None = None
    anomaly_flag_accuracy: float | None = None
    circuit_profile_accuracy: float | None = None
    quality_note: str | None = None


class RaceEventType(str, Enum):
    """Live race monitor event classification."""

    SAFETY_CAR = "SAFETY_CAR"
    VIRTUAL_SC = "VIRTUAL_SC"
    RED_FLAG = "RED_FLAG"
    RETIREMENT = "RETIREMENT"
    PIT_WINDOW_OPEN = "PIT_WINDOW_OPEN"
    WEATHER_CHANGE = "WEATHER_CHANGE"
    RACE_COMPLETE = "RACE_COMPLETE"


class RaceEvent(BaseModel):
    """Persisted / in-memory live race event."""

    model_config = ConfigDict(frozen=True)

    race_key: str
    event_type: RaceEventType
    lap: int | None
    description: str
    utc_timestamp: datetime
    driver_code: str | None = None


class RaceContext(BaseModel):
    """
    Frozen shared context for the current race weekend.

    Agents must return updated copies via ``evolve_race_context()`` —
    never mutate in place.
    """

    model_config = ConfigDict(frozen=True)

    race_weekend: RaceWeekend
    circuit_profile: CircuitProfile
    championship_snapshot: dict[str, ChampionshipRow] | None = None
    weather_forecast: WeatherForecast | None = None
    practice_signals: dict[str, list[PracticeSignal]] | None = None
    qualifying_result: list[QualifyingRow] | None = None
    race_events: list[RaceEvent] = Field(default_factory=list)
    signal_quality: SignalQuality | None = None
    fia_bulletins: list[str] = Field(default_factory=list)
    circuit_intel: dict[str, Any] | None = None
    built_at: datetime
    last_updated: datetime


def evolve_race_context(ctx: RaceContext, **updates: Any) -> RaceContext:
    """
    Return a new RaceContext with fields updated (immutable pattern).

    Always sets last_updated to now (UTC).
    """
    data = ctx.model_dump()
    data.update(updates)
    data["last_updated"] = datetime.now(tz=UTC)
    return RaceContext.model_validate(data)


def initial_race_context(
    weekend: RaceWeekend,
    circuit_profile: CircuitProfile,
) -> RaceContext:
    """Bootstrap context before Agent 1 runs."""
    now = datetime.now(tz=UTC)
    return RaceContext(
        race_weekend=weekend,
        circuit_profile=circuit_profile,
        built_at=now,
        last_updated=now,
    )
