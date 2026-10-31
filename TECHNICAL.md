# PitWallAI — Architecture

A one-page developer note. Product overview: [README.md](README.md). Agent conventions: [CLAUDE.md](CLAUDE.md).

PitWallAI is a Slack app for one friends' F1 Fantasy league. Python 3.11, async throughout.
One long-running process connects out to Slack over Socket Mode — no public URL, no webhook.

## Shape

```
openf1/   feeds/          core/                 store/              slack_app/
(data)    (live prices)   (fantasy brain)       (one SQLite file)   (Bolt, Socket Mode)
   └──────────┴──────────────> core.api <────────┴────────────────────┘
```

Data flows one way: `slack_app` parses a `/pitwall` command, calls `core.api`, and renders the
result as a `Reply`. `core` does the fantasy maths and reaches live timing only through an OpenF1
client that is injected into it — it never imports the store, Slack or SQLAlchemy
(`tests/test_core_boundary.py`).

## Packages

- **`core/`** — the fantasy brain and its public surface (`core/api.py`). Lineup grading, pick
  generation, chip planning, scoring rules, the price catalog (`core/prices.json` plus live
  overlays). Pure logic; no I/O beyond the OpenF1 client passed in.
- **`store/`** — a single SQLite file keyed by Slack user (`store/db.py`, `store/models.py`):
  each league-mate's team, their locked lineups, and a small TTL cache. No migrations, no Postgres.
  On Railway the file lives on a mounted volume (`PITWALL_DB_PATH`). `store.forget_user` erases a
  user's data.
- **`slack_app/`** — plain async handlers (`handlers.py`) with Bolt wiring on top (`app.py`,
  `__main__.py`). Subcommands: `help`, `team`, `picks`, `grade`, `lock`, `score`, `record`,
  `forget`. Personal replies (a user's team, budget, picks) are ephemeral; league banter (grades,
  scores, records) posts to the channel.
- **`openf1/`** — the OpenF1 REST client (`client.py`) and its models; `health.py` reports feed
  reachability.
- **`feeds/`** — `fantasy_prices.py` pulls current driver/constructor prices from the official F1
  Fantasy feed, overlays them onto the catalog, and caches them in the store so prices are current
  on startup and survive a redeploy.

## Run and deploy

- Entry point: `python -m slack_app` (see `railway.toml`). Needs the Slack bot/app tokens in the
  environment.
- Prices: `python scripts/refresh_prices.py` refreshes the cached catalog on demand; the app also
  refreshes on startup.
- Tests: `PYTHONPATH=. PITWALL_DECODE_BACKEND=rules pytest -q`. Lint: `python tools/language_linter.py`.
  No test touches the network.
