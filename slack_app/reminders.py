"""Lock reminders, the one-tap "same team" lock and the auto-lock (brief 014).

A few hours before each fantasy lock, every league-mate with a saved team gets a
DM: when lock closes (in their own time zone), their saved team, the captain on
record and free transfers, with a ✅ Same team and an ✏️ Edit button. One tap
locks their call. Anyone who doesn't respond has their saved team locked
automatically at the deadline, so every player has a lineup every week.

Layout
------
This module is the home for the whole reminder flow so there are no import
cycles: it imports only ``store``, ``core`` and the low-level poster/reply/
scheduler seams, and never ``handlers`` or ``actions``. ``handlers`` calls
:func:`save_lock` for ``/pitwall lock``; ``actions`` routes the button clicks to
:func:`on_lock_same` / :func:`on_lock_edit`; ``app`` registers the jobs from
:func:`reminder_jobs`.

The DM needs no OpenF1 data (team, captain and transfers are all in the store),
so a live-session lockout doesn't affect it. The bot's own pick at lock *does*
come from ``project_race``; as with ``/pitwall lock`` the lock still saves when
that projection is empty, paused or failing.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from loguru import logger

import store
from core import calendar as cal
from core.api import project_race, race_calendar
from core.calendar import RaceWeekend, get_next_race_weekend
from slack_app.openf1_client import build_client
from slack_app.poster import LeaguePoster, Poster
from slack_app.reply import slack_date
from slack_app.scheduler import Job

# The reminder fires this many hours before the fantasy lock. Overridable so a
# local weekend run can bring it close without waiting hours.
REMINDER_HOURS_BEFORE_LOCK = 6.0

# The auto-lock is due a minute before the deadline, with a long grace so that if
# the bot was down at the deadline it still locks soon after rather than never.
_AUTOLOCK_LEAD = timedelta(minutes=1)
_AUTOLOCK_GRACE = timedelta(hours=2)

# Button action ids. Defined here (not in ``actions``) so ``actions`` can import
# them without a cycle; ``app.py`` routes every ``pitwall:`` action to
# ``actions.handle_action`` regardless.
LOCK_SAME = "pitwall:lock_same"
LOCK_EDIT = "pitwall:lock_edit"


def _now() -> datetime:
    """Current UTC instant — one seam tests (and local runs) can freeze."""
    return datetime.now(tz=UTC)


def reminder_hours_before_lock() -> float:
    """Hours before the lock the reminder fires (``PITWALL_REMINDER_HOURS_BEFORE_LOCK``)."""
    raw = os.getenv("PITWALL_REMINDER_HOURS_BEFORE_LOCK", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return REMINDER_HOURS_BEFORE_LOCK


def reminder_time(weekend: RaceWeekend) -> datetime:
    """When the reminder DM goes out: ``fantasy_lock_utc − reminder hours``."""
    return weekend.fantasy_lock_utc - timedelta(hours=reminder_hours_before_lock())


# ── the captain rule and the shared lock path ────────────────────────────────
def _previous_race_key(race_key: str) -> str | None:
    """race_key of the weekend before ``race_key`` by race time, or ``None``."""
    weekend = cal.get_race_weekend(race_key)
    if weekend is None:
        return None
    earlier = [w for w in race_calendar() if w.race_utc < weekend.race_utc]
    return max(earlier, key=lambda w: w.race_utc).race_key if earlier else None


async def captain_for(user_id: str, race_key: str, team: store.Team) -> str | None:
    """The captain to carry over: the player's captain from the *previous* race,
    if that driver is still in their saved team. Otherwise ``None``."""
    prev = _previous_race_key(race_key)
    if prev is None:
        return None
    prev_lock = await store.get_locked(user_id, prev)
    if prev_lock is None or not prev_lock.captain:
        return None
    return prev_lock.captain if prev_lock.captain in team.drivers else None


def _model_lineup_from_projection(projection: dict) -> dict | None:
    """The bot's own pick at lock time, as a plain dict, or ``None``."""
    if not projection:
        return None
    return {
        "drivers": list(projection.get("top_drivers", [])),
        "constructors": list(projection.get("top_constructors", [])),
        "captain": projection.get("captain"),
    }


async def save_lock(
    *,
    user_id: str,
    race_key: str,
    drivers: list[str],
    constructors: list[str],
    chip: str | None,
    captain: str | None,
    client,
) -> tuple[dict | None, BaseException | None]:
    """Project the bot's own pick and save the lock — the one save path.

    Shared by ``/pitwall lock``, the ✅ button and the auto-lock so the bot's
    pick is stored identically everywhere. The projection may come back empty or
    raise (``OpenF1Paused`` during a lockout, an outage otherwise); the lock
    still saves, and the error is returned so a caller can word its confirmation.
    """
    projection_error: BaseException | None = None
    try:
        projection = await project_race(race_key, client)
    except Exception as exc:  # the lock still saves without the bot's own pick
        logger.warning("lock projection failed user={} race={}: {}", user_id, race_key, exc)
        projection = {}
        projection_error = exc
    model_lineup = _model_lineup_from_projection(projection)

    await store.lock_lineup(
        store.LockedLineup(
            slack_user_id=user_id,
            race_key=race_key,
            drivers=list(drivers),
            constructors=list(constructors),
            chip=chip,
            captain=captain,
            model_lineup=model_lineup,
        )
    )
    return model_lineup, projection_error


