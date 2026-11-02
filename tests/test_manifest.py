"""The Slack manifest declares exactly the scopes and settings brief 013 needs."""

from __future__ import annotations

from pathlib import Path

import yaml

MANIFEST = Path(__file__).resolve().parents[1] / "slack_app" / "manifest.yaml"


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_bot_scopes_include_im_write():
    scopes = _manifest()["oauth_config"]["scopes"]["bot"]
    assert set(scopes) >= {"commands", "chat:write", "im:write"}


def test_interactivity_is_enabled():
    assert _manifest()["settings"]["interactivity"]["is_enabled"] is True


def test_messages_tab_is_on_and_read_only():
    app_home = _manifest()["features"]["app_home"]
    assert app_home["messages_tab_enabled"] is True
    assert app_home["messages_tab_read_only_enabled"] is True


def test_token_rotation_stays_off():
    # Rotation expires the long-running Socket Mode token — keep it off.
    assert _manifest()["settings"]["token_rotation_enabled"] is False


def test_socket_mode_stays_on():
    assert _manifest()["settings"]["socket_mode_enabled"] is True
