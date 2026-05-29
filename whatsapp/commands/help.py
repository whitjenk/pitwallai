"""HELP command."""

from __future__ import annotations

_FOOTER = (
    "──────────────────\n"
    "PitWallAI · Not financial advice"
)


async def handle_help(phone_number: str, race_key: str) -> str:
    _ = phone_number, race_key
    # Dynamically reflect off-bet flag state so we don't promise commands
    # that have been gated off this release.
    from pitwallai.feature_flags import (
        budget_transfers_enabled,
        chips_enabled,
        constructor_strategy_enabled,
        season_recap_enabled,
    )

    flagged: list[str] = []
    if chips_enabled():
        flagged.append("CHIPS")
    if budget_transfers_enabled():
        flagged.extend(["TRANSFERS", "BUDGET"])
    if constructor_strategy_enabled():
        flagged.append("WHY CONSTRUCTOR")
    if season_recap_enabled():
        flagged.append("SEASON")
    extras_line = ("\nAlso: " + " · ".join(flagged)) if flagged else ""

    return (
        "🏎 *PitWallAI Commands*\n\n"
        "*PICKS*       → This weekend's recommended picks\n"
        "*[CODE]*      → Driver card e.g. NOR, VER, LEC\n"
        "*SHARE [CODE]* → Forwardable card for your league chat\n"
        "*TEAM*        → Your fantasy team + budget\n"
        "*UPDATE D4 ALB* → Fix one driver slot (D1–D5)\n"
        "*HISTORY*     → Your last 3 race pick outcomes\n"
        "*STREAK*      → PitWallAI hit rate this season\n\n"
        "*LIVE ON / LIVE OFF*  → Sunday race alerts on/off\n"
        "*SUBSCRIBE / UNSUBSCRIBE / DELETE*\n"
        "  UNSUBSCRIBE stops messages · DELETE wipes your data\n\n"
        "💡 Send a screenshot of your F1 Fantasy team anytime to update it."
        f"{extras_line}\n\n"
        f"{_FOOTER}"
    )