async def lock_saved_team(
    *, user_id: str, race_key: str, team: store.Team, client
) -> tuple[str | None, dict | None, BaseException | None]:
    """Lock a player's *saved* team with the captain rule. Used by ✅ and auto-lock."""
    captain = await captain_for(user_id, race_key, team)
    model_lineup, err = await save_lock(
        user_id=user_id,
        race_key=race_key,
        drivers=team.drivers,
        constructors=team.constructors,
        chip=None,
        captain=captain,
        client=client,
    )
    return captain, model_lineup, err


# ── message building (pure) ───────────────────────────────────────────────────
def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _button(text: str, action_id: str, race_key: str) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": text, "emoji": True},
        "action_id": action_id,
        "value": race_key,
    }


def _reminder_buttons(race_key: str) -> dict:
    return {
        "type": "actions",
        "elements": [
            _button("✅ Same team", LOCK_SAME, race_key),
            _button("✏️ Edit", LOCK_EDIT, race_key),
        ],
    }


def _same_team_button(race_key: str) -> dict:
    """Just the ✅ button — kept on the rewritten messages so a later tap works."""
    return {"type": "actions", "elements": [_button("✅ Same team", LOCK_SAME, race_key)]}


def _team_lines(team: store.Team) -> str:
    drivers = " ".join(team.drivers) or "—"
    constructors = " ".join(team.constructors) or "—"
    return f"*Drivers:* {drivers}\n*Constructors:* {constructors}"


def _captain_line(captain: str | None) -> str:
    return f"*Captain on record:* {captain}" if captain else "*No captain on record*"


def _lineup_compact(drivers: list[str], constructors: list[str], captain: str | None) -> str:
    d = ", ".join(drivers) or "—"
    c = ", ".join(constructors) or "—"
    tail = f" · captain {captain}" if captain else ""
    return f"{d} | {c}{tail}"


def _bot_pick_line(model_lineup: dict | None) -> str | None:
    if not model_lineup or not model_lineup.get("drivers"):
        return None
    return "🤖 My pick at lock: " + _lineup_compact(
        list(model_lineup.get("drivers", [])),
        list(model_lineup.get("constructors", [])),
        model_lineup.get("captain"),
    )


def reminder_message(
    weekend: RaceWeekend, team: store.Team, captain: str | None
) -> tuple[str, list]:
    """The reminder DM: race, when lock closes, saved team, captain, transfers."""
    lock = weekend.fantasy_lock_utc
    close = slack_date(lock.timestamp(), f"{lock:%a %d %b %H:%M} UTC")
    hours = reminder_hours_before_lock()
    lines = [
        f"*{weekend.display_name} — lock reminder*",
        f"Lock closes {close} (in ~{hours:g} h).",
        "",
        "*Your saved team*",
        _team_lines(team),
        _captain_line(captain),
        f"*Free transfers:* {team.transfers_available}",
        "",
        "If nothing changes, this team locks automatically at the deadline.",
    ]
    text = "\n".join(lines)
    return text, [_section(text), _reminder_buttons(weekend.race_key)]


def locked_message(
    weekend: RaceWeekend, team: store.Team, captain: str | None, model_lineup: dict | None
) -> tuple[str, list]:
    """The DM after a ✅ lock: what was locked, plus the bot's pick if it has one."""
    lines = [f"🔒 Locked: {_lineup_compact(team.drivers, team.constructors, captain)}"]
    bot_line = _bot_pick_line(model_lineup)
    if bot_line:
        lines.append(bot_line)
    lines.append(f"Run `/pitwall score` after the {weekend.display_name} to see how it went.")
    text = "\n".join(lines)
    return text, [_section(text), _same_team_button(weekend.race_key)]


_EDIT_INSTRUCTIONS = (
    "Two ways to change your call:\n"
    "• Update your saved squad: "
    "`/pitwall team HAM LEC NOR PIA VER MCL FER budget 1.5 transfers 2` "
    "— `budget` is the money left after your team.\n"
    "• Lock something different right now: `/pitwall lock <lineup> captain XXX`.\n"
    "Tap *✅ Same team* once your saved team is how you want it."
)


def edit_message(race_key: str) -> tuple[str, list]:
    """The DM after ✏️ Edit: the two commands, with the ✅ button still present."""
    return _EDIT_INSTRUCTIONS, [_section(_EDIT_INSTRUCTIONS), _same_team_button(race_key)]


