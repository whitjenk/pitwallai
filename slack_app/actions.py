"""Button-click handlers — plain async functions, testable without Slack (brief 013).

Socket Mode delivers clicks over the same socket as slash commands, so Bolt's
``app.action(...)`` fires with no request URL. ``app.py`` registers one handler
for every action id starting ``pitwall:`` and turns an :class:`ActionUpdate`
into an in-place message edit; everything below is pure, so a test calls it with
a plain ``message`` dict.

No new per-user data: the "who clicked I'm in" list lives in the button's own
``value`` on the message, so there's nothing to forget.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

IM_IN = "pitwall:im_in"
PING_OK = "pitwall:ping_ok"


@dataclass(frozen=True)
class ActionUpdate:
    """How the clicked message should be rewritten in place."""

    text: str
    blocks: list


def _button(blocks: list, action_id: str) -> dict | None:
    """The button element in ``blocks`` with this action id, if present."""
    for block in blocks:
        if block.get("type") != "actions":
            continue
        for element in block.get("elements", []):
            if element.get("action_id") == action_id:
                return element
    return None


def _parse_ids(value: str | None) -> list[str]:
    return [uid for uid in (value or "").split(",") if uid]


def _im_in(user_id: str, message: dict) -> ActionUpdate:
    """Add the clicker to the "In:" line once, keeping the list in the button value."""
    blocks = [dict(b) for b in message.get("blocks", [])]
    button = _button(blocks, IM_IN)
    ids = _parse_ids(button.get("value") if button else "")
    if user_id not in ids:  # at most once per user
        ids.append(user_id)
    value = ",".join(ids)

    # Rebuild the button with the new value.
    for block in blocks:
        if block.get("type") != "actions":
            continue
        elements = []
        for element in block.get("elements", []):
            if element.get("action_id") == IM_IN:
                element = {**element, "value": value}
            elements.append(element)
        block["elements"] = elements

    in_line = "In: " + " ".join(f"<@{uid}>" for uid in ids)
    # Replace an existing "In:" context block, or add one at the end.
    context = {"type": "context", "elements": [{"type": "mrkdwn", "text": in_line}]}
    for i, block in enumerate(blocks):
        if block.get("type") == "context":
            blocks[i] = context
            break
    else:
        blocks.append(context)

    return ActionUpdate(text=message.get("text", ""), blocks=blocks)


def _ping_ok(message: dict) -> ActionUpdate:
    """Collapse the ping DM to a plain acknowledgement, dropping the button."""
    text = "✅ Got it"
    return ActionUpdate(
        text=text, blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    )


async def handle_action(*, action_id: str, user_id: str, message: dict) -> ActionUpdate | None:
    """Route a ``pitwall:`` button click. Unknown ids are ignored (logged)."""
    if action_id == IM_IN:
        return _im_in(user_id, message)
    if action_id == PING_OK:
        return _ping_ok(message)
    logger.info("unknown action id {} — acked and ignored", action_id)
    return None
