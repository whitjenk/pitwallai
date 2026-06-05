"""Build PracticeSignals from lap/pace data alone — no team radio required.

OpenF1 frequently publishes practice laps long before (or instead of) team-radio
audio, and never publishes radio transcripts. The radio-driven analyst therefore
yields nothing on a fresh weekend even though the timesheet is already complete.

This module synthesises a PracticeSignal per driver per session purely from real
lap times, using OpenF1's own /drivers roster for correct codes and teammate
grouping (no hardcoded driver numbers, so it stays correct season to season).

The synthesised fields feed the pick engine the same way radio signals do
(pick_generator weights setup_sentiment*15 + tire_confidence*10 +
pace_satisfaction*10, and penalises >=2 anomaly_flags):

  pace_satisfaction  ← gap to session leader (fast = high)
  setup_sentiment    ← pace standing + FP1→FP2 improvement (front & improving = +)
  tire_confidence    ← timed-lap count vs the field (more running = more confidence)
  anomaly_flags      ← teammate_gap_*, session_regression, short_long_run_count
"""

from __future__ import annotations

from collections import defaultdict

from loguru import logger

from intelligence.schemas import PracticeSignal
from openf1.client import OpenF1Client

# Pace gap (s) to the session leader that maps to zero pace_satisfaction.
_PACE_REFERENCE_S = 2.0
# Teammate best-lap gap (s) that counts as an anomaly.
_TEAMMATE_GAP_THRESHOLD = 0.5
# FP1→FP2 best-lap regression (s) that counts as an anomaly.
_SESSION_REGRESSION_S = 0.3
# Minimum timed laps before a driver can be flagged for a short long-run count.
_MIN_LONG_RUN_LAPS = 5


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _best_and_counts(laps: list) -> tuple[dict[int, float], dict[int, int]]:
    """Best timed lap and timed-lap count per driver (ignoring pit-out laps)."""
    best: dict[int, float] = {}
    counts: dict[int, int] = defaultdict(int)
    for lap in laps:
        if lap.lap_duration is None or lap.is_pit_out_lap:
            continue
        counts[lap.driver_number] += 1
        cur = best.get(lap.driver_number)
        if cur is None or lap.lap_duration < cur:
            best[lap.driver_number] = lap.lap_duration
    return best, dict(counts)


async def build_lap_only_signals(
    client: OpenF1Client,
    *,
    session_keys: dict[str, int],
) -> list[PracticeSignal]:
    """
    Synthesise PracticeSignals from real laps for the given practice sessions.

    Args:
        client: OpenF1 client.
        session_keys: Label -> session_key, e.g. {"FP1": 11292, "FP2": 11293}.

    Returns:
        One PracticeSignal per driver per session that set a timed lap.
    """
    best_by_label: dict[str, dict[int, float]] = {}
    counts_by_label: dict[str, dict[int, int]] = {}
    code_by_num: dict[int, str] = {}
    team_by_num: dict[int, str] = {}

    for label, sk in session_keys.items():
        laps = await client.get_laps(sk)
        best, counts = _best_and_counts(laps)
        if not best:
            continue
        best_by_label[label] = best
        counts_by_label[label] = counts
        for row in await client.get_drivers(sk):
            if row.name_acronym:
                code_by_num[row.driver_number] = row.name_acronym
            if row.team_name:
                team_by_num[row.driver_number] = row.team_name

    if not best_by_label:
        return []

    fp1_best = best_by_label.get("FP1", {})
    signals: list[PracticeSignal] = []

    for label, best in best_by_label.items():
        counts = counts_by_label.get(label, {})
        leader = min(best.values())
        field_max_laps = max(counts.values(), default=0)

        # Teammate best-lap gaps from the real /drivers team grouping.
        by_team: dict[str, list[int]] = defaultdict(list)
        for dn in best:
            by_team[team_by_num.get(dn, f"#{dn}")].append(dn)
        teammate_flag: dict[int, str] = {}
        for members in by_team.values():
            if len(members) != 2:
                continue
            d1, d2 = members
            gap = abs(best[d1] - best[d2])
            if gap > _TEAMMATE_GAP_THRESHOLD:
                for dn in (d1, d2):
                    teammate_flag[dn] = f"teammate_gap_{gap:.2f}s_{label}"

        for dn, lap_time in best.items():
            gap = lap_time - leader
            code = code_by_num.get(dn, f"#{dn}")

            pace_satisfaction = _clamp(1.0 - gap / _PACE_REFERENCE_S, 0.1, 1.0)

            timed = counts.get(dn, 0)
            tire_confidence = (
                _clamp(timed / field_max_laps, 0.2, 1.0) if field_max_laps else 0.5
            )

            # setup_sentiment: pace standing, nudged by FP1→FP2 improvement.
            sentiment = (pace_satisfaction - 0.5) * 1.2  # -0.6..+0.6 from pace
            anomalies: list[str] = []
            if label == "FP2" and dn in fp1_best:
                delta = lap_time - fp1_best[dn]  # >0 means slower in FP2
                sentiment -= _clamp(delta, -0.5, 0.5)  # improving lifts sentiment
                if delta > _SESSION_REGRESSION_S:
                    anomalies.append("session_regression")
            sentiment = _clamp(sentiment, -1.0, 1.0)

            if dn in teammate_flag:
                anomalies.append(teammate_flag[dn])
            if timed < max(_MIN_LONG_RUN_LAPS, field_max_laps * 0.5):
                anomalies.append("short_long_run_count")

            signals.append(
                PracticeSignal(
                    driver_number=dn,
                    driver_code=code,
                    session=label,
                    setup_sentiment=round(sentiment, 3),
                    tire_confidence=round(tire_confidence, 3),
                    mechanical_flags=[],
                    pace_satisfaction=round(pace_satisfaction, 3),
                    anomaly_flags=anomalies,
                    raw_evidence=[
                        f"lap-only: best {lap_time:.3f}s (+{gap:.3f}s to leader), "
                        f"{timed} timed laps in {label}"
                    ],
                )
            )

    logger.bind(signals=len(signals), sessions=list(best_by_label)).info(
        "Lap-only practice signals built (no radio)"
    )
    return signals
