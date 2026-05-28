"""Resolve the active F1 race weekend from OpenF1 or configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from circuits.profiles import CircuitProfile, get_circuit_profile
from intelligence.context import OrchestratorContext
from openf1.client import OpenF1Client
from openf1.models import SessionInfo

_RACE_LOOKBACK = timedelta(days=4)
_RACE_LOOKAHEAD = timedelta(days=10)


@dataclass(frozen=True, slots=True)
class ActiveWeekend:
    """Active or upcoming Grand Prix weekend metadata."""

    circuit_key: str
    display_name: str
    openf1_circuit_name: str
    year: int
    race_session_key: int | None
    qualifying_session_key: int | None
    meeting_key: int | None
    race_start: datetime | None

    @property
    def race_key(self) -> str:
        """Stable key for picks audit log (e.g. 2026_monaco)."""
        return f"{self.year}_{self.circuit_key}"


def _profile_for_openf1_name(
    ctx: OrchestratorContext,
    circuit_short_name: str | None,
) -> CircuitProfile | None:
    if not circuit_short_name:
        return None
    return ctx.get_circuit(circuit_short_name)


def _score_race_session(session: SessionInfo, now: datetime) -> float | None:
    """Lower score is better — prefer in-window races closest to now."""
    if session.date_start is None:
        return None
    start = session.date_start
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    delta = (start - now).total_seconds()
    if delta < -_RACE_LOOKBACK.total_seconds():
        return None
    if delta > _RACE_LOOKAHEAD.total_seconds():
        return None
    return abs(delta)


async def resolve_active_weekend(
    client: OpenF1Client,
    ctx: OrchestratorContext,
    *,
    year: int,
    circuit_key_override: str | None = None,
) -> ActiveWeekend:
    """
    Resolve the active race weekend.

    Uses PITWALL_CIRCUIT_KEY when set; otherwise picks the OpenF1 Race session
    whose start time is nearest to now within the lookback/lookahead window.

    Args:
        client: OpenF1 client.
        ctx: Startup-loaded orchestrator context (circuit profiles).
        year: Championship year.
        circuit_key_override: Optional forced circuit_key.

    Returns:
        ActiveWeekend metadata.

    Raises:
        ValueError: When no circuit can be resolved.
    """
    if circuit_key_override:
        profile = get_circuit_profile(circuit_key_override)
        if profile is None:
            raise ValueError(f"Unknown circuit_key: {circuit_key_override}")
        race_key = await client.find_session_key(
            year=year,
            circuit_short_name=profile.openf1_circuit_name,
            session_name="Race",
        )
        qual_key = await client.find_session_key(
            year=year,
            circuit_short_name=profile.openf1_circuit_name,
            session_name="Qualifying",
        )
        meeting_key: int | None = None
        race_start: datetime | None = None
        if race_key is not None:
            sessions = await client.get_sessions(
                year=year,
                circuit_short_name=profile.openf1_circuit_name,
                session_name="Race",
            )
            if sessions:
                meeting_key = sessions[0].meeting_key
                race_start = sessions[0].date_start
        return ActiveWeekend(
            circuit_key=profile.circuit_key,
            display_name=profile.display_name,
            openf1_circuit_name=profile.openf1_circuit_name,
            year=year,
            race_session_key=race_key,
            qualifying_session_key=qual_key,
            meeting_key=meeting_key,
            race_start=race_start,
        )

    now = datetime.now(tz=UTC)
    races = await client.get_sessions(year=year, session_name="Race")
    best: SessionInfo | None = None
    best_score: float | None = None

    for session in races:
        score = _score_race_session(session, now)
        if score is None:
            continue
        if best_score is None or score < best_score:
            best_score = score
            best = session

    if best is None and races:
        # Off-season: use the next upcoming race
        upcoming = [s for s in races if s.date_start and s.date_start >= now]
        upcoming.sort(key=lambda s: s.date_start or now)
        best = upcoming[0] if upcoming else races[-1]

    if best is None:
        raise ValueError(f"No Race sessions found for year {year}")

    profile = _profile_for_openf1_name(ctx, best.circuit_short_name)
    if profile is None:
        raise ValueError(
            f"No circuit profile for OpenF1 circuit {best.circuit_short_name!r}"
        )

    qual_key = await client.find_session_key(
        year=year,
        circuit_short_name=profile.openf1_circuit_name,
        session_name="Qualifying",
    )

    return ActiveWeekend(
        circuit_key=profile.circuit_key,
        display_name=profile.display_name,
        openf1_circuit_name=profile.openf1_circuit_name,
        year=year,
        race_session_key=best.session_key,
        qualifying_session_key=qual_key,
        meeting_key=best.meeting_key,
        race_start=best.date_start,
    )
