# Brief 008: Switch production from WhatsApp to Slack

**Status:** todo · **Size:** S · **Touches:** `railway.toml`, `docs/slack_setup.md`, `README.md`
**Depends on:** 007 merged.
**Protected:** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`

## Decisions (made 2026-10-31)
- **WhatsApp is shut off.** No goodbye message and no parallel running. The Railway service switches to the Slack bot.
- **Hosting: Railway Hobby** ($5/month, which includes $5 of usage). One service, with a volume for the SQLite file
  and a $10 usage limit as a safety cap.

## Goal
Railway runs `python -m slack_app` as the only always-on service, and saved teams and locked
lineups survive redeploys. Nothing WhatsApp-related is deployed.

## Context
- Current `railway.toml` starts the WhatsApp/FastAPI server: `uvicorn main:app --host 0.0.0.0 --port $PORT`.
- Socket Mode opens an outbound connection to Slack. It needs **no public domain, port or healthcheck endpoint**.
- The store reads `PITWALL_DB_PATH` (default `./pitwall.sqlite`). Railway's filesystem resets on each deploy;
  only a mounted volume persists. Mount it at `/data` and set `PITWALL_DB_PATH=/data/pitwall.sqlite`.
- `docs/slack_setup.md` currently covers local running only (sections 1–4).

## In scope (code; the agent does these)
- `railway.toml`: `startCommand = "python -m slack_app"`. Remove anything only the web server needed.
  Add `restartPolicyType = "ON_FAILURE"` with a small `restartPolicyMaxRetries` (e.g. 5) so a crash loop doesn't run up usage.
- `docs/slack_setup.md`: add **"5. Deploy on Railway"**, a step-by-step guide for the manual steps below, written for someone who has
  never used Railway volumes.
- `README.md`: replace the WhatsApp "Subscribe" and "Run it yourself" sections with a short "Use it in Slack" section
  linking to `docs/slack_setup.md`. Keep the independent-fan-project disclaimer.

## Manual steps (I do these in the Railway dashboard; the agent only documents them)
1. On the existing PitWallAI service: **remove** the WhatsApp/Meta env vars and `DATABASE_URL`. **Add** `SLACK_BOT_TOKEN`,
   `SLACK_APP_TOKEN`, `PITWALL_DB_PATH=/data/pitwall.sqlite`.
2. Remove the service's public domain (no longer needed).
3. Add a volume to the service, mounted at `/data`.
4. Workspace settings → Usage → set a **$10 hard limit**.
5. Unsubscribe the WhatsApp webhook in the Meta developer dashboard.
6. Later, my call: delete the old Railway Postgres service. It holds WhatsApp subscriber data that's no longer needed.

## Out of scope
- Deleting `whatsapp/` and other legacy code (roadmap item "retire legacy"). Scheduled league posts.

## Acceptance criteria
- [ ] `railway.toml` starts the Slack app and has a capped restart policy
- [ ] `python -m slack_app` with `PITWALL_DB_PATH` pointing at a non-existent directory gives a clear error,
      or creates the directory. Say which in the PR, with a test
- [ ] `docs/slack_setup.md` section 5 covers every manual step above, in order
- [ ] No WhatsApp setup instructions remain in `README.md`. CI green

## How I'll review it
Do the manual steps from `docs/slack_setup.md` section 5 only, without looking at this brief. Then: `/pitwall team ...`,
redeploy from the Railway dashboard, `/pitwall team`. The team must still be there.
