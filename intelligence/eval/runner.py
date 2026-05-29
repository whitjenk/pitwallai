"""Post-race eval runner.

Stitches together: load scored picks → compute calibration → compute baseline
hit rate deltas → emit a structured report. Fires from the post-race scorer
job; logs to stdout so it lands in production logs without extra plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from db.models import PickRow
from intelligence.eval.baselines import (
    BaselinePick,
    baseline_hit_rate,
    prior_season_winner_baseline,
    top3_chalk_baseline,
)
from intelligence.eval.calibration import (
    BandReport,
    calibration_report,
    drift_alert,
)


@dataclass(frozen=True, slots=True)
class EvalReport:
    race_key: str
    sample_size: int
    pitwallai_hit_rate: float
    chalk_hit_rate: float
    prior_winner_hit_rate: float
    lift_vs_chalk: float
    lift_vs_prior_winner: float
    band_reports: list[BandReport]
    drifts: list[BandReport]


def _hit_rate(picks: list[PickRow]) -> float:
    scored = [p for p in picks if p.was_correct is not None]
    if not scored:
        return 0.0
    return sum(1 for p in scored if p.was_correct) / len(scored)


def compute_eval_report(
    race_key: str,
    circuit_key: str,
    picks: list[PickRow],
    positions: dict[str, int],
    prior_winners: dict[str, str],
) -> EvalReport:
    """Compute the full per-race eval. Pure function — caller does I/O."""
    pitwallai_rate = _hit_rate(picks)

    chalk_picks: list[BaselinePick] = top3_chalk_baseline(race_key, circuit_key)
    chalk_rate = baseline_hit_rate(chalk_picks, positions)

    prior_picks = prior_season_winner_baseline(circuit_key, prior_winners=prior_winners)
    prior_rate = baseline_hit_rate(prior_picks, positions) if prior_picks else 0.0

    bands = calibration_report(picks)
    drifts = drift_alert(bands)

    return EvalReport(
        race_key=race_key,
        sample_size=sum(1 for p in picks if p.was_correct is not None),
        pitwallai_hit_rate=pitwallai_rate,
        chalk_hit_rate=chalk_rate,
        prior_winner_hit_rate=prior_rate,
        lift_vs_chalk=pitwallai_rate - chalk_rate,
        lift_vs_prior_winner=pitwallai_rate - prior_rate if prior_picks else 0.0,
        band_reports=bands,
        drifts=drifts,
    )


def log_eval_report(report: EvalReport) -> None:
    """Structured log line per band + headline lifts. Lands in prod logs as-is."""
    logger.bind(eval_race=report.race_key).info(
        "eval_summary race={} n={} pitwall={:.1%} chalk={:.1%} prior={:.1%} "
        "lift_chalk={:+.1%} lift_prior={:+.1%}",
        report.race_key,
        report.sample_size,
        report.pitwallai_hit_rate,
        report.chalk_hit_rate,
        report.prior_winner_hit_rate,
        report.lift_vs_chalk,
        report.lift_vs_prior_winner,
    )
    for band in report.band_reports:
        logger.bind(eval_race=report.race_key).info(
            "eval_band race={} band={} n={} hit={:.1%} target={:.1%} drift={:+.1%}",
            report.race_key,
            band.band.value,
            band.sample_size,
            band.hit_rate,
            band.target_hit_rate,
            band.drift,
        )
    for d in report.drifts:
        logger.warning(
            "calibration_drift race={} band={} n={} hit={:.1%} target={:.1%} drift={:+.1%}",
            report.race_key,
            d.band.value,
            d.sample_size,
            d.hit_rate,
            d.target_hit_rate,
            d.drift,
        )
