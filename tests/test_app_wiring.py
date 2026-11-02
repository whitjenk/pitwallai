"""app.py wiring (brief 013): the action listener is registered, thinly.

Builds the Bolt app with a dummy token (no network, no socket) and checks that a
``pitwall:`` action request matches a registered listener and a slash command
matches another — i.e. both are wired.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

import pytest

from slack_app.app import build_app


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-dummy-for-tests")
    return build_app()


def _request(body: str):
    from slack_bolt.request.async_request import AsyncBoltRequest

    return AsyncBoltRequest(
        body=body, headers={"content-type": ["application/x-www-form-urlencoded"]}
    )


async def _matching_listeners(app, req) -> int:
    from slack_bolt.response import BoltResponse

    hits = 0
    for listener in app._async_listeners:
        if await listener.async_matches(req=req, resp=BoltResponse(status=200)):
            hits += 1
    return hits


async def test_action_listener_is_registered(app):
    payload = {
        "type": "block_actions",
        "user": {"id": "U1"},
        "actions": [{"action_id": "pitwall:im_in", "value": ""}],
        "message": {"blocks": []},
    }
    req = _request("payload=" + urlencode({"p": json.dumps(payload)})[2:])
    assert await _matching_listeners(app, req) == 1


async def test_slash_command_listener_is_registered(app):
    body = urlencode(
        {"command": "/pitwall", "text": "help", "user_id": "U1", "team_id": "T1", "channel_id": "C1"}
    )
    assert await _matching_listeners(app, _request(body)) == 1
