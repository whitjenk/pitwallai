# Brief 002: Extract the fantasy brain into a `core/` package with a small public API

**Status:** todo · **Size:** M · **Touches:** new `core/`, `fantasy/`, `intelligence/` (pick/grade/score/chip modules), `circuits/`, `utils/race_key.py`
**Depends on:** 001 merged (so CI is green). Can run in parallel with 003.

## Goal
Everything the bot "knows" (rules, prices, projections, transfers, grading, scoring, chips) lives
in one package. It has no dependency on the database, WhatsApp, Slack or the agent/orchestrator layer,
and it's reachable through a handful of functions the Slack app (brief 004) can call directly.

## Context
- Most of this code is already almost independent: `fantasy/rules.py`, `fantasy/price_catalog.py`,
  `intelligence/drivers.py`, `circuits/profiles.py` and `utils/race_key.py` import nothing from
  `db/`, `whatsapp/` or `intelligence/repository.py`.
- The coupling to remove:
  - `intelligence/pick_generator.py` imports `db.models.FantasyTeam` and calls `repository.append_picks`
    (an audit log, so move the logging to the caller)
  - `intelligence/chip_planner.py` takes a `FantasyTeam` and has `persist_chip_plan` / `load_chip_plan`
  - `intelligence/schemas.py` imports `FantasyTeam`, `PricePrediction` from `db.models`
  - `intelligence/lineup_grader.py` imports `scheduler.calendar`
- Code that needs live data may take an `OpenF1Client` argument. That's fine. Caching is not
  core's job.

## In scope
- Create `core/` with:
  - `core/types.py`: plain Pydantic models. At minimum
    `Team(drivers: list[str], constructors: list[str], budget_m: float, transfers_available: int, chips_used: dict[str, bool])`
    and `Lineup(drivers: list[str], constructors: list[str], chip: str | None, captain: str | None)`.
    **Use exactly these field names.** Brief 003 stores the same fields.
  - `core/api.py`: the public surface, each with a docstring and a test:
    `project_race(race_key, client)`, `suggest_transfers(team, race_key, client)`,
    `grade_lineup(lineup, race_key, client)`, `score_lineup(lineup, race_key, client)`
    (vs the actual result and the perfect lineup), `chip_plan(team, ...)`, `race_calendar()`.
  - The implementation modules, moved from `fantasy/`, `intelligence/`, `circuits/` and `utils/` into `core/`.
- Leave one-line re-export shims at the old import paths so existing WhatsApp code and tests keep
  working until it's retired. Put a `# shim: remove when whatsapp/ is retired` comment on each.
- Add `tests/test_core_boundary.py`: fails if any file under `core/` imports `db`, `whatsapp`,
  `slack_app`, `store`, `agents`, `orchestrator`, `scheduler.jobs`, `intelligence.repository` or
  `sqlalchemy`.

## Out of scope
- Changing scoring maths or weights. Outputs must be identical.
- Natural-language or lineup-text parsing (brief 004).
- Deleting WhatsApp code or the old modules beyond replacing them with shims.

## Acceptance criteria
- [ ] `tests/test_core_boundary.py` exists and passes
- [ ] Each function in `core/api.py` has at least one test in `tests/test_core_api.py` that uses
      the existing fixtures in `tests/fixtures_signal_cache.py` and never touches the network
- [ ] Existing tests pass. Any test edits are import-path changes only (state this in the PR)
- [ ] `core/README.md` lists the public functions with a one-line example each
- [ ] Full suite and `tools/language_linter.py` pass. CI is green

## How I'll review it
Read `core/api.py` and `core/README.md`. If I can't tell what each function does from those two
files, it goes back. Check the boundary test fails when I add `import db` to a core file.
