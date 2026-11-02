# Setting up the PitWallAI Slack app

The app runs in **Socket Mode**: one long-running Python process connects out to
Slack, so there's no public URL, no webhook to host, and no request signatures to
verify. It's installed only in our workspace, so there's no Marketplace review.

Follow these steps from scratch. They take about five minutes.

## Updating an existing install

Already have PitWallAI installed from an earlier version? When a release changes
the manifest (new scopes, interactivity, the Messages tab), update it like this —
no need to recreate the app:

1. In the app settings, open **Features** → **App Manifest**, switch to **YAML**,
   and paste the current [`slack_app/manifest.yaml`](../slack_app/manifest.yaml)
   over what's there. Save.
2. New scopes mean a **reinstall**: Slack prompts you to reinstall, or go to
   **OAuth & Permissions** → **Reinstall to Workspace** → **Allow**.
3. After reinstalling, check the **Bot User OAuth Token** (`xoxb-…`) on **OAuth &
   Permissions**. If it **changed**, update `SLACK_BOT_TOKEN` both locally and in
   the Railway service's **Variables** (section 6.1), then redeploy. The
   app-level `xapp-…` token doesn't change on a reinstall.
4. Then point the bot at the league channel — section 5.

> **Don't enable token rotation** when you update (it's off in the manifest).
> See the warning in section 1 for why.

## 1. Create the app from the manifest

1. Go to <https://api.slack.com/apps> and click **Create New App** → **From a
   manifest**.
2. Pick our workspace.
3. Choose **YAML** and paste the contents of [`slack_app/manifest.yaml`](../slack_app/manifest.yaml).
4. Review and click **Create**. The manifest asks for the `commands`,
   `chat:write` and `im:write` scopes, turns Socket Mode on, turns
   **interactivity** on (so buttons work over the socket — no request URL
   needed), and enables the **Messages tab** (read-only) so people can see the
   bot's DMs.

> **Don't enable token rotation.** The manifest keeps
> `token_rotation_enabled: false`. If you turn rotation on, Slack starts expiring
> the `xoxb-` bot token on a schedule, and the long-running Socket Mode process
> keeps using the stale one until it simply stops working — and getting back to a
> clean state means recreating the install. We've been bitten by this once
> already. Leave rotation off.

## 2. Get the two tokens

The app needs two tokens, set as environment variables:

- **`SLACK_BOT_TOKEN`** — the bot token (`xoxb-…`).
  - In the app settings: **OAuth & Permissions** → **Install to Workspace** →
    **Allow**. After install, copy the **Bot User OAuth Token** (`xoxb-…`).
- **`SLACK_APP_TOKEN`** — an app-level token (`xapp-…`) that opens the socket.
  - In **Basic Information** → **App-Level Tokens** → **Generate Token and
    Scopes**. Give it a name, add the **`connections:write`** scope, generate it,
    and copy the token (`xapp-…`).

## 3. Set the environment and run

```bash
export SLACK_BOT_TOKEN="xoxb-…"
export SLACK_APP_TOKEN="xapp-…"
python -m slack_app
```

If either variable is missing, the app exits immediately and names the one that's
unset — nothing starts until both are set.

The SQLite file is created automatically on first run (default `./pitwall.sqlite`;
override with `PITWALL_DB_PATH`). No Postgres, no migrations.

On startup, and then every 12 hours, the app fetches current F1 Fantasy prices and
caches them in that SQLite file, so budget maths stays current and survives a
redeploy. If a fetch fails it keeps the last good prices; when the newest prices are
more than 48 hours old, `team` and `picks` replies add a short line saying so. Set
`PITWALL_PRICES_VERIFIED=1` to pin the catalog as trusted regardless.

## 4. Try it in Slack

In any channel or DM in our workspace:

```
/pitwall help
/pitwall team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2
/pitwall team
/pitwall picks
/pitwall forget
```

- `team …` validates the driver and constructor codes, the count (5 drivers, 2
  constructors) and the budget, then saves your squad.
- `team` with no arguments shows the squad you saved.
- `picks` reads the next race from the calendar and returns transfer and captain
  suggestions for your saved team.
- `forget` erases everything the app stores about you.

**Not every reply is private.** Personal reads (`team`, `picks`, and your own
`lock` confirmation) are visible only to you; league banter (`grade`, `score`,
`record`, and a one-line "locked in" note) posts to the whole channel. The
[README commands table](../README.md#commands) lists exactly who sees what.

## 5. Point the bot at the league channel

The bot only posts in a channel it's been invited to (we don't give it
`chat:write.public` — inviting it is the opt-in). Do this once:

1. In the channel you want league updates in, run `/invite @PitWallAI`.
2. Run `/pitwall channel` **in that channel**. The bot posts a short intro with a
   "👋 I'm in" button and remembers the channel; whoever ran it becomes the admin
   the bot DMs if a post ever fails.
   - Run it in a DM and it just tells you to run it in the channel instead.
   - Run `/pitwall channel` before inviting the bot and it points you at
     `/invite @PitWallAI` first.
   - Run `/pitwall channel` in a different channel later to move where it posts.
   - `/pitwall channel status` shows the current channel and admin.
