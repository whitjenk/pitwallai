# Brief 004: Slack app with `/pitwall` commands for the league

**Status:** todo · **Size:** M · **Touches:** new `slack_app/`, `core/parse.py`, `requirements.txt`, `railway.toml`, `docs/slack_setup.md`
**Depends on:** 002 and 003 merged.

## Goal
League-mates in one Slack workspace can set their team, get picks, grade or lock a lineup, and
see scores with a `/pitwall` slash command. Personal answers are only visible to the person who
asked. Grades, scores and the season record post in the channel for banter.

## Context
- Use **Slack Bolt for Python** (`slack_bolt`, async `AsyncApp`) in **Socket Mode**. That means no
  public URL, no webhook signature handling, and one long-running process. It's installed only
  to our own workspace, so no Slack Marketplace review.
- All logic comes from `core.api` (brief 002) and persistence from `store` (brief 003).
  `slack_app/` should contain almost no F1 logic.
- Lineup parsing already exists in `whatsapp/inbound.py` (`_extract_lineup`, `_extract_captain`),
  and driver/constructor name resolution is in `whatsapp/intent.py` (e.g. "Lewis" → `HAM`).
  Move these into `core/parse.py` and leave shims behind.
- Existing reply wording in `whatsapp/commands/` and `whatsapp/inbound.py` (`_handle_grade`,
  `_handle_lock`, `_handle_score`, `_handle_record`) is a good starting point for message text.
  Use Slack markdown (mrkdwn), not WhatsApp formatting.

## In scope
- Subcommands (show this list for `/pitwall` and `/pitwall help`):

  | Command | Example | Who sees the reply |
  |---|---|---|
  | `team` | `/pitwall team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2` | only you |
  | `team` (no args) | shows your saved team | only you |
  | `picks` | transfer suggestions for your team, next race | only you |
  | `grade <lineup>` | `/pitwall grade HAM LEC ANT RUS VER MER FER captain HAM` | channel |
  | `lock <lineup>` | saves it with the bot's own pick for comparison | only you, plus a one-line "@user locked in" to the channel |
  | `score [race]` | your locked lineup vs bot vs actual result | channel |
  | `record` | season scorecard | channel |
  | `forget` | deletes your data (`store.forget_user`) | only you |

- Write handlers as plain async functions `handle(text, user_id, team_id) -> Reply(text, visibility)`,
  so tests don't need Slack. Bolt wiring is a thin layer on top.
- Use the OpenF1 cache through `store.cache_get` / `cache_set`.
- Errors never reach the user as stack traces. Reply with a short message and log the error.
- `slack_app/manifest.yaml` (Socket Mode on, `/pitwall` command, scopes `commands`, `chat:write`).
- `docs/slack_setup.md`: steps for me to create the app from the manifest, get the bot and app
  tokens, set `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN`, run locally with `python -m slack_app`, and deploy on Railway.
- `railway.toml`: start command runs the Slack app instead of the WhatsApp server.

## Out of scope
- Scheduled league posts (Friday changes, pre-lock reminder, Monday leaderboard). That's the next brief.
- @-mention / natural-language mode, screenshot team setup, LLM calls of any kind.
- Deleting `whatsapp/`.

## Acceptance criteria
- [ ] `tests/test_slack_handlers.py` covers every subcommand, including: invalid driver code →
      helpful error, over-budget team rejected, `lock` twice replaces, `score` with nothing locked → hint
- [ ] Tests make no network calls (OpenF1 mocked with existing fixtures, no Slack connection)
- [ ] `slack_app/` contains no scoring or rules logic. Everything goes through `core.api` (reviewer will check)
- [ ] `python -m slack_app` without tokens exits with a clear message naming the missing env vars
- [ ] Full suite and `tools/language_linter.py` pass. CI is green

## How I'll review it
Follow `docs/slack_setup.md` from scratch in a test workspace. If any step is missing, it goes
back. Then run each command once and check who can see each reply.
