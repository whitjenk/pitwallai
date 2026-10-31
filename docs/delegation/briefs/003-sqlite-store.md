# Brief 003: A small SQLite store keyed by Slack user

**Status:** todo · **Size:** S · **Touches:** new `store/`, `requirements.txt` (only if needed)
**Depends on:** 001 merged. Can run in parallel with 002.

## Goal
One SQLite file holds everything the Slack bot needs to remember: each league-mate's team,
their locked lineups, and cached OpenF1 responses. It's created automatically on first run
with no migrations and no Postgres.

## Context
- The existing `db/` layer is built for a public WhatsApp product: 31 ORM classes, phone-number
  identity, encrypted per-user keys, Alembic migrations. Don't reuse it. Write a new, small module.
  (`db/session.py` has useful SQLite pragma setup you can copy.)
- `sqlalchemy[asyncio]` and `aiosqlite` are already in `requirements.txt`. Slack Bolt's async app
  will call this, so keep the API async.
- Team fields must match `core.types.Team` from brief 002 exactly, so converting is one line:
  `drivers: list[str]`, `constructors: list[str]`, `budget_m: float`, `transfers_available: int`,
  `chips_used: dict[str, bool]`. Lineups match `core.types.Lineup`: `drivers`, `constructors`,
  `chip`, `captain`. Don't import `core/`. Define store-local Pydantic models with the same fields.

## In scope
- `store/` with three tables:
  - `users`: `slack_user_id` (primary key), `slack_team_id`, `display_name`, the team fields, `updated_at`
  - `locked_lineups`: `slack_user_id`, `race_key`, lineup fields, `model_lineup` (JSON, the bot's
    pick at lock time), `locked_at`. Unique on (user, race)
  - `openf1_cache`: `key`, `payload` (JSON text), `fetched_at`, `ttl_seconds`
- Async functions: `init_db()`, `get_team(user_id)`, `upsert_team(user_id, ...)`,
  `lock_lineup(user_id, race_key, lineup, model_lineup)` (re-locking before the race replaces the
  old one), `get_locked(user_id, race_key)`, `list_locked_for_race(race_key)` (for a league
  leaderboard), `forget_user(user_id)` (deletes their rows from every table), `cache_get(key)`,
  `cache_set(key, payload, ttl_seconds)`.
- DB path from env var `PITWALL_DB_PATH`, default `./pitwall.sqlite`. `init_db()` runs `create_all`.
- `pitwall.sqlite*` is already in `.gitignore`. Confirm that.

## Out of scope
- Migrating data from the old Postgres schema.
- Wiring into Slack (brief 004) or into the existing OpenF1 client.

## Acceptance criteria
- [ ] `tests/test_store.py` covers every function above using a temp-file DB (pytest `tmp_path`),
      including: re-lock replaces, `forget_user` leaves no rows for that user in any table, an expired cache entry returns `None`
- [ ] `store/` does not import `db/`, `whatsapp/`, `core/` or `intelligence/` (add a check in the test)
- [ ] Under 300 lines of code in `store/`, excluding tests
- [ ] Full suite passes. CI is green

## How I'll review it
Read `store/` top to bottom, which should take under five minutes. Run the tests.
