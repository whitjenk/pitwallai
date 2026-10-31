# Brief 001: Snapshot test that proves refactors don't change the bot's answers

**Status:** todo · **Size:** S · **Touches:** new `tests/test_behaviour_snapshot.py`, new `tests/snapshots/`
**Depends on:** 000 merged.
**Protected:** all existing files. This brief only adds files.

## Goal
One test pins down what the bot currently outputs (picks, grades, scores, chip plans, points
tables). Briefs 002–004 move and delete thousands of lines. This test is how we know they didn't
change behaviour. After this brief, the snapshot files are frozen.

## Context
Reuse input patterns that already exist rather than inventing new ones:
- Picks: `generate_picks(PickGeneratorInput(...))` in `intelligence/pick_generator.py`. See how
  `tests/test_intelligence.py` and `tests/test_beta_launch.py` build inputs (generic and personalised).
- Grading: `grade_lineup` in `intelligence/lineup_grader.py`. `tests/test_lineup_grader.py`
  shows the monkeypatch pattern (`load_practice_by_driver`, `circuit_key_for_race`) that avoids the network.
- Scoring: `score_against_result`, `perfect_lineup_from_positions` (same module).
- Chips: `generate_chip_plan(team, remaining_races)` in `intelligence/chip_planner.py`. See
  `tests/test_chip_conviction.py`. Pass a fixed list of races, never "races from now".
- Rules: `driver_points_race`, `driver_points_sprint`, `driver_points_qualifying`,
  `constructor_points_race`, `transfer_penalty_points` in `fantasy/rules.py`, for every position 1–22 plus DNF.

## In scope
- `tests/test_behaviour_snapshot.py` with at least 8 cases covering every area above, including
  one personalised pick with a real budget constraint and one lineup using a chip and a captain.
- Snapshots stored as JSON in `tests/snapshots/`, with sorted keys and floats rounded to 3 decimal places.
  Strip anything time-dependent (timestamps, "now", random IDs) before comparing.
- Snapshots regenerate only when `UPDATE_SNAPSHOTS=1` is set. Otherwise the test compares and
  fails with a readable diff.

## Out of scope
- Changing any production code, even if you spot a bug. List it under Follow-ups.

## Acceptance criteria
- [ ] Test passes, makes no network calls, and runs in under 5 seconds
- [ ] **Sensitivity check:** temporarily change `base += sig.setup_sentiment * 15.0` to `16.0` in
      `intelligence/pick_generator.py`, confirm the snapshot test fails, then revert. Paste the failure output in the PR
- [ ] Same check for one value in `fantasy/rules.py` (e.g. a race points value)
- [ ] `git diff --stat main` shows only new files

## How I'll review it
Read the JSON snapshots. They should look like real bot output I'd recognise. Rerun the sensitivity check myself.
