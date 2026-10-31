# Brief 009: The Slack bot always uses current F1 Fantasy prices

**Status:** todo · **Size:** S · **Touches:** new `feeds/`, `fantasy/price_feed.py` (becomes a shim), `slack_app/`, `core/price_catalog.py`, `store/`
**Depends on:** 008 merged.
**Protected:** `tests/test_behaviour_snapshot.py`, `tests/snapshots/`

## Goal
Budget checks, `team` validation and `picks` use this week's prices, not the January baseline. Prices refresh
automatically, survive redeploys, and the bot says so plainly when it can't get fresh ones.

## Context
- `core/prices.json` is dated **2026-01-01**. `core/price_catalog.load_price_catalog()` layers `core/prices.live.json`
  (gitignored) on top when it exists.
- `fantasy/price_feed.py` (`refresh_prices_from_live`) already fetches the official game's public price JSON and calls
  `core.price_catalog.apply_live_prices(..., persist=True)`, which writes `prices.live.json`. Today only
  `scripts/refresh_prices.py` runs it, by hand. On Railway that file is lost on every deploy.
- The WhatsApp app also layered prices from Postgres (`overlay_prices_from_db`, called from `db/session.py`). That database
  is gone in production since brief 008. Don't revive it.
- `core.price_catalog.prices_trusted()` currently depends on an operator env var `PITWALL_PRICES_VERIFIED`.
- `core/` must not do network I/O beyond the OpenF1 client (CLAUDE.md), so the fetcher lives outside `core/`.

## In scope
- Move `fantasy/price_feed.py` to `feeds/fantasy_prices.py` and leave a shim at the old path.
- Persist the fetched prices with `store.cache_set("fantasy_prices", payload, ttl_seconds=7 days)` instead of a file. On startup,
  load them from the store into the catalog (via `apply_live_prices(..., persist=False)`).
- `slack_app`: refresh once at startup and then every 12 hours in a background asyncio task inside the Bolt process (no APScheduler).
  A failed fetch logs a warning and keeps the last good prices.
- Prices count as "trusted" when the last successful refresh is under 48 hours old. Otherwise, `picks` and `team` replies
  add one short line, e.g. "_Prices last updated 3 days ago and may be out of date._" Keep the env-var override working.

## Out of scope
- Price predictions or price-change alerts. Any change to scoring maths.

## Acceptance criteria
- [ ] Tests with a mocked feed (no network) cover: startup loads stored prices; a successful refresh updates the catalog and store;
      a failed refresh keeps the previous prices; prices older than 48 hours make `picks` and `team` add the out-of-date line
- [ ] A test proves prices survive a restart: refresh, start a new app instance against the same SQLite file, and get the same prices
- [ ] Snapshot test passes unedited (it pins its own prices). CI green
- [ ] `docs/slack_setup.md` mentions the refresh in one or two sentences

## How I'll review it
Locally: run `python -m slack_app`, then `/pitwall team` with a driver whose price has moved this season. The budget maths should match
the official app. Stop the process, restart it, and check prices are still current without waiting for a refresh.
