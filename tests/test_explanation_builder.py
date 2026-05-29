"""
Tests for pick explanation cards (Bet 1).

``build_explanation()`` is synchronous and reads pre-loaded signals from
``ExplanationBuildContext`` (practice_by_driver, quali_grid). Radio is derived
from ``PracticeSignal.raw_evidence``, not a separate cache call inside the builder.
"""

from __future__ import annotations

from unittest.mock import patch

from circuits.profiles import get_circuit_profile
from intelligence.explanation_attach import attach_explanations
from intelligence.explanation_builder import (
    ExplanationBuildContext,
    _build_field_angle,
    _build_risk_note,
    _select_primary_signal,
    build_explanation,
)
from intelligence.schemas import PickOutput
from models.pick_explanation import PickExplanation, SignalSource
from tests.fixtures_signal_cache import (
    make_pick,
    make_practice,
    make_practice_with_gap,
    make_practice_with_radio,
)

RACE_KEY = "2026_monaco"


def _ctx(**kwargs) -> ExplanationBuildContext:
    return ExplanationBuildContext(
        race_key=RACE_KEY,
        circuit_key="monaco",
        circuit=get_circuit_profile("monaco"),
        **kwargs,
    )


# ── 1. Radio wins when all signals present ────────────────────────────────────


def test_radio_wins_over_practice_when_both_present() -> None:
    """Radio is highest priority — must win over practice teammate-gap signal."""
    pick = make_pick()
    practice = make_practice_with_gap(
        0.8,
        raw_evidence=["radio: Feels planted in sector 2, confidence in tyres."],
    )

    result = build_explanation(pick, _ctx(practice_by_driver={"NOR": practice}, quali_grid={"NOR": 2}))

    assert result is not None
    assert result.signal_source == SignalSource.RADIO
    assert "sector 2" in result.primary_signal.lower()


# ── 2. Practice when radio absent ─────────────────────────────────────────────


def test_falls_back_to_practice_when_no_radio() -> None:
    pick = make_pick()
    practice = make_practice_with_gap(0.6)

    result = build_explanation(pick, _ctx(practice_by_driver={"NOR": practice}))

    assert result is not None
    assert result.signal_source == SignalSource.PRACTICE
    assert "gap vs teammate" in result.primary_signal.lower()


# ── 3. Quali gap when practice and radio absent ────────────────────────────────


def test_falls_back_to_quali_gap() -> None:
    pick = make_pick(driver_code="BOT", confidence=65.0)
    # BOT is cheap (~P17 by price); P8 quali is well above expectation
    result = build_explanation(pick, _ctx(quali_grid={"BOT": 8}))

    assert result is not None
    assert result.signal_source == SignalSource.QUALI
    assert "P8" in result.primary_signal


# ── 4. Price when only price path available ───────────────────────────────────


def test_falls_back_to_price_signal() -> None:
    pick = make_pick(driver_code="ALB", confidence=70.0)

    result = build_explanation(
        pick,
        ExplanationBuildContext(race_key=RACE_KEY, circuit_key="monaco"),
    )

    assert result is not None
    assert result.signal_source == SignalSource.PRICE
    assert "$" in result.primary_signal


# ── 5. None when no signal path ───────────────────────────────────────────────


def test_returns_none_when_no_signal() -> None:
    pick = make_pick(driver_code="BOT", confidence=50.0)

    result = build_explanation(
        pick,
        ExplanationBuildContext(race_key=RACE_KEY, circuit_key="test_circuit"),
    )

    assert result is None


# ── 6. UNKNOWN ownership omits field_angle ───────────────────────────────────


def test_unknown_ownership_omits_field_angle() -> None:
    pick = make_pick(ownership_tier="UNKNOWN", is_contrarian=False)
    practice = make_practice_with_radio(summary="Feels planted in sector 2.")

    result = build_explanation(pick, _ctx(practice_by_driver={"NOR": practice}))

    assert result is not None
    assert result.field_angle is None


# ── 7. primary_signal capped at 120 chars ─────────────────────────────────────


def test_primary_signal_max_120_chars() -> None:
    long_summary = "A" * 200
    practice = make_practice_with_radio(snippet=long_summary)
    pick = make_pick()

    result = build_explanation(pick, _ctx(practice_by_driver={"NOR": practice}))

    assert result is not None
    assert len(result.primary_signal) <= 120


# ── 8. Attach path must not raise on build failure ──────────────────────────────


