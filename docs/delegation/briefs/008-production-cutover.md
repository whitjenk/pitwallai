# Brief 008: Switch production from WhatsApp to Slack

**Status:** blocked on my decision · **Size:** S · **Touches:** `railway.toml`, `README.md`, Railway env vars (manual)
**Depends on:** 007 merged and used for at least one race weekend locally.

## Decision needed before delegating
- [ ] Is anyone still on the WhatsApp beta? If so: send a goodbye message and stop the number, or run both for a while?
- [ ] Where does the SQLite file live on Railway? A volume, so it survives deploys.

## Goal
Railway runs the Slack app as the always-on service. The WhatsApp webhook server is no longer deployed.

## In scope
- `railway.toml`: start command `python -m slack_app`. Remove the web/healthcheck settings that only the FastAPI server needed.
- Railway volume mounted at the path in `PITWALL_DB_PATH`. Document it in `docs/slack_setup.md`.
- README: replace the WhatsApp "Subscribe" and "Run it yourself" sections with a short Slack setup section.

## Out of scope
- Deleting `whatsapp/` and other legacy code (roadmap: "retire legacy").

## Acceptance criteria
- [ ] After deploy, `/pitwall help` answers in our workspace. Screenshot in the PR
- [ ] Redeploying keeps saved teams (volume check: save a team, redeploy, `/pitwall team` still shows it)

## How I'll review it
Do the redeploy check myself.
