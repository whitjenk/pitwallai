"""Inbound WhatsApp text command handlers."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from db.models import Subscriber
from db.session import get_session
from intelligence.repository import (
    get_league_onboarding_state,
    get_onboarding_state,
    update_subscriber_preferences,
)
from whatsapp.league_flow import handle_league_command
from whatsapp.sender import send_message
from whatsapp.team_flow import handle_team_command

_SETTINGS_URL = "https://pitwallai.app/settings"

# Phones awaiting timezone after SUBSCRIBE (in-memory; single-instance OK for MVP).
_pending_timezone: set[str] = set()


def _truncate(msg: str, limit: int = 160) -> str:
    """Ensure outbound text fits WhatsApp short-message UX."""
    if len(msg) <= limit:
        return msg
    return msg[: limit - 3] + "..."


def _is_valid_iana_timezone(tz_name: str) -> bool:
    """
    Validate an IANA timezone string.

    Args:
        tz_name: Candidate timezone (e.g. Europe/London).

    Returns:
        True if recognized by zoneinfo.
    """
    try:
        ZoneInfo(tz_name.strip())
        return True
    except ZoneInfoNotFoundError:
        return False


async def _handle_subscribe(phone: str) -> str:
    """
    Start or continue SUBSCRIBE flow.

    Args:
        phone: E.164 sender phone.

    Returns:
        Outbound reply text (<=160 chars).
    """
    async with get_session() as session:
        existing = await session.get(Subscriber, phone)
        if existing and existing.active:
            return _truncate(f"Already subscribed ({existing.timezone}). Send UNSUBSCRIBE to stop.")

    _pending_timezone.add(phone)
    return _truncate("PitWallAI: reply with your IANA timezone (e.g. Europe/London or America/New_York).")


async def _complete_subscribe(phone: str, timezone: str) -> str:
    """
    Store subscriber after timezone is provided.

    Args:
        phone: E.164 sender phone.
        timezone: IANA timezone string.

    Returns:
        Outbound confirmation text.
    """
    if not _is_valid_iana_timezone(timezone):
        return _truncate("Unknown timezone. Use IANA format, e.g. Europe/London.")

    _pending_timezone.discard(phone)
    tz_clean = timezone.strip()

    async with get_session() as session:
        row = await session.get(Subscriber, phone)
        if row is None:
            row = Subscriber(phone=phone, timezone=tz_clean, preferred_provider="gemini", active=True)
            session.add(row)
        else:
            row.timezone = tz_clean
            row.active = True
            row.preferred_provider = row.preferred_provider or "gemini"

    logger.bind(phone=phone, timezone=tz_clean).info("Subscriber activated")
    return _truncate(
        f"Subscribed ({tz_clean}). Text LIVE ON for race alerts. "
        "Text CADENCE RACEDAY for picks only. HELP for commands."
    )


async def _handle_unsubscribe(phone: str) -> str:
    """
    Soft-delete subscriber (active=False).

    Args:
        phone: E.164 sender phone.

    Returns:
        Outbound reply text.
    """
    async with get_session() as session:
        row = await session.get(Subscriber, phone)
        if row is None or not row.active:
            return _truncate("Not subscribed. Send SUBSCRIBE to get race alerts.")
        row.active = False

    _pending_timezone.discard(phone)
    logger.bind(phone=phone).info("Subscriber deactivated")
    return _truncate("Unsubscribed. You won't receive alerts. Send SUBSCRIBE to rejoin.")


def _handle_help() -> str:
    """Return command list."""
    return _truncate(
        "SUBSCRIBE · UNSUBSCRIBE · TEAM · LEAGUE · LEAGUE UPDATE · LIVE ON/OFF · "
        "CADENCE FULL/RACEDAY · HELP · SETTINGS"
    )


def _handle_settings() -> str:
    """Return BYOK settings link."""
    return _truncate(f"Manage API keys & provider: {_SETTINGS_URL}")


async def _handle_live(phone: str, *, enabled: bool) -> str:
    """Toggle live race day alerts."""
    row = await update_subscriber_preferences(phone, live_alerts=enabled)
    if row is None:
        return _truncate("Subscribe first: text SUBSCRIBE")
    if enabled:
        return _truncate("✅ Race day alerts on. You'll get live updates during Sunday's race.")
    return _truncate("✅ Race day alerts off. Picks only.")


async def _handle_cadence(phone: str, *, mode: str) -> str:
    """Set notification cadence preference."""
    row = await update_subscriber_preferences(phone, cadence_preference=mode)
    if row is None:
        return _truncate("Subscribe first: text SUBSCRIBE")
    if mode == "FULL":
        return _truncate(
            "✅ Full weekend mode. Practice summary, quali picks, live alerts, post-race recap."
        )
    return _truncate("✅ Race day only. Saturday picks and live alerts (if LIVE ON).")


async def handle_inbound_text(phone: str, text: str, raw_text: str) -> None:
    """
    Route an inbound text message to the appropriate command handler.

    Sends the response via Meta Cloud API. Swallows send errors after logging.

    Args:
        phone: E.164 sender phone.
        text: Uppercased message body for command matching.
        raw_text: Original message body (for timezone capture).
    """
    reply: str

    try:
        onboarding = await get_onboarding_state(phone)
        league_state = await get_league_onboarding_state(phone)
        in_team_flow = onboarding is not None and (
            onboarding.awaiting_confirm or onboarding.step > 0
        )
        in_league_flow = league_state is not None and (
            league_state.awaiting_confirm or league_state.step > 0 or league_state.update_mode
        )

        if phone in _pending_timezone and text not in {
            "SUBSCRIBE",
            "UNSUBSCRIBE",
            "HELP",
            "SETTINGS",
            "TEAM",
        }:
            reply = await _complete_subscribe(phone, raw_text)
        elif in_team_flow and text != "TEAM":
            reply = await handle_team_command(phone, text, raw_text)
        elif in_league_flow and text not in {"LEAGUE", "LEAGUE UPDATE"}:
            reply = await handle_league_command(phone, text, raw_text)
        elif text == "TEAM":
            reply = await handle_team_command(phone, text, raw_text)
        elif text in {"LEAGUE", "LEAGUE UPDATE"}:
            reply = await handle_league_command(phone, text, raw_text)
        elif text == "SUBSCRIBE":
            reply = await _handle_subscribe(phone)
        elif text == "UNSUBSCRIBE":
            reply = await _handle_unsubscribe(phone)
        elif text == "HELP":
            reply = _handle_help()
        elif text == "SETTINGS":
            reply = _handle_settings()
        elif text == "LIVE ON":
            reply = await _handle_live(phone, enabled=True)
        elif text == "LIVE OFF":
            reply = await _handle_live(phone, enabled=False)
        elif text == "CADENCE FULL":
            reply = await _handle_cadence(phone, mode="FULL")
        elif text in {"CADENCE RACEDAY", "CADENCE RACE_DAY_ONLY"}:
            reply = await _handle_cadence(phone, mode="RACE_DAY_ONLY")
        else:
            reply = _truncate("Unknown command. Send HELP for options.")
    except ValueError as exc:
        logger.error("Command handler config error phone={}: {}", phone, exc)
        reply = _truncate("Service unavailable. Try again later.")
    except Exception as exc:
        logger.exception("Command handler error phone={}: {}", phone, exc)
        reply = _truncate("Something went wrong. Send HELP or try later.")

    try:
        await send_message(phone, reply)
    except Exception as exc:
        logger.error("Failed to send WhatsApp reply phone={}: {}", phone, exc)
