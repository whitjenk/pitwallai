# Brief 001: Remove the radio intercept stack so a clean install passes CI

**Status:** todo · **Size:** M · **Touches:** `pitwallai/agents/radio_intercept/`, `requirements.txt`,
`.github/workflows/ci.yml`, `api/`, `intelligence/` (picks pipeline), `agents/base.py`, `tests/`

## Goal
Delete the team-radio decoder and everything that exists only to support it, so that a clean
`pip install -r requirements.txt` on Python 3.11 runs the test suite green. CI on `main` has
failed on every run since early June 2026.

## Context
- **Why it can go:** `intelligence/lap_signals.py` already builds the same `PracticeSignal`
  fields (`setup_sentiment`, `tire_confidence`, `pace_satisfaction`, `anomaly_flags`) from lap
  times, and its docstring notes OpenF1 never publishes radio transcripts, so the radio path
  yields nothing on a real weekend. Picks should come only from the lap-only path.
- **Why CI is red** (reproduced 2026-10-31 in a clean 3.11 venv):
  1. `pydantic_ai/messages.py` imports `opentelemetry._events`, which no longer exists in
     opentelemetry-api 1.45. Pinning `opentelemetry-api<1.39` fixes this (verified).
  2. `chromadb` then fails with mismatched opentelemetry sdk/exporter versions. Removing
     chromadb removes this failure.
- **Shared code that lives inside the radio package and must be moved first, not deleted:**
  - `radio_intercept/model_factory.py` (`get_model`, `resolve_api_key`), used by `llm_insight`,
    `team_extractor`, `standings_extractor`, `constructor_strategy`
  - `radio_intercept/config.py` (`PitWallSettings`), used by `main.py`, `whatsapp/`,
    `intelligence/`, `agents/quali_strategist.py`
  - `decoder_factory._sanitise_evidence_summary`, used by `constructor_strategy`
  Move these to `pitwallai/llm/` (e.g. `model_factory.py`, `settings.py`, `sanitize.py`) and
  update the imports. Drop any settings fields that only configured the decoder.
- Radio-only code to delete (check with `grep -rn radio_intercept`): the rest of
  `pitwallai/agents/radio_intercept/`, `intelligence/radio_transcribe.py`, the radio-decode
  branch of `intelligence/practice_analyst.py` (keep its lap-only path), `RadioInterceptAgent` /
  `MockVectorStore` parameters threaded through `agents/base.py`, `intelligence/picks_pipeline.py`,
  `intelligence/weekend_picks.py` and `whatsapp/app_runtime.py`, the radio and rehearsal endpoints in
  `api/server.py` and `api/rehearsal.py`, `onboarding/monaco_*.py`, `bench.py`,
  `latency_report.json`, `dashboard.jsx`, `track_map.jsx`, `tests/test_ws_stress.py`, and
  radio fixtures in `tests/conftest.py`.

## In scope
- Move the shared helpers listed above, then delete the radio code.
- Remove `chromadb`, `sentence-transformers`, `huggingface-hub` and `websockets` from
  `requirements.txt` (uvicorn[standard] brings its own websockets). Add `opentelemetry-api<1.39`
  with a one-line comment explaining it's coupled to pydantic-ai 0.8, matching the anthropic pin's style.
- CI: remove the Hugging Face cache and embedding pre-download steps and the `ws-stress` job.
- Delete radio-only tests. Remove radio-specific cases from `test_e2e.py`,
  `test_resilience.py` and `test_llm_contracts.py`, and delete each file if nothing meaningful is left.
- Remove `--mode rehearsal` and the dashboard from `main.py`, the README and TECHNICAL.md.

## Out of scope
- Anything else in the "public product" layer (subscribe flows, privacy tooling, WhatsApp). Later briefs handle it.
- Changing pick scoring weights or `lap_signals.py` logic.
- Upgrading pydantic-ai.

## Acceptance criteria
- [ ] `grep -rn "radio_intercept\|chromadb\|sentence_transformers\|RadioIntercept" --include=*.py .` returns nothing
- [ ] New Python 3.11 venv: `pip install -r requirements.txt` then
      `PYTHONPATH=. PITWALL_DECODE_BACKEND=rules pytest -q` passes. Paste the summary line in the PR
- [ ] These test files pass **without being edited** (confirm with `git diff --stat main -- <files>`):
      `test_picks_agent.py`, `test_lineup_grader.py`, `test_lock_score.py`, `test_constructor_swap.py`,
      `test_fantasy_rules.py`, `test_chip_conviction.py`
- [ ] `python tools/language_linter.py` passes
- [ ] CI `test` job is green on the PR
- [ ] PR lists every deleted file or directory and the line count removed (`git diff --shortstat main`)

## How I'll review it
Check that CI is green and the protected test files are untouched. Skim the deleted-file list for
anything that isn't radio-related. Run `python scripts/whatsapp_chat.py` and send `PICKS` to
check the bot still answers.
