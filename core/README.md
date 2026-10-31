# `core/` — the fantasy brain

Everything the bot knows — rules, prices, projections, transfers, grading,
scoring and chips — lives here. `core/` has **no dependency on the database,
chat platforms or the old agent layer** (enforced by
`tests/test_core_boundary.py`), so the Slack app can call it directly.

The public surface is `core.api`. Functions that need live timing data take an
`OpenF1Client` and read it live — caching is not core's job.

## Data types (`core.types`)

```python
Team(drivers=["VER", "NOR", "LEC", "ALB", "HAM"], constructors=["MER", "HAA"],
     budget_m=4.0, transfers_available=2, chips_used={})
Lineup(drivers=["NOR", "LEC", "VER", "RUS", "PIA"], constructors=["MCL", "FER"],
       chip="limitless", captain="NOR")
```

## Public API (`core.api`)

| Function | What it does | One-line example |
| --- | --- | --- |
| `race_calendar()` | The 2026 race calendar in schedule order. | `race_calendar()[5].display_name  # 'Monaco Grand Prix'` |
| `chip_plan(team, races)` | Ranks `races` for chip windows for `team` (observational; never recommends a used chip). | `chip_plan(team, race_calendar())` |
| `project_race(race_key, client)` | Projects a race from live FP1/FP2 pace: each driver's projected slot/points plus the model's top drivers, constructors and captain. `{}` before practice. | `await project_race("2026_monaco", client)` |
| `suggest_transfers(team, race_key, client)` | Ranked transfer/captain picks for `team`, as the sacred `PickOutput`. | `(await suggest_transfers(team, "2026_monza", client)).picks[0].headline` |
| `grade_lineup(lineup, race_key, client)` | Grades a stated lineup against the model's projection: projected points, captain, matches. `{}` before practice. | `await grade_lineup(lineup, "2026_monaco", client)` |
| `score_lineup(lineup, race_key, client)` | Actual fantasy points from the finished race, or `None` if not classified yet. | `await score_lineup(lineup, "2026_monaco", client)` |

## Layout

Pure foundation: `rules.py` (points/transfers/chips), `price_catalog.py`
(+ `prices.json`), `drivers.py`, `circuits.py`, `calendar.py`, `race_key.py`,
`schemas.py`, `lap_signals.py`. Fantasy logic: `pick_generator.py`,
`chip_planner.py`, `chip_conviction.py`, `lineup_grader.py`. Public surface:
`types.py`, `api.py`.

The old import paths (`fantasy.*`, `intelligence.*`, `circuits.profiles`,
`utils.race_key`, `scheduler.calendar`) keep working via one-line shims that
re-export from here, to be removed when `whatsapp/` is retired.
