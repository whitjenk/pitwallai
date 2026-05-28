"""Database persistence for practice signals and picks."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from db.models import (
    FantasyTeam,
    LeagueOnboardingState,
    LiveAlertDelivery,
    PickRow,
    PickOwnershipRow,
    ProcessedInboundMessage,
    PracticeSignalRow,
    RaceEventRow,
    RaceMonitorState,
    SeasonAccuracy,
    SignalQualityRow,
    Subscriber,
    TeamOnboardingState,
)
from orchestrator.race_context import RaceEvent, SignalQuality, SignalQualityEntry
from db.session import get_session
from intelligence.schemas import PickOutput, PracticeSignal

_FALLBACK_SEEN_MESSAGES: set[str] = set()
_FALLBACK_ALERT_LOG: dict[str, dict[str, list[datetime]]] = defaultdict(lambda: defaultdict(list))
_LAST_SECURITY_PRUNE_AT: datetime | None = None
_SECURITY_PRUNE_EVERY = timedelta(minutes=15)
_PROCESSED_MESSAGE_RETENTION = timedelta(days=7)
_LIVE_ALERT_RETENTION = timedelta(days=14)


async def _maybe_prune_security_tables() -> None:
    """Best-effort retention pruning for security/alert tracking tables."""
    global _LAST_SECURITY_PRUNE_AT
    now = datetime.now(tz=UTC)
    if _LAST_SECURITY_PRUNE_AT and (now - _LAST_SECURITY_PRUNE_AT) < _SECURITY_PRUNE_EVERY:
        return
    _LAST_SECURITY_PRUNE_AT = now
    try:
        async with get_session() as session:
            await session.execute(
                delete(ProcessedInboundMessage).where(
                    ProcessedInboundMessage.processed_at < (now - _PROCESSED_MESSAGE_RETENTION)
                )
            )
            await session.execute(
                delete(LiveAlertDelivery).where(
                    LiveAlertDelivery.sent_at < (now - _LIVE_ALERT_RETENTION)
                )
            )
    except ValueError:
        # No DATABASE_URL configured; fallback mode keeps data in memory only.
        return


async def save_practice_signals(
    session_key: int,
    circuit_key: str,
    signals: list[PracticeSignal],
) -> None:
    """Persist practice signals for a session weekend."""
    async with get_session() as session:
        for sig in signals:
            session.add(
                PracticeSignalRow(
                    session_key=session_key,
                    circuit_key=circuit_key,
                    driver_number=sig.driver_number,
                    driver_code=sig.driver_code,
                    session_label=sig.session,
                    setup_sentiment=sig.setup_sentiment,
                    tire_confidence=sig.tire_confidence,
                    mechanical_flags=list(sig.mechanical_flags),
                    pace_satisfaction=sig.pace_satisfaction,
                    anomaly_flags=list(sig.anomaly_flags),
                    raw_evidence=list(sig.raw_evidence),
                )
            )


async def load_practice_signals(
    session_key: int,
    *,
    circuit_key: str | None = None,
) -> list[PracticeSignal]:
    """Load practice signals for a session."""
    async with get_session() as session:
        stmt = select(PracticeSignalRow).where(PracticeSignalRow.session_key == session_key)
        if circuit_key is not None:
            stmt = stmt.where(PracticeSignalRow.circuit_key == circuit_key)
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return [
        PracticeSignal(
            driver_number=r.driver_number,
            driver_code=r.driver_code,
            session=r.session_label,
            setup_sentiment=r.setup_sentiment,
            tire_confidence=r.tire_confidence,
            mechanical_flags=list(r.mechanical_flags or []),
            pace_satisfaction=r.pace_satisfaction,
            anomaly_flags=list(r.anomaly_flags or []),
            raw_evidence=list(r.raw_evidence or []),
        )
        for r in rows
    ]


async def load_historical_practice_signals(
    circuit_key: str,
    session_label: str,
    *,
    exclude_session_key: int | None = None,
) -> list[PracticeSignal]:
    """Load prior practice signals at the same circuit for anomaly comparison."""
    async with get_session() as session:
        stmt = select(PracticeSignalRow).where(
            PracticeSignalRow.circuit_key == circuit_key,
            PracticeSignalRow.session_label == session_label,
        )
        if exclude_session_key is not None:
            stmt = stmt.where(PracticeSignalRow.session_key != exclude_session_key)
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return [
        PracticeSignal(
            driver_number=r.driver_number,
            driver_code=r.driver_code,
            session=r.session_label,
            setup_sentiment=r.setup_sentiment,
            tire_confidence=r.tire_confidence,
            mechanical_flags=list(r.mechanical_flags or []),
            pace_satisfaction=r.pace_satisfaction,
            anomaly_flags=list(r.anomaly_flags or []),
            raw_evidence=list(r.raw_evidence or []),
        )
        for r in rows
    ]


async def get_fantasy_team(phone: str) -> FantasyTeam | None:
    """Load fantasy team profile."""
    async with get_session() as session:
        return await session.get(FantasyTeam, phone)


async def upsert_fantasy_team_fields(phone: str, **fields: Any) -> FantasyTeam:
    """
    Update fantasy team fields; never overwrite with None.

    Args:
        phone: Subscriber phone.
        **fields: Column updates (only non-None applied).

    Returns:
        Updated FantasyTeam row.
    """
    async with get_session() as session:
        row = await session.get(FantasyTeam, phone)
        if row is None:
            row = FantasyTeam(phone=phone)
            session.add(row)
        for key, value in fields.items():
            if value is None:
                continue
            if hasattr(row, key):
                setattr(row, key, value)
        row.updated_at = datetime.now(tz=UTC)
        await session.flush()
        return row


async def get_onboarding_state(phone: str) -> TeamOnboardingState | None:
    """Load TEAM onboarding state."""
    async with get_session() as session:
        return await session.get(TeamOnboardingState, phone)


async def set_onboarding_state(
    phone: str,
    *,
    step: int,
    awaiting_confirm: bool = False,
) -> TeamOnboardingState:
    """Create or update onboarding state."""
    async with get_session() as session:
        row = await session.get(TeamOnboardingState, phone)
        if row is None:
            row = TeamOnboardingState(phone=phone, step=step, awaiting_confirm=awaiting_confirm)
            session.add(row)
        else:
            row.step = step
            row.awaiting_confirm = awaiting_confirm
            row.updated_at = datetime.now(tz=UTC)
        await session.flush()
        return row


async def get_league_onboarding_state(phone: str) -> LeagueOnboardingState | None:
    """Load LEAGUE onboarding state."""
    async with get_session() as session:
        return await session.get(LeagueOnboardingState, phone)


async def set_league_onboarding_state(
    phone: str,
    *,
    step: int,
    awaiting_confirm: bool = False,
    update_mode: bool = False,
    pending_nickname: str | None = None,
    draft_opponents: list[dict[str, Any]] | None = None,
) -> LeagueOnboardingState:
    """Create or update LEAGUE onboarding state."""
    async with get_session() as session:
        row = await session.get(LeagueOnboardingState, phone)
        if row is None:
            row = LeagueOnboardingState(
                phone=phone,
                step=step,
                awaiting_confirm=awaiting_confirm,
                update_mode=update_mode,
                pending_nickname=pending_nickname,
                draft_opponents=list(draft_opponents or []),
            )
            session.add(row)
        else:
            row.step = step
            row.awaiting_confirm = awaiting_confirm
            row.update_mode = update_mode
            row.pending_nickname = pending_nickname
            if draft_opponents is not None:
                row.draft_opponents = list(draft_opponents)
            row.updated_at = datetime.now(tz=UTC)
        await session.flush()
        return row


async def list_active_subscribers() -> list[Subscriber]:
    """Return all active WhatsApp subscribers."""
    async with get_session() as session:
        result = await session.execute(
            select(Subscriber).where(Subscriber.active.is_(True))
        )
        return list(result.scalars().all())


async def get_picks_for_race(
    race_key: str,
    *,
    phone: str | None = None,
) -> list[PickRow]:
    """Load pick audit rows for a race, optionally filtered by phone."""
    async with get_session() as session:
        stmt = select(PickRow).where(PickRow.race_key == race_key)
        if phone is not None:
            stmt = stmt.where(PickRow.phone == phone)
        else:
            stmt = stmt.where(PickRow.phone.is_(None))
        stmt = stmt.order_by(PickRow.pick_rank)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def list_subscribers_for_race_picks(race_key: str) -> list[Subscriber]:
    """Subscribers who received picks for this race (distinct phones on audit log)."""
    async with get_session() as session:
        result = await session.execute(
            select(PickRow.phone).where(
                PickRow.race_key == race_key,
                PickRow.phone.is_not(None),
            ).distinct()
        )
        phones = [row[0] for row in result.all() if row[0]]
        if not phones:
            return await list_active_subscribers()
        subs: list[Subscriber] = []
        for phone in phones:
            sub = await session.get(Subscriber, phone)
            if sub and sub.active:
                subs.append(sub)
        return subs


async def upsert_season_accuracy(
    *,
    season: int,
    overall_accuracy: float,
    personalized_accuracy: float,
    generic_accuracy: float,
    best_circuit: str,
    worst_circuit: str,
) -> SeasonAccuracy:
    """Upsert season accuracy stats."""
    async with get_session() as session:
        row = await session.get(SeasonAccuracy, season)
        if row is None:
            row = SeasonAccuracy(
                season=season,
                overall_accuracy=overall_accuracy,
                personalized_accuracy=personalized_accuracy,
                generic_accuracy=generic_accuracy,
                best_circuit=best_circuit,
                worst_circuit=worst_circuit,
            )
            session.add(row)
        else:
            row.overall_accuracy = overall_accuracy
            row.personalized_accuracy = personalized_accuracy
            row.generic_accuracy = generic_accuracy
            row.best_circuit = best_circuit
            row.worst_circuit = worst_circuit
            row.updated_at = datetime.now(tz=UTC)
        await session.flush()
        return row


async def append_picks(
    race_key: str,
    output: PickOutput,
    *,
    phone: str | None,
    circuit_key: str,
) -> list[uuid.UUID]:
    """
    Append pick rows to the audit log (never delete).

    Returns:
        List of created pick UUIDs.
    """
    ids: list[uuid.UUID] = []
    async with get_session() as session:
        for pick in output.picks:
            row_id = uuid.uuid4()
            session.add(
                PickRow(
                    id=row_id,
                    race_key=race_key,
                    phone=phone,
                    driver_code=pick.driver_code,
                    pick_rank=pick.rank,
                    confidence=pick.confidence,
                    reasoning=pick.reasoning,
                    personalized=output.personalized,
                    provider=output.generated_by,
                    circuit_key=circuit_key,
                    predicted_points_delta=pick.predicted_points_delta,
                    transfer_out=pick.transfer_out,
                    transfer_in=pick.transfer_in,
                    is_contrarian=pick.is_contrarian,
                    ownership_tier=pick.ownership_tier,
                    league_strategy_applied=pick.league_strategy_applied,
                    opponent_conflict=pick.opponent_conflict,
                )
            )
            ids.append(row_id)
    return ids


async def update_pick_result(
    pick_id: uuid.UUID,
    *,
    actual_points_delta: float,
    was_correct: bool,
) -> None:
    """Post-race update — only allowed mutation on picks."""
    async with get_session() as session:
        row = await session.get(PickRow, pick_id)
        if row is None:
            raise ValueError(f"Pick {pick_id} not found")
        row.actual_points_delta = actual_points_delta
        row.was_correct = was_correct


async def get_all_picks_for_race(race_key: str) -> list[PickRow]:
    """All pick rows for a race (any phone)."""
    async with get_session() as session:
        result = await session.execute(
            select(PickRow).where(PickRow.race_key == race_key).order_by(PickRow.pick_rank)
        )
        return list(result.scalars().all())


async def load_practice_signals_by_circuit(circuit_key: str) -> list[PracticeSignal]:
    """Load latest practice signals for a circuit."""
    async with get_session() as session:
        result = await session.execute(
            select(PracticeSignalRow)
            .where(PracticeSignalRow.circuit_key == circuit_key)
            .order_by(PracticeSignalRow.created_at.desc())
        )
        rows = list(result.scalars().all())
    return [
        PracticeSignal(
            driver_number=r.driver_number,
            driver_code=r.driver_code,
            session=r.session_label,
            setup_sentiment=r.setup_sentiment,
            tire_confidence=r.tire_confidence,
            mechanical_flags=list(r.mechanical_flags or []),
            pace_satisfaction=r.pace_satisfaction,
            anomaly_flags=list(r.anomaly_flags or []),
            raw_evidence=list(r.raw_evidence or []),
        )
        for r in rows
    ]


async def list_live_alert_subscribers() -> list[Subscriber]:
    """Active subscribers with live race alerts enabled."""
    async with get_session() as session:
        result = await session.execute(
            select(Subscriber).where(
                Subscriber.active.is_(True),
                Subscriber.live_alerts.is_(True),
            )
        )
        return list(result.scalars().all())


async def update_subscriber_preferences(
    phone: str,
    *,
    live_alerts: bool | None = None,
    cadence_preference: str | None = None,
) -> Subscriber | None:
    """Update subscriber LIVE/cadence preferences."""
    async with get_session() as session:
        row = await session.get(Subscriber, phone)
        if row is None:
            return None
        if live_alerts is not None:
            row.live_alerts = live_alerts
        if cadence_preference is not None:
            row.cadence_preference = cadence_preference
        await session.flush()
        return row


async def save_race_event(event: RaceEvent) -> None:
    """Persist a live race monitor event."""
    async with get_session() as session:
        session.add(
            RaceEventRow(
                race_key=event.race_key,
                event_type=event.event_type.value,
                lap=event.lap,
                description=event.description,
                driver_code=event.driver_code,
                utc_timestamp=event.utc_timestamp,
            )
        )


async def get_monitor_state(race_key: str) -> RaceMonitorState | None:
    """Load race monitor resume state."""
    async with get_session() as session:
        return await session.get(RaceMonitorState, race_key)


async def set_monitor_state(
    race_key: str,
    *,
    session_key: int,
    last_lap: int,
    running: bool,
) -> None:
    """Upsert race monitor state."""
    async with get_session() as session:
        row = await session.get(RaceMonitorState, race_key)
        if row is None:
            row = RaceMonitorState(
                race_key=race_key,
                session_key=session_key,
                last_lap=last_lap,
                running=running,
            )
            session.add(row)
        else:
            row.session_key = session_key
            row.last_lap = last_lap
            row.running = running
            row.updated_at = datetime.now(tz=UTC)


async def upsert_signal_quality_row(
    circuit_key: str,
    signal_type: str,
    hit_rate: float,
) -> None:
    """Rolling hit rate update with exponential weight toward recent races."""
    async with get_session() as session:
        result = await session.execute(
            select(SignalQualityRow).where(
                SignalQualityRow.circuit_key == circuit_key,
                SignalQualityRow.signal_type == signal_type,
            )
        )
        row = result.scalars().first()
        if row is None:
            session.add(
                SignalQualityRow(
                    circuit_key=circuit_key,
                    signal_type=signal_type,
                    sample_size=1,
                    hit_rate=hit_rate,
                )
            )
        else:
            n = row.sample_size
            row.hit_rate = (row.hit_rate * n + hit_rate) / (n + 1)
            row.sample_size = n + 1
            row.updated_at = datetime.now(tz=UTC)


async def build_signal_quality_from_db(circuit_key: str) -> SignalQuality | None:
    """Load signal quality entries for orchestrator context."""
    async with get_session() as session:
        result = await session.execute(
            select(SignalQualityRow).where(SignalQualityRow.circuit_key == circuit_key)
        )
        rows = list(result.scalars().all())
    if not rows:
        return None
    entries: dict[str, SignalQualityEntry] = {}
    for row in rows:
        mult = 1.3 if row.hit_rate > 0.7 else (0.5 if row.hit_rate < 0.4 else 1.0)
        mult = max(0.1, min(2.0, mult))
        entries[row.signal_type] = SignalQualityEntry(
            circuit_key=row.circuit_key,
            signal_type=row.signal_type,
            sample_size=row.sample_size,
            hit_rate=row.hit_rate,
            weight_multiplier=mult,
        )
    return SignalQuality(entries=entries)


async def was_inbound_message_processed(message_id: str) -> bool:
    """True when this inbound WhatsApp message_id was already handled."""
    if not message_id.strip():
        return False
    await _maybe_prune_security_tables()
    try:
        async with get_session() as session:
            row = await session.get(ProcessedInboundMessage, message_id)
            return row is not None
    except ValueError:
        return message_id in _FALLBACK_SEEN_MESSAGES


async def mark_inbound_message_processed(message_id: str) -> None:
    """Record successful handling for webhook deduplication."""
    if not message_id.strip():
        return
    await _maybe_prune_security_tables()
    try:
        async with get_session() as session:
            session.add(ProcessedInboundMessage(message_id=message_id))
            try:
                await session.flush()
            except IntegrityError:
                # Already recorded by another worker/request.
                await session.rollback()
    except ValueError:
        _FALLBACK_SEEN_MESSAGES.add(message_id)


async def can_send_live_alert(
    race_key: str,
    phone: str,
    *,
    per_hour_limit: int,
) -> bool:
    """Cross-instance live-alert rate limiter by subscriber and race key."""
    cutoff = datetime.now(tz=UTC) - timedelta(hours=1)
    await _maybe_prune_security_tables()
    try:
        async with get_session() as session:
            count_stmt = (
                select(func.count())
                .select_from(LiveAlertDelivery)
                .where(
                    LiveAlertDelivery.race_key == race_key,
                    LiveAlertDelivery.phone == phone,
                    LiveAlertDelivery.sent_at >= cutoff,
                )
            )
            recent = int((await session.execute(count_stmt)).scalar_one())
            return recent < per_hour_limit
    except ValueError:
        history = _FALLBACK_ALERT_LOG[race_key][phone]
        _FALLBACK_ALERT_LOG[race_key][phone] = [ts for ts in history if ts >= cutoff]
        return len(_FALLBACK_ALERT_LOG[race_key][phone]) < per_hour_limit


async def record_live_alert_delivery(race_key: str, phone: str) -> None:
    """Persist a sent live alert delivery for rate limiting and audit."""
    now = datetime.now(tz=UTC)
    await _maybe_prune_security_tables()
    try:
        async with get_session() as session:
            session.add(
                LiveAlertDelivery(
                    race_key=race_key,
                    phone=phone,
                    sent_at=now,
                )
            )
    except ValueError:
        _FALLBACK_ALERT_LOG[race_key][phone].append(now)


async def save_pick_ownership(
    race_key: str,
    ownership_rows: list[dict[str, Any]],
) -> None:
    """Persist aggregate ownership proxy rows for a race."""
    if not ownership_rows:
        return
    async with get_session() as session:
        for row in ownership_rows:
            session.add(
                PickOwnershipRow(
                    race_key=race_key,
                    driver_code=row["driver_code"],
                    pitwallai_ownership_pct=float(row["pitwallai_ownership_pct"]),
                    recommendation_count=int(row["recommendation_count"]),
                )
            )


async def load_latest_pick_ownership(race_key: str) -> dict[str, PickOwnershipRow]:
    """Latest per-driver ownership rows for a race key."""
    async with get_session() as session:
        result = await session.execute(
            select(PickOwnershipRow).where(PickOwnershipRow.race_key == race_key)
        )
        rows = list(result.scalars().all())
    latest: dict[str, PickOwnershipRow] = {}
    for row in rows:
        prior = latest.get(row.driver_code)
        if prior is None or prior.created_at <= row.created_at:
            latest[row.driver_code] = row
    return latest
