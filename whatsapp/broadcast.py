"""WhatsApp broadcast pipeline for race-weekend picks."""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from typing import Any

from loguru import logger

from db.models import FantasyTeam, Subscriber
from intelligence.repository import list_active_subscribers, save_pick_ownership
from intelligence.schemas import PickOutput
from intelligence.weekend_picks import generate_picks_for_weekend
from openf1.client import OpenF1Client
from pitwallai.agents.radio_intercept.config import PitWallSettings
from scheduler.calendar import RaceWeekend, get_race_weekend
from scheduler.jobs import _require_ctx
from whatsapp.message_format import format_generic_picks, format_personalized_picks
from whatsapp.sender import mask_phone, send_message


@dataclass(frozen=True, slots=True)
class BroadcastResult:
    """Per-subscriber send outcome."""

    phone: str
    success: bool
    personalized: bool
    recommended_drivers: list[str]
    error: str | None = None


def _is_personalized_eligible(team: FantasyTeam | None) -> bool:
    """PATH A when remaining_budget is set (progressive profile)."""
    return team is not None and team.remaining_budget is not None


async def broadcast_race_picks(race_key: str) -> dict[str, Any]:
    """
    Generate and broadcast picks to all active subscribers.

    1. Load subscribers from Postgres
    2. PATH A (FantasyTeam + budget) vs PATH B per subscriber
    3. Generate picks, persist audit log before send
    4. Send independently — one failure never blocks others

    Args:
        race_key: Calendar race key (e.g. 2026_monaco).

    Returns:
        Summary dict with send counts and failures.
    """
    weekend = get_race_weekend(race_key)
    if weekend is None:
        raise ValueError(f"Unknown race_key: {race_key}")

    ctx = _require_ctx()
    app = ctx.app
    settings: PitWallSettings = app.state.settings
    subscribers = await list_active_subscribers()

    if not subscribers:
        logger.warning("broadcast_race_picks: no active subscribers race_key={}", race_key)
        return {"race_key": race_key, "sent": 0, "failed": 0, "skipped": 0}

    client = OpenF1Client()
    results: list[BroadcastResult] = []

    try:
        for sub in subscribers:
            result = await _broadcast_to_subscriber(
                sub,
                weekend=weekend,
                client=client,
                app=app,
                settings=settings,
            )
            results.append(result)
    finally:
        pass

    sent = sum(1 for r in results if r.success)
    ownership_counts: Counter[str] = Counter()
    for row in results:
        if not row.success:
            continue
        ownership_counts.update(row.recommended_drivers)
    if sent > 0 and ownership_counts:
        await save_pick_ownership(
            race_key,
            [
                {
                    "driver_code": code,
                    "pitwallai_ownership_pct": round(100.0 * count / sent, 1),
                    "recommendation_count": count,
                }
                for code, count in ownership_counts.items()
            ],
        )

    failed = sum(1 for r in results if not r.success)
    personalized = sum(1 for r in results if r.success and r.personalized)

    logger.bind(
        race_key=race_key,
        sent=sent,
        failed=failed,
        personalized=personalized,
        total=len(subscribers),
    ).info("broadcast_race_picks finished")

    return {
        "race_key": race_key,
        "sent": sent,
        "failed": failed,
        "personalized": personalized,
        "total": len(subscribers),
        "failures": [
            {"phone": mask_phone(r.phone), "error": r.error}
            for r in results
            if not r.success
        ],
    }


async def _broadcast_to_subscriber(
    sub: Subscriber,
    *,
    weekend: RaceWeekend,
    client: OpenF1Client,
    app: Any,
    settings: PitWallSettings,
) -> BroadcastResult:
    """Generate, log, and send picks for one subscriber."""
    from intelligence.repository import get_fantasy_team

    phone = sub.phone
    try:
        team = await get_fantasy_team(phone)
        personalized = _is_personalized_eligible(team)

        output = await generate_picks_for_weekend(
            weekend,
            client=client,
            agent=app.state.agent,
            vector_store=app.state.vector_store,
            settings=settings,
            phone=phone,
            persist_picks=True,
            refresh_practice=False,
        )

        message = _format_message(weekend, output, sub, personalized=personalized)
        await send_message(phone, message)

        logger.bind(
            phone=mask_phone(phone),
            race_key=weekend.race_key,
            personalized=personalized,
            chars=len(message),
        ).info("Pick broadcast sent")

        return BroadcastResult(
            phone=phone,
            success=True,
            personalized=personalized,
            recommended_drivers=[p.driver_code for p in output.picks],
        )
    except Exception as exc:
        logger.error(
            "Pick broadcast failed phone={} race_key={}: {}",
            mask_phone(phone),
            weekend.race_key,
            exc,
        )
        return BroadcastResult(
            phone=phone,
            success=False,
            personalized=False,
            recommended_drivers=[],
            error=str(exc),
        )


def _format_message(
    weekend: RaceWeekend,
    output: PickOutput,
    sub: Subscriber,
    *,
    personalized: bool,
) -> str:
    if personalized:
        return format_personalized_picks(weekend, output, timezone=sub.timezone)
    return format_generic_picks(weekend, output, timezone=sub.timezone)
