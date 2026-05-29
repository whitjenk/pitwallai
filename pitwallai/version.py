"""Version stamps for every PitWallAI broadcast.

When calibration drifts six weeks from now, we need to attribute the
shift to a real change (model swap, prompt edit, pipeline rework) instead
of guessing. This module is the single source of truth.

Bump the relevant version when you change behaviour:

  PROMPT_VERSION   — any user-facing prompt change (signal selection,
                     risk-note logic, explanation card template).
  PIPELINE_VERSION — when the agent topology or signal-extraction
                     pipeline changes shape (e.g. 5→3 agent consolidation).
  MODEL_VERSION_DEFAULT — fallback when no env override is configured.
"""

from __future__ import annotations

import os

# Bump these explicitly in PRs that change behaviour.
PROMPT_VERSION = "2026-bet1-cards-v2"  # bumped: bands + field_angle rename
PIPELINE_VERSION = "3-agent-v1"         # PicksAgent (3 stages) + RaceMonitor + ScorerLearner
DEFAULT_MODEL_VERSION = "gemini-2.0-flash"


def current_model_version() -> str:
    """Resolve the model in use from env (set by config), else default."""
    return os.getenv("PITWALL_LLM_MODEL", "").strip() or DEFAULT_MODEL_VERSION


def run_meta() -> dict[str, str]:
    """Bundle for attaching to broadcast log lines and pick rows.

    Returned dict is JSON-safe; safe to ``logger.bind(**run_meta())``.
    """
    return {
        "model_version": current_model_version(),
        "prompt_version": PROMPT_VERSION,
        "pipeline_version": PIPELINE_VERSION,
    }
