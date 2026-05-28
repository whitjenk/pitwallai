"""SQLAlchemy models for PitWallAI."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


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
    actual_points_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
