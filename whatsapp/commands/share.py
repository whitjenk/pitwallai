"""SHARE [driver] — forwardable, attributed pick card (Bet 1 growth loop)."""

from __future__ import annotations

from intelligence.explanation_builder import build_explanation
from intelligence.repository import load_latest_pick_for_driver
from whatsapp.commands._utils import (
    confidence_band,
    driver_price_line,
    explanation_context_for_race,
    is_known_driver_code,
    pick_row_to_recommendation,
)
from whatsapp.message_format import format_explanation_card

def _attribution_line() -> str:
    """One-tap acquisition: wa.me link opens WhatsApp with SUBSCRIBE pre-typed.

    Falls back to the static landing page if the display number isn't set.
    Plain number is included as a fallback for screenshots/non-tap contexts.
    """
    from whatsapp.settings import get_whatsapp_settings, wa_me_link

    link = wa_me_link("SUBSCRIBE")
    number = (get_whatsapp_settings().display_number or "").strip()
    if link and number:
        return f"via PitWallAI · Get picks: {link}\n(or text SUBSCRIBE to {number})"
    if link:
        return f"via PitWallAI · Get picks: {link}"
    return "via PitWallAI · pitwallai.app"


async def handle_share(
    driver_code: str,
    phone_number: str,
    race_key: str,
) -> str:
    """Forwardable card for a single driver pick. Self-contained on purpose."""
    code = driver_code.upper()
    if not is_known_driver_code(code):
        return (
            f"Unknown driver code *{code}*.\n"
            "Try: SHARE NOR  ·  SHARE VER  ·  SHARE LEC"
        )

    row = await load_latest_pick_for_driver(race_key, code, phone=phone_number)
    if row is None:
        row = await load_latest_pick_for_driver(race_key, code, phone=None)
    if row is None:
        return (
            f"No PitWallAI pick for *{code}* this weekend yet.\n"
            "Picks ship Saturday morning after qualifying."
        )

    pick = pick_row_to_recommendation(row)
    ctx = await explanation_context_for_race(race_key)
    explanation = build_explanation(pick, ctx)
    price = driver_price_line(code)
    band = confidence_band(pick.confidence)

    header = f"🏎  *{code}*  ·  `{price}`  ·  *{band}*"
    if explanation is None:
        body = "Pick is live but the signal card isn't ready yet."
    else:
        body = format_explanation_card(explanation)

    return (
        f"{header}\n\n"
        f"{body}\n\n"
        f"{_attribution_line()}\n"
        "Not financial advice."
    )