3. Run `/pitwall ping`. The bot DMs you with a "Got it" button — that's the
   quick check that DMs and buttons reach you before any scheduled content relies
   on them. For the DM to arrive, the Messages tab must be enabled (it is, via the
   manifest in section 1).

**Scheduled posts only fire while the process is running.** They come from the
in-process scheduler, so nothing posts while the bot is stopped. Deploy on
Railway (section 6) before inviting the league, so updates land even when your
laptop is closed. And don't run the bot locally and on Railway at the same time
with the same tokens — two sockets double every reply. When you run locally for a
quick test, set `PITWALL_SCHEDULER=off` so only Railway posts.

## 6. Deploy on Railway

This runs the same `python -m slack_app` process on [Railway](https://railway.app)
so the bot is always on, instead of only while your laptop is. There's **one
service, no public URL** (Socket Mode connects out to Slack), and a **volume** so
saved teams and locked lineups survive deploys.

Plan: **Hobby** ($5/month, includes $5 of usage). Step 6.4 adds a $10 hard limit as
a safety cap.

These steps assume the PitWallAI service already exists on Railway from the
WhatsApp days. We're repurposing it, not creating a new one.

> **Don't change the Python version.** The repo root has a `.python-version`
> file pinning **3.11**. Railway's Nixpacks build reads it and builds on the same
> Python as CI. The project doesn't import on 3.13, so leave that file alone — no
> `PYTHON_VERSION`/`NIXPACKS_PYTHON_VERSION` override in the service variables.

### 6.1 Swap the environment variables

Open the PitWallAI service → **Variables**.

1. **Delete** the WhatsApp/Meta variables (anything like `WHATSAPP_*`,
   `META_*`, `VERIFY_TOKEN`) and **`DATABASE_URL`** — the Slack app uses none of
   them. (`DATABASE_URL` pointed at the old Postgres; see step 6.)
2. **Add** three variables (same values you used locally in sections 2–3, plus
   the DB path):
   - `SLACK_BOT_TOKEN` = your `xoxb-…` token
   - `SLACK_APP_TOKEN` = your `xapp-…` token
   - `PITWALL_DB_PATH` = `/data/pitwall.sqlite`

`/data` is where the volume gets mounted in the next step. The app creates the
`pitwall.sqlite` file (and the `/data` directory if it's somehow missing) on
first run.

### 6.2 Remove the public domain

Open the service → **Settings** → **Networking**. If there's a **public domain**
(a `*.up.railway.app` URL from the webhook days), **remove it**. Socket Mode needs
no inbound traffic, and an open domain to nothing is just surface area.

### 6.3 Add the volume (this is what makes teams survive a redeploy)

Railway wipes a service's filesystem on every deploy. A **volume** is a disk that
stays attached across deploys, so the SQLite file on it persists.

1. In the service, click **+ New** (or the **Volume** option) → **Add Volume**.
2. Set the **mount path** to **`/data`** — this must match the directory in
   `PITWALL_DB_PATH` above.
3. Save. Railway attaches the volume and redeploys.

After this deploy, the DB lives at `/data/pitwall.sqlite` on the volume. A later
redeploy reuses the same volume, so saved teams and locked lineups are still
there.

### 6.4 Cap usage

Workspace **Settings** → **Usage** → set a **hard limit of $10**. On Hobby, usage
over the included $5 bills per-use; the hard limit stops a runaway (e.g. a crash
loop — `railway.toml` already caps restarts at 5) from running up a bill. At the
hard limit Railway stops the service rather than charging past it.

### 6.5 Turn off the WhatsApp webhook

In the **Meta developer dashboard** (developers.facebook.com → your WhatsApp app
→ **WhatsApp** → **Configuration**), **unsubscribe / remove the webhook callback
URL** that pointed at the old Railway domain. Nothing is listening there anymore;
this stops Meta from trying to deliver to a dead endpoint.

### 6.6 Later — delete the old Postgres (your call)

The old Railway **Postgres** service held WhatsApp subscriber data the Slack app
doesn't use. Once you're happy the Slack bot is working and you don't need that
data, **delete the Postgres service** to stop paying for it. Not urgent, and
irreversible — leave it until you're sure.

### Verify

1. Deploy (Railway redeploys automatically after the volume change). Open the
   service **Logs** — you should see the app start without complaining about
   missing tokens.
2. In Slack: `/pitwall help` should answer.
3. The persistence check: `/pitwall team HAM LEC NOR PIA VER MCL FER budget 2.5
   transfers 2`, then **Redeploy** from the Railway dashboard, then `/pitwall
   team`. Your squad should still be there — that's the volume working.
