"""TEAM snapshot (read-only); multi-step onboarding stays in team_flow."""

from __future__ import annotations

from db.models import FantasyTeam
from fantasy.rules import BUDGET_CAP_M, transfers_configured
from intelligence.repository import get_fantasy_team
from whatsapp.commands._utils import driver_price_line

_FOOTER = (
    "──────────────────\n"
    "PitWallAI · Not financial advice"
)


def _driver_lines(team: FantasyTeam) -> list[str]:
    codes = [
        c
        for c in (
            team.driver_1,
            team.driver_2,
            team.driver_3,
            team.driver_4,
            team.driver_5,
        )
        if c
    ]
    if not codes:
        return []
    return [f"  {code}  ·  {driver_price_line(code)}" for code in codes]


async def handle_team(phone_number: str, race_key: str) -> str:
    _ = race_key
    team = await get_fantasy_team(phone_number)

    if team is None or not _driver_lines(team):
        return (
            "No team found for your number.\n\n"
            "Reply *SUBSCRIBE* to get started, then *TEAM* to set up your squad."
        )

    drivers = "\n".join(_driver_lines(team))
    budget = (
        f"${team.remaining_budget:.1f}M"
        if team.remaining_budget is not None
        else "—"
    )
    transfers = (
        str(team.transfers_available)
        if transfers_configured(team.transfers_available)
        else "—"
    )
    return (
        "🏎 *Your Team*\n\n"
        f"{drivers}\n\n"
        f"Budget remaining: `{budget}` / ${BUDGET_CAP_M:.0f}M cap\n"
        f"Transfers left: {transfers}\n\n"
        "Reply a driver code (e.g. *NOR*) for their pick brief.\n\n"
        f"{_FOOTER}"
    )
