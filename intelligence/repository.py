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
    ChipPlanStore,
    ConstructorStrategyProfile,
    ConstructorStrategyRow,
    DriverPrice,
    FantasyTeam,
    LeagueOnboardingState,
    LiveAlertDelivery,
    PickRow,
    PendingScreenshotState,
    PendingTimezoneState,
    PickOwnershipRow,
    PricePrediction,
    ProcessedInboundMessage,
    PracticeSignalRow,
    RaceEventRow,
    RaceMonitorState,
    SeasonAccuracy,
    ShareCard,
    SignalQualityRow,
    Subscriber,
    TeamOnboardingState,
    TeamValueSnapshot,
    UserReportedPriceChange,
    VisionCallLog,
    WeekendNotificationSent,
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
    try:
        async with get_session() as session:
            stmt = select(PickRow).where(PickRow.race_key == race_key)
            if phone is not None:
                stmt = stmt.where(PickRow.phone == phone)
            else:
                stmt = stmt.where(PickRow.phone.is_(None))
            stmt = stmt.order_by(PickRow.pick_rank)
            result = await session.execute(stmt)
            return list(result.scalars().all())
    except ValueError:
        return []


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
    pick_status: str = "sent",
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
                    pick_status=pick_status,
                )
            )
            ids.append(row_id)
    return ids


async def get_draft_picks_for_race(phone: str, race_key: str) -> list[PickRow]:
    """Thursday draft recommendations (not yet broadcast)."""
    async with get_session() as session:
        result = await session.execute(
            select(PickRow)
            .where(
                PickRow.race_key == race_key,
                PickRow.phone == phone,
                PickRow.pick_status == "draft",
            )
            .order_by(PickRow.pick_rank)
        )
        return list(result.scalars().all())


async def mark_picks_sent_for_race(phone: str, race_key: str) -> None:
    """Promote draft picks to sent when Saturday broadcast fires."""
    async with get_session() as session:
        result = await session.execute(
            select(PickRow).where(
                PickRow.race_key == race_key,
                PickRow.phone == phone,
                PickRow.pick_status == "draft",
            )
        )
        for row in result.scalars().all():
            row.pick_status = "sent"


async def get_subscriber(phone: str) -> Subscriber | None:
    async with get_session() as session:
        return await session.get(Subscriber, phone)


async def set_subscriber_share_private(phone: str, *, private: bool) -> None:
    async with get_session() as session:
        row = await session.get(Subscriber, phone)
        if row:
            row.share_cards_private = private


async def increment_subscriber_races_received(phone: str) -> None:
    async with get_session() as session:
        row = await session.get(Subscriber, phone)
        if row:
            row.races_received = int(row.races_received or 0) + 1


async def get_share_card_by_token(share_token: str) -> ShareCard | None:
    async with get_session() as session:
        return await session.get(ShareCard, share_token)


async def get_share_card_for_race(phone: str, race_key: str) -> ShareCard | None:
    """Latest share card for a subscriber/race (post-scorer)."""
    async with get_session() as session:
        result = await session.execute(
            select(ShareCard)
            .where(ShareCard.phone == phone, ShareCard.race_key == race_key)
            .order_by(ShareCard.created_at.desc())
        )
        return result.scalars().first()


async def get_latest_team_value_snapshot(phone: str) -> TeamValueSnapshot | None:
    """Most recent team value snapshot for budget-aware picks."""
    async with get_session() as session:
        result = await session.execute(
            select(TeamValueSnapshot)
            .where(TeamValueSnapshot.phone == phone)
            .order_by(TeamValueSnapshot.updated_at.desc())
        )
        return result.scalars().first()


async def load_season_accuracy_row(season: int) -> SeasonAccuracy | None:
    async with get_session() as session:
        return await session.get(SeasonAccuracy, season)


async def load_latest_pick_for_driver(
    race_key: str,
    driver_code: str,
    *,
    phone: str | None = None,
) -> PickRow | None:
    """Latest audit pick row for a driver on a race weekend (personalized then generic)."""
    code = driver_code.upper()
    if phone:
        rows = await get_picks_for_race(race_key, phone=phone)
        for row in rows:
            if row.driver_code.upper() == code:
                return row
    rows = await get_picks_for_race(race_key, phone=None)
    for row in rows:
        if row.driver_code.upper() == code:
            return row
    return None


