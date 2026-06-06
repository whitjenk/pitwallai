#!/usr/bin/env python3
"""
Run the Practice Analyst against REAL OpenF1 FP1/FP2 data.

This is the unmocked path: it hits the live OpenF1 REST API, decodes every
team-radio transmission through the rules-path decoder (free, no API key, no
LLM), runs the lap-based anomaly rules, and prints the resulting
PracticeSignals per session plus the Thursday practice summary.

No DATABASE_URL needed — the OpenF1 cache degrades to a no-op and we pass
persist=False so nothing is written to Postgres.

Good real-data targets (verified to have FP1+FP2 radio AND laps in OpenF1):
    2025 spielberg      (radio 12/13, laps 639/664)   <-- default
    2025 silverstone    (radio 17/9,  laps 506/536)
    2025 barcelona      (radio  9/9,  laps 515/582)   (OpenF1 name: Catalunya)

Note: 2026 practice radio is not yet populated in OpenF1, and Monaco/Barcelona
profiles use OpenF1 names that differ from the live feed (Monte Carlo /
Catalunya) — pass --openf1-name to override if you target those.

The radio-sentiment layer needs transcript text, which OpenF1 does not provide
(audio only). Pass --transcribe to transcribe the clips locally with
faster-whisper (free, no API key) so the radio path also runs on real data.

Usage:
    python scripts/test_real_practice.py
    python scripts/test_real_practice.py --circuit silverstone --year 2025
    python scripts/test_real_practice.py --circuit barcelona --openf1-name Catalunya
    python scripts/test_real_practice.py --transcribe --whisper-model base.en
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from circuits.profiles import get_circuit_profile  # noqa: E402
from intelligence.drivers import driver_code_for  # noqa: E402
from intelligence.practice_analyst import (  # noqa: E402
    _best_lap_by_driver,
    _teammate_pairs,
    analyze_practice_weekend,
)
from intelligence.schemas import PracticeSignal  # noqa: E402
from openf1.client import OpenF1Client  # noqa: E402
from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent  # noqa: E402
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore  # noqa: E402

_SESSION_REGRESSION_S = 0.3
_TEAMMATE_GAP_THRESHOLD = 0.5


def _print_session(label: str, signals: list[PracticeSignal]) -> None:
    print(f"\n=== {label}  ({len(signals)} drivers) ===")
    if not signals:
        print("  (no radio-derived signals)")
        return
    for s in sorted(signals, key=lambda x: x.driver_number):
        flags = ", ".join(s.anomaly_flags) if s.anomaly_flags else "-"
        mech = ", ".join(s.mechanical_flags) if s.mechanical_flags else "-"
        print(
            f"  #{s.driver_number:<2} {s.driver_code:<4} "
            f"sentiment={s.setup_sentiment:+.2f} "
            f"tyre_conf={s.tire_confidence:.2f} "
            f"pace_sat={s.pace_satisfaction:.2f} "
            f"mech=[{mech}] anomalies=[{flags}]"
        )


def _fmt_lap(seconds: float | None) -> str:
    if seconds is None:
        return "  --  "
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:06.3f}"


async def _code_map(client: OpenF1Client, session_key: int) -> dict[int, str]:
    """Real per-session driver number -> acronym from OpenF1 /drivers."""
    rows = await client.get_drivers(session_key)
    return {r.driver_number: (r.name_acronym or f"#{r.driver_number}") for r in rows}


async def _lap_report(client: OpenF1Client, circuit, year: int) -> None:
    """Real-data lap analysis — works even when team radio has no transcripts."""
    name_map = {"FP1": "Practice 1", "FP2": "Practice 2"}
    best_by_session: dict[str, dict[int, float]] = {}
    laps_by_session: dict[str, list] = {}
    codes: dict[int, str] = {}

    def code(dn: int) -> str:
        return codes.get(dn) or driver_code_for(dn)

    for label, session_name in name_map.items():
        sk = await client.find_session_key(
            year=year,
            circuit_short_name=circuit.openf1_circuit_name,
            session_name=session_name,
        )
        if sk is None:
            print(f"\n[{label}] not found for {circuit.openf1_circuit_name} {year}")
            continue
        codes.update(await _code_map(client, sk))
        laps = await client.get_laps(sk)
        laps_by_session[label] = laps
        best = _best_lap_by_driver(laps)
        best_by_session[label] = best

        # Long-run / lap counts (non-pit-out, timed laps) per driver.
        counts: dict[int, int] = {}
        for lap in laps:
            if lap.lap_duration is not None and not lap.is_pit_out_lap:
                counts[lap.driver_number] = counts.get(lap.driver_number, 0) + 1

        print(f"\n=== {label} — real laps (session_key={sk}, {len(laps)} lap rows) ===")
        ranked = sorted(best.items(), key=lambda kv: kv[1])
        leader = ranked[0][1] if ranked else None
        for dn, t in ranked:
            gap = f"+{t - leader:.3f}" if leader is not None and t != leader else "leader"
            print(
                f"  #{dn:<2} {code(dn):<4} best={_fmt_lap(t)}  "
                f"{gap:>8}  timed_laps={counts.get(dn, 0)}"
            )

        # Teammate best-lap gaps on real data.
        flagged = []
        for d1, d2 in _teammate_pairs(set(best.keys())):
            gap = abs(best[d1] - best[d2])
            mark = "  <-- ANOMALY" if gap > _TEAMMATE_GAP_THRESHOLD else ""
            flagged.append(f"  {code(d1)} vs {code(d2)}: {gap:.3f}s{mark}")
        if flagged:
            print("  teammate best-lap gaps:")
            print("\n".join(flagged))

    # FP1 -> FP2 session regression (real data).
    fp1, fp2 = best_by_session.get("FP1"), best_by_session.get("FP2")
    if fp1 and fp2:
        print("\n=== FP1 -> FP2 regression (real data) ===")
        regressed = []
        for dn, fp2_t in fp2.items():
            fp1_t = fp1.get(dn)
            if fp1_t is None:
                continue
            delta = fp2_t - fp1_t
            if delta > _SESSION_REGRESSION_S:
                regressed.append(
                    f"  #{dn:<2} {code(dn):<4} "
                    f"FP1 {_fmt_lap(fp1_t)} -> FP2 {_fmt_lap(fp2_t)}  (+{delta:.3f}s)"
                )
        print("\n".join(regressed) if regressed else "  (no driver >0.3s slower in FP2)")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--circuit", default="spielberg", help="circuit_key (default: spielberg)")
    parser.add_argument("--year", type=int, default=2025, help="championship year (default: 2025)")
    parser.add_argument(
        "--openf1-name",
        default=None,
        help="override OpenF1 circuit_short_name (e.g. Catalunya, 'Monte Carlo')",
    )
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="transcribe team-radio .mp3s locally (faster-whisper) so the radio path runs on real data",
    )
    parser.add_argument(
        "--whisper-model",
        default=None,
        help="faster-whisper model size (tiny.en | base.en | small.en …); default base.en",
    )
    args = parser.parse_args()

    if args.transcribe:
        os.environ["PITWALL_RADIO_TRANSCRIBE"] = "true"
        if args.whisper_model:
            os.environ["PITWALL_WHISPER_MODEL"] = args.whisper_model

    circuit = get_circuit_profile(args.circuit)
    if circuit is None:
        print(f"Unknown circuit_key: {args.circuit!r}", file=sys.stderr)
        return 2
    if args.openf1_name:
        circuit = circuit.model_copy(update={"openf1_circuit_name": args.openf1_name})

    client = OpenF1Client()
    # Force the rules backend explicitly: free, no API key, no billed LLM.
    agent = RadioInterceptAgent(backend="rules")
    vector_store = MockVectorStore()

    print(
        f"Fetching REAL FP1/FP2 from OpenF1 — "
        f"{circuit.display_name} ({circuit.openf1_circuit_name}) {args.year}"
    )

    # 1) Lap/telemetry layer — works fully on real OpenF1 data.
    print("\n" + "#" * 64 + "\n#  LAP / PACE ANALYSIS (real data)\n" + "#" * 64)
    await _lap_report(client, circuit, args.year)

    # 2) Radio-sentiment layer — driven by team_radio TRANSCRIPTS.
    #    OpenF1 only exposes recording_url (.mp3), never transcript text, so on
    #    real data this yields zero signals unless a transcription step is added.
    print("\n" + "#" * 64 + "\n#  RADIO SENTIMENT ANALYSIS (real data)\n" + "#" * 64)
    signals = await analyze_practice_weekend(
        client=client,
        agent=agent,
        vector_store=vector_store,
        circuit=circuit,
        year=args.year,
        persist=False,
    )

    if not signals:
        print(
            "\n0 radio signals. OpenF1 team_radio returns audio recording_url only — "
            "no transcript text — so the rules decoder has nothing to parse.\n"
            "Re-run with --transcribe to transcribe the .mp3s locally (faster-whisper, "
            "free) and exercise the radio path on real data."
        )
        return 0

    by_session: dict[str, list[PracticeSignal]] = defaultdict(list)
    for s in signals:
        by_session[s.session].append(s)

    for label in ("FP1", "FP2"):
        _print_session(label, by_session.get(label, []))

    flagged = [s for s in signals if s.anomaly_flags]
    print(f"\nTotal radio signals: {len(signals)}  |  with anomaly flags: {len(flagged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
