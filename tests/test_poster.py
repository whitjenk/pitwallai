"""The poster: the weekly cap and the can't-post alert (brief 013).

Frozen clock, temp DB, a FakePoster — no Slack, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import store
from slack_app.poster import FakePoster, LeaguePoster, iso_week
from store import db as store_db

_TEAM = "T1"
_CHANNEL = "C-league"
_ADMIN = "U-admin"

# Two instants in different ISO weeks.
_WEEK_A = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)  # 2026-W45 (Wed)
_WEEK_B = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)  # 2026-W46 (Wed)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "pitwall.sqlite"
    monkeypatch.setenv("PITWALL_DB_PATH", str(path))
    yield path
    engine = store_db._engines.pop(str(path), None)
    store_db._factories.pop(str(path), None)
    if engine is not None:
        engine.sync_engine.dispose()


async def _with_channel(admin: str | None = _ADMIN) -> None:
    await store.init_db()
    await store.set_league_config(_TEAM, _CHANNEL, admin)


def test_iso_week_label():
    assert iso_week(_WEEK_A) == "2026-W45"
    assert iso_week(_WEEK_B) == "2026-W46"


async def test_no_channel_skips_without_raising(tmp_db):
    await store.init_db()  # no league config set
    lp = LeaguePoster(FakePoster(), _TEAM)
    result = await lp.post_league("reveal", "hi", now=_WEEK_A)
    assert result is None
    assert lp.poster.posts == []  # nothing attempted


async def test_weekly_cap_allows_four_and_refuses_the_fifth(tmp_db):
    await _with_channel()
    fake = FakePoster()
    lp = LeaguePoster(fake, _TEAM)
    for _ in range(4):
        assert (await lp.post_league("reveal", "x", now=_WEEK_A)).ok
    # The 5th scheduled post in the week is refused.
    assert await lp.post_league("reveal", "x", now=_WEEK_A) is None
    assert len(fake.posts) == 4
    assert await store.count_bot_posts(_TEAM, "2026-W45") == 4


async def test_unscheduled_post_is_never_refused_and_does_not_count(tmp_db):
    await _with_channel()
    fake = FakePoster()
    lp = LeaguePoster(fake, _TEAM)
    for _ in range(4):
        await lp.post_league("reveal", "x", now=_WEEK_A)
    # Command-triggered (scheduled=False) still goes out past the cap...
    result = await lp.post_league("manual", "hello", scheduled=False, now=_WEEK_A)
    assert result is not None and result.ok
    assert len(fake.posts) == 5
    # ...and isn't recorded, so the scheduled count is unchanged.
    assert await store.count_bot_posts(_TEAM, "2026-W45") == 4


async def test_new_iso_week_resets_the_count(tmp_db):
    await _with_channel()
    lp = LeaguePoster(FakePoster(), _TEAM)
    for _ in range(4):
        await lp.post_league("reveal", "x", now=_WEEK_A)
    assert await lp.post_league("reveal", "x", now=_WEEK_A) is None
    # A post in the following week succeeds again.
    assert (await lp.post_league("reveal", "x", now=_WEEK_B)).ok
    assert await store.count_bot_posts(_TEAM, "2026-W46") == 1


async def test_failed_post_dms_the_admin_with_kind_channel_and_error(tmp_db):
    await _with_channel()
    fake = FakePoster(fail_post="not_in_channel")
    lp = LeaguePoster(fake, _TEAM)
    result = await lp.post_league("reveal", "x", now=_WEEK_A)
    assert result is not None and not result.ok
    assert len(fake.dms) == 1
    dm = fake.dms[0]
    assert dm.user_id == _ADMIN
    assert "reveal" in dm.text
    assert _CHANNEL in dm.text  # <#C-league>
    assert "not_in_channel" in dm.text
    assert "/invite" in dm.text  # the remedy line
    # A failed post is never recorded.
    assert await store.count_bot_posts(_TEAM, "2026-W45") == 0


async def test_admin_alerted_once_per_kind_and_week(tmp_db):
    await _with_channel()
    fake = FakePoster(fail_post="not_in_channel")
    lp = LeaguePoster(fake, _TEAM)
    await lp.post_league("reveal", "x", now=_WEEK_A)
    await lp.post_league("reveal", "x", now=_WEEK_A)  # same kind + week
    assert len(fake.dms) == 1  # second failure doesn't DM again
    # A different kind in the same week does alert.
    await lp.post_league("lock_reminder", "x", now=_WEEK_A)
    assert len(fake.dms) == 2


async def test_no_admin_logs_and_does_not_raise(tmp_db):
    await _with_channel(admin=None)
    fake = FakePoster(fail_post="is_archived")
    lp = LeaguePoster(fake, _TEAM)
    result = await lp.post_league("reveal", "x", now=_WEEK_A)
    assert result is not None and not result.ok
    assert fake.dms == []  # nobody to alert


async def test_failed_alert_dm_logs_and_does_not_raise(tmp_db):
    await _with_channel()
    fake = FakePoster(fail_post="channel_not_found", fail_dm="cannot_dm_bot")
    lp = LeaguePoster(fake, _TEAM)
    result = await lp.post_league("reveal", "x", now=_WEEK_A)
    assert result is not None and not result.ok
    assert len(fake.dms) == 1  # it tried, the DM failed, no raise


async def test_dm_player_failure_never_alerts_admin(tmp_db):
    await _with_channel()
    fake = FakePoster(fail_dm="user_not_found")
    lp = LeaguePoster(fake, _TEAM)
    result = await lp.dm_player("U-someone", "hello")
    assert not result.ok
    assert len(fake.dms) == 1  # only the player DM; no extra admin alert
    assert fake.dms[0].user_id == "U-someone"
