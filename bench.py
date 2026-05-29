#!/usr/bin/env python3
"""
PitWallAI Latency Telemetry
Measures wall-clock time for each stage of the decode pipeline.

This is *telemetry*, not a contract. Under the current product strategy
the live-race surface earns its value from shareable call-outs and
signal-quality feedback into the picks model — not from beating physics.
The "beat broadcast" bar is ~30 seconds; sub-second decode is bonus,
not a target. The previous P50<800ms / P95<1200ms thresholds remain
visible here only as a soft budget for spotting regressions, never as
a CI gate.

Usage: python bench.py [--runs N] [--backend rules|hybrid|llm] [--verbose]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import numpy as np
from pydantic import ValidationError

from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.models import (
    AgentDependencies,
    DecodedTransmission,
    RadioRawMessage,
)
from pitwallai.agents.radio_intercept.seed_data import (
    JARGON_GLOSSARY,
    MONACO_REHEARSAL_SCENARIO,
    SEED_TRANSCRIPTS,
    TEAM_COLORS,
)
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore

BACKEND_NOTES: dict[str, str] = {
    "rules": (
        "Rules path only. No LLM calls. For LLM path numbers run: "
        "python bench.py --backend hybrid --runs 20"
    ),
    "hybrid": (
        "Hybrid path. LLM called only on low-confidence decodes. "
        "Set PITWALL_LLM_MODEL and PITWALL_LLM_BUDGET_ACK=1 first."
    ),
    "llm": (
        "Full LLM path. Every decode calls the configured LLM provider."
    ),
}


def _stage_stats(values: list[float]) -> dict[str, float]:
    """Compute mean, P50, P75, P95, P99, and max for a list of timings (ms)."""
    if not values:
        return {
            "mean": 0.0,
            "p50": 0.0,
            "median": 0.0,
            "p75": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
        }
    arr = np.array(values, dtype=float)
    p50 = float(np.percentile(arr, 50))
    return {
        "mean": float(np.mean(arr)),
        "p50": p50,
        "median": p50,
        "p75": float(np.percentile(arr, 75)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(np.max(arr)),
    }


def _inference_stage_key(backend: str) -> str:
    """Return JSON stage key for decode timing (rules vs LLM path)."""
    return "rules_inference" if backend == "rules" else "llm_inference"


def _inference_stage_label(backend: str) -> str:
    """Return human-readable table row label for decode timing."""
    return "Rules Decode" if backend == "rules" else "LLM Inference"


def _build_corpus() -> list[RadioRawMessage]:
    """Return 12 Monaco + 8 seed transcripts as RadioRawMessage fixtures."""
    messages = list(MONACO_REHEARSAL_SCENARIO.events)
    for record in SEED_TRANSCRIPTS[:8]:
        messages.append(
            RadioRawMessage(
                session_key=9158,
                driver_number=1,
                driver_code=str(record["driver_code"]),
                team=str(record["team"]),
                timestamp=datetime.now(tz=UTC),
                raw_transcript=str(record["raw_transcript"]),
                lap_number=int(record["lap_number"]) if record.get("lap_number") else None,
            )
        )
    return messages[:20]


async def _benchmark_message(
    message: RadioRawMessage,
    vector_store: MockVectorStore,
    agent: RadioInterceptAgent,
    deps: AgentDependencies,
    inference_key: str,
    *,
    verbose: bool,
) -> dict[str, float]:
    """Time each decode stage for a single message."""
    total_start = time.perf_counter()

    embed_start = time.perf_counter()
    embedding = await asyncio.to_thread(vector_store._embed, [message.raw_transcript])
    embed_ms = (time.perf_counter() - embed_start) * 1000

    query_start = time.perf_counter()
    await asyncio.to_thread(
        vector_store._collection.query,
        query_embeddings=[embedding[0]],
        n_results=min(5, vector_store.collection_size()),
        include=["documents", "metadatas", "distances"],
    )
    vector_query_ms = (time.perf_counter() - query_start) * 1000

    msg_deps = replace(deps, session_key=message.session_key)
    inference_start = time.perf_counter()
    result = await agent.decode(message, msg_deps)
    inference_ms = (time.perf_counter() - inference_start) * 1000

    validation_start = time.perf_counter()
    try:
        DecodedTransmission.model_validate(result.model_dump())
    except ValidationError:
        pass
    validation_ms = (time.perf_counter() - validation_start) * 1000

    total_ms = (time.perf_counter() - total_start) * 1000

    if verbose:
        print(
            f"  {message.driver_code}: embed={embed_ms:.1f}ms "
            f"vector={vector_query_ms:.1f}ms {inference_key}={inference_ms:.1f}ms "
            f"valid={validation_ms:.1f}ms total={total_ms:.1f}ms"
        )

    return {
        "embedding": embed_ms,
        "vector_query": vector_query_ms,
        inference_key: inference_ms,
        "validation": validation_ms,
        "total": total_ms,
    }


def _print_table(
    stage_stats: dict[str, dict[str, float]],
    runs: int,
    backend: str,
    inference_key: str,
    within_soft_budget: bool,
) -> None:
    """Print formatted benchmark table with mean and percentile columns."""
    green = "\033[32m"
    yellow = "\033[33m"
    reset = "\033[0m"
    print(f"\nPITWALLAI LATENCY TELEMETRY — {runs} runs  [backend: {backend}]")
    print("─" * 68)
    print(f"{'Stage':<18}{'Mean':>10}{'P50':>10}{'P95':>10}{'P99':>10}{'Max':>10}")
    print("─" * 68)
    labels = [
        ("Embedding", "embedding"),
        ("Vector Query", "vector_query"),
        (_inference_stage_label(backend), inference_key),
        ("Validation", "validation"),
    ]
    for label, key in labels:
        stats = stage_stats[key]
        print(
            f"{label:<18}{stats['mean']:>9.0f}ms{stats['p50']:>9.0f}ms"
            f"{stats['p95']:>9.0f}ms{stats['p99']:>9.0f}ms{stats['max']:>9.0f}ms"
        )
    print("─" * 68)
    total_stats = stage_stats["total"]
    print(
        f"{'END-TO-END TOTAL':<18}{total_stats['mean']:>9.0f}ms{total_stats['p50']:>9.0f}ms"
        f"{total_stats['p95']:>9.0f}ms{total_stats['p99']:>9.0f}ms{total_stats['max']:>9.0f}ms"
    )
    print("─" * 68)
    # Soft regression budget — for noticing drift, not for failing CI.
    # The product no longer requires sub-second decode (see module docstring).
    status = (
        f"{green}within soft budget{reset}"
        if within_soft_budget
        else f"{yellow}slower than soft budget{reset}"
    )
    print(f"Soft regression budget (P50<800ms, P95<1200ms): {status}")


async def run_benchmark(runs: int, backend: str, verbose: bool) -> dict[str, Any]:
    """Execute the full benchmark suite and write latency_report.json."""
    os.environ["PITWALL_DECODE_BACKEND"] = backend
    inference_key = _inference_stage_key(backend)

    corpus = _build_corpus()[:runs]
    vector_store = MockVectorStore()
    agent = RadioInterceptAgent(backend=backend)
    deps = AgentDependencies(
        vector_store=vector_store,
        session_key=9158,
        jargon_glossary=JARGON_GLOSSARY,
        team_colors=TEAM_COLORS,
    )

    stage_results: dict[str, list[float]] = {
        "embedding": [],
        "vector_query": [],
        inference_key: [],
        "validation": [],
        "total": [],
    }

    for message in corpus:
        timings = await _benchmark_message(
            message,
            vector_store,
            agent,
            deps,
            inference_key,
            verbose=verbose,
        )
        for key, value in timings.items():
            stage_results[key].append(value)

    stage_stats = {key: _stage_stats(vals) for key, vals in stage_results.items()}
    within_soft_budget = (
        stage_stats["total"]["p50"] < 800.0 and stage_stats["total"]["p95"] < 1200.0
    )
    slow_count = sum(1 for value in stage_results["total"] if value >= 800.0)

    report = {
        "run_at": datetime.now(tz=UTC).isoformat(),
        "backend": backend,
        "runs": len(corpus),
        "notes": BACKEND_NOTES[backend],
        "stages": stage_stats,
        "within_soft_budget": within_soft_budget,
        "slow_count": slow_count,
    }

    _print_table(stage_stats, len(corpus), backend, inference_key, within_soft_budget)

    with open("latency_report.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print("\nWrote latency_report.json")

    return report


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="PitWallAI latency benchmark")
    parser.add_argument("--runs", type=int, default=20, help="Number of runs (max 20)")
    parser.add_argument(
        "--backend",
        choices=["rules", "hybrid", "llm"],
        default="rules",
        help="Decode backend to benchmark",
    )
    parser.add_argument("--verbose", action="store_true", help="Per-message timing output")
    args = parser.parse_args()
    asyncio.run(run_benchmark(max(args.runs, 20), args.backend, args.verbose))


if __name__ == "__main__":
    main()
