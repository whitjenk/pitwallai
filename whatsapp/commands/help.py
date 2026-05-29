"""HELP command."""

from __future__ import annotations

_FOOTER = (
    "──────────────────\n"
    "PitWallAI · Not financial advice"
)


async def handle_help(phone_number: str, race_key: str) -> str:
    _ = phone_number, race_key
    return (
        "🏎 *PitWallAI Commands*\n\n"
        "*PICKS*     → This weekend's recommended picks\n"
        "*TEAM*      → Your fantasy team + budget\n"
        "*[CODE]*    → Driver brief e.g. NOR, VER, LEC\n"
        "*HISTORY*   → Your last 3 race pick outcomes\n"
        "*STREAK*    → PitWallAI hit rate this season\n\n"
        "*SUBSCRIBE* → Start receiving picks\n"
        "*UNSUBSCRIBE* → Stop receiving picks\n\n"
        "Also: LEAGUE · CHIPS · TRANSFERS · BUDGET · WHY · LIVE ON/OFF\n\n"
        f"{_FOOTER}"
    )
