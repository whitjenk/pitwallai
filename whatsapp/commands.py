"""Inbound WhatsApp text command handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from db.models import Subscriber
from db.session import get_session
from intelligence.repository import (
    add_user_reported_price_change,
    erase_subscriber_data,
    get_league_onboarding_state,
    get_onboarding_state,
    get_price_prediction_map,
    set_subscriber_share_private,
    update_subscriber_preferences,
)
from whatsapp.sender import mask_phone
from intelligence.season_recap import build_season_recap
from scheduler.calendar import CALENDAR_2026, get_next_race_weekend
from whatsapp.league_flow import handle_league_command
from whatsapp.message_format import format_season_recap_message
from whatsapp.sender import send_message as _send_message
from whatsapp.team_flow import handle_team_command

_SETTINGS_URL = "https://pitwallai.app/settings"
_SEASON_SHARE_BASE_URL = "https://pitwallai.app"

# Phones awaiting timezone after SUBSCRIBE (in-memory; single-instance OK for MVP).
_pending_timezone: set[str] = set()

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


async def _complete_subscribe(phone: str, timezone: str) -> list[str]:
    """
    Store subscriber after timezone is provided.

    Args:
        phone: E.164 sender phone.
        timezone: IANA timezone string.

    Returns:
        Outbound messages (data note on first subscribe, then confirmation).
    """
    if not _is_valid_iana_timezone(timezone):
        return [_truncate("Unknown timezone. Use IANA format, e.g. Europe/London.")]

    _pending_timezone.discard(phone)
    tz_clean = timezone.strip()

    async with get_session() as session:
        row = await session.get(Subscriber, phone)
        is_first_subscribe = row is None
        if row is None:
            row = Subscriber(phone=phone, timezone=tz_clean, preferred_provider="gemini", active=True)
            session.add(row)
        else:
            row.timezone = tz_clean
            row.active = True
            row.preferred_provider = row.preferred_provider or "gemini"

    logger.bind(phone=mask_phone(phone), timezone=tz_clean).info("Subscriber activated")
    outbound: list[str] = []
    if is_first_subscribe:
        outbound.append(_truncate(_SUBSCRIBE_DATA_NOTE))
    outbound.append(_SUBSCRIBE_CONFIRM)
    return outbound


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


async def _handle_delete(phone: str) -> str:
    """Erase subscriber data after explicit DELETE request."""
    deleted = await erase_subscriber_data(phone)
    _pending_timezone.discard(phone)
    if deleted:
        logger.bind(phone=mask_phone(phone)).info("Subscriber data erased (DELETE command)")
    else:
        logger.bind(phone=mask_phone(phone)).info("DELETE command: no subscriber row found")
    return _truncate(
        "✅ All your data has been deleted. Sorry to see you go. "
        "Text SUBSCRIBE anytime to rejoin."
    )


def _handle_help() -> str:
    """Return command list."""
    return _truncate(
        "SUBSCRIBE · UNSUBSCRIBE · DELETE · TEAM · LEAGUE · PICKS · CHIPS · TRANSFERS · "
        "BUDGET · PRIVATE · PRICE · WHY · SEASON · SHARE · LIVE ON/OFF · CADENCE · HELP",
        300,
    )


def _app_deps():
    """FastAPI app + settings when scheduler context is registered."""
    try:
        from scheduler.jobs import _require_ctx

        app = _require_ctx().app
        return app, app.state.settings
    except RuntimeError:
        return None, None


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


def _last_race_key() -> str | None:
    now = datetime.now(tz=UTC)
    completed = [w for w in CALENDAR_2026 if w.race_utc <= now]
    if not completed:
        return None
    return max(completed, key=lambda w: w.race_utc).race_key


def _next_race_key() -> str | None:
    nxt = get_next_race_weekend(after=datetime.now(tz=UTC))
    return nxt.race_key if nxt else None


async def _handle_price_report(phone: str, raw_text: str) -> str:
    parts = raw_text.strip().split()
    if len(parts) != 3:
        return _truncate("Use: PRICE NOR +0.2")
    _, code, delta_raw = parts
    code = code.strip().upper()
    try:
        delta = float(delta_raw)
    except ValueError:
        return _truncate("Use numeric change like +0.2 or -0.1")
    race_key = _last_race_key()
    if race_key is None:
        return _truncate("No completed race found yet for price reports.")
    await add_user_reported_price_change(
        driver_code=code,
        race_key=race_key,
        reported_change=delta,
        reporter_phone=phone,
    )
    return _truncate("Thanks! Helps improve predictions.")


async def _handle_why(raw_text: str) -> str:
    parts = raw_text.strip().split()
    if len(parts) != 2:
        return _truncate("Use: WHY NOR")
    _, code = parts
    code = code.strip().upper()
    race_key = _next_race_key()
    if race_key is None:
        return _truncate("No upcoming race found.")
    preds = await get_price_prediction_map(race_key)
    pred = preds.get(code)
    if pred is None:
        return _truncate(f"No prediction yet for {code}.")
    bd = pred.signal_breakdown or {}
    lines = [
        f"{code}: likely {pred.predicted_direction} (${pred.predicted_magnitude:.1f}M), conf {pred.confidence:.2f}",
    ]
    for key in ("momentum", "value_ratio", "circuit_hist", "practice_align", "ownership_pressure"):
        seg = bd.get(key) or {}
        if not seg:
            continue
        lines.append(f"{key}: {seg.get('score', 0):+.2f} × {seg.get('weight', 0):.2f}")
    return _truncate(" | ".join(lines), limit=300)


def _season_share_secret() -> str:
    from whatsapp.settings import get_whatsapp_settings

    settings = get_whatsapp_settings()
    # Prefer app secret; fallback to verify token for local/dev continuity.
    if settings.whatsapp_app_secret.strip():
        return settings.whatsapp_app_secret.strip()
    if settings.webhook_verify_token.strip():
        return settings.webhook_verify_token.strip()
    return "pitwallai-season-share-local-secret"


async def _handle_season(phone: str, *, compact: bool = False) -> str:
    recap = await build_season_recap(
        phone=phone,
        season=2026,
        share_base_url=_SEASON_SHARE_BASE_URL,
        share_secret=_season_share_secret(),
    )
    message = format_season_recap_message(
        season=recap.season,
        personalized_accuracy_pct=recap.personalized_accuracy_pct,
        community_accuracy_pct=recap.community_accuracy_pct,
        best_call=recap.best_call,
        worst_call=recap.worst_call,
        biggest_signal=recap.biggest_signal,
        share_url=recap.share_url,
    )
    if not compact:
        return message
    # "SHARE" returns a cleaner copy-paste block for cross-platform posting.
    return "\n".join(
        [
            "🏁 PitWallAI season recap",
            f"My GP picks: {recap.personalized_accuracy_pct:.0f}% hit rate (race results)",
            f"Community GP hit rate: {recap.community_accuracy_pct:.0f}%",
            f"Best call: {recap.best_call}",
            f"Worst call: {recap.worst_call}",
            f"Biggest signal: {recap.biggest_signal}",
            recap.share_url,
        ]
    )


async def handle_inbound_text(phone: str, text: str, raw_text: str) -> None:
    """
    Route an inbound text message to the appropriate command handler.

    Sends the response via Meta Cloud API. Swallows send errors after logging.

    Args:
        phone: E.164 sender phone.
        text: Uppercased message body for command matching.
        raw_text: Original message body (for timezone capture).
    """
    reply: str | list[str]

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
        elif text.startswith("PRICE "):
            reply = await _handle_price_report(phone, raw_text)
        elif text.startswith("WHY "):
            reply = await _handle_why(raw_text)
        elif text == "SEASON":
            reply = await _handle_season(phone, compact=False)
        elif text == "SHARE":
            reply = await _handle_season(phone, compact=True)
        elif text == "SUBSCRIBE":
            reply = await _handle_subscribe(phone)
        elif text == "UNSUBSCRIBE":
            reply = await _handle_unsubscribe(phone)
        elif text == "DELETE":
            reply = await _handle_delete(phone)
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
        elif text == "PICKS":
            from whatsapp.phase7 import send_picks_on_demand

            app, settings = _app_deps()
            if app is None:
                reply = _truncate("PICKS unavailable — service starting up.")
            else:
                from openf1.client import OpenF1Client

                reply = await send_picks_on_demand(
                    phone,
                    client=OpenF1Client(),
                    app=app,
                    settings=settings,
                )
        elif text == "CHIPS":
            from whatsapp.phase7 import send_chips_summary

            reply = await send_chips_summary(phone)
        elif text.startswith("CHIPS "):
            from whatsapp.phase7 import send_chip_detail

            chip = raw_text.strip().split(maxsplit=1)[1] if len(raw_text.split()) > 1 else ""
            reply = await send_chip_detail(phone, chip)
        elif text == "TRANSFERS":
            from whatsapp.phase7 import send_transfers_status

            reply = await send_transfers_status(phone)
        elif text == "BUDGET":
            from whatsapp.phase7 import send_budget_status

            reply = await send_budget_status(phone)
        elif text == "PRIVATE":
            await set_subscriber_share_private(phone, private=True)
            reply = _truncate("Share cards set to private. Future recaps won't be public links.")
        else:
            reply = _truncate("Unknown command. Send HELP for options.")
    except ValueError as exc:
        logger.error("Command handler config error phone={}: {}", phone, exc)
        reply = _truncate("Service unavailable. Try again later.")
    except Exception as exc:
        logger.exception("Command handler error phone={}: {}", phone, exc)
        reply = _truncate("Something went wrong. Send HELP or try later.")

    try:
        messages = reply if isinstance(reply, list) else [reply]
        for message in messages:
            await _send_message(phone, message)
    except Exception as exc:
        logger.error("Failed to send WhatsApp reply phone={}: {}", mask_phone(phone), exc)
