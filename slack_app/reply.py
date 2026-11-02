"""The value a handler returns: reply text plus who can see it.

Kept tiny and platform-neutral so handlers are plain async functions a test can
call without Slack. ``app.py`` turns a :class:`Reply` into a Slack response
(``response_type`` ``ephemeral`` or ``in_channel``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Slack's two slash-command response types.
EPHEMERAL = "ephemeral"  # only the user who ran the command sees it
IN_CHANNEL = "in_channel"  # posted to the whole channel

# Slack renders <!date^UNIX^{token}|fallback> in each reader's own time zone.
_DATE_TOKEN = re.compile(r"<!date\^\d+\^[^|]*\|([^>]*)>")


def slack_date(unix_ts: float, fallback: str, *, token: str = "{time}") -> str:
    """A Slack date mrkdwn token that each reader sees in their own time zone.

    ``fallback`` is shown anywhere the token can't render (older clients, the
    CLI); keep it a plain UTC string so it still reads correctly.
    """
    return f"<!date^{int(unix_ts)}^{token}|{fallback}>"


def to_plain_text(text: str) -> str:
    """Replace every Slack date token with its fallback — for non-Slack output."""
    return _DATE_TOKEN.sub(r"\1", text)


@dataclass(frozen=True)
class Reply:
    """A reply from a handler: the text and its visibility.

    Everything in brief 006 is personal, so ``visibility`` defaults to
    ``ephemeral``. League banter (brief 007) will pass ``IN_CHANNEL``.
    """

    text: str
    visibility: str = EPHEMERAL
