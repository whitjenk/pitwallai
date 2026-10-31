# PitWallAI — instructions for coding agents

Read this before touching code. It is the standing context every delegated task inherits.
Product overview: `README.md`. Deep reference: `TECHNICAL.md`.

## What this is
An F1 Fantasy companion for one friends' league, delivered as a Slack app. Python 3.11,
Pydantic v2, SQLAlchemy async, OpenF1 data. Deployed on Railway.

## Direction (read this first)
PitWallAI is a **Slack app for one friends' league**. Shape: `core/` (fantasy logic, no I/O
beyond the OpenF1 client) → `store/` (one SQLite file) → `slack_app/` (Bolt, Socket Mode).
Data comes from `openf1/` and `feeds/`. Briefs live in `docs/delegation/briefs/`.
- The WhatsApp-era packages, the old agent/orchestrator/scheduler layers and the
  Postgres/Alembic DB layer were deleted in brief 011. Don't reintroduce them.
- Prefer deleting code to adding abstraction. This is a for-fun app with a handful of users.

## Environment and tests
```bash
python3.11 -m venv .venv || (pip install uv && uv venv -p 3.11 .venv)   # 3.11 only; uv fetches it if missing
source .venv/bin/activate
pip install -r requirements.txt            # with a uv venv: uv pip install -r requirements.txt
PYTHONPATH=. PITWALL_DECODE_BACKEND=rules pytest -q                                   # what CI gates on
python tools/language_linter.py                                                       # evidence-language lint
```
- Use Python **3.11** (CI's version). The project fails to import on 3.13. Don't "fix" that by upgrading packages.
- Name the virtualenv **`.venv`** (not `venv`). `tests/test_mask_phone_audit.py` scans the repo and only skips `.venv`.
- Don't create a `.env` file in the checkout. Settings read it, and it breaks tests that expect missing env vars.
- No API keys are needed for tests. Never add tests that hit the network.

## Rules that are easy to break
1. **Evidence, not instructions.** User-facing copy states observations, never orders.
   No "box now", "you should", "guaranteed", "use your chip". `tools/language_linter.py`
   enforces this in `core/` and `slack_app/`.
2. **`core/` stays pure.** No top-level imports of the store, SQLAlchemy or Slack
   (`tests/test_core_boundary.py` enforces this). Don't change scoring maths
   unless the brief asks for it.
3. **Personal data.** Anything new that stores per-user data must be removed by
   `store.forget_user`, and its test must prove it.
4. **Slack reply visibility.** Personal info (a user's team, budget, picks) goes in replies only
   that user can see. League banter (grades, scores, records) goes in the channel.
5. **The behaviour snapshot is frozen.** Never edit `tests/test_behaviour_snapshot.py` or
   `tests/snapshots/`, and never run with `UPDATE_SNAPSHOTS=1`, unless your brief explicitly says
   to. If a snapshot fails, you changed behaviour: stop and explain in the PR.
6. **Tests never hit the network**: no OpenF1, Slack or LLM calls. Use `tests/fixtures_signal_cache.py` and mocks.
7. No affiliation claims with F1 / F1 Fantasy, and no betting or financial framing (see `DISCLAIMER.md`).

## Where things live
- `core/` — fantasy logic and public API (`core/api.py`); pure, no I/O beyond the injected OpenF1 client.
- `store/` — one SQLite file, keyed by Slack user (`store/db.py`).
- `slack_app/` — Slack handlers (plain async functions, Bolt wiring on top); `python -m slack_app` is the entry point.
- `openf1/` — OpenF1 data client. `feeds/` — the live F1 Fantasy price feed.
- `tools/language_linter.py` — the evidence-language lint. `scripts/refresh_prices.py` — one-shot price refresh.

## How to finish a task
- Work on a branch named `agent/<brief-number>-<slug>` from latest `main`; one brief = one PR.
- Never edit a file the brief lists as protected.
- Keep the PR under ~500 changed lines (pure deletions and moves don't count). If it's heading
  past that, stop and propose a split in the PR.
- Stay inside the brief's scope. If you find something else broken, note it under
  "Follow-ups" in the PR description instead of fixing it.
- Before opening the PR: full test command above passes, linter passes, and every
  acceptance criterion in the brief is ticked with how you verified it.
- PR description: what changed, why, how verified, follow-ups. Plain language.
- If the brief is ambiguous or a criterion can't be met, stop and say so in the PR — don't guess.
