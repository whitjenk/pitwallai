# PitWallAI — instructions for coding agents

Read this before touching code. It is the standing context every delegated task inherits.
Product overview: `README.md`. Deep reference: `TECHNICAL.md`.

## What this is
An F1 Fantasy companion delivered over WhatsApp. Python 3.11, FastAPI, Pydantic v2,
pydantic-ai, SQLAlchemy (async; SQLite locally, Postgres in prod via Alembic), APScheduler,
OpenF1 data. Deployed on Railway.

## Environment and tests
```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. PITWALL_DECODE_BACKEND=rules pytest --ignore=tests/test_ws_stress.py -q   # what CI gates on
python tools/language_linter.py                                                       # evidence-language lint
```
- Use Python **3.11** (CI's version). 3.13 is untested.
- `tests/test_ws_stress.py` needs a live server — never part of a normal task's check.
- No API keys are needed for tests; LLM providers are mocked. Never add tests that hit the network.

## Rules that are easy to break
1. **Evidence, not instructions.** User-facing copy states observations, never orders.
   No "box now", "you should", "guaranteed", "use your chip". `tools/language_linter.py`
   enforces this in `whatsapp/`, `intelligence/`, `agents/`, `orchestrator/`.
2. **Three agents only** (PicksAgent, RaceMonitor, ScorerLearner). Extend a stage or agent
   before proposing a new top-level agent.
3. **Version bumps.** Change user-facing or pipeline behaviour → bump `PROMPT_VERSION` /
   `PIPELINE_VERSION` in `pitwallai/version.py`.
4. **Schema changes** need an Alembic migration under `alembic/` (Postgres) — see the
   `locked_lineups` migration for the pattern.
5. **Privacy.** Anything that stores subscriber data must be covered by DELETE
   (`tests/test_erase_subscriber.py`) and phone masking (`tests/test_mask_phone_audit.py`).
6. **Latency.** The rules decode path has an 800 ms P50 contract. Don't add blocking I/O to it.
7. No affiliation claims with F1 / F1 Fantasy, and no betting or financial framing (see `DISCLAIMER.md`).

## Where things live
`agents/` weekend agents · `intelligence/` picks, scoring, pages · `whatsapp/` webhook,
commands, intent · `openf1/` data client + cache · `db/` models · `scheduler/` race calendar jobs ·
`api/` FastAPI routers · `fantasy/` rules and prices · `pitwallai/agents/radio_intercept/` radio decoder.
New WhatsApp commands go through `whatsapp/command_router.py` and get a test in `tests/test_command_router.py`.

## How to finish a task
- Work on a branch named `agent/<brief-number>-<slug>`; one brief = one PR.
- Stay inside the brief's scope. If you find something else broken, note it under
  "Follow-ups" in the PR description instead of fixing it.
- Before opening the PR: full test command above passes, linter passes, and every
  acceptance criterion in the brief is ticked with how you verified it.
- PR description: what changed, why, how verified, follow-ups. Plain language.
- If the brief is ambiguous or a criterion can't be met, stop and say so in the PR — don't guess.
