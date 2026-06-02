"""Natural-language → canonical command intent resolution."""

from __future__ import annotations

import pytest

from whatsapp.intent import resolve_intent


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Chips — the headline ask.
        ("should i play a chip", "CHIPS"),
        ("should I play a chip this weekend?", "CHIPS"),
        ("is it worth using my wildcard?", "CHIPS WILDCARD"),
        ("thinking about limitless", "CHIPS LIMITLESS"),
        ("when do i use no negative", "CHIPS NO_NEGATIVE"),
        # Picks.
        ("who should i pick this week?", "PICKS"),
        ("any recommendations?", "PICKS"),
        ("who do i bring in", "PICKS"),
        # Live alerts.
        ("turn on race alerts", "LIVE ON"),
        ("please stop the alerts", "LIVE OFF"),
        # Budget vs transfers.
        ("how much budget do i have?", "BUDGET"),
        ("how many transfers do i have left", "TRANSFERS"),
        # History vs hit rate.
        ("how am i doing?", "HISTORY"),
        ("how accurate are you?", "STREAK"),
        # Account.
        ("please delete my data", "DELETE"),
        ("i want to unsubscribe", "UNSUBSCRIBE"),
        # Drivers.
        ("tell me about verstappen", "VER"),
        ("why is norris so cheap?", "WHY NOR"),
        ("LEC", "LEC"),
        # Help / greeting fallback.
        ("hello", "HELP"),
        ("what can you do?", "HELP"),
    ],
)
def test_resolve_intent_maps_natural_language(text: str, expected: str) -> None:
    assert resolve_intent(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "12.5",  # budget number mid-onboarding
        "NOR,VER,LEC,ALB,HAM",  # driver list
        "Europe/London",  # timezone
        "UPDATE D4 ALB",  # exact command with args — leave to exact handler
        "",
        "   ",
    ],
)
def test_resolve_intent_returns_none_for_data_and_unmatched(text: str) -> None:
    assert resolve_intent(text) is None


def test_exact_commands_round_trip() -> None:
    # Typing the exact command still resolves to itself (no surprise mangling).
    assert resolve_intent("picks") == "PICKS"
    assert resolve_intent("chips") == "CHIPS"
    assert resolve_intent("help") == "HELP"
