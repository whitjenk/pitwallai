# Brief 004: Extract the fantasy brain into `core/` with a small public API

**Status:** todo · **Size:** M · **Touches:** new `core/`, `fantasy/`, `intelligence/` (pick/grade/score/chip modules), `circuits/`, `utils/race_key.py`
**Depends on:** 003 merged.
**Protected:** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`

## Goal
Everything the bot knows (rules, prices, projections, transfers, grading, scoring, chips) lives in
`core/`. It has no dependency on the database, chat platforms or the old agent layer, and it's
reachable through a few functions the Slack app can call.

## Context
- Already almost independent: `fantasy/rules.py`, `fantasy/price_catalog.py`, `intelligence/drivers.py`,
  `intelligence/lap_signals.py`, `circuits/profiles.py`, `utils/race_key.py`.
- Coupling to remove: `pick_generator.py` (imports `db.models.FantasyTeam`, calls `repository.append_picks`,
  so move the logging to the caller), `chip_planner.py` (`FantasyTeam`, `persist_chip_plan`/`load_chip_plan`),
  `schemas.py` (imports `FantasyTeam`, `PricePrediction` from `db.models`), `lineup_grader.py` (imports `scheduler.calendar`).
- Functions needing live data may take an `OpenF1Client` argument. Caching is not core's job.

## In scope
- `core/types.py`: Pydantic models with **exactly** these fields (brief 005 stores the same ones):
  `Team(drivers: list[str], constructors: list[str], budget_m: float, transfers_available: int, chips_used: dict[str, bool])`
  and `Lineup(drivers: list[str], constructors: list[str], chip: str | None, captain: str | None)`.
- `core/api.py`, each function with a docstring and a test: `project_race(race_key, client)`,
  `suggest_transfers(team, race_key, client)`, `grade_lineup(lineup, race_key, client)`,
  `score_lineup(lineup, race_key, client)`, `chip_plan(team, races)`, `race_calendar()`.
- Move the implementation modules into `core/`. Leave one-line re-export shims at the old paths
  (`# shim: remove when whatsapp/ is retired`) so legacy code and the snapshot test keep working.
- `tests/test_core_boundary.py`: fails if any `core/` file imports `db`, `whatsapp`, `slack_app`, `store`,
  `agents`, `orchestrator`, `scheduler`, `intelligence.repository` or `sqlalchemy`.
- `core/README.md`: each public function with a one-line example.

## Out of scope
- Changing scoring maths. Text parsing (brief 006). Deleting legacy modules beyond replacing them with shims.

## Acceptance criteria
- [ ] Snapshot test passes **unedited**. This is the main correctness check
- [ ] `tests/test_core_boundary.py` passes, and the PR shows it failing when `import db` is added to a core file
- [ ] `tests/test_core_api.py` covers every `core/api.py` function with no network
- [ ] Any edits to existing tests are import-path changes only (say so in the PR). Full suite and CI green

## How I'll review it
Read `core/api.py` and `core/README.md`. If I can't tell what each function does from those two files, it goes back.
