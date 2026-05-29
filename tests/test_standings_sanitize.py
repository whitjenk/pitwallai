"""Standings extractor output sanitization."""

from __future__ import annotations

from intelligence.standings_extractor import StandingsEntry, _sanitize_name


def test_sanitize_name_strips_control_chars_and_truncates():
    raw = "A" * 100 + "\x00evil"
    assert _sanitize_name(raw) == "A" * 80
    assert _sanitize_name("  \n\t  ") is None


def test_sanitize_name_on_entry_copy():
    entry = StandingsEntry(user_name="Leader\x01", position=1)
    cleaned = entry.model_copy(update={"user_name": _sanitize_name(entry.user_name)})
    assert cleaned.user_name == "Leader"
