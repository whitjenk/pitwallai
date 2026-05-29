"""Tests for group-chat-moment broadcast generators."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from db.models import FantasyTeam, PickRow
from intelligence.group_chat_moments import (
    FridayDigest,
    build_league_postmortem_from_data,
    render_friday_digest,
    render_league_postmortem,
)


def _pick(was_correct: bool | None = True, code: str = "NOR") -> PickRow:
    return PickRow(
        id=uuid.uuid4(),
        race_key="2026_monaco",
        phone=None,
        driver_code=code,
        pick_rank=1,
        confidence=80.0,
        reasoning="r",
        personalized=False,
        provider="t",
        circuit_key="monaco",
        was_correct=was_correct,
        created_at=datetime.now(tz=UTC),
    )


def test_friday_digest_empty_returns_empty_string() -> None:
    out = render_friday_digest(FridayDigest("Monaco GP", [], []))
    assert out == ""


def test_friday_digest_renders_movers() -> None:
    digest = FridayDigest(
        "Monaco GP",
        [("NOR", "FP2 P1, +0.4s vs teammate"), ("LEC", "tyre confidence dropped")],
        ["weather radar shows rain risk during quali"],
    )
    out = render_friday_digest(digest)
    assert "Monaco GP" in out
    assert "NOR" in out
    assert "rain risk" in out
    assert "Not financial advice" in out


def test_postmortem_cold_start_no_league_data() -> None:
    picks = [_pick(True), _pick(True, "VER"), _pick(False, "LEC")]
    pm = build_league_postmortem_from_data(
        race_label="Monaco GP",
        user_picks=picks,
        league_team=None,
        pitwallai_hit_rate=0.67,
    )
    assert pm.user_position is None
    assert pm.leader_name is None
    assert pm.pitwallai_score_pct > 60.0
    out = render_league_postmortem(pm)
    assert "Monaco" in out
    assert "Not financial advice" in out


def test_postmortem_with_league_standings() -> None:
    team = FantasyTeam(phone="+447700900001")
    team.opponent_profiles = [{
        "entries": [
            {"position": 1, "user_name": "Alice", "points": 1200, "is_user": False},
            {"position": 4, "user_name": "Me", "points": 1000, "is_user": True},
        ]
    }]
    pm = build_league_postmortem_from_data(
        race_label="Monaco GP",
        user_picks=[_pick(True)],
        league_team=team,
        pitwallai_hit_rate=0.75,
    )
    assert pm.user_position == 4
    assert pm.leader_name == "Alice"
    out = render_league_postmortem(pm)
    assert "P4" in out
    assert "Alice" in out
