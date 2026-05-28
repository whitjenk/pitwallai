"""Tests for recap metric labels and GP scoring scope."""

from __future__ import annotations

from uuid import uuid4

from db.models import PickRow
from intelligence.recap_metrics import PICK_SCORING_SCOPE, session_quality_note


def test_session_quality_note_uses_gp_wording() -> None:
    picks = [
        PickRow(
            id=uuid4(),
            race_key="2026_monaco",
            circuit_key="monaco",
            driver_code="LEC",
            was_correct=True,
            actual_points_delta=5.0,
            personalized=True,
        ),
        PickRow(
            id=uuid4(),
            race_key="2026_monaco",
            circuit_key="monaco",
            driver_code="NOR",
            was_correct=False,
            actual_points_delta=-2.0,
            personalized=True,
        ),
    ]
    note = session_quality_note(picks)
    assert note is not None
    assert "GP picks" in note
    assert "race pts" in note
    assert "Grand Prix" in PICK_SCORING_SCOPE
