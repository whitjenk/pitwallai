"""Compressed Monaco 2024 sample weekend for new subscribers."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

from loguru import logger

from intelligence.repository import get_subscriber
from onboarding.monaco_messages import (
    build_fp2_delta_message,
    build_sample_counterfactual_message,
    build_saturday_picks_message,
    build_sc_live_alert_message,
    build_welcome_context_message,
    lock_time_label,
    rehearsal_delays_seconds,
)
from openf1.client import OpenF1Client
from scheduler.calendar import get_next_race_weekend
from whatsapp.app_runtime import get_pick_runtime
from whatsapp.sender import mask_phone, send_message

_REHEARSAL_RUNNING: set[str] = set()
_rehearsal_user_active: dict[str, datetime] = {}


def notify_rehearsal_user_activity(phone: str) -> None:
    """Pause rehearsal pacing when the subscriber sends a real command."""
    _rehearsal_user_active[phone] = datetime.now(tz=UTC)


async def maybe_start_rehearsal(phone: str) -> bool:
    """
    Start sample weekend if first TEAM setup and next race is 5+ days away.

    Returns True when a rehearsal run was scheduled.
    """
    sub = await get_subscriber(phone)
    if sub is None or sub.rehearsal_complete:
        return False
    nxt = get_next_race_weekend(after=datetime.now(tz=UTC))
    if nxt is None:
        return False
    days = (nxt.race_utc - datetime.now(tz=UTC)).days
    if days <= 5:
        return False
    if phone in _REHEARSAL_RUNNING:
        return False
    _REHEARSAL_RUNNING.add(phone)
    asyncio.create_task(_run_rehearsal(phone, nxt.display_name, nxt.race_utc, sub.timezone))
    return True


async def _sleep_with_activity_pause(phone: str, seconds: float) -> None:
    """Sleep in chunks; extend delay if subscriber recently sent a command."""
    remaining = seconds
    while remaining > 0:
        active_at = _rehearsal_user_active.get(phone)
        if active_at and datetime.now(tz=UTC) - active_at < timedelta(minutes=2):
            await asyncio.sleep(min(60.0, remaining))
            remaining = max(0.0, remaining - 60.0)
            continue
        step = min(10.0, remaining)
        await asyncio.sleep(step)
        remaining -= step


async def _run_rehearsal(
    phone: str,
    next_race_name: str,
    next_race_utc: datetime,
    timezone: str,
) -> None:
    """Background Monaco 2024 walkthrough using OpenF1 session 9158."""
    from db.models import Subscriber
    from db.session import get_session

    fast = os.environ.get("PITWALL_REHEARSAL_FAST", "").strip() in {"1", "true", "yes"}
    delays = rehearsal_delays_seconds(fast=fast)
    runtime = get_pick_runtime(allow_lazy=True)
    client = OpenF1Client()

    try:
        await send_message(phone, build_welcome_context_message())

        await _sleep_with_activity_pause(phone, delays[0])
        await send_message(phone, build_fp2_delta_message(lock_label=lock_time_label(timezone)))

        await _sleep_with_activity_pause(phone, delays[1])
        if runtime is not None:
            picks_msg = await build_saturday_picks_message(phone, runtime, timezone=timezone)
        else:
            picks_msg = (
                "🎯 Saturday picks (Monaco 2024 sample)\n"
                "Service warming up — text PICKS on your first real race for live picks."
            )
        await send_message(phone, picks_msg)

        await _sleep_with_activity_pause(phone, delays[2])
        await send_message(phone, await build_sc_live_alert_message(client))

        await _sleep_with_activity_pause(phone, delays[3])
        await send_message(phone, build_sample_counterfactual_message())

        date_str = next_race_utc.astimezone(UTC).strftime("%d %b")
        await send_message(
            phone,
            f"That's a full PitWallAI race weekend!\n"
            f"Your first real race is {next_race_name} on {date_str}.\n"
            f"Text HELP for commands. Text TEAM to update your squad before then.",
        )
        async with get_session() as session:
            row = await session.get(Subscriber, phone)
            if row:
                row.rehearsal_complete = True
    except Exception as exc:
        logger.error("rehearsal failed phone={}: {}", mask_phone(phone), exc)
    finally:
        _REHEARSAL_RUNNING.discard(phone)
        _rehearsal_user_active.pop(phone, None)
