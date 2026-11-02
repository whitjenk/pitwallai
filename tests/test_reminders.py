"""Lock reminders, the ✅/✏️ buttons and the auto-lock (brief 014).

Frozen clock + temp DB + FakePoster, no network: ``project_race`` is
monkeypatched wherever the lock path runs so no OpenF1 call happens.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import store
from core import calendar as cal
from slack_app import reminders
from slack_app.actions import handle_action
from slack_app.poster import FakePoster
from store import db as store_db

_VEGAS = "2026_las_vegas"
_LOCK = datetime(2026, 11, 21, 4, 0, tzinfo=UTC)  # fantasy lock = quali start
_BEFORE = _LOCK - timedelta(hours=3)
_AFTER = _LOCK + timedelta(minutes=5)

# A projection with no VER, so a VER-containing team's bot pick is distinguishable.
_PROJECTION = {"top_drivers": ["LEC", "NOR"], "top_constructors": ["MCL", "FER"], "captain": "LEC"}


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "pitwall.sqlite"
    monkeypatch.setenv("PITWALL_DB_PATH", str(path))
    yield path
    engine = store_db._engines.pop(str(path), None)
    store_db._factories.pop(str(path), None)
    if engine is not None:
        engine.sync_engine.dispose()


def _team(user, *, drivers=("VER", "LEC", "NOR", "PIA", "HAM"), constructors=("MCL", "FER"), transfers=2, team_id="T1"):
    return store.Team(
        slack_user_id=user,
        slack_team_id=team_id,
        display_name=user,
        drivers=list(drivers),
        constructors=list(constructors),
        budget_m=1.5,
        transfers_available=transfers,
    )


async def _fake_project(race_key, client):
    return dict(_PROJECTION, race_key=race_key)


async def _vegas_message(user="U1", captain=None):
    """A reminder DM as Slack would feed it back on a button click."""
    weekend = cal.get_race_weekend(_VEGAS)
    team = await store.get_team(user) or _team(user)
    text, blocks = reminders.reminder_message(weekend, team, captain)
    return {"text": text, "blocks": blocks}


# ── 1. job times ──────────────────────────────────────────────────────────────
def test_vegas_job_times_frozen_clock():
    weekend = cal.get_race_weekend(_VEGAS)
    jobs = {j.key: j for j in reminders.build_reminder_jobs(weekend, FakePoster())}
    assert jobs["reminder:2026_las_vegas"].due_at == datetime(2026, 11, 20, 22, 0, tzinfo=UTC)
    assert jobs["autolock:2026_las_vegas"].due_at == datetime(2026, 11, 21, 3, 59, tzinfo=UTC)
    # Auto-lock keeps a long grace so a deadline outage still locks soon after.
    assert jobs["autolock:2026_las_vegas"].grace == timedelta(hours=2)


def test_reminder_env_override_shifts_the_time(monkeypatch):
    monkeypatch.setenv("PITWALL_REMINDER_HOURS_BEFORE_LOCK", "2")
    weekend = cal.get_race_weekend(_VEGAS)
    jobs = {j.key: j for j in reminders.build_reminder_jobs(weekend, FakePoster())}
    assert jobs["reminder:2026_las_vegas"].due_at == datetime(2026, 11, 21, 2, 0, tzinfo=UTC)


# ── 2. the reminder DM ──────────────────────────────────────────────────────────
async def _run_reminder(poster):
    weekend = cal.get_race_weekend(_VEGAS)
    await reminders._reminder_run(weekend, poster)()


async def test_reminder_dm_content_and_eligibility(tmp_db):
    await store.init_db()
    await store.upsert_team(_team("U-in"))           # eligible
    await store.upsert_team(_team("U-off"))          # DMs off
    await store.upsert_team(_team("U-locked"))       # already locked
    await store.upsert_team(_team("U-noteam", drivers=()))  # no saved team
    await store.set_dms_enabled("U-off", False)
    await store.lock_lineup(
        store.LockedLineup(slack_user_id="U-locked", race_key=_VEGAS, drivers=["VER"], constructors=["MCL"])
    )

    fake = FakePoster()
    await _run_reminder(fake)

    # Only the one eligible player was DMed.
    assert [d.user_id for d in fake.dms] == ["U-in"]
    dm = fake.dms[0]
    assert dm.text and "<!date^" in dm.blocks[0]["text"]["text"]  # a date token
    assert "No captain on record" in dm.text          # captain line (no prev race)
    assert "Free transfers:" in dm.text
    assert "locks automatically at the deadline" in dm.text
    # Both buttons, and plain-text fallback is set.
    ids = {el["action_id"] for b in dm.blocks if b.get("type") == "actions" for el in b["elements"]}
    assert ids == {reminders.LOCK_SAME, reminders.LOCK_EDIT}
    assert dm.text == dm.blocks[0]["text"]["text"]  # plain-text fallback mirrors the body


async def test_reminder_shows_carried_captain(tmp_db):
    await store.init_db()
    await store.upsert_team(_team("U1"))  # VER is in the team
    prev = reminders._previous_race_key(_VEGAS)
    await store.lock_lineup(
        store.LockedLineup(slack_user_id="U1", race_key=prev, drivers=["VER"], constructors=["MCL"], captain="VER")
    )
    fake = FakePoster()
    await _run_reminder(fake)
    assert "*Captain on record:* VER" in fake.dms[0].text


class _RaiseForOne(FakePoster):
    def __init__(self, bad):
        super().__init__()
        self._bad = bad

    async def dm(self, user_id, text, blocks=None):
        if user_id == self._bad:
            raise RuntimeError("Slack blew up")
        return await super().dm(user_id, text, blocks)


async def test_one_failing_dm_does_not_stop_the_rest(tmp_db):
    await store.init_db()
    for u in ("U-a", "U-b", "U-c"):
        await store.upsert_team(_team(u))
    fake = _RaiseForOne("U-b")
    await _run_reminder(fake)
    # U-b raised, but U-a and U-c still got theirs.
    assert {d.user_id for d in fake.dms} == {"U-a", "U-c"}


# ── 3. ✅ Same team ─────────────────────────────────────────────────────────────
async def test_lock_same_before_deadline_locks_and_posts(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(reminders, "project_race", _fake_project)
    monkeypatch.setattr(reminders, "_now", lambda: _BEFORE)
    await store.upsert_team(_team("U1"))
    await store.set_league_config("T1", "C-league", "U-admin")

    fake = FakePoster()
    update = await handle_action(
        action_id=reminders.LOCK_SAME, user_id="U1", message=await _vegas_message("U1"),
        team_id="T1", poster=fake,
    )
    # The saved team was locked, with the bot's pick stored.
    locked = await store.get_locked("U1", _VEGAS)
    assert locked is not None and locked.drivers == ["VER", "LEC", "NOR", "PIA", "HAM"]
    assert locked.model_lineup is not None and locked.model_lineup["drivers"] == ["LEC", "NOR"]
    # The DM was rewritten to a "Locked" confirmation.
    assert "🔒 Locked" in update.text and "My pick at lock" in update.text
    # The channel one-liner went out, user-triggered (not counted against the cap).
    assert len(fake.posts) == 1 and fake.posts[0].channel_id == "C-league"
    assert "locked in for the" in fake.posts[0].text
    assert await store.count_bot_posts("T1", store_db._now().strftime("%G-W%V")) == 0


async def test_lock_same_carries_previous_captain_if_still_in_team(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(reminders, "project_race", _fake_project)
    monkeypatch.setattr(reminders, "_now", lambda: _BEFORE)
    await store.upsert_team(_team("U1"))  # VER present
    prev = reminders._previous_race_key(_VEGAS)
    await store.lock_lineup(
        store.LockedLineup(slack_user_id="U1", race_key=prev, drivers=["VER"], constructors=["MCL"], captain="VER")
    )
    await handle_action(
        action_id=reminders.LOCK_SAME, user_id="U1", message=await _vegas_message("U1"),
        team_id="T1", poster=FakePoster(),
    )
    assert (await store.get_locked("U1", _VEGAS)).captain == "VER"


async def test_lock_same_no_captain_when_previous_driver_gone(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(reminders, "project_race", _fake_project)
    monkeypatch.setattr(reminders, "_now", lambda: _BEFORE)
    # Saved team has no RUS, so last race's RUS captain can't carry over.
    await store.upsert_team(_team("U1", drivers=("VER", "LEC", "NOR", "PIA", "HAM")))
    prev = reminders._previous_race_key(_VEGAS)
    await store.lock_lineup(
        store.LockedLineup(slack_user_id="U1", race_key=prev, drivers=["RUS"], constructors=["MER"], captain="RUS")
    )
    await handle_action(
        action_id=reminders.LOCK_SAME, user_id="U1", message=await _vegas_message("U1"),
        team_id="T1", poster=FakePoster(),
    )
    assert (await store.get_locked("U1", _VEGAS)).captain is None


async def test_lock_same_still_locks_when_projection_fails(tmp_db, monkeypatch):
    await store.init_db()

    async def boom(race_key, client):
        raise RuntimeError("OpenF1 down")

    monkeypatch.setattr(reminders, "project_race", boom)
    monkeypatch.setattr(reminders, "_now", lambda: _BEFORE)
    await store.upsert_team(_team("U1"))
    update = await handle_action(
        action_id=reminders.LOCK_SAME, user_id="U1", message=await _vegas_message("U1"),
        team_id="T1", poster=FakePoster(),
    )
    locked = await store.get_locked("U1", _VEGAS)
    assert locked is not None and locked.model_lineup is None  # saved without a bot pick
    assert "🔒 Locked" in update.text


async def test_lock_same_after_deadline_saves_nothing(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(reminders, "_now", lambda: _AFTER)
    await store.upsert_team(_team("U1"))
    update = await handle_action(
        action_id=reminders.LOCK_SAME, user_id="U1", message=await _vegas_message("U1"),
        team_id="T1", poster=FakePoster(),
    )
    assert await store.get_locked("U1", _VEGAS) is None
    assert "has closed" in update.text


async def test_double_click_leaves_one_lock(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(reminders, "project_race", _fake_project)
    monkeypatch.setattr(reminders, "_now", lambda: _BEFORE)
    await store.upsert_team(_team("U1"))
    msg = await _vegas_message("U1")
    await handle_action(action_id=reminders.LOCK_SAME, user_id="U1", message=msg, team_id="T1", poster=FakePoster())
    update = await handle_action(action_id=reminders.LOCK_SAME, user_id="U1", message=msg, team_id="T1", poster=FakePoster())
    assert "🔒 Locked" in update.text
    locked = [lk for w in cal.CALENDAR_2026 if (lk := await store.get_locked("U1", w.race_key))]
    assert len(locked) == 1


# ── 4. ✏️ Edit ──────────────────────────────────────────────────────────────────
async def test_lock_edit_rewrites_with_commands_and_keeps_same_button(tmp_db):
    await store.init_db()
    await store.upsert_team(_team("U1"))
    update = await handle_action(
        action_id=reminders.LOCK_EDIT, user_id="U1", message=await _vegas_message("U1"),
        team_id="T1", poster=FakePoster(),
    )
    assert "/pitwall team" in update.text and "/pitwall lock" in update.text
    ids = {el["action_id"] for b in update.blocks if b.get("type") == "actions" for el in b["elements"]}
    assert ids == {reminders.LOCK_SAME}  # ✅ stays so they can still tap it


# ── 5. auto-lock ────────────────────────────────────────────────────────────────
async def test_autolock_locks_only_unlocked_players(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(reminders, "project_race", _fake_project)
    await store.upsert_team(_team("U-free"))        # VER in team
    await store.upsert_team(_team("U-already"))
    await store.lock_lineup(
        store.LockedLineup(slack_user_id="U-already", race_key=_VEGAS, drivers=["LEC"], constructors=["FER"], captain="LEC")
    )
    # U-free carried a VER captain from last race.
    prev = reminders._previous_race_key(_VEGAS)
    await store.lock_lineup(
        store.LockedLineup(slack_user_id="U-free", race_key=prev, drivers=["VER"], constructors=["MCL"], captain="VER")
    )

    fake = FakePoster()
    weekend = cal.get_race_weekend(_VEGAS)
    await reminders._autolock_run(weekend)()

    free = await store.get_locked("U-free", _VEGAS)
    assert free is not None and free.captain == "VER"       # captain rule applied
    # The already-locked player is untouched.
    assert (await store.get_locked("U-already", _VEGAS)).drivers == ["LEC"]
    # Nothing posted, nobody DMed.
    assert fake.posts == [] and fake.dms == []


# ── 7. dms off/on ───────────────────────────────────────────────────────────────
async def test_opted_out_player_gets_no_reminder_but_is_still_autolocked(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(reminders, "project_race", _fake_project)
    await store.upsert_team(_team("U-off"))
    await store.set_dms_enabled("U-off", False)

    fake = FakePoster()
    weekend = cal.get_race_weekend(_VEGAS)
    await reminders._reminder_run(weekend, fake)()
    assert fake.dms == []  # opted out: no reminder DM

    await reminders._autolock_run(weekend)()
    assert await store.get_locked("U-off", _VEGAS) is not None  # still auto-locked
