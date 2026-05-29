"""Static results page generator tests."""

from __future__ import annotations

from db.scorer import RaceResult, SeasonAccuracy
from scripts.generate_results_page import no_data_body, render_html, results_body


def test_render_no_data_state() -> None:
    html = render_html(None, season=2026)
    assert "<!DOCTYPE html>" in html
    assert "No races scored yet" in html
    assert "SUBSCRIBE" in html
    assert "<script" not in html.lower()


def test_render_with_results() -> None:
    stats = SeasonAccuracy(
        season=2026,
        races_scored=2,
        correct_picks=1,
        hit_rate_pct=50.0,
        best_race_name="Monaco Grand Prix",
        best_race_pct=100.0,
        results=[
            RaceResult(
                race_name="Monaco Grand Prix",
                round_number=6,
                pick_driver="NOR",
                actual_top_scorer="LEC",
                fantasy_points=18.0,
                was_correct=True,
                race_date="2026-05-25",
            ),
            RaceResult(
                race_name="Spanish Grand Prix",
                round_number=7,
                pick_driver="VER",
                actual_top_scorer="NOR",
                fantasy_points=-5.0,
                was_correct=False,
                race_date="2026-06-14",
            ),
        ],
    )
    html = render_html(stats, season=2026)
    assert "50%" in html
    assert "Monaco Grand Prix" in html
    assert "NOR" in html
    assert "✓" in html
    assert "✗" in html
    assert results_body(stats).count("<tr>") >= 2


def test_no_data_body_has_cta() -> None:
    body = no_data_body(2026)
    assert "Text SUBSCRIBE" in body
