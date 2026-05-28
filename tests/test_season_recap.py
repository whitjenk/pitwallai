"""Tests for season recap utilities."""

from __future__ import annotations

from intelligence.season_recap import build_share_token, parse_share_token


def test_build_share_token_is_stable_and_opaque() -> None:
    token_a = build_share_token(phone="+15551234567", season=2026, secret="s3cr3t")
    token_b = build_share_token(phone="+15551234567", season=2026, secret="s3cr3t")
    token_c = build_share_token(phone="+15551234567", season=2026, secret="different")
    assert token_a == token_b
    assert token_a != token_c
    assert "." in token_a
    assert "+1555" not in token_a


def test_parse_share_token_round_trip() -> None:
    token = build_share_token(phone="+15551234567", season=2026, secret="s3cr3t")
    parsed = parse_share_token(token, "s3cr3t")
    assert parsed == ("+15551234567", 2026)
    assert parse_share_token(token, "wrong-secret") is None
