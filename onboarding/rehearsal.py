"""Compressed Monaco 2024 sample weekend for new subscribers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from loguru import logger

from intelligence.repository import get_subscriber
from scheduler.calendar import get_next_race_weekend
from whatsapp.sender import mask_phone, send_message

_REHEARSAL_RUNNING: set[str] = set()


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
    asyncio.create_task(_run_rehearsal(phone, nxt.display_name, nxt.race_utc))
    return True


async def _run_rehearsal(phone: str, next_race_name: str, next_race_utc: datetime) -> None:
    """Background compressed Monaco 2024 walkthrough (historical data)."""
    from db.session import get_session
    from db.models import Subscriber

    try:
        await send_message(
            phone,
            "🏁 Welcome to PitWallAI!\n"
            "Before your first real race, here's a sample weekend (Monaco 2024 — historical).\n"
            "FP2 signals, Saturday picks, live alert, and post-race recap follow.",
        )
        await asyncio.sleep(15 * 60)
        await send_message(
            phone,
            "📻 FP2 signal update (Monaco 2024 sample)\n\n"
            "NOR strong practice signal in FP2.\n"
            "LEC anomaly flag: pace deficit vs teammate in FP2.\n"
            "Saturday pick still shows LEC — consider reviewing before lock.",
        )
        await asyncio.sleep(30 * 60)
        await send_message(
            phone,
            "🎯 Saturday picks (Monaco 2024 sample)\n"
            "Personalised swap example based on your squad — historical quali grid applied.",
        )
        await asyncio.sleep(45 * 60)
        await send_message(
            phone,
            "🚨 Live alert (Monaco 2024 sample)\n"
            "Safety Car deployed lap 32 — observed from race replay data.",
        )
        await asyncio.sleep(30 * 60)
        await send_message(
            phone,
            "📊 Monaco 2024 sample recap\n\n"
            "2/3 picks scored this weekend.\n"
            "Season GP hit rate builds from your real races.\n"
            "Full recap format arrives after each real Sunday race.",
        )
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
