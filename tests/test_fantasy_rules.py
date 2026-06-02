"""Official F1 Fantasy rules compliance tests."""

from __future__ import annotations

from fantasy.rules import (
    BUDGET_CAP_M,
    FREE_TRANSFERS_PER_RACE,
    MAX_TRANSFERS_WITH_BANK,
    MIN_ASSET_PRICE_M,
    PENALTY_CONSTRUCTOR_DRIVER_DSQ,
    PENALTY_EXTRA_TRANSFER_PTS,
    PENALTY_NOT_CLASSIFIED_RACE,
    PENALTY_NOT_CLASSIFIED_SPRINT,
    PENALTY_QUALIFYING_NC,
    PIT_STOP_FASTEST_BONUS,
    PIT_STOP_WORLD_RECORD_BONUS,
    PIT_STOP_WORLD_RECORD_S,
    constructor_pit_stop_points,
    constructor_points_qualifying,
    constructor_points_race,
    constructor_qualifying_progression,
    driver_points_qualifying,
    driver_points_race,
    driver_points_sprint,
    driver_price_m,
    free_transfer_allowance,
    qualifying_phase_counts_from_grid,
    team_value_m,
    transfer_penalty_points,
    transfers_configured,
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
    drivers = ["COL", "LAW", "BOT", "LIN", "BEA"]
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


def test_quali_nc_penalty() -> None:
    assert driver_points_qualifying(None, classified=False) == PENALTY_QUALIFYING_NC
    assert driver_points_qualifying(11) == 0


def test_constructor_qualifying_progression() -> None:
    assert constructor_qualifying_progression(0, 0) == -1
    assert constructor_qualifying_progression(1, 0) == 1
    assert constructor_qualifying_progression(2, 0) == 3
    assert constructor_qualifying_progression(2, 1) == 5
    assert constructor_qualifying_progression(2, 2) == 10


def test_constructor_points_qualifying_sums_drivers_and_progression() -> None:
    pts = constructor_points_qualifying([10, 8], drivers_in_q2=2, drivers_in_q3=2)
    assert pts == 10 + 8 + 10


def test_qualifying_phase_counts_from_grid() -> None:
    q2, q3 = qualifying_phase_counts_from_grid([1, 12])
    assert q3 == 1
    assert q2 == 2


def test_constructor_pit_stop_points_bands() -> None:
    assert constructor_pit_stop_points(3.1) == 0
    assert constructor_pit_stop_points(2.7) == 2
    assert constructor_pit_stop_points(2.3) == 5
    assert constructor_pit_stop_points(2.1) == 10
    assert constructor_pit_stop_points(1.9) == 20


def test_constructor_points_race_includes_pit_and_dsq() -> None:
    base = constructor_points_race([25, 10], pit_stop_duration_s=2.05)
    assert base == 25 + 10 + 10
    fastest = constructor_points_race([25, 10], pit_stop_duration_s=2.4, has_fastest_pit_in_race=True)
    assert fastest == 25 + 10 + 5 + PIT_STOP_FASTEST_BONUS
    record = constructor_points_race(
        [25, 10],
        pit_stop_duration_s=PIT_STOP_WORLD_RECORD_S,
        pit_world_record=True,
    )
    assert record == 25 + 10 + 20 + PIT_STOP_WORLD_RECORD_BONUS
    dsq = constructor_points_race([0, 10], drivers_dsq=1)
    assert dsq == 10 + PENALTY_CONSTRUCTOR_DRIVER_DSQ


def test_free_transfer_allowance() -> None:
    assert free_transfer_allowance(2) == 2
    assert free_transfer_allowance(99, limitless_chip=False) == MAX_TRANSFERS_WITH_BANK
    assert free_transfer_allowance(2, limitless_chip=True) == 5
    assert free_transfer_allowance(-1) == 0
    assert not transfers_configured(-1)
    assert transfers_configured(0)


def test_min_price_floor() -> None:
    assert driver_price_m("UNK") >= MIN_ASSET_PRICE_M
