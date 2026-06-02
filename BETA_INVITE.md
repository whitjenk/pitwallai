# Closed beta invite (first 5 users)

Operator checklist before sending any invite. All 🔴 items must pass.

## Recommended first launch: receipts-only 🟢

For the first weekend, ship **receipts-only** — the Sunday "what we called" recap.
It works from race one, needs no price sync, and doesn't depend on the fantasy
lock time. Set:

```bash
PITWALL_PICKS_BROADCAST_ENABLED=0   # disables proactive Thu/Fri/Sat pick sends
```

The live race monitor and CalledRecap still run. Turn picks on (`=1`) only after
the price + lock checks below pass.

## Pre-flight (Railway / production)

1. Set `PITWALL_MODE=live`
2. Set `DATABASE_URL`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_DISPLAY_NUMBER`
3. Meta webhook URL → `https://<your-app>/webhook` (GET verify + POST messages)
4. Config check + **Friday live dry-run** (run during/after FP1 — confirms OpenF1
   resolves the weekend and our driver map matches the real grid):

```bash
python scripts/verify_launch.py --mode live
python scripts/verify_launch.py --mode live --live-openf1 --circuit monaco   # 🔴 Friday
python scripts/verify_webhook.py --base-url https://<your-app>
```

5. 🔴 **Confirm the fantasy lock time** in the live F1 Fantasy app (standard
   weekend ≈ 1h before Saturday qualifying). If it differs, set
   `PITWALL_FANTASY_LOCK_HOURS_BEFORE_QUALI`.
6. If running picks: update `fantasy/prices.json` from in-game prices (the
   preflight warns if it's stale), then set `PITWALL_PRICES_VERIFIED=1`.
7. Smoke test on your phone: **SUBSCRIBE** → screenshot **TEAM** → **PICKS** → **DELETE**

## 🔴 WhatsApp 24-hour window (tell your testers)

Meta only delivers proactive free-form messages **within 24h of the user's last
inbound message**. There are no approved templates yet. So:

- Tell each tester to text the bot something (e.g. **PICKS** or **HI**) shortly
  before each scheduled drop, and especially before lights-out on Sunday.
- A blocked send is now logged clearly (`outside 24h window`) rather than failing
  silently — watch the logs during the race.

## What beta includes

- Sunday **CalledRecap** — timestamped race call-outs with a shareable link, forwardable to your league chat (works from race one)
- *(picks on)* Saturday pre-lock picks ~3h before Saturday qualifying lock (after **TEAM** setup)
- On-demand **PICKS** anytime after team is saved
- **HELP**, **UNSUBSCRIBE**, **DELETE** (full data erase)

## What beta does *not* include

- Not affiliated with F1, F1 Fantasy, or ESPN
- No chip advice (feature flag off)
- No proactive picks unless `PITWALL_PICKS_BROADCAST_ENABLED=1` **and** `PITWALL_PRICES_VERIFIED=1`
- No guaranteed delivery outside the WhatsApp 24h window (no templates yet)
- No guarantee of uptime — OpenF1 or Meta outages may delay messages

## Invite message template

Replace `<number>` with digits-only E.164 (no `+`) for the wa.me link, or send from your saved contact.

```
Hey — trying a small closed beta of PitWallAI, an open-source F1 Fantasy tool on WhatsApp. ~5 testers max.

What you get: a Sunday "what we called" recap — every safety car, retirement and pit window, timestamped, ready to forward to your league chat. Plus personalized picks before lock once you set up your team.

1. Open: https://wa.me/<number>?text=SUBSCRIBE
2. Send a screenshot of your F1 Fantasy My Team (or text TEAM)
3. Text PICKS anytime after setup · HELP for commands

Beta disclaimer: independent fan tool, not F1 or F1 Fantasy. Picks are informational — you decide every transfer. Text DELETE anytime to wipe your data.

Privacy: https://github.com/whitjenk/f1-tactical-intelligence-hive/blob/main/PRIVACY.md

Reply here if anything breaks — that's the point of the beta.
```

## Local simulator (no Meta creds)

```bash
python scripts/whatsapp_chat.py --practice
```

Commands: `SUBSCRIBE`, `TEAM`, `PICKS`, `DELETE`, `HELP`