def closed_message(weekend: RaceWeekend) -> tuple[str, list]:
    """The DM when ✅ is tapped after the deadline: nothing is saved."""
    text = f"Lock for the {weekend.display_name} has closed."
    return text, [_section(text)]


# ── button handling (called by actions.handle_action) ────────────────────────
def _button_race_key(message: dict, action_id: str) -> str | None:
    for block in message.get("blocks", []):
        if block.get("type") != "actions":
            continue
        for element in block.get("elements", []):
            if element.get("action_id") == action_id:
                return element.get("value")
    return None


def _message_race_key(message: dict) -> str | None:
    """The race_key carried on either button, or the next weekend as a fallback."""
    rk = _button_race_key(message, LOCK_SAME) or _button_race_key(message, LOCK_EDIT)
    if rk:
        return rk
    weekend = get_next_race_weekend()
    return weekend.race_key if weekend is not None else None


async def on_lock_same(
    *, user_id: str, message: dict, team_id: str, poster: Poster | None, client=None
) -> tuple[str, list]:
    """✅ Same team: lock the saved team (unless the deadline has passed)."""
    race_key = _message_race_key(message)
    weekend = cal.get_race_weekend(race_key) if race_key else None
    if weekend is None:
        text = "That race isn't on the calendar any more."
        return text, [_section(text)]
    if _now() >= weekend.fantasy_lock_utc:
        return closed_message(weekend)

    team = await store.get_team(user_id)
    if team is None or not team.drivers:
        text = "I don't have a saved team to lock. Save one with `/pitwall team …`."
        return text, [_section(text)]

    captain, model_lineup, _err = await lock_saved_team(
        user_id=user_id, race_key=race_key, team=team, client=client or build_client()
    )
    # The same one-line channel note `/pitwall lock` posts — user-triggered, so
    # it doesn't count against the weekly cap.
    if poster is not None and team_id:
        await LeaguePoster(poster, team_id).post_league(
            "lock",
            f"🔒 <@{user_id}> locked in for the {weekend.display_name}.",
            scheduled=False,
        )
    return locked_message(weekend, team, captain, model_lineup)


def on_lock_edit(message: dict) -> tuple[str, list]:
    """✏️ Edit: rewrite the DM with the two commands; keep the ✅ button."""
    return edit_message(_message_race_key(message) or "")


# ── scheduler jobs ────────────────────────────────────────────────────────────
def _reminder_run(weekend: RaceWeekend, poster: Poster) -> Callable[[], Awaitable[None]]:
    race_key = weekend.race_key

    async def run() -> None:
        for team in await store.list_teams():
            if not team.drivers:
                continue  # no saved team to remind about
            if not await store.get_dms_enabled(team.slack_user_id):
                continue  # opted out of reminder DMs (still auto-locked later)
            if await store.get_locked(team.slack_user_id, race_key) is not None:
                continue  # already locked this race
            captain = await captain_for(team.slack_user_id, race_key, team)
            text, blocks = reminder_message(weekend, team, captain)
            try:  # one player's DM failing must not stop the others
                await LeaguePoster(poster, team.slack_team_id).dm_player(
                    team.slack_user_id, text, blocks
                )
            except Exception as exc:
                logger.warning("reminder DM to {} failed: {}", team.slack_user_id, exc)

    return run


def _autolock_run(weekend: RaceWeekend) -> Callable[[], Awaitable[None]]:
    race_key = weekend.race_key

    async def run() -> None:
        client = build_client()
        locked = 0
        for team in await store.list_teams():
            if not team.drivers:
                continue
            if await store.get_locked(team.slack_user_id, race_key) is not None:
                continue  # they already locked (by command or ✅)
            await lock_saved_team(
                user_id=team.slack_user_id, race_key=race_key, team=team, client=client
            )
            locked += 1
        logger.info("auto-locked {} player(s) for {}", locked, race_key)

    return run


def build_reminder_jobs(weekend: RaceWeekend, poster: Poster) -> list[Job]:
    """The reminder DM job and the auto-lock job for one weekend."""
    return [
        Job(
            key=f"reminder:{weekend.race_key}",
            due_at=reminder_time(weekend),
            run=_reminder_run(weekend, poster),
        ),
        Job(
            key=f"autolock:{weekend.race_key}",
            due_at=weekend.fantasy_lock_utc - _AUTOLOCK_LEAD,
            run=_autolock_run(weekend),
            grace=_AUTOLOCK_GRACE,
        ),
    ]


def reminder_jobs(poster: Poster) -> list[Job]:
    """Reminder + auto-lock jobs for the next race weekend, or none off-season."""
    weekend = get_next_race_weekend()
    return build_reminder_jobs(weekend, poster) if weekend is not None else []
