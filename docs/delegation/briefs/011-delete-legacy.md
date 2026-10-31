# Brief 011: Delete the WhatsApp-era code, database layer and public-product docs

**Status:** todo · **Size:** L in lines, but deletions only, so the size cap doesn't apply · **Touches:** most of the repo
**Depends on:** 010 merged.
**Protected:** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`, `tests/test_no_legacy_imports.py`, `tests/test_store.py`,
`tests/test_slack_handlers.py`, `tests/test_core_api.py`, `tests/test_core_boundary.py`

## Goal
The repo contains only what the Slack bot uses: about 5k lines instead of about 25k. This is the actual fix for the
over-engineering that started this project.

## Context
After brief 010, `tests/test_no_legacy_imports.py` proves the bot runs with every legacy package absent, so deletion is safe
when that test and the snapshot keep passing unedited.

## In scope
- **Delete:** `whatsapp/`, `agents/`, `orchestrator/`, `scheduler/`, `db/`, `api/`, `intelligence/`, `models/`, `fantasy/`,
  `circuits/`, `utils/`, `sharing/`, `onboarding/`, `alembic/`, `alembic.ini`, `main.py`, `legal_review/`, `data/` (if unused),
  the shims, `openf1/cache.py` (Postgres), `pitwallai/` modules nothing imports (check `pitwallai/llm/` before deleting it),
  every script in `scripts/` except a price-refresh script (repoint it to `feeds/`), and all tests that only cover deleted code.
- **Docs:** delete `BETA_INVITE.md`, `CREATOR_REFERRAL.md`, `PRIVACY.md`. Rewrite `TECHNICAL.md` as a one-page architecture
  note (`core` → `store` → `slack_app`, `openf1`/`feeds` for data). Keep `DISCLAIMER.md` and `LICENSE`.
- **Dependencies:** remove every package nothing imports any more (likely: fastapi, uvicorn, asyncpg, psycopg2-binary,
  alembic, apscheduler, cryptography, pillow, google-genai/openai/anthropic if no LLM code remains). Check each one by grep,
  then confirm with a clean install.
- `tools/language_linter.py`: `SCAN_DIRS` becomes the directories that still exist. `CLAUDE.md`: update "What this is",
  "Where things live" and the rules that mention deleted folders.

## Out of scope
- Any change to `core/`, `store/`, `slack_app/`, `openf1/client.py`, `feeds/` beyond import fixes. New features.

## Acceptance criteria
- [ ] Protected tests untouched (`git diff --stat main -- <protected files>` is empty) and passing
- [ ] `ls` at the repo root shows only: `core/ store/ slack_app/ openf1/ feeds/ tests/ tools/ docs/ scripts/` (if kept),
      `pitwallai/` (only if still imported), plus config files and `README.md`, `TECHNICAL.md`, `DISCLAIMER.md`, `LICENSE`, `CLAUDE.md`
- [ ] Clean Python 3.11 venv: install and the full test suite pass. PR lists every removed dependency
- [ ] PR body includes `git diff --shortstat main` and the new total of Python lines outside `tests/`. CI green

## How I'll review it
Deploy to Railway, then run every `/pitwall` command once.
