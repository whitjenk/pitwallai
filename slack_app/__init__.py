"""PitWallAI Slack app (brief 006).

A Bolt app in Socket Mode for one friends' league. ``handlers`` holds the
Slack-free logic (``handle`` returns a :class:`Reply`); ``app`` is the thin Bolt
wiring. All F1 logic comes from ``core.api`` and persistence from ``store``.
"""

from __future__ import annotations

from slack_app.handlers import handle
from slack_app.reply import EPHEMERAL, IN_CHANNEL, Reply

__all__ = ["EPHEMERAL", "IN_CHANNEL", "Reply", "handle"]
