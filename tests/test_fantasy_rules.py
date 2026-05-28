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
    driver_points_race,
    driver_points_sprint,
    driver_price_m,
    team_value_m,
    transfer_penalty_points,
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


def test_budget_cap() -> None:
    drivers = ["VER", "NOR", "LEC", "ALB", "HAM"]
    constructors = ["MCL", "RBR"]
    assert team_value_m(drivers, constructors) <= BUDGET_CAP_M or not validate_team_under_budget(
        drivers, constructors
    )


def test_min_price_floor() -> None:
    assert driver_price_m("UNK") >= MIN_ASSET_PRICE_M
