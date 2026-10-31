"""The value a handler returns: reply text plus who can see it.

Kept tiny and platform-neutral so handlers are plain async functions a test can
call without Slack. ``app.py`` turns a :class:`Reply` into a Slack response
(``response_type`` ``ephemeral`` or ``in_channel``).
"""

from __future__ import annotations

from dataclasses import dataclass

# Slack's two slash-command response types.
EPHEMERAL = "ephemeral"  # only the user who ran the command sees it
IN_CHANNEL = "in_channel"  # posted to the whole channel


@dataclass(frozen=True)
class Reply:
    """A reply from a handler: the text and its visibility.

    Everything in brief 006 is personal, so ``visibility`` defaults to
    ``ephemeral``. League banter (brief 007) will pass ``IN_CHANNEL``.
    """

    text: str
    visibility: str = EPHEMERAL
