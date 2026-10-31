# Brief 006: Slack app, part 1: set up your team and get picks

**Status:** todo · **Size:** M · **Touches:** new `slack_app/`, new `core/parse.py`, `requirements.txt`, new `docs/slack_setup.md`
**Depends on:** 004 and 005 merged.
**Protected:** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`, `railway.toml` (production stays on WhatsApp until brief 008)

## Goal
In our Slack workspace, a league-mate can type `/pitwall team ...` to save their team and
`/pitwall picks` to get transfer suggestions. Both replies are visible only to them. Runs locally with one command.

## Context
- **Slack Bolt for Python** (`slack_bolt`, async `AsyncApp`) in **Socket Mode**: no public URL, no
  webhook signatures, one long-running process. Installed only in our workspace, so no Marketplace review.
- Logic comes from `core.api`, persistence from `store`. `slack_app/` holds no F1 logic.
- Name resolution ("Lewis" → `HAM`, "Ferrari" → `FER`) lives in `whatsapp/intent.py`. Lineup and
  captain parsing is `_extract_lineup` / `_extract_captain` in `whatsapp/inbound.py`. Move them into
  `core/parse.py` and leave shims behind.
- Existing reply wording in `whatsapp/commands/team.py` and `picks.py` is a starting point. Use Slack mrkdwn.

## In scope
- Subcommands, all with **only-you** (ephemeral) replies:
  - `help` (also bare `/pitwall`): the command list
  - `team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2`: validates codes, count and budget, then saves
  - `team` with no arguments: shows the saved team
  - `picks`: `core.api.suggest_transfers` for the next race
  - `forget`: `store.forget_user` and a confirmation
- Handlers are plain async functions `handle(text, user_id, team_id) -> Reply(text, visibility)`,
  so tests don't need Slack. Bolt wiring is a thin layer on top.
- OpenF1 caching goes through `store.cache_get` / `cache_set`. Errors reply with a short message and log the
  details, never a stack trace.
- `slack_app/manifest.yaml` (Socket Mode on, `/pitwall` command, scopes `commands`, `chat:write`).
- `docs/slack_setup.md`: create the app from the manifest, get the tokens, set `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`,
  and run locally with `python -m slack_app`.

## Out of scope
- grade/lock/score/record (brief 007). Production deploy (008). Scheduled posts, LLM features, screenshots.

## Acceptance criteria
- [ ] `tests/test_slack_handlers.py` covers each subcommand, including: unknown driver code gives a helpful
      error, a full name resolves ("Lewis"), over-budget team rejected, `picks` with no saved team gives a hint
- [ ] Every reply in this brief has visibility `ephemeral` (asserted in tests)
- [ ] No network in tests. `slack_app/` contains no rules or scoring logic
- [ ] `python -m slack_app` with no tokens exits with a message naming the missing env vars. CI green

## How I'll review it
Follow `docs/slack_setup.md` from scratch. If any step is missing, it goes back. Then save my team and ask for picks.
