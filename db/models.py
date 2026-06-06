"""SQLAlchemy models for PitWallAI."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import (
    JSON,
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
from sqlalchemy.dialects.postgresql import JSONB as _PG_JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Portable JSON column: Postgres keeps native JSONB (indexable, identical to
# before); other dialects (e.g. SQLite for the local command simulator) fall
# back to generic JSON. Production behaviour is unchanged.
JSONB = JSON().with_variant(_PG_JSONB(), "postgresql")


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


class LockedLineup(Base):
    """A player's committed lineup for one race, plus PitWallAI's pick at lock
    time — so the call can be scored against the actual result afterward."""

    __tablename__ = "locked_lineups"

    phone: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("subscribers.phone", ondelete="CASCADE"),
        primary_key=True,
    )
    race_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    drivers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    constructors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    chip: Mapped[str | None] = mapped_column(String(16), nullable=True)
    captain: Mapped[str | None] = mapped_column(String(8), nullable=True)
    model_drivers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model_constructors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model_captain: Mapped[str | None] = mapped_column(String(8), nullable=True)
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Filled when the race is scored (also used by ad-hoc backtests).
    your_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    perfect_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capture_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    decoded_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RaceMonitorSeen(Base):
    """Persistent dedup ledger for the live race monitor.

    `kind` is "msg" (race-control message) or "pit" (driver+lap pit stop).
    Rehydrated into in-memory sets on monitor startup so a Railway restart
    mid-race doesn't re-broadcast previously-seen events or double-count
    them in the called-recap.
    """

    __tablename__ = "race_monitor_seen"

    race_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RaceMonitorState(Base):
    """Resume state for Agent 4 after process restart."""

    __tablename__ = "race_monitor_state"

    race_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_key: Mapped[int] = mapped_column(Integer, nullable=False)
    last_lap: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    consecutive_poll_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_unavailable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SpendEvent(Base):
    """Append-only platform spend ledger (LLM, vision, WhatsApp). Monthly rollup."""

    __tablename__ = "spend_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    month_key: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    detail: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )


class ProcessedInboundMessage(Base):
    """Dedup ledger for inbound WhatsApp webhook message IDs.

    Two-phase: ``status='claimed'`` written at the start of handling;
    upgraded to ``'done'`` after success. Stale ``'claimed'`` rows
    (>5 min) are eligible for re-claim — covers crash-mid-handle cases.
    """

    __tablename__ = "processed_inbound_messages"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="done")
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PendingScreenshotState(Base):
    """Durable per-subscriber state: 'I'm expecting a screenshot of kind X.'

    Replaces the in-memory dict so state survives restarts and is consistent
    across uvicorn workers. TTL is enforced on read.
    """

    __tablename__ = "pending_screenshot_state"

    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class PendingTimezoneState(Base):
    """Awaiting manual IANA timezone reply after SUBSCRIBE (unknown country code)."""

    __tablename__ = "pending_timezone_state"

    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class VisionCallLog(Base):
    """One row per Gemini Vision call. Feeds per-phone hourly + global daily caps."""

    __tablename__ = "vision_call_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
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


class ConstructorStrategyProfile(Base):
    """
    Fantasy-framed constructor pit strategy at a circuit (seeded from OpenF1).

    Composite key: (constructor_code, circuit_key). Upsert on conflict.
    """

    __tablename__ = "constructor_strategy_profiles"
    __table_args__ = (
        UniqueConstraint(
            "constructor_code",
            "circuit_key",
            name="uq_constructor_strategy_profile",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    constructor_code: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    circuit_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    early_box_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    undercut_attempt_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    overcut_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_pit_window_open_lap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    double_stack_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    safety_car_opportunist: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    championship_pressure_modifier: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fantasy_tendency: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    data_quality: Mapped[str] = mapped_column(String(8), nullable=False, default="LOW")
    source_race_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConstructorStrategyRow(Base):
    """Legacy per-circuit constructor aggregates (superseded by ConstructorStrategyProfile)."""

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


class CalledRecapStore(Base):
    """Persisted post-race 'we called it' recap for web share."""

    __tablename__ = "called_recaps"

    share_token: Mapped[str] = mapped_column(String(36), primary_key=True)
    race_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    recap_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
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
