"""SQLAlchemy models for PitWallAI."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Subscriber(Base):
    """WhatsApp subscriber with optional BYOK LLM credentials."""

    __tablename__ = "subscribers"

    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    preferred_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="gemini")
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    live_alerts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cadence_preference: Mapped[str] = mapped_column(String(20), nullable=False, default="FULL")
    rehearsal_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    share_cards_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    races_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class OpponentProfile(BaseModel):
    """User-estimated league opponent profile persisted as JSON."""

    nickname: str
    estimated_budget: float | None = None
    known_drivers: list[str] = Field(default_factory=list)
    chip_wildcard_used: bool = False
    chip_limitless_used: bool = False
    chip_megadrivers_used: bool = False
    tendency: str | None = None
    last_updated: datetime


class FantasyTeam(Base):
    """
    Progressive fantasy team profile linked to a subscriber.

    Fields are nullable and filled across race weekends; updates never
    overwrite an existing value with None.
    """

    __tablename__ = "fantasy_teams"

    phone: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("subscribers.phone", ondelete="CASCADE"),
        primary_key=True,
    )
    driver_1: Mapped[str | None] = mapped_column(String(8), nullable=True)
    driver_2: Mapped[str | None] = mapped_column(String(8), nullable=True)
    driver_3: Mapped[str | None] = mapped_column(String(8), nullable=True)
    driver_4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    driver_5: Mapped[str | None] = mapped_column(String(8), nullable=True)
    constructor_1: Mapped[str | None] = mapped_column(String(8), nullable=True)
    constructor_2: Mapped[str | None] = mapped_column(String(8), nullable=True)
    remaining_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    transfers_available: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    chips_used: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    league_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    league_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    league_total_races: Mapped[int | None] = mapped_column(Integer, nullable=True)
    league_strategy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    opponent_profiles: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    league_mode_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TeamOnboardingState(Base):
    """Persisted TEAM command conversation state."""

    __tablename__ = "team_onboarding_state"

    phone: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("subscribers.phone", ondelete="CASCADE"),
        primary_key=True,
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    awaiting_confirm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class LeagueOnboardingState(Base):
    """Persisted LEAGUE command conversation state."""

    __tablename__ = "league_onboarding_state"

    phone: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("subscribers.phone", ondelete="CASCADE"),
        primary_key=True,
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    awaiting_confirm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    update_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pending_nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    draft_opponents: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PracticeSignalRow(Base):
    """Persisted practice session intelligence per driver."""

    __tablename__ = "practice_signals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_key: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    circuit_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    driver_number: Mapped[int] = mapped_column(Integer, nullable=False)
    driver_code: Mapped[str] = mapped_column(String(8), nullable=False)
    session_label: Mapped[str] = mapped_column(String(16), nullable=False)
    setup_sentiment: Mapped[float] = mapped_column(Float, nullable=False)
    tire_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    mechanical_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    pace_satisfaction: Mapped[float] = mapped_column(Float, nullable=False)
    anomaly_flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    raw_evidence: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RaceEventRow(Base):
    """Persisted live race monitor events."""

    __tablename__ = "race_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    lap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    driver_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    utc_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RaceMonitorState(Base):
    """Resume state for Agent 4 after process restart."""

    __tablename__ = "race_monitor_state"

    race_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_key: Mapped[int] = mapped_column(Integer, nullable=False)
    last_lap: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProcessedInboundMessage(Base):
    """Dedup ledger for inbound WhatsApp webhook message IDs."""

    __tablename__ = "processed_inbound_messages"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class LiveAlertDelivery(Base):
    """Per-subscriber live alert deliveries for cross-instance rate limiting."""

    __tablename__ = "live_alert_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )


class SignalQualityRow(Base):
    """Per-circuit rolling signal hit rates (Agent 5 learner)."""

    __tablename__ = "signal_quality"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    circuit_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hit_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SeasonAccuracy(Base):
    """Season-level pick accuracy rollup (one row per season)."""

    __tablename__ = "season_accuracy"

    season: Mapped[int] = mapped_column(Integer, primary_key=True)
    overall_accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    personalized_accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    generic_accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    best_circuit: Mapped[str] = mapped_column(String(64), nullable=False, default="n/a")
    worst_circuit: Mapped[str] = mapped_column(String(64), nullable=False, default="n/a")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConstructorStrategyRow(Base):
    """Per-circuit constructor pit-strategy tendency aggregates."""

    __tablename__ = "constructor_strategy"
    __table_args__ = (
        UniqueConstraint(
            "circuit_key",
            "constructor_code",
            name="uq_constructor_strategy_circuit_constructor",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    circuit_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    constructor_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    sample_races: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lead_window_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    early_pit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    early_pit_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    undercut_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    undercut_successes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    undercut_success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    hedge_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hedge_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PickRow(Base):
    """
    Append-only pick audit log.

    Only actual_points_delta and was_correct may be updated post-race.
    """

    __tablename__ = "picks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    driver_code: Mapped[str] = mapped_column(String(8), nullable=False)
    pick_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    personalized: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    circuit_key: Mapped[str] = mapped_column(String(64), nullable=False)
    predicted_points_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    transfer_out: Mapped[str | None] = mapped_column(String(8), nullable=True)
    transfer_in: Mapped[str | None] = mapped_column(String(8), nullable=True)
    is_contrarian: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ownership_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    league_strategy_applied: Mapped[str | None] = mapped_column(String(20), nullable=True)
    opponent_conflict: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    actual_points_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pick_status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ShareCard(Base):
    """Public race recap share card (token-only access)."""

    __tablename__ = "share_cards"

    share_token: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    race_name: Mapped[str] = mapped_column(String(128), nullable=False)
    circuit_key: Mapped[str] = mapped_column(String(64), nullable=False)
    picks_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    picks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    season_accuracy_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    best_pick_driver: Mapped[str | None] = mapped_column(String(8), nullable=True)
    best_pick_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    league_position_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vs_no_change_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    pick_details: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ChipPlanStore(Base):
    """Persisted chip planner output for web share."""

    __tablename__ = "chip_plans"

    share_token: Mapped[str] = mapped_column(String(36), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TeamValueSnapshot(Base):
    """Post-race team value vs $100M cap baseline."""

    __tablename__ = "team_value_snapshots"
    __table_args__ = (UniqueConstraint("phone", "race_key", name="uq_team_value_phone_race"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    team_value: Mapped[float] = mapped_column(Float, nullable=False)
    value_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    effective_budget: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class WeekendNotificationSent(Base):
    """Dedup automated weekend notifications per subscriber."""

    __tablename__ = "weekend_notifications_sent"
    __table_args__ = (
        UniqueConstraint(
            "race_key",
            "phone",
            "notification_type",
            name="uq_weekend_notification",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PickOwnershipRow(Base):
    """Aggregate recommendation ownership proxy for a race."""

    __tablename__ = "pick_ownership"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    driver_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    pitwallai_ownership_pct: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DriverPrice(Base):
    """Immutable per-race driver price history."""

    __tablename__ = "driver_prices"
    __table_args__ = (UniqueConstraint("driver_code", "race_key", name="uq_driver_price_driver_race"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    driver_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    fantasy_points_scored: Mapped[float | None] = mapped_column(Float, nullable=True)
    ownership_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PricePrediction(Base):
    """One-race-ahead price direction prediction."""

    __tablename__ = "price_predictions"
    __table_args__ = (UniqueConstraint("driver_code", "race_key", name="uq_price_prediction_driver_race"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    driver_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    predicted_direction: Mapped[str] = mapped_column(String(16), nullable=False)
    predicted_magnitude: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    signal_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    actual_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actual_magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UserReportedPriceChange(Base):
    """Crowdsourced post-race price change reports from subscribers."""

    __tablename__ = "user_reported_price_changes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    driver_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reported_change: Mapped[float] = mapped_column(Float, nullable=False)
    reporter_phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
