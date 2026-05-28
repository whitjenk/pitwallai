"""Pydantic schemas for the intelligence layer (sacred output contracts)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from circuits.profiles import CircuitProfile
from db.models import FantasyTeam, PricePrediction


class PracticeSignal(BaseModel):
    """Practice session intelligence for one driver."""

    model_config = ConfigDict(frozen=True)

    driver_number: int
    driver_code: str
    session: str
    setup_sentiment: float = Field(ge=-1.0, le=1.0)
    tire_confidence: float = Field(ge=0.0, le=1.0)
    mechanical_flags: list[str] = Field(default_factory=list)
    pace_satisfaction: float = Field(ge=0.0, le=1.0)
    anomaly_flags: list[str] = Field(default_factory=list)
    raw_evidence: list[str] = Field(default_factory=list)


class QualifyingRow(BaseModel):
    """Qualifying grid row."""

    model_config = ConfigDict(frozen=True)

    driver_number: int
    driver_code: str
    grid_position: int
    session_key: int


class WeatherForecast(BaseModel):
    """Aggregated weather outlook for race weekend."""

    model_config = ConfigDict(frozen=True)

    session_key: int
    rainfall_likely: bool
    air_temperature_c: float | None = None
    track_temperature_c: float | None = None
    summary: str


class PickRecommendation(BaseModel):
    """Single ranked pick recommendation."""

    model_config = ConfigDict(frozen=True)

    rank: int = Field(ge=1, le=3)
    headline: str
    confidence: float = Field(ge=0.0, le=100.0)
    reasoning: str
    driver_code: str
    predicted_points_delta: float | None = None
    transfer_out: str | None = None
    transfer_in: str | None = None
    is_contrarian: bool | None = None
    ownership_tier: str | None = None
    league_strategy_applied: str | None = None
    opponent_conflict: bool | None = None
    price_direction: str | None = None
    price_magnitude: float | None = None
    price_confidence: float | None = None
    price_timing_note: str | None = None


class PickOutput(BaseModel):
    """
    Sacred pick generator output — identical schema for PATH A and PATH B.

    Attributes:
        picks: Up to three ranked recommendations.
        personalized: True when FantasyTeam was used.
        circuit_note: One sentence on circuit fantasy traits.
        confidence_note: One sentence on signal quality this week.
        generated_by: Model/provider identifier (rules, gemini, etc.).
    """

    model_config = ConfigDict(frozen=True)

    picks: list[PickRecommendation]
    personalized: bool
    circuit_note: str
    confidence_note: str
    generated_by: str


class PickGeneratorInput(BaseModel):
    """Input context for pick generation — CircuitProfile injected, not fetched."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    circuit: CircuitProfile
    practice_signals: list[PracticeSignal]
    qualifying_result: list[QualifyingRow]
    weather_forecast: WeatherForecast | None
    user_team: FantasyTeam | None = None
    price_predictions: dict[str, PricePrediction] | None = None
    race_key: str
    generated_by: str = "rules"