async def load_subscriber_pick_history(
    phone: str,
    *,
    limit: int = 3,
) -> list[tuple[str, str, str, float, bool]]:
    """
    Return recent race outcomes for a subscriber.

    Each tuple: (race_key, race_name, driver_code, points_delta, was_correct).
    """
    from scheduler.calendar import get_race_weekend

    async with get_session() as session:
        result = await session.execute(
            select(PickRow)
            .where(
                PickRow.phone == phone,
                PickRow.was_correct.is_not(None),
            )
            .order_by(PickRow.created_at.desc())
        )
        rows = list(result.scalars().all())

    by_race: dict[str, PickRow] = {}
    for row in rows:
        if row.race_key not in by_race:
            by_race[row.race_key] = row

    history: list[tuple[str, str, str, float, bool]] = []
    for race_key, row in list(by_race.items())[:limit]:
        weekend = get_race_weekend(race_key)
        race_name = weekend.display_name if weekend else race_key.replace("_", " ").title()
        pts = float(row.actual_points_delta or 0.0)
        history.append(
            (
                race_key,
                race_name,
                row.driver_code,
                pts,
                bool(row.was_correct),
            )
        )
    return history


async def load_season_hit_rate_for_phone(phone: str, *, season: int) -> float:
    prefix = f"{season}_"
    async with get_session() as session:
        result = await session.execute(
            select(PickRow).where(
                PickRow.phone == phone,
                PickRow.race_key.like(f"{prefix}%"),
                PickRow.personalized.is_(True),
                PickRow.was_correct.is_not(None),
            )
        )
        rows = list(result.scalars().all())
    if not rows:
        return 0.0
    return round(100.0 * sum(1 for r in rows if r.was_correct) / len(rows), 1)


async def notification_already_sent(
    race_key: str,
    phone: str,
    notification_type: str,
) -> bool:
    async with get_session() as session:
        result = await session.execute(
            select(WeekendNotificationSent).where(
                WeekendNotificationSent.race_key == race_key,
                WeekendNotificationSent.phone == phone,
                WeekendNotificationSent.notification_type == notification_type,
            )
        )
        return result.scalars().first() is not None


async def record_notification_sent(
    race_key: str,
    phone: str,
    notification_type: str,
) -> None:
    async with get_session() as session:
        session.add(
            WeekendNotificationSent(
                race_key=race_key,
                phone=phone,
                notification_type=notification_type,
            )
        )


async def save_chip_plan(phone: str, share_token: str, plan_json: dict[str, Any]) -> None:
    async with get_session() as session:
        session.add(
            ChipPlanStore(
                share_token=share_token,
                phone=phone,
                plan_json=plan_json,
            )
        )


async def get_chip_plan_by_token(share_token: str) -> ChipPlanStore | None:
    async with get_session() as session:
        return await session.get(ChipPlanStore, share_token)


