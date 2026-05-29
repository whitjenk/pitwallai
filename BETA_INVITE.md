# Closed beta invite (first 5 users)

Operator checklist before sending any invite. All 🔴 items must pass.

## Pre-flight (Railway / production)

1. Set `PITWALL_MODE=live`
2. Set `DATABASE_URL`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_DISPLAY_NUMBER`
3. Meta webhook URL → `https://<your-app>/webhook` (GET verify + POST messages)
4. Run:

```bash
python scripts/verify_launch.py --mode live
python scripts/verify_webhook.py --base-url https://<your-app>
```

5. Update `fantasy/prices.json` from in-game F1 Fantasy prices, then set `PITWALL_PRICES_VERIFIED=1`
6. Smoke test on your phone: **SUBSCRIBE** → screenshot **TEAM** → **PICKS** → **DELETE**

## What beta includes

- Saturday picks ~3 hours before race lock (after **TEAM** setup)
- On-demand **PICKS** anytime after team is saved
- Sunday **CalledRecap** with shareable link
- **HELP**, **UNSUBSCRIBE**, **DELETE** (full data erase)

## What beta does *not* include

- Not affiliated with F1, F1 Fantasy, or ESPN
- No chip advice (feature flag off)
- No transfer swaps until prices are verified (`PITWALL_PRICES_VERIFIED=1`)
- No guarantee of uptime — OpenF1 or Meta outages may delay messages

## Invite message template

Replace `<number>` with digits-only E.164 (no `+`) for the wa.me link, or send from your saved contact.

```
Hey — trying a small closed beta of PitWallAI, an open-source F1 Fantasy picks bot on WhatsApp.

Scope: personalized Saturday picks before lock + Sunday recap. ~5 testers max.

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
