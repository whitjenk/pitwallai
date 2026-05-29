"""SUBSCRIBE / UNSUBSCRIBE flows (shared by inbound handler and command router)."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from db.models import Subscriber
from db.session import get_session
from pitwallai.feature_flags import screenshot_onboarding_enabled
from whatsapp.sender import mask_phone
from whatsapp.timezone_infer import infer_timezone

pending_timezone: set[str] = set()
pending_screenshot: set[str] = set()

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

_SCREENSHOT_PROMPT = (
    "Open F1 Fantasy → take a screenshot of your team → send it here.\n\n"
    "I'll pull out your 5 drivers, constructors, budget, and transfers — "
    "no typing required. Image is read once, not stored.\n\n"
    "(Or text your 5 driver codes if you'd rather.)"
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


async def handle_subscribe(phone: str) -> list[str]:
    async with get_session() as session:
        existing = await session.get(Subscriber, phone)
        if existing and existing.active:
            return [truncate(
                f"Already subscribed ({existing.timezone}). Send UNSUBSCRIBE to stop."
            )]

        # Infer timezone from phone country code — skip the ask for the 95% case.
        inferred_tz = infer_timezone(phone)
        is_first = existing is None
        if existing is None:
            session.add(Subscriber(
                phone=phone, timezone=inferred_tz, preferred_provider="gemini", active=True,
            ))
        else:
            existing.timezone = inferred_tz
            existing.active = True
            existing.preferred_provider = existing.preferred_provider or "gemini"

    logger.bind(phone=mask_phone(phone), timezone=inferred_tz).info("Subscriber activated (inferred tz)")

    out: list[str] = []
    if is_first:
        out.append(truncate(_SUBSCRIBE_DATA_NOTE))
    out.append(_SUBSCRIBE_CONFIRM)
    if screenshot_onboarding_enabled():
        pending_screenshot.add(phone)
        out.append(_SCREENSHOT_PROMPT)
    return out


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
