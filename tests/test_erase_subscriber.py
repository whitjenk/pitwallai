"""Ensure DELETE erasure covers every table with a phone / reporter_phone column."""

from __future__ import annotations

from db.models import Base
from intelligence.repository import _ERASE_PHONE_TARGETS


def _phone_columns_in_schema() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if column.name in ("phone", "reporter_phone"):
                found.add((table.name, column.name))
    return found


def test_erase_targets_cover_all_phone_columns() -> None:
    """Every PII phone column must be erased explicitly or via subscriber CASCADE."""
    explicit = {(model.__tablename__, col) for model, col in _ERASE_PHONE_TARGETS}
    # subscribers.phone is removed by session.delete(row), not a WHERE delete.
    explicit.add(("subscribers", "phone"))
    # fantasy_teams, team_onboarding_state, league_onboarding_state CASCADE on subscriber delete.
    cascade = {
        ("fantasy_teams", "phone"),
        ("team_onboarding_state", "phone"),
        ("league_onboarding_state", "phone"),
    }
    covered = explicit | cascade
    assert _phone_columns_in_schema() == covered
