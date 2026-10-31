"""Subcommand handlers for ``/pitwall`` — plain async functions, no Slack.

Each returns a :class:`~slack_app.reply.Reply` (or a list of them, when one
command posts both a private note and a public line), so a test can call
``handle`` directly without a Slack client. All F1 logic comes from ``core.api``
and all persistence from ``store``; this module only parses, routes and formats.

Visibility follows the reply, not the handler: personal reads (``team``,
``picks``) stay ``ephemeral``; league banter (``grade``, ``score``, ``record``)
goes ``in_channel`` so the group can react. ``lock`` is private apart from a
one-line channel note that names who locked in but never their lineup.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from loguru import logger

import store
from core.api import (
    grade_lineup,
    project_race,
    race_calendar,
    score_lineup,
    suggest_transfers,
)
from core.parse import extract_captain, extract_lineup, parse_team_command
from core.types import Lineup as CoreLineup
from core.types import Team as CoreTeam
from slack_app.openf1_client import build_client
from slack_app.reply import IN_CHANNEL, Reply

_HELP = (
    "*PitWallAI* — F1 Fantasy for the league.\n"
    "• `/pitwall team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2` — save your squad\n"
    "• `/pitwall team` — show your saved squad\n"
    "• `/pitwall picks` — transfer and captain reads for the next race\n"
    "• `/pitwall grade HAM LEC ANT RUS VER MER FER captain HAM 3x` — grade a lineup (posts to the channel)\n"
    "• `/pitwall lock <lineup>` — lock your call for the next race (private; a one-liner tells the channel you're in)\n"
    "• `/pitwall score [race]` — your locked call vs mine vs the result (posts to the channel)\n"
    "• `/pitwall record` — your season so far vs mine (posts to the channel)\n"
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


def _race_name(race_key: str) -> str:
    """Display name for a race_key, falling back to the key itself."""
    for w in race_calendar():
        if w.race_key == race_key:
            return w.display_name
    return race_key


def _resolve_race_key(text: str) -> str | None:
    """Find a race in free text by circuit key or a word from its name."""
    aliases: dict[str, str] = {}
    for w in race_calendar():
        aliases[w.circuit_key] = w.race_key
        for word in w.display_name.lower().replace("-", " ").split():
            if word not in {"grand", "prix"} and len(word) > 3:
                aliases.setdefault(word, w.race_key)
    low = text.lower()
    for alias, rk in aliases.items():
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return rk
    return None


def _lineup_from_text(text: str) -> CoreLineup:
    """Parse drivers, constructors, chip and captain out of free text."""
    drivers, constructors, chip = extract_lineup(text)
    captain = extract_captain(text, drivers) if drivers else None
    return CoreLineup(
        drivers=drivers, constructors=constructors, chip=chip, captain=captain
    )


def _fmt_lineup(lineup: CoreLineup) -> str:
    """A compact one-line rendering of a lineup for a private confirmation."""
    drivers = ", ".join(lineup.drivers) or "—"
    constructors = ", ".join(lineup.constructors) or "—"
    tail = ""
    if lineup.captain:
        tail += f" · captain {lineup.captain}"
    if lineup.chip:
        tail += f" · {lineup.chip}"
    return f"{drivers} | {constructors}{tail}"


def _model_lineup_from_projection(projection: dict) -> dict | None:
    """The bot's own pick at lock time, as a plain dict, or ``None``."""
    if not projection:
        return None
    return {
        "drivers": list(projection.get("top_drivers", [])),
        "constructors": list(projection.get("top_constructors", [])),
        "captain": projection.get("captain"),
    }


def _model_as_lineup(model_lineup: dict | None) -> CoreLineup | None:
    """Rebuild a :class:`CoreLineup` from a stored model pick, if present."""
    if not model_lineup or not model_lineup.get("drivers"):
        return None
    return CoreLineup(
        drivers=list(model_lineup.get("drivers", [])),
        constructors=list(model_lineup.get("constructors", [])),
        captain=model_lineup.get("captain"),
    )


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


