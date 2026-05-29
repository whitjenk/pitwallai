"""On-demand driver explanation card (e.g. NOR, VER)."""

from __future__ import annotations

from intelligence.explanation_builder import build_explanation
from intelligence.repository import load_latest_pick_for_driver
from whatsapp.commands._utils import (
    conf_bar,
    confidence_band,
    driver_price_line,
    explanation_context_for_race,
    is_known_driver_code,
    pick_row_to_recommendation,
)
from whatsapp.message_format import format_explanation_card

_FOOTER = (
    "──────────────────\n"
    "PitWallAI · Not financial advice"
)


async def handle_driver(driver_code: str, phone_number: str, race_key: str) -> str:
    code = driver_code.upper()
    if not is_known_driver_code(code):
        return (
            f"Unknown driver code *{code}*.\n\n"
            "Reply *HELP* for commands or *PICKS* for this weekend's picks."
        )

    row = await load_latest_pick_for_driver(race_key, code, phone=phone_number)
    price = driver_price_line(code)

    if row is None:
        return (
            f"No pick data for *{code}* this weekend.\n\n"
            "Check back after qualifying, or reply *PICKS* for current recommendations."
        )

    pick = pick_row_to_recommendation(row)
    ctx = await explanation_context_for_race(race_key)
    explanation = build_explanation(pick, ctx)
    bar = conf_bar(pick.confidence)
    band = confidence_band(pick.confidence)

    if explanation is None:
        return (
            f"*{code}*  ·  {price}\n\n"
            f"Confidence: *{band}*  {bar}\n\n"
            "Signal data not yet available for this driver.\n"
            "Check back after FP2.\n\n"
            f"{_FOOTER}"
        )

    card = format_explanation_card(explanation)
    return (
        f"*{code}*  ·  {price}\n\n"
        f"Confidence: *{band}*  {bar}\n\n"
        f"{card}\n\n"
        f"{_FOOTER}"
    )
