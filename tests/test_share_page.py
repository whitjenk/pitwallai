"""Tests for accessible share page rendering."""

from __future__ import annotations

from intelligence.season_recap import SeasonRecap, SessionSnapshot
from intelligence.share_page import render_season_share_html


def _sample_recap() -> SeasonRecap:
    return SeasonRecap(
        season=2026,
        personalized_accuracy_pct=61.0,
        community_accuracy_pct=58.0,
        best_call="ALB at Monaco (+12 pts)",
        worst_call="SAI at Silverstone (-9 pts)",
        biggest_signal="practice sentiment was 71% predictive",
        share_url="https://pitwallai.app/you/test",
    )


def test_share_page_uses_accessible_trend_pills() -> None:
    html = render_season_share_html(
        _sample_recap(),
        session=SessionSnapshot(
            circuit_label="Abu Dhabi Grand Prix",
            hit_pct=67.0,
            avg_points_delta=2.3,
            momentum_trend="up",
            momentum_delta_pp=8,
        ),
        page_title="PitWallAI 2026 Season Recap",
        meta_description="test",
    )
    assert 'data-trend="up"' in html
    assert "role=\"status\"" in html
    assert "Improved 8 pts" in html
    assert "--pw-trend-up" in html
    assert "--pw-trend-down" in html


def test_share_page_community_ahead_teal_not_red() -> None:
    html = render_season_share_html(
        _sample_recap(),
        session=None,
        page_title="title",
        meta_description="desc",
    )
    assert "+3 vs community" in html
    assert 'data-trend="up"' in html
    assert "#5ae0c8" in html.lower() or "5ae0c8" in html.lower()
