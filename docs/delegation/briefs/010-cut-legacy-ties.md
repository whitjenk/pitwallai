# Brief 010: The Slack bot runs with every legacy package absent

**Status:** todo · **Size:** M · **Touches:** `core/`, `openf1/`, `slack_app/`, `models/`, `tests/test_behaviour_snapshot.py` (sanctioned, see below), new `tests/test_no_legacy_imports.py`
**Depends on:** 009 merged.
**Protected:** `tests/snapshots/` (**the JSON files must stay byte-identical**)

## Goal
After this brief, deleting the legacy folders (brief 011) can't break the Slack bot, and a test proves it.

## Context
Today the new code still reaches into legacy modules, mostly through imports placed inside functions so the boundary
test doesn't see them. Tests monkeypatch those functions, so **deleting a legacy folder today would leave CI green while
`/pitwall grade` and `score` crash in production.** The ties found on 2026-10-31:
- `core/lineup_grader.py`: `circuit_key_for_race` and `load_practice_by_driver` import `intelligence.signal_cache`, which
  reads the Postgres practice cache through `intelligence.repository`. It also constructs `OpenF1Client()` itself in two
  places instead of using the client passed in through `core.api`, so grading bypasses the SQLite cache.
- `core/price_catalog.py`: `overlay_prices_from_db` imports `intelligence.repository`. Its only caller is `db/session.py`.
- `core/schemas.py` imports `models.pick_explanation.PickExplanation`, a pure Pydantic model.
- `openf1/client.py` hardwires the Postgres cache from `openf1/cache.py`, which imports `db.models` and `db.session` at module level.
  `slack_app/openf1_client.py` subclasses the client to put the SQLite cache in front of it.
- `tests/test_behaviour_snapshot.py` imports through legacy paths (`db.models.FantasyTeam`, `intelligence.lineup_grader`,
  `scheduler.calendar`, `fantasy.*`, `circuits.profiles`) and monkeypatches `lg.load_practice_by_driver` / `lg.circuit_key_for_race`.

## In scope
- `core/lineup_grader.py`: `circuit_key_for_race` implemented purely from `core.calendar` / `core.race_key`.
  `load_practice_by_driver` no longer touches any database: it returns `{}` so grading uses its existing live-laps path.
  **Keep both function names**, because the snapshot test monkeypatches them. Use the `OpenF1Client` passed in, never construct one.
- `core/price_catalog.py`: move `overlay_prices_from_db` out of core, into `db/session.py` next to its only caller.
- Move `models/pick_explanation.py` to `core/pick_explanation.py` and leave a shim at the old path.
- `openf1/`: move `CacheTier` and `cache_key_for` to a new pure `openf1/cache_keys.py`. `OpenF1Client` takes an optional
  `cache` object (async `get(key)` / `set(key, endpoint, tier, data)`), default `None` = no caching, and no longer imports
  `openf1/cache.py`. `slack_app` passes a store-backed cache instead of subclassing. The legacy app may lose its Postgres
  caching; WhatsApp is off. Update or delete legacy tests that asserted the Postgres cache path, and list them in the PR.
- **Sanctioned one-time edit to `tests/test_behaviour_snapshot.py`:** import everything from `core.*` instead of legacy paths,
  and replace `db.models.FantasyTeam` with a small local class that has the same attribute names (`driver_1`…`driver_5`,
  `constructor_1/2`, `remaining_budget`, `transfers_available`, `chips_used`). Core reads teams by attribute. **No other changes**
  to that file, and the snapshot JSON must not change.
- `tests/test_no_legacy_imports.py`:
  1. AST-walk **every** import (including inside functions) in `core/`, `store/`, `slack_app/`, `openf1/`, `feeds/`, and fail on
     `whatsapp, agents, orchestrator, scheduler, db, api, intelligence, models, fantasy, circuits, utils, sharing, onboarding`.
  2. Install an import blocker for those same packages, then import `slack_app.handlers` and run **every** subcommand handler
     against a temp store and a fake OpenF1 client. All must succeed.

## Out of scope
- Deleting legacy folders (brief 011). Behaviour changes.

## Acceptance criteria
- [ ] `tests/test_no_legacy_imports.py` passes. The PR shows part 2 failing on `main` before the fix (paste output)
- [ ] `git diff --stat main -- tests/snapshots` is empty. `git diff main -- tests/test_behaviour_snapshot.py` shows only import
      lines and the local team class
- [ ] Snapshot test passes. Full suite passes (listing any legacy test edits and deletions). CI green

## How I'll review it
Read the snapshot test diff line by line. Then, in Slack, run `grade`, `lock` and `score` once each.