def test_build_failure_in_attach_does_not_raise() -> None:
    """Broadcast attach catches per-pick failures and omits the card."""
    output = PickOutput(
        picks=[make_pick()],
        personalized=False,
        circuit_note="Monaco street circuit.",
        confidence_note="Signals mixed.",
        generated_by="rules",
    )
    ctx = _ctx()

    with patch(
        "intelligence.explanation_attach.build_explanation",
        side_effect=Exception("DB timeout"),
    ):
        result = attach_explanations(output, ctx, enabled=True)

    assert result.picks[0].explanation is None


# ── 9–10. League angle helpers ────────────────────────────────────────────────


def test_field_angle_contrarian() -> None:
    pick = make_pick(ownership_tier="LOW", is_contrarian=True)
    angle = _build_field_angle(pick)
    assert angle is not None
    assert "contrarian" in angle.lower()


def test_field_angle_consensus() -> None:
    pick = make_pick(ownership_tier="HIGH", is_contrarian=False)
    angle = _build_field_angle(pick)
    assert angle is not None
    assert "consensus" in angle.lower()


# ── 11–12. Risk note helpers ──────────────────────────────────────────────────


def test_risk_note_uses_mechanical_flags() -> None:
    pick = make_pick()
    practice = make_practice(mechanical_flags=["brake overheating"])
    note = _build_risk_note(pick, practice, get_circuit_profile("monaco"), "NOR")
    assert "reliability" in note.lower()


def test_risk_note_mechanical_before_circuit() -> None:
    pick = make_pick(driver_code="NOR")
    practice = make_practice(mechanical_flags=["brake overheating"])
    circuit = get_circuit_profile("monaco")
    note = _build_risk_note(pick, practice, circuit, "NOR")
    assert "brake" in note.lower()
    assert "street circuit" not in note.lower()


# ── 13. Blank radio snippet falls through to practice ─────────────────────────


def test_radio_with_empty_summary_skips_to_practice() -> None:
    pick = make_pick()
    practice = make_practice_with_gap(
        0.5,
        raw_evidence=["radio:   "],  # too short after strip — skipped
    )

    result = build_explanation(pick, _ctx(practice_by_driver={"NOR": practice}))

    assert result is not None
    assert result.signal_source == SignalSource.PRACTICE


# ── 14. Practice gap below 0.3s threshold ───────────────────────────────────


def test_practice_delta_below_threshold_skips() -> None:
    pick = make_pick(driver_code="BOT", confidence=65.0)
    practice = make_practice_with_gap(
        0.2,
        setup_sentiment=0.1,
        tire_confidence=0.4,
        raw_evidence=[],
    )

    result = build_explanation(
        pick,
        _ctx(practice_by_driver={"BOT": practice}, quali_grid={"BOT": 8}),
    )

    assert result is not None
    assert result.signal_source == SignalSource.QUALI


# ── 15. Full card shape ───────────────────────────────────────────────────────


def test_full_card_shape() -> None:
    pick = make_pick(ownership_tier="LOW", is_contrarian=True)
    practice = make_practice_with_radio(summary="Feels planted in sector 2.")

    result = build_explanation(pick, _ctx(practice_by_driver={"NOR": practice}))

    assert isinstance(result, PickExplanation)
    assert isinstance(result.driver_code, str)
    assert isinstance(result.primary_signal, str)
    assert isinstance(result.signal_source, SignalSource)
    assert isinstance(result.risk_note, str)
    assert result.field_angle is None or isinstance(result.field_angle, str)
    assert len(result.primary_signal) > 0
    assert len(result.risk_note) > 0


# ── Existing unit coverage (helpers / formatting) ─────────────────────────────


def test_select_primary_signal_radio_priority() -> None:
    practice = make_practice_with_radio(snippet="planted in sector 2")
    selected = _select_primary_signal(
        make_pick(),
        practice,
        quali_position=1,
        driver_code="NOR",
    )
    assert selected is not None
    assert selected[1] == SignalSource.RADIO


def test_primary_signal_char_limit_on_model() -> None:
    long_text = "x" * 130
    explanation = PickExplanation(
        driver_code="NOR",
        primary_signal=long_text,
        signal_source=SignalSource.PRACTICE,
        risk_note="ok",
    )
    assert len(explanation.primary_signal) <= 120
    assert explanation.primary_signal.endswith("…")


def test_format_explanation_card_lines() -> None:
    from whatsapp.message_format import format_explanation_card

    card = format_explanation_card(
        PickExplanation(
            driver_code="NOR",
            primary_signal="FP2: setup sentiment +0.55.",
            signal_source=SignalSource.PRACTICE,
            risk_note="Limited downside at this price point.",
            field_angle="Contrarian — upside if rivals play chalk this weekend.",
        )
    )
    lines = card.split("\n")
    assert len(lines) <= 3
    assert lines[0].startswith("📊 Signal:")
    assert "⚠️" in lines[1]
