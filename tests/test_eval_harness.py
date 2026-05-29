"""Tests for the eval harness: baselines, calibration, and runner glue."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from db.models import PickRow
from intelligence.eval.baselines import (
    baseline_hit_rate,
    prior_season_winner_baseline,
    top3_chalk_baseline,
)
from intelligence.eval.calibration import (
    ConfidenceBand,
    band_for_confidence,
    calibration_report,
    drift_alert,
)
from intelligence.eval.runner import compute_eval_report


def _pick(*, confidence: float, was_correct: bool | None, driver_code: str = "NOR",
          actual_points_delta: float = 0.0) -> PickRow:
    return PickRow(
        id=uuid.uuid4(),
        race_key="2026_monaco",
        phone=None,
        driver_code=driver_code,
        pick_rank=1,
        confidence=confidence,
        reasoning="test",
        personalized=False,
        provider="test",
        circuit_key="monaco",
        was_correct=was_correct,
        actual_points_delta=actual_points_delta,
        created_at=datetime.now(tz=UTC),
    )


# ── 1. Baselines ─────────────────────────────────────────────────────────────


def test_top3_chalk_returns_three_picks() -> None:
    picks = top3_chalk_baseline("2026_monaco", "monaco")
    assert len(picks) == 3
    assert all(p.rank in {1, 2, 3} for p in picks)
    assert len({p.driver_code for p in picks}) == 3


def test_baseline_hit_rate_full_hit() -> None:
    picks = top3_chalk_baseline("2026_monaco", "monaco")
    positions = {p.driver_code: 1 for p in picks}
    assert baseline_hit_rate(picks, positions) == 1.0


def test_baseline_hit_rate_zero_hit() -> None:
    picks = top3_chalk_baseline("2026_monaco", "monaco")
    positions = {p.driver_code: 15 for p in picks}
    assert baseline_hit_rate(picks, positions) == 0.0


def test_baseline_hit_rate_empty() -> None:
    assert baseline_hit_rate([], {}) == 0.0


def test_prior_season_winner_unknown_circuit_returns_empty() -> None:
    assert prior_season_winner_baseline("monaco", prior_winners={}) == []


def test_prior_season_winner_known_circuit_returns_pick() -> None:
    out = prior_season_winner_baseline("monaco", prior_winners={"monaco": "LEC"})
    assert len(out) == 1
    assert out[0].driver_code == "LEC"


# ── 2. Calibration ───────────────────────────────────────────────────────────


def test_band_for_confidence_buckets() -> None:
    assert band_for_confidence(85) == ConfidenceBand.HIGH
    assert band_for_confidence(70) == ConfidenceBand.HIGH
    assert band_for_confidence(60) == ConfidenceBand.MED
    assert band_for_confidence(50) == ConfidenceBand.MED
    assert band_for_confidence(40) == ConfidenceBand.LOW


def test_calibration_report_empty_picks() -> None:
    reports = calibration_report([])
    assert {r.band for r in reports} == set(ConfidenceBand)
    assert all(r.sample_size == 0 for r in reports)


def test_calibration_report_perfectly_calibrated_high_band() -> None:
    picks = [_pick(confidence=85, was_correct=True) for _ in range(7)] + \
            [_pick(confidence=85, was_correct=False) for _ in range(3)]
    reports = calibration_report(picks)
    high = next(r for r in reports if r.band == ConfidenceBand.HIGH)
    assert high.sample_size == 10
    assert high.hit_rate == 0.7
    assert high.is_well_calibrated


def test_calibration_report_drift_detected() -> None:
    picks = [_pick(confidence=85, was_correct=False) for _ in range(10)]  # 0% hit, target 70%
    reports = calibration_report(picks)
    drifts = drift_alert(reports, min_sample=5)
    assert len(drifts) == 1
    assert drifts[0].band == ConfidenceBand.HIGH


def test_calibration_report_ignores_unscored_picks() -> None:
    picks = [_pick(confidence=85, was_correct=None) for _ in range(5)]
    reports = calibration_report(picks)
    assert all(r.sample_size == 0 for r in reports)


# ── 3. Runner glue ───────────────────────────────────────────────────────────


def test_compute_eval_report_basic_lift() -> None:
    # PitWallAI picks: 2 of 3 hit. Chalk: 0 of 3 hit. Lift should be positive.
    picks = [
        _pick(confidence=85, was_correct=True, driver_code="NOR"),
        _pick(confidence=75, was_correct=True, driver_code="ALB"),
        _pick(confidence=80, was_correct=False, driver_code="STR"),
    ]
    chalk_codes = {p.driver_code for p in top3_chalk_baseline("2026_monaco", "monaco")}
    positions = {code: 15 for code in chalk_codes}  # chalk drivers all finish poorly
    positions.update({"NOR": 1, "ALB": 5})           # pitwall picks hit

    report = compute_eval_report(
        race_key="2026_monaco",
        circuit_key="monaco",
        picks=picks,
        positions=positions,
        prior_winners={"monaco": "LEC"},
    )
    assert report.sample_size == 3
    assert report.pitwallai_hit_rate > report.chalk_hit_rate
    assert report.lift_vs_chalk > 0
