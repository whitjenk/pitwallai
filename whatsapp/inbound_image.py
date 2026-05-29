"""Handle inbound WhatsApp images — primarily F1 Fantasy team screenshots."""

from __future__ import annotations

from loguru import logger

from fantasy.rules import DRIVERS_PER_TEAM
from intelligence.repository import upsert_fantasy_team_fields
from intelligence.team_extractor import extract_team_from_image
from intelligence.standings_extractor import extract_standings_from_image
from whatsapp.media import download_media
from whatsapp.sender import mask_phone, send_message
from whatsapp.subscribe_flow import (
    clear_pending_screenshot,
    get_pending_screenshot,
    truncate,
)


def _save_fields(team) -> dict[str, object]:
    """Map ExtractedTeam → repository upsert payload (only non-empty fields)."""
    fields: dict[str, object] = {}
    drivers = team.drivers[:DRIVERS_PER_TEAM]
    for idx, code in enumerate(drivers, start=1):
        fields[f"driver_{idx}"] = code
    for idx, code in enumerate(team.constructors[:2], start=1):
        fields[f"constructor_{idx}"] = code
    if team.remaining_budget_m is not None:
        fields["remaining_budget"] = float(team.remaining_budget_m)
    if team.transfers_available is not None:
        fields["transfers_available"] = int(team.transfers_available)
    return fields


def _summary_line(team) -> str:
    drivers = " · ".join(team.drivers) if team.drivers else "—"
    cons = " · ".join(team.constructors) if team.constructors else "—"
    budget = (
        f"`${team.remaining_budget_m:.1f}M`"
        if team.remaining_budget_m is not None
        else "—"
    )
    tfr = team.transfers_available if team.transfers_available is not None else "—"
    return (
        f"*Drivers:* {drivers}\n"
        f"*Constructors:* {cons}\n"
        f"*Budget left:* {budget}  ·  *Transfers:* {tfr}"
    )


def _missing_followup(missing: list[str]) -> str:
    if not missing:
        return ""
    labels = {
        "drivers": "your 5 driver codes (e.g. NOR VER LEC ALB HAM)",
        "constructors": "your 2 constructor codes (e.g. MCL FER)",
        "budget": "your remaining budget in $M (e.g. 4.2)",
        "transfers": "transfers available (a number, usually 1-5)",
    }
    parts = [labels[f] for f in missing if f in labels]
    if not parts:
        return ""
    return "I couldn't read everything — reply with " + "; ".join(parts) + "."


async def _handle_team_screenshot(
    phone: str, image_bytes: bytes, mime_type: str, kind: str,
) -> None:
    """Save a team screenshot (initial setup or post-lock confirmation)."""
    result = await extract_team_from_image(image_bytes, mime_type=mime_type)

    if result.status == "error":
        await send_message(phone, truncate(
            "Sorry — I couldn't read that screenshot. "
            "Try a clearer shot of your F1 Fantasy team screen, or text your 5 driver codes."
        ))
        return

    if result.status == "rejected" or result.team is None:
        await send_message(phone, truncate(
            "That doesn't look like an F1 Fantasy team screen. "
            "Open the F1 Fantasy app → My Team → screenshot that screen."
        ))
        return

    fields = _save_fields(result.team)
    if fields:
        await upsert_fantasy_team_fields(phone, **fields)
        logger.bind(phone=mask_phone(phone), kind=kind).info(
            "Team saved from screenshot · drivers={} constructors={} budget={} transfers={}",
            len(result.team.drivers),
            len(result.team.constructors),
            result.team.remaining_budget_m,
            result.team.transfers_available,
        )

    clear_pending_screenshot(phone)

    if kind == "locked_team":
        await send_message(phone, (
            "✅ Locked team saved:\n\n"
            f"{_summary_line(result.team)}\n\n"
            "I'll score against this on Sunday and tell you how you did vs PitWallAI's picks."
        ))
        return

    if result.status == "ok":
        await send_message(phone, (
            "✅ Got your team:\n\n"
            f"{_summary_line(result.team)}\n\n"
            "Saturday picks land before lock. Text PICKS anytime, or a driver code (e.g. NOR) for one card."
        ))
        return

    await send_message(phone, (
        "Got most of it:\n\n"
        f"{_summary_line(result.team)}\n\n"
        f"{_missing_followup(result.missing_fields)}"
    ).strip())


async def _handle_standings_screenshot(
    phone: str, image_bytes: bytes, mime_type: str,
) -> None:
    """Save a league standings screenshot for the Monday post-mortem."""
    from intelligence.repository import save_league_standings_snapshot

    result = await extract_standings_from_image(image_bytes, mime_type=mime_type)

    if result.status != "ok" or result.standings is None:
        clear_pending_screenshot(phone)
        await send_message(phone, truncate(
            "Couldn't read those standings. No worries — try again from your league page next week."
        ))
        return

    try:
        await save_league_standings_snapshot(
            phone=phone,
            entries=[e.model_dump() for e in result.standings.entries],
            captured_at_race_key=None,
        )
    except Exception as exc:  # additive: never block
        logger.warning("save_league_standings_snapshot skipped phone={}: {}", mask_phone(phone), exc)

    clear_pending_screenshot(phone)
    top = result.standings.entries[0] if result.standings.entries else None
    me = next((e for e in result.standings.entries if e.is_user), None)
    if top and me and me.position:
        await send_message(phone, (
            f"Got your league. You're *P{me.position}* — "
            f"leader is *{top.user_name or 'unknown'}*. "
            "I'll show you what they did differently on Monday."
        ))
    else:
        await send_message(phone, truncate(
            "Saved. I'll show you what your league leader did differently on Monday."
        ))


async def handle_inbound_image(phone: str, media_id: str, mime_type: str) -> None:
    """Process an inbound image. Dispatches on the pending_screenshot state."""
    kind = get_pending_screenshot(phone)
    if kind is None:
        logger.debug("Inbound image ignored (not awaiting screenshot) phone={}", mask_phone(phone))
        return

    try:
        image_bytes, detected_mime = await download_media(media_id)
    except Exception as exc:
        logger.exception("download_media failed phone={}: {}", mask_phone(phone), exc)
        await send_message(phone, truncate(
            "Couldn't download that image. Try again in a moment."
        ))
        return

    effective_mime = detected_mime or mime_type

    if kind in {"team_setup", "locked_team"}:
        await _handle_team_screenshot(phone, image_bytes, effective_mime, kind)
        return
    if kind == "league_standings":
        await _handle_standings_screenshot(phone, image_bytes, effective_mime)
        return

    logger.warning("Unknown pending screenshot kind={} phone={}", kind, mask_phone(phone))
    clear_pending_screenshot(phone)
