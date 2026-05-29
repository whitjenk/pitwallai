"""Tests for the Phase 1 public surfaces: homepage, sample, OG metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from db.models import ShareCard
from intelligence.called_recap import build_called_recap
from intelligence.called_recap_page import render_called_recap_share_html
from intelligence.chip_planner import ChipPlan
from intelligence.chips_page import render_chips_share_html
from intelligence.homepage import render_homepage_html
from intelligence.recap_page import render_recap_share_html
from intelligence.sample_page import render_sample_page


# ── Homepage ───────────────────────────────────────────────────────────────


def test_homepage_cold_start_shows_dashes_not_zero_percent() -> None:
    """A 0% hit rate would be a misleading public claim before any race
    has been scored. Cold-start must render '—' for both hit rate and
    subscribers."""
    html = render_homepage_html(
        {
            "active_subscribers": 0,
            "season_hit_rate_pct": 0.0,
            "races_scored": 0,
            "scored_picks": 0,
        }
    )
    assert "<!doctype html>" in html
    # Three "—" placeholders, one per stat column.
    assert html.count("—") >= 3
    assert "no races scored yet" in html
    assert "pre-launch" in html
    # Must not display a misleading "0%" anywhere in the stat block.
    assert ">0%<" not in html


def test_homepage_live_numbers_render() -> None:
    html = render_homepage_html(
        {
            "active_subscribers": 1234,
            "season_hit_rate_pct": 64.0,
            "races_scored": 7,
            "scored_picks": 28,
        }
    )
    assert "1,234" in html  # thousands separator
    assert "64%" in html
    assert "across 28 scored picks" in html
    assert ">7<" in html
    assert "this season" in html


def test_homepage_has_og_metadata() -> None:
    html = render_homepage_html(
        {"active_subscribers": 0, "season_hit_rate_pct": 0.0,
         "races_scored": 0, "scored_picks": 0}
    )
    assert 'property="og:title"' in html
    assert 'name="twitter:card"' in html


def test_homepage_links_to_sample_and_results() -> None:
    html = render_homepage_html(
        {"active_subscribers": 0, "season_hit_rate_pct": 0.0,
         "races_scored": 0, "scored_picks": 0}
    )
    assert 'href="/sample"' in html
    assert 'href="/results"' in html


# ── Sample page ────────────────────────────────────────────────────────────


def test_sample_page_is_marked_as_sample() -> None:
    """Critical: visitors must never confuse the sample with live data."""
    html = render_sample_page()
    assert "Sample" in html
    assert "not live data" in html.lower()


def test_sample_page_shows_three_artifacts() -> None:
    html = render_sample_page()
    assert "WhatsApp pick message" in html
    assert "Race recap card" in html
    assert "Live race call-outs" in html


# ── OG metadata on token share pages ───────────────────────────────────────


def _share_card() -> ShareCard:
    return ShareCard(
        share_token="t",
        phone="+10000000001",
        race_key="2026_test",
        race_name="Test Grand Prix",
        circuit_key="test",
        picks_correct=3,
        picks_total=4,
        accuracy_pct=75.0,
        season_accuracy_pct=64.0,
        pick_details=[],
        is_public=True,
        created_at=datetime.now(tz=UTC),
    )


def test_recap_page_has_og_tags() -> None:
    html = render_recap_share_html(_share_card())
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    assert 'name="twitter:card"' in html
    # Description should carry the actual numbers.
    assert "3/4 picks" in html
    assert "64%" in html


def test_chips_page_has_og_tags() -> None:
    plan = ChipPlan(
        windows=[],
        recommended_sequence=[],
        sprint_warnings=[],
        mini_league_windows=[],
        generated_at=datetime.now(tz=UTC),
        share_token="t",
    )
    html = render_chips_share_html(plan)
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    assert 'name="twitter:card"' in html


def test_called_recap_page_has_og_tags() -> None:
    recap = build_called_recap(
        race_key="2026_test", race_label="Test GP", events=[]
    )
    html = render_called_recap_share_html(recap)
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    assert 'name="twitter:card"' in html
