# Brief 012: Picks keep working through OpenF1's live-session lockout, and the bot says when data is back

**Status:** todo · **Size:** M (up to ~500 changed lines excl. deletions; if heading past it, see "Split point")
**Touches:** `core/calendar.py`, `store/db.py`, `store/__init__.py`, `slack_app/openf1_client.py`, `slack_app/handlers.py`,
`slack_app/app.py`, new `slack_app/scheduler.py`, `scripts/pitwall_cli.py`, `README.md` (timing note), tests
**Depends on:** 011 merged (it is).
**Protected (must not be edited):** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`, `tests/test_no_legacy_imports.py`,
`tests/test_core_boundary.py`, `core/rules.py`, `core/lineup_grader.py`, `core/pick_generator.py`

## Goal
During a race weekend, `/pitwall picks`, `grade` and `lock` answer from data fetched before the lockout. When they
can't, they say plainly that OpenF1 is paused for a live session and when it's back, in the reader's own time zone.
That's instead of "Couldn't pull the picks right now". This also adds the in-process scheduler the social-layer
posts will use (ROADMAP → Social layer).

## Context
- **The lockout.** OpenF1's free tier refuses *all* data from 30 minutes before each live session starts until 30
  minutes after it ends (live access is the paid Sponsor tier). Outside that window everything is free. Seen on
  a real weekend: picks fail with "Couldn't pull the picks right now", and grade says "No practice pace loaded yet"
  even after FP1/FP2 have run. Don't rely on a particular HTTP status to detect the pause. Use the session timetable.
- **The calendar is wrong for the remaining races.** `core/calendar.py::_race` gives every weekend the same generic
  timetable (FP1 11:00 UTC Friday, qualifying 14:00 UTC Saturday). The real 2026 timetables, in **UTC**, from the
  official F1 timetable pages (check them against formula1.com if anything looks off, and say so in the PR):

  | Race | FP1 | FP2 | FP3 | Qualifying (= fantasy lock) | Race |
  |---|---|---|---|---|---|
  | São Paulo | Fri 6 Nov 15:30 | Fri 6 Nov 19:00 | Sat 7 Nov 14:30 | Sat 7 Nov 18:00 | Sun 8 Nov 17:00 |
  | Las Vegas | Fri 20 Nov 00:30 | Fri 20 Nov 04:00 | Sat 21 Nov 00:30 | Sat 21 Nov 04:00 | Sun 22 Nov 04:00 |
  | Qatar | Fri 27 Nov 13:30 | Fri 27 Nov 17:00 | Sat 28 Nov 14:30 | Sat 28 Nov 18:00 | Sun 29 Nov 16:00 |
  | Abu Dhabi | Fri 4 Dec 09:30 | Fri 4 Dec 13:00 | Sat 5 Dec 10:30 | Sat 5 Dec 14:00 | Sun 6 Dec 13:00 |

  Las Vegas's `race_utc` is currently `2026-11-21 06:00`, which is wrong (it's Sun 22 Nov 04:00 UTC). Qatar is marked `is_sprint=True`, but the
  2026 Qatar timetable has FP1–FP3 and no sprint. None of the four remaining races is a sprint weekend.
  Durations: practice 60 min, qualifying 60 min, race 120 min.
- **Why caching alone doesn't fix it.** `slack_app/openf1_client.py` caches through `store.cache_get`, which returns
  `None` once a row's TTL passes. Laps have a 1-hour TTL. On Saturday, FP3 data fetched at 12:30 has expired by the
  time qualifying's lockout starts at 13:30, which is exactly when people want picks before lock. During a pause, a stale
  cached row is far better than nothing.
- **Why "No practice pace loaded yet" is misleading.** `core.api` swallows OpenF1 errors and returns `{}`/`None`, so a
  handler can't tell "OpenF1 unreachable" from "no practice has run yet". `openf1/health.py` already counts
  consecutive failures (the client records every success and failure). Use it from `slack_app/`. Don't change `core/` error handling.
- **Showing times.** Slack renders `<!date^UNIX_TS^{time}|fallback text>` in each reader's own time zone. Use that for
  "back around …", with a UTC fallback (e.g. `16:30 UTC`). The CLI should print the fallback text, not the raw token.
- The app already runs a background asyncio task for prices (`_price_refresh_loop` in `slack_app/app.py`). The
  scheduler follows the same pattern: an in-process asyncio loop, no APScheduler, no Slack `chat.scheduleMessage`.
- `store.init_db()` uses `create_all`, which adds **new tables** to an existing SQLite file but never adds columns to an
  existing table. Put new state in new tables.

## In scope
1. **Calendar (`core/calendar.py`, stays pure).** Let `_race` take explicit session times, and give the four remaining
   races the times above. Fix Las Vegas `race_utc` and Qatar `is_sprint=False`. Earlier 2026 races keep the generic
   timetable. Add:
   - `sessions(weekend) -> list[Session]` (name, start, end), using the durations above.
   - `data_pause_at(now) -> Pause | None`: the session whose window `[start − 30 min, end + 30 min]` contains `now`,
     with `reopens_at`.
   - `next_unpaused(dt) -> datetime`: `dt` itself, or the end of the pause window containing it plus 10 minutes. Scheduled
     posts in later briefs use this to stay out of the lockout.
2. **Stale reads during a pause.** `store.cache_get(key, *, allow_stale=False)`: with `allow_stale=True`, return the
   payload regardless of age. In `slack_app/openf1_client.py`: while `data_pause_at(now)` is set, read the cache with
   `allow_stale=True`, and on a cache miss raise a small `OpenF1Paused(reopens_at)` instead of calling OpenF1.
   Outside a pause, behaviour is unchanged.
3. **Honest replies in `picks`, `grade`, `lock`** (the bot's own pick at lock time) **and `score`.** When the data
   isn't there, pick the first state that applies and reply with it:
   - *Paused:* names the session and gives the reopen time as a Slack date token plus a rough "in ~40 min". E.g. "OpenF1's free live
     data is paused while Qualifying is on. It's back around 16:30 (in ~40 min)."
   - *Unreachable* (OpenF1 calls failed during this request, no pause): says OpenF1 couldn't be reached and that it isn't a
     scheduled pause. If it's within 2 hours after a pause window, add that sessions can overrun.
   - *Genuinely nothing yet* (calls succeeded, no practice laps): "No practice laps for the São Paulo GP yet. FP1 starts
     <date token>." Only this case may talk about practice not being loaded.
   Visibility per command doesn't change. Wording passes `tools/language_linter.py`.
4. **Scheduler (`slack_app/scheduler.py`).** A small, generic job runner that later briefs register jobs with:
   - `Job(key: str, due_at: datetime, run: async callable, grace: timedelta = 6h)`.
   - A function that builds the jobs for the next race weekend from the calendar. A loop checks every 60 s and runs
     each job whose `due_at <= now <= due_at + grace` and that hasn't already run.
   - "Already ran" is recorded in a new `job_runs` table (`key` primary key, `ran_at`) via two store functions. A job is
     marked done only when it succeeds; a failure is logged and retried on the next tick while still within grace.
     A restart doesn't re-run finished jobs, and doesn't run jobs whose grace has passed.
   - `PITWALL_SCHEDULER=off` disables the loop (for local runs while Railway is live, and for the CLI).
   - Started from `run()` in `slack_app/app.py` next to the price loop. Cancelled the same way.
5. **The first job: warm the cache when each window reopens.** For each session of the next race weekend, two jobs at
   pause-end + 5 min and + 40 min (OpenF1 sometimes lags). Each fetches through the store-cached client what `picks`,
   `grade`, `lock` and `score` read: calling the same `core.api` functions those handlers call is fine. After the race
   window, warm the race result. So the cache already holds what the next lockout will need.
6. **Docs.** Replace the README "Timing note" with one or two sentences: answers come from data fetched before the
   lockout, and the bot says when fresh data is back.

## Out of scope
- Any channel post or DM (brief 013+). The scheduler ships with only the warm-up jobs.
- Sprint-weekend lock times and a 2027 calendar (ROADMAP → Before the 2027 season).
- Paying for OpenF1 Sponsor, or fetching the timetable from OpenF1 at runtime.
- "Any race" for score/picks/grade/lock (issues 2–3), budget wording (issue 5), setup docs (issue 6).
- Changing scoring maths, pick logic or `core/` error handling.

## Split point (only if the PR is heading past ~500 lines)
Stop after items 1–3 and 6 (calendar, stale reads, honest replies) and open that PR. Propose items 4–5
(scheduler + warm-up) as 012b in the PR description. Don't cut test coverage to stay under the cap.

## Acceptance criteria
- [ ] `core.calendar` returns the table's times for the four remaining races (Las Vegas race Sun 22 Nov 04:00 UTC, Qatar not
      a sprint), and earlier races are unchanged. Verified by a test that checks each of the 20 values in the table
- [ ] `data_pause_at` covers start − 30 min to end + 30 min, with tests at both edges and mid-session. `next_unpaused` moves
      a time inside a window to window end + 10 min and leaves other times alone
- [ ] During a pause, a cached row older than its TTL is served and no HTTP request is made. On a miss, `OpenF1Paused` is
      raised without an HTTP request. Outside a pause, expired rows are refetched as before. Verified by tests with a
      mocked transport that counts requests
- [ ] `picks`, `grade`, `lock` and `score` each show the *paused*, *unreachable* and *nothing yet* replies in the right
      situations (tests with a frozen clock and a fake client). The paused reply contains a `<!date^` token and the
      session name. "No practice" wording appears only in the *nothing yet* case
- [ ] Scheduler tests (frozen clock, temp DB): a due job runs once. A second instance against the same DB doesn't re-run it.
      A job past its grace is skipped. A failing job isn't marked done and runs again on the next tick.
      `PITWALL_SCHEDULER=off` starts no loop
- [ ] The warm-up jobs for São Paulo exist at the expected times (test lists keys and `due_at`s)
- [ ] `store.forget_user` is unaffected (`job_runs` and the cache hold no per-user data). Say so in the PR
- [ ] CLI prints the fallback time, not `<!date^…>` (show a pasted CLI run during a simulated pause, e.g. with a frozen clock)
- [ ] Protected files untouched (`git diff --stat main -- <protected files>` is empty)
- [ ] Full test suite + `tools/language_linter.py` pass; CI green; no test touches the network

## How I'll review it
1. Read the calendar diff against the table above (2 min).
2. `PYTHONPATH=. pytest -q tests/` and the linter (2 min).
3. Run `python -m slack_app` locally through the São Paulo weekend. During qualifying's lockout on Saturday
   (17:30–19:30 UTC, 12:30–14:30 ET), run `/pitwall picks`. I should get picks (from cached data) or the paused message
   with a time that reads correctly in my time zone. Never "Couldn't pull the picks".
