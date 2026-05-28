"""Official F1 Fantasy rules compliance tests."""

from __future__ import annotations

from fantasy.rules import (
    BUDGET_CAP_M,
    FREE_TRANSFERS_PER_RACE,
    MAX_TRANSFERS_WITH_BANK,
    MIN_ASSET_PRICE_M,
    PENALTY_EXTRA_TRANSFER_PTS,
    PENALTY_NOT_CLASSIFIED_RACE,
    PENALTY_NOT_CLASSIFIED_SPRINT,
    driver_points_qualifying,
    driver_points_race,
    driver_points_sprint,
    driver_price_m,
    free_transfer_allowance,
    team_value_m,
    transfer_penalty_points,
    validate_constructor_codes,
    validate_driver_codes,
    validate_team_under_budget,
)


def test_official_race_points_scale() -> None:
    assert driver_points_race(1) == 25
    assert driver_points_race(10) == 1
    assert driver_points_race(11) == 0
    assert driver_points_race(None, classified=False) == PENALTY_NOT_CLASSIFIED_RACE


def test_sprint_dnf_penalty_2026() -> None:
    assert driver_points_sprint(None, classified=False) == PENALTY_NOT_CLASSIFIED_SPRINT


def test_transfer_penalty() -> None:
    assert transfer_penalty_points(2, FREE_TRANSFERS_PER_RACE) == 0
    assert transfer_penalty_points(3, FREE_TRANSFERS_PER_RACE) == -PENALTY_EXTRA_TRANSFER_PTS
    assert transfer_penalty_points(4, MAX_TRANSFERS_WITH_BANK) == -PENALTY_EXTRA_TRANSFER_PTS


def test_budget_cap_example_squad() -> None:
    drivers = ["SAR", "LAW", "BOT", "MAG", "BEA"]
    constructors = ["CAD", "SAU"]
    assert validate_driver_codes(drivers) is None
    assert validate_constructor_codes(constructors) is None
    assert team_value_m(drivers, constructors) <= BUDGET_CAP_M
    assert validate_team_under_budget(drivers, constructors)


def test_validate_driver_codes_unique() -> None:
    assert validate_driver_codes(["VER", "VER", "NOR", "LEC", "HAM"]) is not None


def test_validate_unknown_driver() -> None:
    assert validate_driver_codes(["VER", "NOR", "LEC", "ALB", "ZZZ"]) is not None


def test_quali_points_not_race_scale() -> None:
    assert driver_points_qualifying(1) == 10
    assert driver_points_race(1) == 25


def test_free_transfer_allowance() -> None:
    assert free_transfer_allowance(2) == 2
    assert free_transfer_allowance(99, limitless_chip=False) == 5


def test_min_price_floor() -> None:
    assert driver_price_m("UNK") >= MIN_ASSET_PRICE_M
