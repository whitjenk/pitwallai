"""`/pitwall channel` and `/pitwall ping` (brief 013) — a fake poster, no Slack."""

from __future__ import annotations

import pytest

import store
from slack_app import handlers
from slack_app.poster import FakePoster
from slack_app.reply import EPHEMERAL
from store import db as store_db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "pitwall.sqlite"
    monkeypatch.setenv("PITWALL_DB_PATH", str(path))
    yield path
    engine = store_db._engines.pop(str(path), None)
    store_db._factories.pop(str(path), None)
    if engine is not None:
        engine.sync_engine.dispose()


async def _call(text, *, channel_id="C-league", poster=None):
    return await handlers.handle(
        text,
        user_id="U-admin",
        team_id="T1",
        display_name="Alice",
        channel_id=channel_id,
        poster=poster or FakePoster(),
    )


# ── /pitwall channel ──────────────────────────────────────────────────────────
async def test_channel_success_saves_config_and_admin(tmp_db):
    await store.init_db()
    fake = FakePoster()
    reply = await _call("channel", channel_id="C-league", poster=fake)
    assert reply.visibility == EPHEMERAL
    assert "admin" in reply.text.lower()
    # The intro was posted to the channel the command ran in...
    assert len(fake.posts) == 1 and fake.posts[0].channel_id == "C-league"
    assert "4 posts a race week" in fake.posts[0].text
    # ...and the config saved, with the caller as admin.
    config = await store.get_league_config("T1")
    assert config is not None
    assert config.channel_id == "C-league"
    assert config.admin_user_id == "U-admin"


async def test_channel_not_in_channel_saves_nothing_and_hints_invite(tmp_db):
    await store.init_db()
    fake = FakePoster(fail_post="not_in_channel")
    reply = await _call("channel", channel_id="C-league", poster=fake)
    assert reply.visibility == EPHEMERAL
    assert "/invite @PitWallAI" in reply.text
    assert await store.get_league_config("T1") is None  # nothing saved


async def test_channel_in_a_dm_is_refused(tmp_db):
    await store.init_db()
    fake = FakePoster()
    reply = await _call("channel", channel_id="D-123", poster=fake)
    assert reply.visibility == EPHEMERAL
    assert "league channel" in reply.text.lower()
    assert fake.posts == []  # didn't try to post
    assert await store.get_league_config("T1") is None


async def test_channel_moves_to_another_channel(tmp_db):
    await store.init_db()
    await _call("channel", channel_id="C-old", poster=FakePoster())
    assert (await store.get_league_config("T1")).channel_id == "C-old"
    # Re-running elsewhere moves it.
    await _call("channel", channel_id="C-new", poster=FakePoster())
    assert (await store.get_league_config("T1")).channel_id == "C-new"


async def test_channel_status_shows_the_config(tmp_db):
    await store.init_db()
    await _call("channel", channel_id="C-league", poster=FakePoster())
    reply = await _call("channel status", channel_id="C-league", poster=FakePoster())
    assert reply.visibility == EPHEMERAL
    assert "C-league" in reply.text
    assert "<@U-admin>" in reply.text


async def test_channel_status_with_nothing_set(tmp_db):
    await store.init_db()
    reply = await _call("channel status", poster=FakePoster())
    assert reply.visibility == EPHEMERAL
    assert "no league channel" in reply.text.lower()


# ── /pitwall ping ───────────────────────────────────────────────────────────
async def test_ping_dms_the_caller_with_a_button(tmp_db):
    await store.init_db()
    fake = FakePoster()
    reply = await _call("ping", poster=fake)
    assert reply.visibility == EPHEMERAL
    assert len(fake.dms) == 1 and fake.dms[0].user_id == "U-admin"
    # The DM carries the "Got it" button.
    blocks = fake.dms[0].blocks
    assert any(
        el.get("action_id") == "pitwall:ping_ok"
        for b in blocks
        if b.get("type") == "actions"
        for el in b["elements"]
    )


async def test_ping_failure_reports_the_error_code(tmp_db):
    await store.init_db()
    fake = FakePoster(fail_dm="cannot_dm_bot")
    reply = await _call("ping", poster=fake)
    assert reply.visibility == EPHEMERAL
    assert "cannot_dm_bot" in reply.text


# ── help ──────────────────────────────────────────────────────────────────────
async def test_help_lists_channel_and_ping():
    reply = await handlers.handle("help", user_id="U1", team_id="T1")
    for cmd in ("channel", "ping"):
        assert cmd in reply.text
