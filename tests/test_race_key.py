"""race_key utility tests."""

from __future__ import annotations

from utils.race_key import make_race_key, parse_race_key


def test_make_race_key_matches_calendar() -> None:
    assert make_race_key(2026, "monaco") == "2026_monaco"
    assert make_race_key(2024, "Monaco", round_number=8) == "2024_monaco"


def test_parse_race_key() -> None:
    assert parse_race_key("2026_monaco") == (2026, "monaco")
    assert parse_race_key("bad") is None
