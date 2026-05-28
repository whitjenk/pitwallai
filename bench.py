#!/usr/bin/env python3
"""
PitWallAI Latency Benchmark
Measures wall-clock time for each stage of the decode pipeline.
Target: median end-to-end < 800ms, p95 < 1200ms.

Usage: python bench.py [--runs N] [--verbose]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
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

os.environ.setdefault("PITWALL_DECODE_BACKEND", "rules")


def _percentiles(values: list[float]) -> dict[str, float]:
    """Compute median, p75, p95, and max for a list of timings."""
    if not values:
        return {"median": 0.0, "p75": 0.0, "p95": 0.0, "max": 0.0}
    arr = np.array(values, dtype=float)
    return {
        "median": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(np.max(arr)),
    }


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
    *,
    verbose: bool,
) -> dict[str, float]:
    """
    Time each decode stage for a single message.

    Args:
        message: Raw radio message.
        vector_store: Vector store instance.
        agent: Decoder agent.
        deps: Agent dependencies.
        verbose: Print per-run detail.

    Returns:
        Dict of stage timings in milliseconds.
    """
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

    llm_start = time.perf_counter()
    result = await agent.decode(message, deps)
    llm_inference_ms = (time.perf_counter() - llm_start) * 1000

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
            f"vector={vector_query_ms:.1f}ms llm={llm_inference_ms:.1f}ms "
            f"valid={validation_ms:.1f}ms total={total_ms:.1f}ms"
        )

    return {
        "embedding": embed_ms,
        "vector_query": vector_query_ms,
        "llm_inference": llm_inference_ms,
        "validation": validation_ms,
        "total": total_ms,
    }


def _print_table(stage_stats: dict[str, dict[str, float]], runs: int, target_met: bool) -> None:
    """Print formatted benchmark table with ANSI colors."""
    green = "\033[32m"
    red = "\033[31m"
    reset = "\033[0m"
    print(f"\nPITWALLAI LATENCY BENCHMARK — {runs} runs")
    print("─" * 57)
    print(f"{'Stage':<18}{'Median':>10}{'p75':>10}{'p95':>10}{'Max':>10}")
    print("─" * 57)
    labels = [
        ("Embedding", "embedding"),
        ("Vector Query", "vector_query"),
        ("LLM Inference", "llm_inference"),
        ("Validation", "validation"),
    ]
    for label, key in labels:
        s = stage_stats[key]
        print(
            f"{label:<18}{s['median']:>9.0f}ms{s['p75']:>9.0f}ms"
            f"{s['p95']:>9.0f}ms{s['max']:>9.0f}ms"
        )
    print("─" * 57)
    t = stage_stats["total"]
    print(
        f"{'END-TO-END TOTAL':<18}{t['median']:>9.0f}ms{t['p75']:>9.0f}ms"
        f"{t['p95']:>9.0f}ms{t['max']:>9.0f}ms"
    )
    print("─" * 57)
    status = f"{green}PASS{reset}" if target_met else f"{red}FAIL{reset}"
    print(f"TARGET (800ms):     {status}")


async def run_benchmark(runs: int, verbose: bool) -> dict[str, Any]:
    """
    Execute the full benchmark suite.

    Args:
        runs: Number of messages to benchmark (max 20).
        verbose: Enable per-message logging.

    Returns:
        JSON-serializable report dict.
    """
    corpus = _build_corpus()[:runs]
    vector_store = MockVectorStore()
    agent = RadioInterceptAgent()
    deps = AgentDependencies(
        vector_store=vector_store,
        session_key=9158,
        jargon_glossary=JARGON_GLOSSARY,
        team_colors=TEAM_COLORS,
    )

    stage_results: dict[str, list[float]] = {
        "embedding": [],
        "vector_query": [],
        "llm_inference": [],
        "validation": [],
        "total": [],
    }

    for message in corpus:
        timings = await _benchmark_message(
            message, vector_store, agent, deps, verbose=verbose
        )
        for key, value in timings.items():
            stage_results[key].append(value)

    stage_stats = {key: _percentiles(vals) for key, vals in stage_results.items()}
    target_met = stage_stats["total"]["median"] < 800.0 and stage_stats["total"]["p95"] < 1200.0
    breach_count = sum(1 for v in stage_results["total"] if v >= 800.0)

    report = {
        "run_at": datetime.now(tz=UTC).isoformat(),
        "runs": len(corpus),
        "stages": stage_stats,
        "target_met": target_met,
        "breach_count": breach_count,
    }

    _print_table(stage_stats, len(corpus), target_met)

    with open("latency_report.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print("\nWrote latency_report.json")

    return report


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="PitWallAI latency benchmark")
    parser.add_argument("--runs", type=int, default=20, help="Number of runs (max 20)")
    parser.add_argument("--verbose", action="store_true", help="Per-message timing output")
    args = parser.parse_args()
    asyncio.run(run_benchmark(min(args.runs, 20), args.verbose))


if __name__ == "__main__":
    main()
