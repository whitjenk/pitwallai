"""Slack date-token formatting helpers (brief 012)."""

from __future__ import annotations

from slack_app.reply import slack_date, to_plain_text


def test_slack_date_builds_a_date_token():
    token = slack_date(1762538400, "16:30 UTC")
    assert token == "<!date^1762538400^{time}|16:30 UTC>"


def test_to_plain_text_replaces_token_with_its_fallback():
    text = f"It's back around {slack_date(1762538400, '16:30 UTC')} (in ~40 min)."
    assert to_plain_text(text) == "It's back around 16:30 UTC (in ~40 min)."
    assert "<!date^" not in to_plain_text(text)


def test_to_plain_text_leaves_plain_text_untouched():
    assert to_plain_text("no tokens here") == "no tokens here"
