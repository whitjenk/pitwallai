# Brief 014: Each player gets a private lock reminder with a one-tap "same team" lock

**Status:** todo · **Size:** M (up to ~500 changed lines excl. deletions; bigger → split)
**Touches:** new `slack_app/reminders.py`, `slack_app/actions.py`, `slack_app/app.py`, `slack_app/handlers.py`,
`core/parse.py`, `store/db.py`, `store/__init__.py`, `README.md`, `docs/slack_setup.md`, tests
**Depends on:** 013 merged (it is).
**Protected (must not be edited):** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`, `tests/test_no_legacy_imports.py`,
`tests/test_core_boundary.py`, `slack_app/scheduler.py`, `slack_app/poster.py`, `core/calendar.py`, every other file in `core/` except `core/parse.py`

## Goal
A few hours before each fantasy lock, every league-mate with a saved team gets a DM: when lock closes (in their own
time zone), their saved team, the captain on record and free transfers, with **✅ Same team** and **✏️ Edit** buttons.
One tap locks their call for the race. Anyone who doesn't respond has their saved team locked automatically at the
deadline, so every player has a lineup every week. That's what head-to-head (brief 015) needs. Target: live for the
Las Vegas lock, Fri 20 Nov 23:00 ET (Sat 21 Nov 04:00 UTC).

## Decisions (made 2026-11-01)
- **Reminder time:** `fantasy_lock_utc − 6 h`, overridable with `PITWALL_REMINDER_HOURS_BEFORE_LOCK`. The DM needs no
  OpenF1 data (team, captain, transfers are all in the store), so the lockout doesn't affect it.
- **No response → auto-lock at the deadline** with the saved team. The reminder DM says so. Auto-lock happens for
  players who turned DMs off too (the `dms off` reply says so).
- **Captain on ✅ and auto-lock:** the captain from the player's lock for the *previous* race, if that driver is still in
  their saved team. Otherwise no captain. The DM shows which ("Captain on record: ANT" / "No captain on record").
  Changing it means Edit.
- **Edit** doesn't open a modal. It rewrites the DM in place with the two commands to use: `/pitwall team …` to update
  the saved squad, and `/pitwall lock <lineup> captain XXX` to lock something different. Modals can come later if Edit gets used a lot.
- Auto-locks are silent in the channel (they don't count against the weekly cap, since nothing is posted). A ✅ lock
  posts the same one-line "🔒 @user locked in for the <race>" that `/pitwall lock` posts, as a user-triggered post
  (`scheduled=False`).
- The ownership reveal after lock moves to brief 015.

## Context
- **Scheduler (012):** `slack_app.scheduler.start_scheduler(build_jobs)` takes a function returning `list[Job]`.
  Today `app.py` passes the default (cache warm-up jobs). Add the reminder and auto-lock jobs by passing a function that
  returns `default_jobs() + <this brief's jobs>`. Don't edit `scheduler.py`. Jobs run at most once (`job_runs`),
  within `due_at … due_at + grace`.
- **Posting (013):** `LeaguePoster(poster, team_id)` in `slack_app/poster.py` has `dm_player(user_id, text, blocks)` and
  `post_league(kind, text, blocks, scheduled=...)`. Today `app.py` builds a `SlackPoster` inside `build_app()`. The jobs
  need one too, so build it where both can reach it. `users.slack_team_id` says which workspace a player is in.
- **Buttons (013):** `slack_app.actions.handle_action(action_id, user_id, message)` gets no team id or poster, and
  `app.py` replaces the clicked message with the returned `ActionUpdate`. ✅ needs the store, the core projection (for the
  bot's own pick at lock) and the poster (channel line), so extend the signature (e.g. add `team_id` from
  `body["team"]["id"]` and the poster). Keep the existing actions working.
- **Locking:** `_handle_lock` in `slack_app/handlers.py` saves the lineup plus the bot's own pick (`project_race`, which
  may come back empty or raise `OpenF1Paused` during a lockout; the lock still saves, exactly as today). Pull the
  save-and-confirm part into a shared function used by `/pitwall lock`, the ✅ button and auto-lock, rather than copying it.
- **Time display:** 012 added helpers for the `<!date^…>` token with a fallback (see `slack_app/reply.py`). Reuse them.
- **Budget wording (issue 5):** `core/parse.py::parse_team_command` accepts any `budget` from 0 to the $100M cap, so people
  type `budget 100` meaning the cap. Money left after a full team is a few million at most.