async def _handle_grade(args: str, user_id: str, team_id: str, display_name: str) -> Reply:
    """Grade a stated lineup against the bot's projection — posted to the channel."""
    lineup = _lineup_from_text(args)
    if not lineup.drivers:
        return Reply(
            "Tell me a lineup to grade, e.g. "
            "`/pitwall grade HAM LEC ANT RUS VER MER FER captain HAM 3x`."
        )
    race_key = _next_race_key()
    if race_key is None:
        return Reply("No upcoming race on the calendar to grade against.")

    client = build_client()
    try:
        graded = await grade_lineup(lineup, race_key, client)
    except Exception as exc:  # never leak a stack trace to the channel
        logger.warning("grade failed user={} race={}: {}", user_id, race_key, exc)
        return Reply("Couldn't grade that right now — the data wasn't available. Try again later.")
    if not graded:
        return Reply(
            f"No practice pace loaded for the {_race_name(race_key)} yet, "
            "so there's nothing to grade a lineup against. Try again once FP1/FP2 are in."
        )

    matched = graded["drivers_matching_model"]
    cap = graded["captain"]
    cap_bonus = graded["captain_bonus"]
    lines = [
        f"*{display_name}'s {_race_name(race_key)} lineup — graded*",
        f"Lineup: {_fmt_lineup(lineup)}",
        f"Projects *~{graded['projected_total']:.0f} pts* on practice pace"
        + (f" (captain {cap} +{cap_bonus:.0f})" if cap else "")
        + ".",
        f"Overlaps with {len(matched)}/5 of my top driver picks"
        + (f": {', '.join(matched)}." if matched else "."),
        f"My top picks on pace: {', '.join(graded['model_top_drivers']) or '—'}.",
    ]
    return Reply("\n".join(lines), visibility=IN_CHANNEL)


async def _handle_lock(args: str, user_id: str, team_id: str, display_name: str) -> list[Reply]:
    """Lock a lineup privately; drop a one-line channel note that reveals no picks."""
    lineup = _lineup_from_text(args)
    if not lineup.drivers:
        return [
            Reply(
                "Tell me the lineup to lock, e.g. "
                "`/pitwall lock HAM LEC ANT RUS VER MER FER captain HAM 3x`."
            )
        ]
    race_key = _next_race_key()
    if race_key is None:
        return [Reply("No upcoming race on the calendar to lock for.")]

    client = build_client()
    try:
        projection = await project_race(race_key, client)
    except Exception as exc:  # the lock still saves without the bot's own pick
        logger.warning("lock projection failed user={} race={}: {}", user_id, race_key, exc)
        projection = {}
    model_lineup = _model_lineup_from_projection(projection)

    await store.lock_lineup(
        store.LockedLineup(
            slack_user_id=user_id,
            race_key=race_key,
            drivers=lineup.drivers,
            constructors=lineup.constructors,
            chip=lineup.chip,
            captain=lineup.captain,
            model_lineup=model_lineup,
        )
    )

    name = _race_name(race_key)
    confirm_lines = [
        f"🔒 Locked your {name} call.",
        f"You: {_fmt_lineup(lineup)}",
    ]
    if model_lineup:
        bot = _model_as_lineup(model_lineup)
        confirm_lines.append(f"🤖 My pick at lock: {_fmt_lineup(bot)}")
    else:
        confirm_lines.append(
            "🤖 No practice pace loaded yet, so I don't have my own pick on record for this one."
        )
    confirm_lines.append(f"Run `/pitwall score` after the {name} to see how it went.")

    channel_line = f"🔒 <@{user_id}> locked in for the {name}."
    return [
        Reply("\n".join(confirm_lines)),  # ephemeral confirmation (private picks)
        Reply(channel_line, visibility=IN_CHANNEL),  # public, no lineup
    ]


async def _handle_score(args: str, user_id: str, team_id: str, display_name: str) -> Reply:
    """Score your locked call vs the bot vs the result vs the perfect lineup."""
    race_key = _resolve_race_key(args) or _next_race_key()
    if race_key is None:
        return Reply("No race on the calendar to score against.")
    name = _race_name(race_key)

    locked = await store.get_locked(user_id, race_key)
    if locked is None:
        return Reply(
            f"Nothing locked for the {name}. Lock a call with "
            "`/pitwall lock <lineup>`, then score it after the race."
        )

    your_lineup = CoreLineup(
        drivers=list(locked.drivers),
        constructors=list(locked.constructors),
        chip=locked.chip,
        captain=locked.captain,
    )
    client = build_client()
    try:
        you = await score_lineup(your_lineup, race_key, client)
        bot_lineup = _model_as_lineup(locked.model_lineup)
        bot = await score_lineup(bot_lineup, race_key, client) if bot_lineup else None
    except Exception as exc:  # never leak a stack trace to the channel
        logger.warning("score failed user={} race={}: {}", user_id, race_key, exc)
        return Reply("Couldn't score that right now — the data wasn't available. Try again later.")

    if you is None:
        return Reply(f"The {name} hasn't been classified yet — I'll have a score once it's done.")

    perfect = you["perfect"]
    you_t = you["total"]
    ceiling = perfect["total"] or 1
    capture = round(100 * you_t / ceiling)

    lines = [f"*{display_name} — {name} scored*"]
    cap = you["captain"]
    lines.append(f"You: *{you_t} pts*" + (f" (captain {cap} +{you['captain_bonus']})" if cap else ""))
    if bot is not None:
        bot_t = bot["total"]
        verdict = (
            "you beat me 🏆" if you_t > bot_t
            else "I edged it 🤖" if bot_t > you_t else "dead heat 🤝"
        )
        lines.append(f"Me: {bot_t} pts")
    else:
        verdict = ""
    lines.append(f"Perfect: {perfect['total']} pts ({', '.join(perfect['drivers']) or '—'})")
    lines.append(
        (f"→ {verdict}. " if verdict else "→ ") + f"You captured {capture}% of the ceiling."
    )
    return Reply("\n".join(lines), visibility=IN_CHANNEL)


