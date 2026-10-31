# Running the PitWallAI Slack app locally

The app runs in **Socket Mode**: one long-running Python process connects out to
Slack, so there's no public URL, no webhook to host, and no request signatures to
verify. It's installed only in our workspace, so there's no Marketplace review.

Follow these steps from scratch. They take about five minutes.

## 1. Create the app from the manifest

1. Go to <https://api.slack.com/apps> and click **Create New App** → **From a
   manifest**.
2. Pick our workspace.
3. Choose **YAML** and paste the contents of [`slack_app/manifest.yaml`](../slack_app/manifest.yaml).
4. Review (it asks for the `commands` and `chat:write` scopes and turns Socket
   Mode on) and click **Create**.

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

## 4. Try it in Slack

In any channel or DM in our workspace (every reply below is visible only to you):

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
