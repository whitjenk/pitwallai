"""Tests for recap momentum suffix formatting."""

from __future__ import annotations

from intelligence.recap_metrics import momentum_suffix as _momentum_suffix


def test_momentum_suffix_uptrend() -> None:
    assert _momentum_suffix(72.0, 60.0) == " · ↑12 vs last race"


def test_momentum_suffix_downtrend() -> None:
    assert _momentum_suffix(48.0, 60.0) == " · ↓12 vs last race"


def test_momentum_suffix_flat() -> None:
    assert _momentum_suffix(60.0, 60.0) == " · → flat vs last race"


def test_momentum_suffix_no_prior_data() -> None:
    assert _momentum_suffix(60.0, None) == ""
