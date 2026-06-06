"""Forgiving name/lineup parsing for messy WhatsApp messages."""

from __future__ import annotations

from intelligence.lineup_parse import (
    resolve_captain,
    resolve_chip,
    resolve_constructors,
    resolve_drivers,
)
from whatsapp.intent import resolve_intent


def test_resolve_drivers_by_full_name_lowercase() -> None:
    msg = "im thinking hamilton, leclerc, antonelli, russell and verstappen"
    assert resolve_drivers(msg) == ["HAM", "LEC", "ANT", "RUS", "VER"]


def test_resolve_drivers_by_first_name_or_nickname() -> None:
    assert resolve_drivers("gonna throw the antonelli kid and max in") == ["ANT", "VER"]
    assert resolve_drivers("captain lewis this week") == ["HAM"]


def test_resolve_constructors_by_name_and_order() -> None:
    assert resolve_constructors("ferrari and mercedes") == ["FER", "MER"]
    assert resolve_constructors("red bull double + mclaren") == ["RBR", "MCL"]


def test_resolve_chip_and_captain_by_name() -> None:
    msg = "ham lec ver rus ant, ferrari merc, going limitless, captain lewis"
    drivers = resolve_drivers(msg)
    assert resolve_chip(msg) == "limitless"
    assert resolve_captain(msg, drivers) == "HAM"


def test_messy_lineup_routes_to_grade() -> None:
    msg = "im thinking hamilton leclerc antonelli russell verstappen, ferrari merc, limitless"
    out = resolve_intent(msg)
    assert out is not None and out.startswith("GRADE")


def test_incidental_name_does_not_misroute() -> None:
    # A single name in a non-lineup question shouldn't trigger GRADE (needs >=3).
    assert resolve_intent("is max worth it") != "GRADE"
