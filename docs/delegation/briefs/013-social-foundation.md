# Brief 013: The bot can post to the league channel, DM players and handle button clicks

**Status:** todo · **Size:** M (up to ~500 changed lines excl. deletions; bigger → split)
**Touches:** `slack_app/manifest.yaml`, `slack_app/app.py`, `slack_app/handlers.py`, new `slack_app/poster.py`,
new `slack_app/actions.py`, `store/db.py`, `store/__init__.py`, `scripts/pitwall_cli.py`, `docs/slack_setup.md`,
`README.md` (commands table), tests
**Depends on:** 012 merged (scheduler, `core.calendar.next_unpaused`).
**Protected (must not be edited):** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`, `tests/test_no_legacy_imports.py`,
`tests/test_core_boundary.py`, everything in `core/`, `slack_app/scheduler.py` (register jobs from outside it; don't change it)

## Goal
The plumbing every social-layer feature needs (ROADMAP → Social layer), proven end to end in our workspace before the
league is invited for Las Vegas:
- the bot knows the league channel;
- it can post there and DM a player;
- buttons work;
- someone hears about it when a post fails;
- the "max 4 channel posts per race week" rule is enforced in code.

No scheduled social content ships yet. That's brief 014 onwards.

## Context
- Today the app only answers slash commands with `respond()` (`slack_app/app.py`). It has never posted on its own,
  and the manifest has only `commands` + `chat:write`, `interactivity.is_enabled: false`, no App Home messages tab.
- **Socket Mode supports interactivity with no request URL.** Turning on `interactivity.is_enabled` in the manifest is
  enough. Bolt's `app.action(...)` receives clicks over the same socket. A click must be `ack()`ed within 3 seconds.
- **DMs:** `conversations.open` (needs `im:write`) returns a DM channel id to post into. For players to see bot DMs,
  the manifest needs `features.app_home.messages_tab_enabled: true`. Read-only is fine (`messages_tab_read_only_enabled: true`); buttons still work.
- **Posting to a channel** with `chat:write` requires the bot to be a member. We deliberately don't add
  `chat:write.public`: inviting the bot to the league channel is the explicit opt-in. Slack returns `not_in_channel`,
  `channel_not_found`, `is_archived`, `missing_scope`, etc. as error codes on the response.
- **Changing scopes means reinstalling the app.** Token rotation is off in our manifest
  (`token_rotation_enabled: false`). The workspace install was recreated once already because rotation had been switched on.
- Handlers today are `handle(text, user_id, team_id, display_name)`. Slash-command payloads also carry `channel_id`
  (it starts with `D` in a DM).
- Personal data rule (CLAUDE.md #3): anything stored per user must be erased by `store.forget_user`.
- Agreed post budget: at most 4 bot posts in the channel per race week. A race week is Monday–Sunday in UTC
  (ISO week). The cap counts posts the bot makes **on its own** (scheduled). Posts made because someone ran a command, and all DMs, don't count.

## In scope
1. **Manifest.** Add the `im:write` scope, `interactivity.is_enabled: true`, and the App Home messages tab
   (read-only). Update the command description and usage hint, which still say every reply is private.
2. **League channel config.** New `league_config` table: `team_id` primary key, `channel_id`, `admin_user_id`, `set_at`.
   Store functions to get and set it. `forget_user` sets `admin_user_id` to null for that user and keeps the channel.
3. **`/pitwall channel`**, run inside the league channel. Pass `channel_id` through `handle()` (optional kwarg; the CLI
   passes a fake one).
   - In a DM: ephemeral "run this in the league channel".
   - Otherwise: post an intro message to the channel through the poster (item 5). It says what the bot will do, mentions
     "at most 4 posts a race week", and has a **"👋 I'm in"** button. On success: save the config with the caller as
     admin, and send the caller an ephemeral note that they'll get a DM if a post ever fails. On `not_in_channel`:
     ephemeral "Invite me first: `/invite @PitWallAI`, then run `/pitwall channel` again", and save nothing.
   - Running it in another channel moves the config there.
   - `/pitwall channel` with the word `status` shows the current channel and admin, ephemerally.
4. **Buttons (`slack_app/actions.py`).** Plain async functions, testable without Slack, behind one Bolt registration for
   action ids starting `pitwall:`.
   - `pitwall:im_in` adds the clicker to an "In: @a @b" line on the intro message, at most once per user. It keeps the
     list in the button's `value` (no DB, so nothing to forget) and updates the message in place.
   - `pitwall:ping_ok` (see `ping`) updates the DM to "✅ Got it".
   - Unknown action ids are acked and logged.
5. **Poster (`slack_app/poster.py`).** One small module that later briefs call. Everything else goes through it.
   - A `Poster` protocol with `post(channel_id, text, blocks=None)` and `dm(user_id, text, blocks=None)`. Both return
     a result with `ok`, `ts`, `channel_id` and `error` and never raise on a Slack error. There's a real implementation
     on Bolt's `AsyncWebClient` and a fake for tests and the CLI.
   - `post_league(kind, text, blocks=None, *, scheduled=True, now=None)`:
     - Looks up the league channel. If none is set, it logs and skips.
     - Enforces the weekly cap when `scheduled=True`: the 5th scheduled post in an ISO week is refused and logged.
     - Records successful posts in a new `bot_posts` table (`team_id`, `channel_id`, `kind`, `iso_week`, `ts`,
       `posted_at`). No per-user data. The `ts` is kept so later briefs can thread or edit.
     - **Can't-post alert:** when the post fails, it DMs the admin once per (kind, ISO week). The DM names the post,
       the channel and Slack's error code, plus the one-line remedy for `not_in_channel`/`is_archived`/`channel_not_found`.
       If that DM also fails, or there's no admin, it logs an error.
   - `dm_player(user_id, ...)`: DM failures are logged and never alert the admin.
   - Every post sets plain `text` as a notification fallback, even when it sends `blocks`.
6. **`/pitwall ping`:** DMs the caller "DMs from PitWallAI work" with a **"Got it"** button. If the DM fails, the
   ephemeral reply says so and gives Slack's error code. This is how I check DMs and buttons before brief 014 relies on them.
7. **Docs (`docs/slack_setup.md`, README).**
   - Section 1: the new scopes and settings.
   - A short "Updating an existing install" section: paste the new manifest, reinstall, and if the `xoxb-` token
     changed, update it locally and on Railway.
   - A prominent **"Don't enable token rotation"** warning, with what happens if you do (issue 6).
   - Fix step 4 (issue 6): not every reply is private. Point to the README commands table for who sees what.
   - A new step: invite the bot to the league channel and run `/pitwall channel`.
   - A note that scheduled posts only fire while the process runs (deploy on Railway before inviting the league), and
     that you shouldn't run locally and on Railway at the same time with the same tokens (set `PITWALL_SCHEDULER=off` locally).
   - Add `channel` and `ping` to `help` and to the README commands table.

## Out of scope
- Any scheduled social content: lock reminder, ownership reveal, head-to-head, previews, race thread (briefs 014–018).
- DM opt-out (`/pitwall dms off`): brief 014, alongside the first DM people get unasked.
- `chat.scheduleMessage`, threads, an App Home *tab*, modals, multiple workspaces, `chat:write.public`.
- Changes to `core/` or to the scheduler internals.

## Acceptance criteria
- [ ] The manifest has `commands`, `chat:write`, `im:write`, interactivity on, the read-only messages tab, and token
      rotation off. Verified by a test that loads the YAML
- [ ] `/pitwall channel` tests with a fake poster cover: success saves config and admin; `not_in_channel` saves nothing and
      the reply has the `/invite` hint; running it in a DM is refused; re-running elsewhere moves it; `status` shows the config
- [ ] `post_league` tests (frozen clock): 4 scheduled posts in an ISO week succeed and the 5th is refused. A post with
      `scheduled=False` is never refused and doesn't count. A new ISO week resets the count. With no channel set, it skips
      without raising
- [ ] Can't-post alert tests: a failed post DMs the admin with the kind, channel and error code. A second failure of
      the same kind in the same week doesn't DM again. With no admin, or a failed alert DM, it logs and doesn't raise
- [ ] Action tests: `im_in` adds a user once (a second click doesn't duplicate) and updates the message. `ping_ok` updates
      the DM. An unknown id is acked without error
- [ ] `forget_user` nulls `admin_user_id` and keeps the channel (test). No other new table holds per-user data. Say so in the PR
- [ ] Bolt wiring is thin: `app.py` registers the action handler and passes `channel_id` and a real poster, with no logic
      beyond that. A test builds the app with a dummy token and checks the action listener is registered
- [ ] Protected files untouched (`git diff --stat main -- <protected files>` is empty)
- [ ] Full test suite + `tools/language_linter.py` pass; CI green; no test touches the network or Slack

## How I'll review it
1. Follow only the new "Updating an existing install" section of `docs/slack_setup.md` to reinstall the app (5 min).
   If a step is missing, it goes back.
2. In a test channel, run `/pitwall channel` before inviting the bot, and check the invite hint. Invite it, run it again,
   and click "👋 I'm in" twice. My name should appear once.
3. `/pitwall ping`, then click "Got it" in the DM.
4. Remove the bot from the channel, then trigger one `post_league` call from a Python shell (the PR should give the
   one-liner). I should get the can't-post DM.
