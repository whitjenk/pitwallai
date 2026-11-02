"""Posting to Slack — the one seam every social-layer feature goes through (brief 013).

Two layers:

* :class:`Poster` — the low level. ``post(channel_id, …)`` and ``dm(user_id, …)``
  each return a :class:`PostResult` and never raise on a Slack error, so callers
  branch on ``ok`` instead of catching. :class:`SlackPoster` wraps Bolt's
  ``AsyncWebClient``; :class:`FakePoster` records calls for tests and the CLI.
* :class:`LeaguePoster` — the high level later briefs call for scheduled content.
  It knows the league channel, enforces the "at most 4 scheduled posts per ISO
  week" cap, records what it posts, and DMs the admin once per (kind, week) when
  a post fails. It holds no F1 logic.

Command-triggered posts (e.g. the ``/pitwall channel`` intro) and all DMs go
through the low-level :class:`Poster` directly: they don't count against the cap
and aren't recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from loguru import logger

import store

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

# The league agreed at most 4 bot posts in the channel per race week. A race week
# is Monday–Sunday UTC (ISO week). Only scheduled posts count (see module docs).
MAX_SCHEDULED_POSTS_PER_WEEK = 4

# One-line remedies for the Slack error codes a channel post can fail with. Shown
# in the can't-post DM so the admin knows what to do.
_REMEDIES = {
    "not_in_channel": "Invite me back with `/invite @PitWallAI`, then run `/pitwall channel` again.",
    "is_archived": "That channel is archived — unarchive it, or run `/pitwall channel` in a live one.",
    "channel_not_found": "I can't find that channel — run `/pitwall channel` in the one you want.",
}


@dataclass(frozen=True)
class PostResult:
    """The outcome of a post or DM. ``error`` is Slack's error code on failure."""

    ok: bool
    ts: str | None = None
    channel_id: str | None = None
    error: str | None = None


def _now() -> datetime:
    return datetime.now(tz=UTC)


def iso_week(now: datetime) -> str:
    """The ISO week label (e.g. ``2026-W45``) a post counts against."""
    cal = now.isocalendar()
    return f"{cal.year}-W{cal.week:02d}"


class Poster(Protocol):
    """Post to a channel or DM a user. Implementations never raise on Slack errors."""

    async def post(
        self, channel_id: str, text: str, blocks: list | None = None
    ) -> PostResult: ...

    async def dm(
        self, user_id: str, text: str, blocks: list | None = None
    ) -> PostResult: ...


def _error_code(exc: Exception) -> str:
    """Slack's error code from a raised client error, or the exception type."""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            code = response.get("error")
        except AttributeError:
            code = None
        if code:
            return str(code)
    return type(exc).__name__


class SlackPoster:
    """A :class:`Poster` on Bolt's ``AsyncWebClient``. Used live, not in tests."""

    def __init__(self, client: AsyncWebClient) -> None:
        self._client = client

    async def post(
        self, channel_id: str, text: str, blocks: list | None = None
    ) -> PostResult:
        try:
            resp = await self._client.chat_postMessage(
                channel=channel_id, text=text, blocks=blocks
            )
        except Exception as exc:  # Slack or transport error: report, never raise
            return PostResult(ok=False, channel_id=channel_id, error=_error_code(exc))
        return PostResult(
            ok=True, ts=resp.get("ts"), channel_id=resp.get("channel", channel_id)
        )

    async def dm(
        self, user_id: str, text: str, blocks: list | None = None
    ) -> PostResult:
        try:
            opened = await self._client.conversations_open(users=user_id)
            channel_id = opened["channel"]["id"]
            resp = await self._client.chat_postMessage(
                channel=channel_id, text=text, blocks=blocks
            )
        except Exception as exc:
            return PostResult(ok=False, error=_error_code(exc))
        return PostResult(ok=True, ts=resp.get("ts"), channel_id=channel_id)


@dataclass
class SentMessage:
    """One message a :class:`FakePoster` was asked to send."""

    text: str
    blocks: list | None = None
    channel_id: str | None = None
    user_id: str | None = None


