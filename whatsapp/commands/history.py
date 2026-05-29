"""HISTORY command — subscriber pick outcomes."""

from __future__ import annotations

from intelligence.repository import load_subscriber_pick_history

_FOOTER = (
    "──────────────────\n"
    "PitWallAI · Not financial advice"
)


async def handle_history(phone_number: str, race_key: str) -> str:
    _ = race_key
    history = await load_subscriber_pick_history(phone_number, limit=3)

    if not history:
        return (
            "No pick history yet.\n\n"
            "History is updated after each race.\n"
            "Reply *STREAK* to see PitWallAI's overall hit rate."
        )

    lines = ["📋 *Your Pick History*\n"]
    for _rk, race_name, driver, points, was_correct in history:
        emoji = "✅" if was_correct else "❌"
        lines.append(f"{emoji} *{race_name}*")
        lines.append(f"   Pick: {driver} → {points:+.0f} pts")

    lines.extend(["", "──────────────────", "Reply *STREAK* for season hit rate.", _FOOTER])
    return "\n".join(lines)