- New per-user state goes in a **new table** (`create_all` doesn't add columns to existing tables), and
  `store.forget_user` must remove it.

## In scope
1. **Jobs (`slack_app/reminders.py`)** for the next race weekend:
   - `reminder:<race_key>` due at the reminder time.
   - `autolock:<race_key>` due 1 minute before `fantasy_lock_utc`, with a grace of 2 hours (if the bot was down at the
     deadline, it still locks soon after rather than never).
2. **Reminder DM.** Sent via `dm_player` to each player who has a saved team, hasn't turned DMs off, and hasn't already
   locked for this race. Content:
   - the race name;
   - when lock closes, as a date token plus "in ~6 h";
   - the saved team;
   - the captain line;
   - free transfers;
   - one line saying the saved team locks automatically at the deadline if nothing changes;
   - buttons `pitwall:lock_same` (value = race_key) and `pitwall:lock_edit`.

   Plain-text fallback set. One player's DM failing doesn't stop the others.
3. **✅ Same team** (`pitwall:lock_same`):
   - After the deadline: rewrite the DM to "Lock for the <race> has closed", and save nothing.
   - Otherwise: lock the saved team with the captain rule, through the shared lock function. Rewrite the DM to
     "🔒 Locked: <lineup>" with the bot's pick if it has one. Post the channel one-liner (`scheduled=False`).
   - A second click is harmless (re-locking replaces, as today).
4. **✏️ Edit** (`pitwall:lock_edit`): rewrite the DM with the two commands and a reminder that `budget` is the money left.
   The ✅ button stays, so they can still tap it after updating their team.
5. **Auto-lock:** for each player with a saved team and no lock for this race, lock the saved team with the captain
   rule through the shared function. No DM, no channel post. Log how many were auto-locked.
6. **`/pitwall dms off|on`:** a new `user_prefs` table (`slack_user_id` primary key, `dms_enabled`). Ephemeral confirmation;
   the `off` reply says the saved team still locks automatically. Default is on. `forget_user` deletes the row. Bare
   `/pitwall dms` shows the current setting. Add to `help` and the README commands table.
7. **Budget wording (issue 5):**
   - In `parse_team_command`, reject a budget of **$30M or more** with "That looks like the $100M cap. `budget` is the
     money left after your team (e.g. `budget 1.5`)". The threshold is a module constant.
   - Make the `help` example, the `team` reply and the README say "money left" wherever they say budget.
8. **Docs:** README "A race weekend" table and `docs/slack_setup.md` get one or two sentences each about the reminder, the
   auto-lock and `dms off`.

## Out of scope
- Ownership reveal, head-to-head, Monday awards (brief 015).
- Modals, a captain picker, detecting drivers replaced in the official game, chip reminders.
- Sprint-weekend lock times (none in 2026; ROADMAP → Before 2027).
- Any change to `scheduler.py`, `poster.py`, `core/calendar.py`, scoring or pick logic.

## Acceptance criteria
- [ ] Job tests (frozen clock): for Las Vegas, `reminder:2026_las_vegas` is due Fri 20 Nov 22:00 UTC (lock 04:00 UTC − 6 h) and
      `autolock:2026_las_vegas` at 03:59 UTC. The env override changes the reminder time
- [ ] Reminder tests with `FakePoster`: DMs go only to players with a saved team, DMs on and no lock yet. The DM has a
      `<!date^` token, the captain line (both cases), transfers, the auto-lock sentence, both buttons and fallback text.
      One failing DM doesn't stop the rest
- [ ] ✅ tests: before the deadline it locks the saved team with the previous race's captain when still in the team (and no
      captain otherwise), stores the bot's pick when the projection works, still locks when the projection fails or is
      paused, rewrites the DM and posts the channel line with `scheduled=False`. After the deadline it saves nothing and
      says lock has closed. A double click leaves one lock
- [ ] Edit test: the DM is rewritten with both commands and the ✅ button is still present
- [ ] Auto-lock test: locks only players without a lock, applies the captain rule, posts nothing, DMs nobody
- [ ] `/pitwall lock` behaves exactly as before (existing tests pass unedited, apart from import paths if the shared
      function moved)
- [ ] `dms off/on` tests: the setting persists, an opted-out player gets no reminder but is still auto-locked, and
      `forget_user` removes the `user_prefs` row
- [ ] Budget test: `budget 100` and `budget 30` are rejected with the "money left" message; `budget 29.9` and `budget 1.5`
      are accepted. Snapshot test passes unedited
- [ ] Protected files untouched (`git diff --stat main -- <protected files>` is empty)
- [ ] Full test suite + `tools/language_linter.py` pass; CI green; no test touches Slack or the network

## How I'll review it
1. Read the job times test against the Las Vegas lock (2 min).
2. Locally, with the clock set a few minutes before a reminder (the PR should say how, e.g. an env var or a one-off
   script calling the job), check that I get the DM in Slack, tap ✅, and see "Locked" plus the channel line.
   `/pitwall score` later uses that lock.
3. `/pitwall dms off`, then trigger the reminder again: no DM.
4. `/pitwall team … budget 100` is rejected with the "money left" message.
