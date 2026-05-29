"""Thursday draft picks for Friday delta comparison."""

from __future__ import annotations

from loguru import logger

from agents.base import AgentRunDependencies
from intelligence.repository import (
    get_draft_picks_for_race,
    get_fantasy_team,
    list_active_subscribers,
)
from intelligence.weekend_picks import generate_picks_for_weekend
from scheduler.calendar import get_race_weekend


async def generate_thursday_draft_picks(race_key: str, deps: AgentRunDependencies) -> int:
    """
    Store draft picks (pick_status=draft) for FULL subscribers with a team.

    Skips subscribers who already have drafts for this race.
    """
    weekend = get_race_weekend(race_key)
    if weekend is None:
        return 0
    created = 0
    for sub in await list_active_subscribers():
        if sub.cadence_preference != "FULL":
            continue
        team = await get_fantasy_team(sub.phone)
        if team is None or team.driver_1 is None:
            continue
        if await get_draft_picks_for_race(sub.phone, race_key):
            continue
        try:
            await generate_picks_for_weekend(
                weekend,
                client=deps.openf1_client,
                agent=deps.radio_agent,
                vector_store=deps.vector_store,
                settings=deps.settings,
                phone=sub.phone,
                persist_picks=True,
                pick_status="draft",
            )
            created += 1
        except Exception as exc:
            from whatsapp.sender import mask_phone

            logger.error("thursday draft failed phone={}: {}", mask_phone(sub.phone), exc)
    return created
