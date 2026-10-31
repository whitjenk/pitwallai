# Brief 003: Delete the radio intercept stack and its heavy dependencies

**Status:** todo · **Size:** M (mostly deletions) · **Touches:** `pitwallai/agents/radio_intercept/`, `requirements.txt`, `.github/workflows/ci.yml`, `api/`, `intelligence/`, `agents/base.py`, `main.py`, `tests/`
**Depends on:** 002 merged.
**Protected:** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`, `tests/test_picks_agent.py`,
`tests/test_lineup_grader.py`, `tests/test_lock_score.py`, `tests/test_constructor_swap.py`,
`tests/test_fantasy_rules.py`, `tests/test_chip_conviction.py`

## Goal
Remove the team-radio decoder and everything that exists only for it: chromadb,
sentence-transformers (which pulls in PyTorch), the vector store, the LLM decoder, the
latency benchmark, the rehearsal demo and the dashboard. Picks come only from lap data.

## Context
- `intelligence/lap_signals.py` already builds the same `PracticeSignal` fields from lap times.
  Its docstring notes OpenF1 never publishes radio transcripts, so the radio path yields nothing on a real weekend.
- Radio-only code (confirm with `grep -rn radio_intercept`): the rest of `pitwallai/agents/radio_intercept/`,
  `intelligence/radio_transcribe.py`, the radio-decode branch of `intelligence/practice_analyst.py`
  (keep the lap-only path), `RadioInterceptAgent` / `MockVectorStore` parameters threaded through
  `agents/base.py`, `intelligence/picks_pipeline.py`, `intelligence/weekend_picks.py`, `whatsapp/app_runtime.py`,
  `scripts/whatsapp_chat.py`, `scripts/test_real_practice.py`, radio/rehearsal endpoints in `api/server.py` and `api/rehearsal.py`,
  `onboarding/monaco_*.py`, `bench.py`, `latency_report.json`, `dashboard.jsx`, `track_map.jsx`,
  `tests/test_ws_stress.py`, and radio fixtures in `tests/conftest.py` and `tests/fixtures_signal_cache.py`.

## In scope
- Delete the above. Remove radio cases from `test_e2e.py`, `test_resilience.py` and
  `test_llm_contracts.py`, and delete each file if nothing meaningful is left.
- `requirements.txt`: remove `chromadb`, `sentence-transformers`, `huggingface-hub`, `websockets`.
  Remove the opentelemetry sdk/proto/exporter pins from brief 000 and keep only
  `opentelemetry-api==1.38.0` (pydantic-ai 0.8 still needs it). Check this in a clean venv.
- CI: remove the Hugging Face cache step, the embedding pre-download step and the `ws-stress` job.
- `main.py`: remove `--mode rehearsal` and the dashboard. Update the README and TECHNICAL.md sections that describe them.

## Out of scope
- WhatsApp, subscribe/privacy tooling, the agent layer (later briefs). Pick logic changes.

## Acceptance criteria
- [ ] `grep -rn "radio_intercept\|chromadb\|sentence_transformers\|RadioIntercept" --include=*.py .` returns nothing
- [ ] Clean Python 3.11 venv: `pip install -r requirements.txt` and the full test command pass. Paste the summary line
- [ ] Protected files untouched (`git diff --stat main -- <protected files>` is empty) and all pass
- [ ] CI green. PR lists deleted paths and `git diff --shortstat main`

## How I'll review it
Check CI, the empty diff on protected files and the deleted-path list. Run `python scripts/whatsapp_chat.py` and send `PICKS`.