async def upsert_team_value_snapshot(
    *,
    phone: str,
    race_key: str,
    team_value: float,
    value_delta: float,
    effective_budget: float,
) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(TeamValueSnapshot).where(
                TeamValueSnapshot.phone == phone,
                TeamValueSnapshot.race_key == race_key,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            session.add(
                TeamValueSnapshot(
                    phone=phone,
                    race_key=race_key,
                    team_value=team_value,
                    value_delta=value_delta,
                    effective_budget=effective_budget,
                )
            )
        else:
            row.team_value = team_value
            row.value_delta = value_delta
            row.effective_budget = effective_budget
            row.updated_at = datetime.now(tz=UTC)


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


async def save_league_standings_snapshot(
    phone: str,
    entries: list[dict[str, Any]],
    captured_at_race_key: str | None,
) -> None:
    """Persist a league standings screenshot extraction onto FantasyTeam.

    Stored on FantasyTeam.opponent_profiles JSONB (already exists, no migration).
    Replaces any prior snapshot — latest wins.
    """
    payload = {
        "captured_at_race_key": captured_at_race_key,
        "entries": entries,
    }
    async with get_session() as session:
        row = await session.get(FantasyTeam, phone)
        if row is None:
            row = FantasyTeam(phone=phone)
            session.add(row)
        row.opponent_profiles = [payload]


async def get_prior_season_circuit_winners(season: int) -> dict[str, str]:
    """{circuit_key → driver_code that scored max points} for a past season.

    Used by the eval baselines. Returns an empty dict when the season has
    no scored picks yet (cold-start safe).
    """
    async with get_session() as session:
        result = await session.execute(
            select(PickRow).where(
                PickRow.race_key.like(f"{season}_%"),
                PickRow.was_correct.is_not(None),
            )
        )
        rows = list(result.scalars().all())

    by_circuit: dict[str, tuple[str, float]] = {}
    for r in rows:
        delta = r.actual_points_delta or 0.0
        prior = by_circuit.get(r.circuit_key)
        if prior is None or delta > prior[1]:
            by_circuit[r.circuit_key] = (r.driver_code, delta)
    return {k: v[0] for k, v in by_circuit.items()}


def _row_to_practice_signal(r: PracticeSignalRow) -> PracticeSignal:
    return PracticeSignal(
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


async def load_practice_signals_by_circuit(circuit_key: str) -> list[PracticeSignal]:
    """Load latest practice signals for a circuit (one row per driver, FP2 over FP1)."""
    try:
        async with get_session() as session:
            result = await session.execute(
                select(PracticeSignalRow)
                .where(PracticeSignalRow.circuit_key == circuit_key)
                .order_by(PracticeSignalRow.created_at.desc())
            )
            rows = list(result.scalars().all())
    except ValueError:
        return []
    priority = {"FP2": 2, "FP1": 1}
    merged: dict[str, PracticeSignal] = {}
    for r in rows:
        sig = _row_to_practice_signal(r)
        code = sig.driver_code.upper()
        existing = merged.get(code)
        if existing is None:
            merged[code] = sig
            continue
        if priority.get(sig.session, 0) > priority.get(existing.session, 0):
            merged[code] = sig
    return list(merged.values())


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


async def save_driver_price_rows(rows: list[dict[str, Any]]) -> int:
    """Insert immutable driver price rows; duplicates are skipped."""
    created = 0
    if not rows:
        return created
    async with get_session() as session:
        existing_rows = await session.execute(select(DriverPrice.driver_code, DriverPrice.race_key))
        existing = {(str(d), str(r)) for d, r in existing_rows.all()}
        for row in rows:
            key = (str(row["driver_code"]), str(row["race_key"]))
            if key in existing:
                continue
            session.add(
                DriverPrice(
                    driver_code=row["driver_code"],
                    race_key=row["race_key"],
                    price=float(row["price"]),
                    price_change=(None if row.get("price_change") is None else float(row["price_change"])),
                    fantasy_points_scored=(
                        None if row.get("fantasy_points_scored") is None else float(row["fantasy_points_scored"])
                    ),
                    ownership_pct=(None if row.get("ownership_pct") is None else float(row["ownership_pct"])),
                )
            )
            existing.add(key)
            created += 1
    return created


async def is_driver_price_history_empty() -> bool:
    """True when price history has no rows."""
    async with get_session() as session:
        count = int((await session.execute(select(func.count()).select_from(DriverPrice))).scalar_one())
        return count == 0


async def get_price_history(driver_code: str, last_n_races: int = 10) -> list[DriverPrice]:
    """Last N prices for a driver, returned chronologically ascending."""
    async with get_session() as session:
        result = await session.execute(
            select(DriverPrice)
            .where(DriverPrice.driver_code == driver_code.upper())
            .order_by(DriverPrice.created_at.desc())
            .limit(max(1, last_n_races))
        )
        rows = list(result.scalars().all())
    return list(reversed(rows))


async def get_all_current_prices() -> dict[str, float]:
    """Most recent known price for each driver."""
    async with get_session() as session:
        result = await session.execute(select(DriverPrice).order_by(DriverPrice.driver_code, DriverPrice.created_at.desc()))
        rows = list(result.scalars().all())
    latest: dict[str, float] = {}
    for row in rows:
        if row.driver_code not in latest:
            latest[row.driver_code] = float(row.price)
    return latest


async def upsert_price_predictions(rows: list[dict[str, Any]]) -> int:
    """Upsert one-race-ahead price predictions."""
    created = 0
    async with get_session() as session:
        for row in rows:
            existing = (
                await session.execute(
                    select(PricePrediction).where(
                        PricePrediction.driver_code == row["driver_code"],
                        PricePrediction.race_key == row["race_key"],
                    )
                )
            ).scalars().first()
            if existing is None:
                session.add(
                    PricePrediction(
                        driver_code=row["driver_code"],
                        race_key=row["race_key"],
                        predicted_direction=row["predicted_direction"],
                        predicted_magnitude=float(row["predicted_magnitude"]),
                        confidence=float(row["confidence"]),
                        reasoning=row["reasoning"],
                        signal_breakdown=dict(row["signal_breakdown"]),
                    )
                )
                created += 1
            else:
                existing.predicted_direction = row["predicted_direction"]
                existing.predicted_magnitude = float(row["predicted_magnitude"])
                existing.confidence = float(row["confidence"])
                existing.reasoning = row["reasoning"]
                existing.signal_breakdown = dict(row["signal_breakdown"])
    return created


async def get_price_prediction_map(race_key: str) -> dict[str, PricePrediction]:
    """Latest predictions for a target race keyed by driver code."""
    async with get_session() as session:
        result = await session.execute(select(PricePrediction).where(PricePrediction.race_key == race_key))
        rows = list(result.scalars().all())
    return {row.driver_code: row for row in rows}


async def add_user_reported_price_change(
    *,
    driver_code: str,
    race_key: str,
    reported_change: float,
    reporter_phone: str,
) -> None:
    """Store one crowdsourced price-change report."""
    async with get_session() as session:
        session.add(
            UserReportedPriceChange(
                driver_code=driver_code.upper(),
                race_key=race_key,
                reported_change=float(reported_change),
                reporter_phone=reporter_phone,
            )
        )


async def get_user_reported_price_changes(race_key: str) -> list[UserReportedPriceChange]:
    """All user-reported price changes for a race key."""
    async with get_session() as session:
        result = await session.execute(
            select(UserReportedPriceChange).where(UserReportedPriceChange.race_key == race_key)
        )
        return list(result.scalars().all())


async def update_price_prediction_actuals(
    *,
    race_key: str,
    actuals: dict[str, float],
) -> int:
    """Update predictions with actual post-race changes."""
    updated = 0
    async with get_session() as session:
        result = await session.execute(select(PricePrediction).where(PricePrediction.race_key == race_key))
        rows = list(result.scalars().all())
        for row in rows:
            if row.driver_code not in actuals:
                continue
            actual_mag = float(actuals[row.driver_code])
            if actual_mag > 0.05:
                actual_dir = "UP"
            elif actual_mag < -0.05:
                actual_dir = "DOWN"
            else:
                actual_dir = "STABLE"
            row.actual_magnitude = actual_mag
            row.actual_direction = actual_dir
            row.was_correct = (row.predicted_direction == actual_dir)
            updated += 1
    return updated


async def upsert_constructor_strategy_rows(
    circuit_key: str,
    rows: list[dict[str, Any]],
) -> int:
    """Upsert constructor strategy tendencies for a circuit."""
    updated = 0
    if not rows:
        return updated
    async with get_session() as session:
        for row in rows:
            result = await session.execute(
                select(ConstructorStrategyRow).where(
                    ConstructorStrategyRow.circuit_key == circuit_key,
                    ConstructorStrategyRow.constructor_code == row["constructor_code"],
                )
            )
            existing = result.scalars().first()
            if existing is None:
                session.add(
                    ConstructorStrategyRow(
                        circuit_key=circuit_key,
                        constructor_code=row["constructor_code"],
                        sample_races=int(row["sample_races"]),
                        lead_window_samples=int(row["lead_window_samples"]),
                        early_pit_count=int(row["early_pit_count"]),
                        early_pit_rate=float(row["early_pit_rate"]),
                        undercut_attempts=int(row["undercut_attempts"]),
                        undercut_successes=int(row["undercut_successes"]),
                        undercut_success_rate=float(row["undercut_success_rate"]),
                        hedge_events=int(row["hedge_events"]),
                        hedge_rate=float(row["hedge_rate"]),
                    )
                )
            else:
                existing.sample_races = int(row["sample_races"])
                existing.lead_window_samples = int(row["lead_window_samples"])
                existing.early_pit_count = int(row["early_pit_count"])
                existing.early_pit_rate = float(row["early_pit_rate"])
                existing.undercut_attempts = int(row["undercut_attempts"])
                existing.undercut_successes = int(row["undercut_successes"])
                existing.undercut_success_rate = float(row["undercut_success_rate"])
                existing.hedge_events = int(row["hedge_events"])
                existing.hedge_rate = float(row["hedge_rate"])
            updated += 1
    return updated


def _profile_row_to_data(row: ConstructorStrategyProfile) -> Any:
    from intelligence.constructor_strategy import ConstructorStrategyProfileData

    return ConstructorStrategyProfileData(
        constructor_code=row.constructor_code,
        circuit_key=row.circuit_key,
        sample_size=row.sample_size,
        early_box_rate=row.early_box_rate,
        undercut_attempt_rate=row.undercut_attempt_rate,
        overcut_rate=row.overcut_rate,
        avg_pit_window_open_lap=row.avg_pit_window_open_lap,
        double_stack_rate=row.double_stack_rate,
        safety_car_opportunist=row.safety_car_opportunist,
        championship_pressure_modifier=row.championship_pressure_modifier,
        fantasy_tendency=row.fantasy_tendency,
        data_quality=row.data_quality,
        source_race_keys=list(row.source_race_keys or []),
    )


async def count_constructor_strategy_profiles() -> int:
    """Count rows in constructor_strategy_profiles (seeder gate)."""
    try:
        async with get_session() as session:
            result = await session.execute(
                select(func.count()).select_from(ConstructorStrategyProfile)
            )
            return int(result.scalar_one() or 0)
    except ValueError:
        return 0


async def load_constructor_strategy_profile(
    constructor_code: str,
    circuit_key: str,
) -> Any | None:
    """Load one persisted constructor strategy profile."""
    try:
        async with get_session() as session:
            result = await session.execute(
                select(ConstructorStrategyProfile).where(
                    ConstructorStrategyProfile.constructor_code == constructor_code,
                    ConstructorStrategyProfile.circuit_key == circuit_key,
                )
            )
            row = result.scalars().first()
        return _profile_row_to_data(row) if row else None
    except ValueError:
        return None


async def load_constructor_strategy_profiles(
    circuit_key: str,
) -> dict[str, Any]:
    """Load all constructor profiles for a circuit keyed by constructor_code."""
    try:
        async with get_session() as session:
            result = await session.execute(
                select(ConstructorStrategyProfile).where(
                    ConstructorStrategyProfile.circuit_key == circuit_key
                )
            )
            rows = list(result.scalars().all())
        return {row.constructor_code: _profile_row_to_data(row) for row in rows}
    except ValueError:
        return {}


async def upsert_constructor_strategy_profile(profile: Any) -> None:
    """Upsert calculated ConstructorStrategyProfileData to Postgres."""
    try:
        async with get_session() as session:
            result = await session.execute(
                select(ConstructorStrategyProfile).where(
                    ConstructorStrategyProfile.constructor_code == profile.constructor_code,
                    ConstructorStrategyProfile.circuit_key == profile.circuit_key,
                )
            )
            existing = result.scalars().first()
            undercut = profile.undercut_attempt_rate
            if existing is None:
                session.add(
                    ConstructorStrategyProfile(
                        constructor_code=profile.constructor_code,
                        circuit_key=profile.circuit_key,
                        sample_size=profile.sample_size,
                        early_box_rate=profile.early_box_rate,
                        undercut_attempt_rate=undercut,
                        overcut_rate=profile.overcut_rate,
                        avg_pit_window_open_lap=profile.avg_pit_window_open_lap,
                        double_stack_rate=profile.double_stack_rate,
                        safety_car_opportunist=profile.safety_car_opportunist,
                        championship_pressure_modifier=profile.championship_pressure_modifier,
                        fantasy_tendency=profile.fantasy_tendency[:120],
                        data_quality=profile.data_quality,
                        source_race_keys=list(profile.source_race_keys),
                        last_updated=datetime.now(tz=UTC),
                    )
                )
            else:
                existing.sample_size = profile.sample_size
                existing.early_box_rate = profile.early_box_rate
                existing.undercut_attempt_rate = undercut
                existing.overcut_rate = profile.overcut_rate
                existing.avg_pit_window_open_lap = profile.avg_pit_window_open_lap
                existing.double_stack_rate = profile.double_stack_rate
                existing.safety_car_opportunist = profile.safety_car_opportunist
                existing.championship_pressure_modifier = profile.championship_pressure_modifier
                existing.fantasy_tendency = profile.fantasy_tendency[:120]
                existing.data_quality = profile.data_quality
                existing.source_race_keys = list(profile.source_race_keys)
                existing.last_updated = datetime.now(tz=UTC)
    except ValueError:
        return


async def load_constructor_strategy(circuit_key: str) -> dict[str, dict[str, Any]]:
    """Load persisted constructor strategy rows keyed by constructor code."""
    async with get_session() as session:
        result = await session.execute(
            select(ConstructorStrategyRow).where(ConstructorStrategyRow.circuit_key == circuit_key)
        )
        rows = list(result.scalars().all())
    return {
        row.constructor_code: {
            "sample_races": row.sample_races,
            "lead_window_samples": row.lead_window_samples,
            "early_pit_count": row.early_pit_count,
            "early_pit_rate": row.early_pit_rate,
            "undercut_attempts": row.undercut_attempts,
            "undercut_successes": row.undercut_successes,
            "undercut_success_rate": row.undercut_success_rate,
            "hedge_events": row.hedge_events,
            "hedge_rate": row.hedge_rate,
        }
        for row in rows
    }


# Tables with phone / reporter_phone that lack ON DELETE CASCADE from subscribers.
# Keep in sync with db.models — tests/test_erase_subscriber.py asserts completeness.
_ERASE_PHONE_TARGETS: tuple[tuple[type, str], ...] = (
    (PickRow, "phone"),
    (LiveAlertDelivery, "phone"),
    (UserReportedPriceChange, "reporter_phone"),
    (PendingScreenshotState, "phone"),
    (PendingTimezoneState, "phone"),
    (VisionCallLog, "phone"),
    (ShareCard, "phone"),
    (ChipPlanStore, "phone"),
    (TeamValueSnapshot, "phone"),
    (WeekendNotificationSent, "phone"),
)


async def erase_subscriber_data(phone: str) -> bool:
    """
    Remove all subscriber-linked rows after explicit DELETE request.

    # HARD DELETE PERMITTED: explicit user data erasure request
    # This is the only hard delete in the codebase.
    # All other deletes are soft (active=False).
    """
    async with get_session() as session:
        for model, column in _ERASE_PHONE_TARGETS:
            await session.execute(
                delete(model).where(getattr(model, column) == phone),
            )
        row = await session.get(Subscriber, phone)
        if row is None:
            return False
        await session.delete(row)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Pending screenshot state — DB-backed replacement for in-memory dict.
# Survives restarts; consistent across uvicorn workers.
# ─────────────────────────────────────────────────────────────────────────────

_SCREENSHOT_TTL_HOURS: dict[str, int] = {
    "team_setup": 48,
    "locked_team": 36,
    "league_standings": 72,
}
_SCREENSHOT_DEFAULT_TTL_HOURS = 48


async def set_pending_screenshot_db(phone: str, kind: str) -> None:
    """Set/refresh the expected screenshot kind for a phone, with TTL."""
    ttl_hours = _SCREENSHOT_TTL_HOURS.get(kind, _SCREENSHOT_DEFAULT_TTL_HOURS)
    expires_at = datetime.now(tz=UTC) + timedelta(hours=ttl_hours)
    try:
        async with get_session() as session:
            row = await session.get(PendingScreenshotState, phone)
            if row is None:
                session.add(PendingScreenshotState(
                    phone=phone, kind=kind, expires_at=expires_at,
                ))
            else:
                row.kind = kind
                row.expires_at = expires_at
    except ValueError:
        pass  # no DB configured — onboarding will degrade gracefully


async def get_pending_screenshot_db(phone: str) -> str | None:
    """Return the expected screenshot kind, or None if absent/expired."""
    now = datetime.now(tz=UTC)
    try:
        async with get_session() as session:
            row = await session.get(PendingScreenshotState, phone)
            if row is None:
                return None
            if row.expires_at <= now:
                await session.delete(row)
                return None
            return row.kind
    except ValueError:
        return None


async def clear_pending_screenshot_db(phone: str) -> None:
    try:
        async with get_session() as session:
            row = await session.get(PendingScreenshotState, phone)
            if row is not None:
                await session.delete(row)
    except ValueError:
        pass


_PENDING_TIMEZONE_TTL_HOURS = 24


async def set_pending_timezone_db(phone: str) -> None:
    expires_at = datetime.now(tz=UTC) + timedelta(hours=_PENDING_TIMEZONE_TTL_HOURS)
    try:
        async with get_session() as session:
            row = await session.get(PendingTimezoneState, phone)
            if row is None:
                session.add(PendingTimezoneState(phone=phone, expires_at=expires_at))
            else:
                row.expires_at = expires_at
    except ValueError:
        pass


async def is_pending_timezone_db(phone: str) -> bool:
    now = datetime.now(tz=UTC)
    try:
        async with get_session() as session:
            row = await session.get(PendingTimezoneState, phone)
            if row is None:
                return False
            if row.expires_at <= now:
                await session.delete(row)
                return False
            return True
    except ValueError:
        return False


async def clear_pending_timezone_db(phone: str) -> None:
    try:
        async with get_session() as session:
            row = await session.get(PendingTimezoneState, phone)
            if row is not None:
                await session.delete(row)
    except ValueError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Vision-call budget — per-phone hourly + global daily caps.
# ─────────────────────────────────────────────────────────────────────────────


async def count_vision_calls(phone: str | None, *, hours: int) -> int:
    """Count vision calls in the trailing window. None = global count."""
    since = datetime.now(tz=UTC) - timedelta(hours=hours)
    try:
        async with get_session() as session:
            stmt = select(func.count()).select_from(VisionCallLog).where(
                VisionCallLog.called_at >= since,
            )
            if phone is not None:
                stmt = stmt.where(VisionCallLog.phone == phone)
            result = await session.execute(stmt)
            return int(result.scalar() or 0)
    except ValueError:
        return 0  # no DB → fail-open in dev/no-storage mode


async def record_vision_call(phone: str, kind: str) -> None:
    try:
        async with get_session() as session:
            session.add(VisionCallLog(phone=phone, kind=kind))
    except ValueError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Two-phase webhook claim — true idempotency under Meta retry.
# ─────────────────────────────────────────────────────────────────────────────

_CLAIM_STALE_AFTER = timedelta(minutes=5)


async def claim_inbound_message(message_id: str) -> bool:
    """Atomic claim. Returns True iff we are the worker that should process.

    Semantics:
      * No row exists                              → INSERT (status=claimed). True.
      * Row exists, status='done'                  → already handled. False.
      * Row exists, status='claimed', fresh        → another worker has it. False.
      * Row exists, status='claimed', >5min stale  → reclaim (refresh). True.
    """
    if not message_id.strip():
        return False
    await _maybe_prune_security_tables()
    now = datetime.now(tz=UTC)
    try:
        async with get_session() as session:
            row = await session.get(ProcessedInboundMessage, message_id)
            if row is None:
                session.add(ProcessedInboundMessage(
                    message_id=message_id,
                    status="claimed",
                    claimed_at=now,
                    processed_at=now,
                ))
                try:
                    await session.flush()
                except IntegrityError:
                    await session.rollback()
                    return False  # another worker won the race
                return True
            if row.status == "done":
                return False
            if row.status == "claimed" and (now - row.claimed_at) > _CLAIM_STALE_AFTER:
                row.claimed_at = now
                return True
            return False
    except ValueError:
        if message_id in _FALLBACK_SEEN_MESSAGES:
            return False
        _FALLBACK_SEEN_MESSAGES.add(message_id)
        return True


async def complete_inbound_message(message_id: str) -> None:
    """Mark a claimed message as fully processed."""
    if not message_id.strip():
        return
    try:
        async with get_session() as session:
            row = await session.get(ProcessedInboundMessage, message_id)
            if row is not None:
                row.status = "done"
                row.processed_at = datetime.now(tz=UTC)
    except ValueError:
        pass