async def _handle_record(args: str, user_id: str, team_id: str, display_name: str) -> Reply:
    """Season scorecard: how your locked calls have done against the bot — channel."""
    locked = [
        lk
        for w in race_calendar()
        if (lk := await store.get_locked(user_id, w.race_key)) is not None
    ]
    if not locked:
        return Reply(
            "No races locked yet. Lock a call with `/pitwall lock <lineup>`, "
            "then I can track your season here."
        )

    client = build_client()
    wins = losses = ties = 0
    captures: list[int] = []
    scored = 0
    try:
        for lk in locked:
            your_lineup = CoreLineup(
                drivers=list(lk.drivers),
                constructors=list(lk.constructors),
                chip=lk.chip,
                captain=lk.captain,
            )
            you = await score_lineup(your_lineup, lk.race_key, client)
            if you is None:  # race not classified yet
                continue
            scored += 1
            perfect_total = you["perfect"]["total"] or 1
            captures.append(round(100 * you["total"] / perfect_total))
            bot_lineup = _model_as_lineup(lk.model_lineup)
            bot = await score_lineup(bot_lineup, lk.race_key, client) if bot_lineup else None
            if bot is not None:
                if you["total"] > bot["total"]:
                    wins += 1
                elif bot["total"] > you["total"]:
                    losses += 1
                else:
                    ties += 1
    except Exception as exc:  # never leak a stack trace to the channel
        logger.warning("record failed user={}: {}", user_id, exc)
        return Reply("Couldn't pull your record right now — the data wasn't available. Try again later.")

    if scored == 0:
        return Reply(
            f"{display_name} has {len(locked)} race(s) locked, but none have been "
            "classified yet — the scorecard fills in after each race."
        )

    avg_capture = round(sum(captures) / len(captures)) if captures else 0
    rec = f"{wins}-{losses}" + (f"-{ties}" if ties else "")
    lines = [
        f"*{display_name}'s PitWallAI scorecard — {scored} race(s)*",
        f"Ceiling capture: {avg_capture}% on average.",
    ]
    if wins + losses + ties:
        lines.append(f"Against me: {rec} (wins-losses{'-ties' if ties else ''}).")
    return Reply("\n".join(lines), visibility=IN_CHANNEL)


async def _handle_help(args: str, user_id: str, team_id: str, display_name: str) -> Reply:
    return Reply(_HELP)


_HANDLERS = {
    "team": _handle_team,
    "picks": _handle_picks,
    "grade": _handle_grade,
    "lock": _handle_lock,
    "score": _handle_score,
    "record": _handle_record,
    "forget": _handle_forget,
    "help": _handle_help,
}


async def handle(
    text: str, user_id: str, team_id: str, display_name: str | None = None
) -> Reply | list[Reply]:
    """Route ``/pitwall <text>`` to a subcommand handler.

    ``text`` is the slash-command argument string (everything after ``/pitwall``).
    A bare command or ``help`` returns the command list. Unknown subcommands get
    the help text too, so a typo is never a dead end. Most handlers return one
    :class:`Reply`; ``lock`` returns a list (a private confirmation plus a public
    one-liner), so ``app.py`` posts each in turn.
    """
    parts = text.strip().split(maxsplit=1)
    command = parts[0].lower() if parts else "help"
    args = parts[1] if len(parts) > 1 else ""
    handler = _HANDLERS.get(command)
    if handler is None:
        return Reply(f"I don't know `{command}`.\n\n{_HELP}")
    return await handler(args, user_id, team_id, display_name or user_id)
