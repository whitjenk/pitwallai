"""Button-click handlers (brief 013) — pure, no Slack."""

from __future__ import annotations

from slack_app.actions import IM_IN, PING_OK, handle_action


def _intro_message() -> dict:
    return {
        "text": "intro",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "intro"}},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "action_id": IM_IN, "value": "", "text": {"type": "plain_text", "text": "👋 I'm in"}}
                ],
            },
        ],
    }


def _button_value(update) -> str:
    for block in update.blocks:
        if block.get("type") == "actions":
            for element in block["elements"]:
                if element.get("action_id") == IM_IN:
                    return element.get("value", "")
    return ""


def _in_line(update) -> str:
    for block in update.blocks:
        if block.get("type") == "context":
            return block["elements"][0]["text"]
    return ""


async def test_im_in_adds_user_and_updates_message():
    update = await handle_action(action_id=IM_IN, user_id="U1", message=_intro_message())
    assert update is not None
    assert _button_value(update) == "U1"
    assert "<@U1>" in _in_line(update)


async def test_im_in_is_idempotent_per_user():
    message = _intro_message()
    first = await handle_action(action_id=IM_IN, user_id="U1", message=message)
    # Feed the updated message back in, as Slack would on a second click.
    message["blocks"] = first.blocks
    second = await handle_action(action_id=IM_IN, user_id="U1", message=message)
    assert _button_value(second) == "U1"  # not "U1,U1"
    assert _in_line(second).count("<@U1>") == 1


async def test_im_in_appends_a_second_distinct_user():
    message = _intro_message()
    first = await handle_action(action_id=IM_IN, user_id="U1", message=message)
    message["blocks"] = first.blocks
    second = await handle_action(action_id=IM_IN, user_id="U2", message=message)
    assert _button_value(second) == "U1,U2"
    assert "<@U1>" in _in_line(second) and "<@U2>" in _in_line(second)


async def test_ping_ok_collapses_the_dm():
    update = await handle_action(action_id=PING_OK, user_id="U1", message={"text": "ping", "blocks": []})
    assert update is not None
    assert update.text == "✅ Got it"
    # The button is gone.
    assert all(b.get("type") != "actions" for b in update.blocks)


async def test_unknown_action_is_acked_without_error():
    update = await handle_action(action_id="pitwall:mystery", user_id="U1", message={})
    assert update is None  # app.py acks and does nothing
