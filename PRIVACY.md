# PitWallAI Privacy & Data Handling

PitWallAI is a WhatsApp-based F1 Fantasy assistant. This document describes what we store, why, and how users control their data. It is intended for Meta WhatsApp Business app review and subscriber transparency.

## What we collect

| Data | Purpose | Retention |
|------|---------|-----------|
| **Phone number (E.164)** | Deliver picks, alerts, and command replies | While subscribed; removed on DELETE |
| **Timezone (IANA)** | Schedule Saturday picks and race-day messages in local time | While subscribed |
| **Fantasy team** (drivers, constructors, budget, transfers) | Personalize picks and team-aware advice | While subscribed |
| **League context** (optional, via LEAGUE flow or standings screenshot) | League-angle recommendations | While subscribed |
| **Pick history** | HISTORY, STREAK, scoring, and recap cards | While subscribed |
| **Inbound message IDs** | Webhook deduplication (not message bodies) | ~7 days |
| **Vision call logs** (phone + timestamp) | Abuse/cost rate limits | Rolling window |

We do **not** sell or share subscriber data with third parties for marketing. LLM providers (e.g. Google Gemini) process prompts when you use vision or radio features; screenshots are sent for extraction only and are not stored as images.

## How to control your data

| Action | Command | Effect |
|--------|---------|--------|
| **Stop messages** | `UNSUBSCRIBE` | Sets `active=false`. Data retained so you can rejoin with `SUBSCRIBE`. |
| **Delete all data** | `DELETE` | Hard-deletes your subscriber row and all linked records (picks, team, league state, pending flows, share tokens, etc.). Immediate — no 30-day wait. |
| **Update team** | `TEAM` or send a My Team screenshot | Overwrites team fields; never writes `NULL` over existing values. |
| **Change timezone** | `TIMEZONE Europe/London` (IANA) | Updates delivery timezone |

`HELP` lists available commands including `DELETE`.

## Deletion scope

`DELETE` removes data keyed to your phone number across:

- Subscriber profile and preferences  
- Fantasy team, team/league onboarding state  
- Personalized picks, live-alert delivery log, price reports you submitted  
- Pending screenshot/timezone flows, vision rate-limit log entries  
- Share cards and chip-plan tokens tied to your phone  
- Team value snapshots and weekend notification dedup rows  

Tables without a per-user phone column (e.g. aggregate season accuracy, circuit-level practice signals) are not deleted.

## Security practices

- WhatsApp webhook payloads are verified with **HMAC-SHA256** (`X-Hub-Signature-256`) in production (`mode=live`).  
- Phone numbers are **masked in logs** (e.g. `+4477…`).  
- Inbound images are size-capped, magic-byte validated, and downloaded only from Meta CDN hosts.  
- Vision API calls are rate-limited per phone and globally.  
- Optional API keys (`encrypted_api_key` on subscriber) use Fernet at rest when configured via the web settings page.

## Contact & jurisdiction

Deployers must publish a contact email or web form for data requests where required (GDPR/CCPA). PitWallAI’s open-source operators should set `PITWALL_PRIVACY_CONTACT` (or equivalent) in their deployment README before production launch.

## Changes

Material changes to this policy should be communicated to active subscribers via WhatsApp before taking effect.
