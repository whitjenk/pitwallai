"""PICKS command — current weekend recommendations."""

from __future__ import annotations

from intelligence.explanation_builder import build_explanation
from intelligence.repository import get_picks_for_race
from scheduler.calendar import get_race_weekend
from whatsapp.commands._utils import (
    conf_bar,
    driver_price_line,
    explanation_context_for_race,
    pick_row_to_recommendation,
)
from whatsapp.message_format import format_explanation_card

_FOOTER = (
    "──────────────────\n"
    "PitWallAI · Not financial advice"
)


async def handle_picks(phone_number: str, race_key: str) -> str:
    rows = await get_picks_for_race(race_key, phone=phone_number)
    if not rows:
        rows = await get_picks_for_race(race_key, phone=None)

    if not rows:
        try:
            from openf1.client import OpenF1Client
            from whatsapp.app_runtime import get_pick_runtime
            from whatsapp.phase7 import send_picks_on_demand

            runtime = get_pick_runtime(allow_lazy=True)
            if runtime is None:
                raise RuntimeError("pick runtime unavailable")
            return await send_picks_on_demand(
                phone_number,
                client=OpenF1Client(),
                runtime=runtime,
            )
        except Exception:
            return (
                "No picks available yet for this race weekend.\n\n"
                "Picks are sent Saturday morning after qualifying.\n"
                "Reply *HELP* for all commands."
            )

    weekend = get_race_weekend(race_key)
    title = weekend.display_name if weekend else race_key
    ctx = await explanation_context_for_race(race_key)
    lines = [f"🏎 *PitWallAI Picks · {title}*\n"]

    for row in rows[:3]:
        pick = pick_row_to_recommendation(row)
        code = pick.driver_code.upper()
        explanation = build_explanation(pick, ctx)
        bar = conf_bar(pick.confidence)
        lines.append(f"*{code}*  ·  {driver_price_line(code)}")
        lines.append(f"Confidence: {int(pick.confidence)}%  {bar}")
        if explanation:
            lines.append(format_explanation_card(explanation))
        lines.append("")

    lines.extend(["──────────────────", "PitWallAI · Not financial advice"])
    return "\n".join(lines)
