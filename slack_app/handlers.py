"""Subcommand handlers for ``/pitwall`` — plain async functions, no Slack.

Each returns a :class:`~slack_app.reply.Reply`, so a test can call ``handle``
directly without a Slack client. All F1 logic comes from ``core.api`` and all
persistence from ``store``; this module only parses, routes and formats. Every
reply in brief 006 is personal, so each is ``ephemeral``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger

import store
from core.api import race_calendar, suggest_transfers
from core.parse import parse_team_command
from core.types import Team as CoreTeam
from slack_app.openf1_client import build_client
from slack_app.reply import Reply

_HELP = (
    "*PitWallAI* — F1 Fantasy, only-you replies.\n"
    "• `/pitwall team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2` — save your squad\n"
    "• `/pitwall team` — show your saved squad\n"
    "• `/pitwall picks` — transfer and captain reads for the next race\n"
    "• `/pitwall forget` — erase everything I store about you\n"
    "• `/pitwall help` — this list"
)


def _next_race_key(now: datetime | None = None) -> str | None:
    """race_key of the next weekend by race time, or ``None`` if the season's done."""
    now = now or datetime.now(tz=UTC)
    upcoming = sorted(
        (w for w in race_calendar() if w.race_utc > now), key=lambda w: w.race_utc
    )
    return upcoming[0].race_key if upcoming else None


def _next_race() -> object | None:
    now = datetime.now(tz=UTC)
    upcoming = sorted(
        (w for w in race_calendar() if w.race_utc > now), key=lambda w: w.race_utc
    )
    return upcoming[0] if upcoming else None


def _format_team(team: store.Team) -> str:
    drivers = " ".join(team.drivers) or "—"
    constructors = " ".join(team.constructors) or "—"
    return (
        f"*Drivers:* {drivers}\n"
        f"*Constructors:* {constructors}\n"
        f"*Budget left:* ${team.budget_m:.1f}M · *Transfers:* {team.transfers_available}"
    )


def _format_picks(out, weekend) -> str:
    name = getattr(weekend, "display_name", None) or getattr(weekend, "race_key", "")
    lines = [f"*Picks for the {name}*", ""]
    if not out.picks:
        lines.append("No clear transfer stands out from the signals available so far.")
    for pick in out.picks:
        if pick.transfer_out and pick.transfer_in:
            move = f"{pick.transfer_in} in for {pick.transfer_out}"
        else:
            move = pick.transfer_in or pick.driver_code
        lines.append(f"{pick.rank}. *{move}* — {pick.headline}")
        if pick.reasoning:
            lines.append(f"   {pick.reasoning}")
    if out.circuit_note:
        lines += ["", out.circuit_note]
    if out.confidence_note:
        lines.append(out.confidence_note)
    return "\n".join(lines)


async def _handle_team(args: str, user_id: str, team_id: str, display_name: str) -> Reply:
    if not args.strip():
        team = await store.get_team(user_id)
        if team is None:
            return Reply(
                "I don't have your team yet. Save it with "
                "`/pitwall team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2`."
            )
        return Reply("*Your saved team*\n" + _format_team(team))

    parsed = parse_team_command(args)
    if not parsed.ok:
        body = "\n".join(f"• {e}" for e in parsed.errors)
        return Reply(
            "I couldn't save that:\n"
            f"{body}\n\n"
            "Example: `/pitwall team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2`"
        )

    team = store.Team(
        slack_user_id=user_id,
        slack_team_id=team_id,
        display_name=display_name or user_id,
        drivers=parsed.drivers,
        constructors=parsed.constructors,
        budget_m=parsed.budget_m or 0.0,
        transfers_available=parsed.transfers,
        chips_used={},
    )
    await store.upsert_team(team)
    return Reply("*Saved your team*\n" + _format_team(team))


async def _handle_picks(args: str, user_id: str, team_id: str, display_name: str) -> Reply:
    stored = await store.get_team(user_id)
    if stored is None:
        return Reply(
            "I don't have your team yet. Save it with `/pitwall team ...`, "
            "then ask for `picks`."
        )
    weekend = _next_race()
    if weekend is None:
        return Reply("No upcoming race on the calendar to suggest picks for.")

    core_team = CoreTeam(
        drivers=list(stored.drivers),
        constructors=list(stored.constructors),
        budget_m=stored.budget_m,
        transfers_available=stored.transfers_available,
        chips_used=dict(stored.chips_used),
    )
    client = build_client()
    try:
        out = await suggest_transfers(core_team, weekend.race_key, client)
    except Exception as exc:  # never leak a stack trace to the user
        logger.warning("picks failed user={} race={}: {}", user_id, weekend.race_key, exc)
        return Reply("Couldn't pull the picks right now — the data wasn't available. Try again later.")
    return Reply(_format_picks(out, weekend))


async def _handle_forget(args: str, user_id: str, team_id: str, display_name: str) -> Reply:
    await store.forget_user(user_id)
    return Reply("Done — I've erased your team and any lineups I had stored for you.")


async def _handle_help(args: str, user_id: str, team_id: str, display_name: str) -> Reply:
    return Reply(_HELP)


_HANDLERS = {
    "team": _handle_team,
    "picks": _handle_picks,
    "forget": _handle_forget,
    "help": _handle_help,
}


async def handle(
    text: str, user_id: str, team_id: str, display_name: str | None = None
) -> Reply:
    """Route ``/pitwall <text>`` to a subcommand handler.

    ``text`` is the slash-command argument string (everything after ``/pitwall``).
    A bare command or ``help`` returns the command list. Unknown subcommands get
    the help text too, so a typo is never a dead end.
    """
    parts = text.strip().split(maxsplit=1)
    command = parts[0].lower() if parts else "help"
    args = parts[1] if len(parts) > 1 else ""
    handler = _HANDLERS.get(command)
    if handler is None:
        return Reply(f"I don't know `{command}`.\n\n{_HELP}")
    return await handler(args, user_id, team_id, display_name or user_id)
