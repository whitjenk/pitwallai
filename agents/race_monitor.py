"""Agent 4 — Live Race Monitor (Sunday)."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from loguru import logger

from agents.base import AgentRunDependencies
from db.models import FantasyTeam
from intelligence.drivers import driver_code_for
from intelligence.repository import (
    can_send_live_alert,
    get_fantasy_team,
    get_monitor_state,
    list_live_alert_subscribers,
    load_seen_keys,
    record_live_alert_delivery,
    record_seen_key,
    save_race_event,
    set_monitor_state,
)
from openf1.client import OpenF1Client
from orchestrator.race_context import RaceEvent, RaceEventType, evolve_race_context, RaceContext
from whatsapp.message_format import LIVE_ALERT_MAX_CHARS
from whatsapp.sender import mask_phone, send_message

_POLL_INTERVAL_S = 15
_MAX_ALERTS_PER_HOUR = 3
_OPENF1_OUTAGE_POLLS = 3  # 3 × 15s without a successful poll

_seen_messages: dict[str, set[str]] = defaultdict(set)
_seen_pit_stops: dict[str, set[str]] = defaultdict(set)
_monitor_tasks: dict[str, asyncio.Task[None]] = {}


def _clear_runtime_state(race_key: str) -> None:
    """Release per-race in-memory caches after completion."""
    _seen_messages.pop(race_key, None)
    _seen_pit_stops.pop(race_key, None)


def _format_alert(text: str) -> str:
    msg = text.strip()
    if len(msg) > LIVE_ALERT_MAX_CHARS:
        msg = msg[: LIVE_ALERT_MAX_CHARS - 1] + "…"
    assert len(msg) <= LIVE_ALERT_MAX_CHARS
    return msg


def _classify_message(msg: str, lap: int | None, driver_number: int | None) -> RaceEventType | None:
    upper = msg.upper()
    if "RED FLAG" in upper:
        return RaceEventType.RED_FLAG
    if "VIRTUAL SAFETY CAR" in upper or "VSC" in upper:
        return RaceEventType.VIRTUAL_SC
    if "SAFETY CAR" in upper or "SC DEPLOYED" in upper:
        return RaceEventType.SAFETY_CAR
    if "RETIRED" in upper or "STOPPED" in upper:
        return RaceEventType.RETIREMENT
    return None


async def _subscriber_drivers(phone: str) -> set[str]:
    team = await get_fantasy_team(phone)
    if team is None:
        return set()
    return {c for c in (team.driver_1, team.driver_2, team.driver_3, team.driver_4, team.driver_5) if c}


def _chip_note(team: FantasyTeam, driver_code: str) -> str:
    from fantasy.rules import CHIP_NAMES_2026, chip_available

    available = [c for c in CHIP_NAMES_2026 if chip_available(team.chips_used or {}, c)]
    if not available:
        return ""
    return f" Pit window open if considering {available[0]} chip."


async def _broadcast_alert(
    race_key: str,
    message: str,
    *,
    affected_driver: str | None = None,
) -> None:
    subs = await list_live_alert_subscribers()
    for sub in subs:
        if not await can_send_live_alert(
            race_key,
            sub.phone,
            per_hour_limit=_MAX_ALERTS_PER_HOUR,
        ):
            continue
        if affected_driver:
            drivers = await _subscriber_drivers(sub.phone)
            if affected_driver not in drivers:
                continue
        try:
            await send_message(sub.phone, _format_alert(message))
            await record_live_alert_delivery(race_key, sub.phone)
        except Exception as exc:
            logger.error("Live alert failed phone={}: {}", mask_phone(sub.phone), exc)


async def _race_complete(client: OpenF1Client, session_key: int) -> bool:
    """Heuristic: race finished when classified results exist."""
    results = await client.get_session_results(session_key)
    if results and sum(1 for r in results if r.position is not None) >= 15:
        return True
    positions = await client.get_positions(session_key)
    by_driver = {p.driver_number for p in positions if p.position is not None}
    return len(by_driver) >= 18


async def _rehydrate_dedup(race_key: str) -> None:
    """Rehydrate dedup ledgers from Postgres into the in-memory sets.

    Called once at monitor start so a Railway restart mid-race doesn't
    re-broadcast events we already processed pre-restart. The in-memory
    sets remain the hot path; the DB is the durable mirror. Failures
    here are logged but never raise — the monitor must keep running.
    """
    try:
        persisted_msgs = await load_seen_keys(race_key, "msg")
        persisted_pits = await load_seen_keys(race_key, "pit")
        if persisted_msgs:
            _seen_messages[race_key].update(persisted_msgs)
        if persisted_pits:
            _seen_pit_stops[race_key].update(persisted_pits)
        logger.bind(
            race_key=race_key,
            msgs=len(persisted_msgs),
            pits=len(persisted_pits),
        ).info("monitor_dedup_rehydrated")
    except Exception as exc:
        logger.warning("monitor_dedup_rehydrate_failed race_key={}: {}", race_key, exc)


async def _poll_loop(
    ctx: RaceContext,
    deps: AgentRunDependencies,
    session_key: int,
) -> None:
    """15s poll loop until race completion."""
    race_key = ctx.race_weekend.race_key
    client = deps.openf1_client
    last_rain: bool | None = None

    await _rehydrate_dedup(race_key)

    logger.bind(race_key=race_key, session_key=session_key).info("Agent 4 race monitor started")

    poll_failures = 0
    while True:
        try:
            messages = await client.get_race_control(session_key)
            poll_failures = 0
            await set_monitor_state(
                race_key,
                session_key=session_key,
                last_lap=0,
                running=True,
                consecutive_poll_failures=0,
                data_unavailable=False,
            )
            for row in messages:
                msg = row.message or ""
                msg_id = f"{row.date}:{msg[:40]}"
                if msg_id in _seen_messages[race_key]:
                    continue
                _seen_messages[race_key].add(msg_id)
                await record_seen_key(race_key, "msg", msg_id)

                event_type = _classify_message(msg, row.lap_number, row.driver_number)
                if event_type is None:
                    continue

                driver_code = (
                    driver_code_for(row.driver_number) if row.driver_number else None
                )
                lap = row.lap_number
                desc = msg[:180]

                event = RaceEvent(
                    race_key=race_key,
                    event_type=event_type,
                    lap=lap,
                    description=desc,
                    utc_timestamp=row.date or datetime.now(tz=UTC),
                    driver_code=driver_code,
                    decoded_at_utc=datetime.now(tz=UTC),
                )
                await save_race_event(event)

                if event_type == RaceEventType.SAFETY_CAR:
                    text = f"🟡 SC deployed lap {lap or '?'} — {desc[:80]}"
                elif event_type == RaceEventType.VIRTUAL_SC:
                    text = f"🟡 VSC lap {lap or '?'} — {desc[:80]}"
                elif event_type == RaceEventType.RED_FLAG:
                    text = f"🔴 Red flag lap {lap or '?'} — {desc[:80]}"
                elif event_type == RaceEventType.RETIREMENT:
                    text = f"{driver_code or 'Driver'} retired lap {lap or '?'} — observation only."
                else:
                    text = desc[:120]

                await _broadcast_alert(race_key, text, affected_driver=driver_code)

            weather = await client.get_weather(session_key)
            raining = any(bool(w.rainfall) for w in weather if w.rainfall is not None)
            if last_rain is not None and raining != last_rain:
                await _broadcast_alert(
                    race_key,
                    f"Weather update: rainfall {'detected' if raining else 'cleared'} (OpenF1).",
                )
            last_rain = raining

            pits = await client.get_pit_stops(session_key)
            for pit in pits:
                pit_key = f"{pit.driver_number}:{pit.lap_number}"
                if pit_key in _seen_pit_stops[race_key]:
                    continue
                _seen_pit_stops[race_key].add(pit_key)
                await record_seen_key(race_key, "pit", pit_key)
                code = driver_code_for(pit.driver_number)
                await _broadcast_alert(
                    race_key,
                    f"⚡ {code} just pitted. Pit window activity observed lap {pit.lap_number or '?'}.",
                    affected_driver=code,
                )
                subs = await list_live_alert_subscribers()
                for sub in subs:
                    team = await get_fantasy_team(sub.phone)
                    if team is None:
                        continue
                    drivers = await _subscriber_drivers(sub.phone)
                    if code in drivers and await can_send_live_alert(
                        race_key,
                        sub.phone,
                        per_hour_limit=_MAX_ALERTS_PER_HOUR,
                    ):
                        note = _chip_note(team, code)
                        if note:
                            await send_message(
                                sub.phone,
                                _format_alert(f"⚡ {code} just pitted.{note}"),
                            )
                            await record_live_alert_delivery(race_key, sub.phone)

            if await _race_complete(client, session_key):
                complete = RaceEvent(
                    race_key=race_key,
                    event_type=RaceEventType.RACE_COMPLETE,
                    lap=None,
                    description="Race classification complete",
                    utc_timestamp=datetime.now(tz=UTC),
                )
                await save_race_event(complete)
                await set_monitor_state(race_key, session_key=session_key, last_lap=0, running=False)
                logger.bind(race_key=race_key).info("Agent 4 race complete — stopping monitor")
                from orchestrator.lead_strategist import LeadStrategist

                await LeadStrategist(deps).run_scorer_and_learner(race_key)
                _clear_runtime_state(race_key)
                return

            await set_monitor_state(
                race_key,
                session_key=session_key,
                last_lap=0,
                running=True,
            )
        except Exception as exc:
            poll_failures += 1
            unavailable = poll_failures >= _OPENF1_OUTAGE_POLLS
            logger.exception(
                "Race monitor poll error race_key={} failures={} unavailable={}: {}",
                race_key,
                poll_failures,
                unavailable,
                exc,
            )
            try:
                await set_monitor_state(
                    race_key,
                    session_key=session_key,
                    last_lap=0,
                    running=True,
                    consecutive_poll_failures=poll_failures,
                    data_unavailable=unavailable,
                )
            except Exception as state_exc:
                logger.warning(
                    "monitor_state update failed race_key={}: {}",
                    race_key,
                    state_exc,
                )

        await asyncio.sleep(_POLL_INTERVAL_S)


async def run_race_monitor(
    ctx: RaceContext,
    deps: AgentRunDependencies,
) -> RaceContext:
    """Start or resume the live race monitor background task."""
    race_key = ctx.race_weekend.race_key
    if race_key in _monitor_tasks and not _monitor_tasks[race_key].done():
        logger.info("Race monitor already running race_key={}", race_key)
        return ctx

    client = deps.openf1_client
    try:
        session_key = await client.find_session_key(
            year=2026,
            circuit_short_name=ctx.circuit_profile.openf1_circuit_name,
            session_name="Race",
        )
    except Exception as exc:
        logger.error("Race session lookup failed race_key={}: {}", race_key, exc)
        return ctx
    if session_key is None:
        logger.error("Race session not found race_key={}", race_key)
        return ctx

    state = await get_monitor_state(race_key)
    if state and not state.running:
        logger.info("Race monitor already completed race_key={}", race_key)
        _clear_runtime_state(race_key)
        return ctx

    task = asyncio.create_task(_poll_loop(ctx, deps, session_key), name=f"monitor:{race_key}")
    _monitor_tasks[race_key] = task
    return ctx


async def resume_monitors_on_startup(deps: AgentRunDependencies) -> None:
    """Resume in-progress monitors after Railway restart."""
    from orchestrator.context_store import get_context
    from scheduler.calendar import CALENDAR_2026, get_race_weekend
    from circuits.profiles import get_circuit_profile
    from scheduler.calendar import profile_circuit_key
    from orchestrator.race_context import initial_race_context

    now = datetime.now(tz=UTC)
    for weekend in CALENDAR_2026:
        if weekend.race_utc < now - timedelta(hours=6):
            continue
        if weekend.race_utc > now + timedelta(hours=1):
            continue
        state = await get_monitor_state(weekend.race_key)
        if state is None or not state.running:
            continue
        ctx = get_context(weekend.race_key)
        if ctx is None:
            profile = get_circuit_profile(profile_circuit_key(weekend.circuit_key))
            if profile is None:
                continue
            ctx = initial_race_context(weekend, profile)
        logger.bind(race_key=weekend.race_key).info("Resuming race monitor after restart")
        await run_race_monitor(ctx, deps)
