"""SUBSCRIBE / UNSUBSCRIBE flows (shared by inbound handler and command router)."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from db.models import Subscriber
from db.session import get_session
from whatsapp.sender import mask_phone

pending_timezone: set[str] = set()

_SUBSCRIBE_DATA_NOTE = (
    "📋 Data note: PitWallAI stores your phone number and "
    "timezone to send picks. No data is sold or shared. "
    "Text DELETE anytime to remove your data."
)

_SUBSCRIBE_CONFIRM = (
    "✅ Subscribed to PitWallAI 🏁\n\n"
    "Picks arrive Saturday before lock. Text HELP for commands.\n\n"
    "⚠️ Independent fan tool. Not affiliated with F1 Fantasy, "
    "ESPN, or Formula 1. All picks are informational only — "
    "never financial or gaming advice. You decide."
)


def truncate(msg: str, limit: int = 160) -> str:
    if len(msg) <= limit:
        return msg
    return msg[: limit - 3] + "..."


def is_valid_iana_timezone(tz_name: str) -> bool:
    try:
        ZoneInfo(tz_name.strip())
        return True
    except ZoneInfoNotFoundError:
        return False


async def handle_subscribe(phone: str) -> str:
    async with get_session() as session:
        existing = await session.get(Subscriber, phone)
        if existing and existing.active:
            return truncate(
                f"Already subscribed ({existing.timezone}). Send UNSUBSCRIBE to stop."
            )

    pending_timezone.add(phone)
    return truncate(
        "PitWallAI: reply with your IANA timezone (e.g. Europe/London or America/New_York)."
    )


async def complete_subscribe(phone: str, timezone: str) -> list[str]:
    if not is_valid_iana_timezone(timezone):
        return [truncate("Unknown timezone. Use IANA format, e.g. Europe/London.")]

    pending_timezone.discard(phone)
    tz_clean = timezone.strip()

    async with get_session() as session:
        row = await session.get(Subscriber, phone)
        is_first = row is None
        if row is None:
            row = Subscriber(phone=phone, timezone=tz_clean, preferred_provider="gemini", active=True)
            session.add(row)
        else:
            row.timezone = tz_clean
            row.active = True
            row.preferred_provider = row.preferred_provider or "gemini"

    logger.bind(phone=mask_phone(phone), timezone=tz_clean).info("Subscriber activated")
    outbound: list[str] = []
    if is_first:
        outbound.append(truncate(_SUBSCRIBE_DATA_NOTE))
    outbound.append(_SUBSCRIBE_CONFIRM)
    return outbound


async def handle_unsubscribe(phone: str) -> str:
    async with get_session() as session:
        row = await session.get(Subscriber, phone)
        if row is None or not row.active:
            return truncate("Not subscribed. Send SUBSCRIBE to get race alerts.")
        row.active = False

    pending_timezone.discard(phone)
    logger.bind(phone=mask_phone(phone)).info("Subscriber deactivated")
    return truncate("Unsubscribed. You won't receive alerts. Send SUBSCRIBE to rejoin.")