class FakePoster:
    """A :class:`Poster` that records calls instead of touching Slack.

    ``fail_post`` / ``fail_dm`` set an error code to return instead of
    succeeding, so a test can drive the failure paths.
    """

    def __init__(self, *, fail_post: str | None = None, fail_dm: str | None = None):
        self.posts: list[SentMessage] = []
        self.dms: list[SentMessage] = []
        self._fail_post = fail_post
        self._fail_dm = fail_dm
        self._ts = 0

    def _next_ts(self) -> str:
        self._ts += 1
        return f"{self._ts}.000100"

    async def post(
        self, channel_id: str, text: str, blocks: list | None = None
    ) -> PostResult:
        self.posts.append(SentMessage(text=text, blocks=blocks, channel_id=channel_id))
        if self._fail_post:
            return PostResult(ok=False, channel_id=channel_id, error=self._fail_post)
        return PostResult(ok=True, ts=self._next_ts(), channel_id=channel_id)

    async def dm(
        self, user_id: str, text: str, blocks: list | None = None
    ) -> PostResult:
        self.dms.append(SentMessage(text=text, blocks=blocks, user_id=user_id))
        if self._fail_dm:
            return PostResult(ok=False, error=self._fail_dm)
        return PostResult(ok=True, ts=self._next_ts(), channel_id=f"D-{user_id}")


def _cant_post_text(kind: str, channel_id: str, error: str | None) -> str:
    text = (
        f"⚠️ I couldn't post the *{kind}* update to <#{channel_id}>. "
        f"Slack said `{error}`."
    )
    remedy = _REMEDIES.get(error or "")
    if remedy:
        text += f"\n{remedy}"
    return text


@dataclass
class LeaguePoster:
    """High-level posting for one workspace's league channel.

    Bound to ``team_id`` so the signatures later briefs use stay small. Holds the
    per-(kind, week) "already alerted the admin" set in memory — persistence
    across a restart isn't needed for a best-effort nudge, and it keeps per-user
    data out of the store.
    """

    poster: Poster
    team_id: str
    _alerted: set[tuple[str, str]] = field(default_factory=set)

    async def post_league(
        self,
        kind: str,
        text: str,
        blocks: list | None = None,
        *,
        scheduled: bool = True,
        now: datetime | None = None,
    ) -> PostResult | None:
        """Post to the league channel, honouring the weekly cap.

        Returns ``None`` when there's nothing to attempt — no channel set, or the
        scheduled cap for the week is already reached — and otherwise the
        :class:`PostResult`. A failed post triggers the can't-post alert.
        """
        config = await store.get_league_config(self.team_id)
        if config is None:
            logger.info("post_league skipped ({}): no league channel set", kind)
            return None
        now = now or _now()
        week = iso_week(now)
        if scheduled:
            count = await store.count_bot_posts(self.team_id, week)
            if count >= MAX_SCHEDULED_POSTS_PER_WEEK:
                logger.info(
                    "post_league refused ({}): weekly cap of {} reached for {}",
                    kind,
                    MAX_SCHEDULED_POSTS_PER_WEEK,
                    week,
                )
                return None
        result = await self.poster.post(config.channel_id, text, blocks=blocks)
        if result.ok:
            if scheduled:
                await store.record_bot_post(
                    self.team_id, config.channel_id, kind, week, result.ts or ""
                )
            return result
        await self._alert_cant_post(config, kind, week, result)
        return result

    async def dm_player(
        self, user_id: str, text: str, blocks: list | None = None
    ) -> PostResult:
        """DM a league-mate. A failure is logged and never alerts the admin."""
        result = await self.poster.dm(user_id, text, blocks=blocks)
        if not result.ok:
            logger.warning("dm_player to {} failed: {}", user_id, result.error)
        return result

    async def _alert_cant_post(
        self, config: store.LeagueConfig, kind: str, week: str, result: PostResult
    ) -> None:
        admin = config.admin_user_id
        if admin is None:
            logger.error(
                "post_league failed ({}) to {} with {}; no admin to alert",
                kind,
                config.channel_id,
                result.error,
            )
            return
        if (kind, week) in self._alerted:
            return
        dm = await self.poster.dm(
            admin, _cant_post_text(kind, config.channel_id, result.error)
        )
        if dm.ok:
            self._alerted.add((kind, week))
        else:
            logger.error(
                "post_league failed ({}) and the alert DM to {} also failed: {}",
                kind,
                admin,
                dm.error,
            )
