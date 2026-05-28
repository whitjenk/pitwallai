"""Database persistence for practice signals and picks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from db.models import FantasyTeam, PickRow, PracticeSignalRow, SeasonAccuracy, Subscriber, TeamOnboardingState
from db.session import get_session
from intelligence.schemas import PickOutput, PracticeSignal


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
