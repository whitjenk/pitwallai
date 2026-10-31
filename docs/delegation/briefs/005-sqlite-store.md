# Brief 005: A small SQLite store keyed by Slack user

**Status:** todo · **Size:** S · **Touches:** new `store/`, new `tests/test_store.py`
**Depends on:** 000 merged. **Independent of 001–004**, so it can run in parallel with any of them.
**Protected:** all existing files. This brief only adds files.

## Goal
One SQLite file remembers each league-mate's team, their locked lineups and cached OpenF1
responses. It's created automatically on first run, with no migrations and no Postgres.

## Context
- The existing `db/` layer is built for a public WhatsApp product (31 ORM classes, phone identity,
  encrypted per-user keys, Alembic). Don't reuse it. `db/session.py` has SQLite pragma setup worth copying.
- `sqlalchemy[asyncio]` and `aiosqlite` are already dependencies. Keep the API async, because Slack Bolt's async app will call it.
- Field names must match `core.types` from brief 004 so converting is one line. Team:
  `drivers: list[str]`, `constructors: list[str]`, `budget_m: float`, `transfers_available: int`,
  `chips_used: dict[str, bool]`. Lineup: `drivers`, `constructors`, `chip`, `captain`.
  Don't import `core/`. Define store-local Pydantic models with the same fields.

## In scope
- Tables: `users` (`slack_user_id` primary key, `slack_team_id`, `display_name`, team fields, `updated_at`),
  `locked_lineups` (`slack_user_id`, `race_key`, lineup fields, `model_lineup` JSON, `locked_at`, unique per user and race),
  `openf1_cache` (`key`, `payload` JSON text, `fetched_at`, `ttl_seconds`).
- Async functions: `init_db()`, `get_team`, `upsert_team`, `list_teams` (for league features),
  `lock_lineup` (re-locking replaces), `get_locked`, `list_locked_for_race`, `forget_user` (removes the user from every table),
  `cache_get`, `cache_set`.
- DB path from `PITWALL_DB_PATH`, default `./pitwall.sqlite` (already covered by `*.sqlite` in `.gitignore`).

## Out of scope
- Migrating old Postgres data. Wiring into Slack or the OpenF1 client.

## Acceptance criteria
- [ ] `tests/test_store.py` covers every function with a `tmp_path` DB, including: re-lock replaces,
      `forget_user` leaves no rows in any table, expired cache returns `None`
- [ ] `store/` imports nothing from `db/`, `whatsapp/`, `core/`, `intelligence/` (checked in the test)
- [ ] Under 300 lines in `store/`, excluding tests. CI green

## How I'll review it
Read `store/` top to bottom in under five minutes. Run the tests.
