# PitWallAI

> The most useful thing an F1 fantasy fan has on race weekend.

PitWallAI is an open-source multi-agent intelligence system that delivers personalized F1 fantasy picks to your WhatsApp — budget-aware, circuit-adjusted, and powered by signals no pundit has access to.

*[Screenshot placeholder: WhatsApp message showing race picks]*

[![CI](https://github.com/whitjenk/f1-tactical-intelligence-hive/actions/workflows/ci.yml/badge.svg)](https://github.com/whitjenk/f1-tactical-intelligence-hive/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![OpenF1](https://img.shields.io/badge/OpenF1-WebSocket-red)](https://openf1.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688)](https://fastapi.tiangolo.com/)

---

## What it does

Three hours before race lock, you get a WhatsApp message. Not generic advice — picks filtered to your actual team, your remaining budget, and your available transfers. Backed by five agents that have been working since Thursday.

| When | Agent | What it does |
|------|--------|----------------|
| **Thursday** | Context Builder | Ingests circuit history, championship pressure per driver, weather forecast, and FIA directives for the week. |
| **Friday** | Practice Analyst | Processes FP1/FP2. Extracts structured sentiment from team radio and flags statistical anomalies (e.g. 0.8s off FP1 pace on used rubber). |
| **Saturday night** | Quali Strategist | Takes your team, budget, and qualifying result. Models legal transfer combinations and surfaces the one swap that pencils out. |
| **Sunday (live)** | Live Race Monitor | Watches the OpenF1 stream. Safety car on lap 23? Alert before the commentators finish the sentence. |
| **Sunday night** | Scorer | Logs every pick against the actual result. The system gets measurably smarter each race. |

**What ships in this repo today:** the **Live Race Monitor** core (Radio Intercept Decoder), a real-time strategist dashboard, Monaco rehearsal mode, and the **WhatsApp subscriber foundation** (subscribe, webhook, outbound messaging). The fantasy pick agents and `TEAM` setup flow are on the roadmap — see [Project status](#project-status).

---

## Subscribe

Text **SUBSCRIBE** to the PitWallAI WhatsApp number *(configure your Meta Business number in production)*.

1. Reply with your IANA timezone (e.g. `Europe/London`).
2. You are in — race-weekend alerts use that timezone.

| Command | Action |
|---------|--------|
| `SUBSCRIBE` | Join alerts (prompts for timezone) |
| `UNSUBSCRIBE` | Stop alerts (soft delete — we never hard-delete your row) |
| `HELP` | Command list |
| `SETTINGS` | BYOK API key page → [pitwallai.app/settings](https://pitwallai.app/settings) |
| `TEAM` | *Coming soon* — set your fantasy team for personalized picks |

*Free. Open source. No app required.*

---

## Season accuracy

**[Live leaderboard](https://github.com/whitjenk/f1-tactical-intelligence-hive)** — updated after every race *(placeholder until Scorer agent ships)*.

---

## Run it yourself

### Prerequisites

- **Python 3.11+** (3.9 will not work)
- Optional: **PostgreSQL** `DATABASE_URL` for WhatsApp subscribers (Railway injects this in production)
- Optional: Meta **WhatsApp Cloud API** credentials for live messaging
- No LLM API key required for the default **rules** decode path

### Install

```bash
git clone https://github.com/whitjenk/f1-tactical-intelligence-hive.git
cd f1-tactical-intelligence-hive
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — see Environment variables below
python main.py --mode rehearsal --speed 3.0
```

Open **http://localhost:8000/dashboard** — the Monaco rehearsal scenario runs automatically (12 radio events, laps 34–40, four teams).

### Environment variables

Copy `.env.example` to `.env`. Key groups:

| Group | Variables | Purpose |
|-------|-----------|---------|
| **Decode** | `PITWALL_DECODE_BACKEND` | `rules` (default, free), `hybrid`, or `llm` |
| **LLM (optional)** | `PITWALL_LLM_PROVIDER`, `PITWALL_LLM_MODEL`, `PITWALL_LLM_BUDGET_ACK` | Vertex Gemini default: `gemini-2.0-flash` |
| **WhatsApp** | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WEBHOOK_VERIFY_TOKEN` | Meta Cloud API + webhook verify |
| **Security** | `ENCRYPTION_KEY` | Fernet key for stored user API keys (BYOK) |
| **Database** | `DATABASE_URL` | Postgres for subscribers (Railway auto-provides) |

Generate a Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### WhatsApp webhook (local)

Expose port 8000 (e.g. [ngrok](https://ngrok.com/)) and point Meta’s webhook to:

- **Callback URL:** `https://<your-host>/webhook`
- **Verify token:** same as `WEBHOOK_VERIFY_TOKEN` in `.env`

```bash
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test123"
# → test123
```

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `rehearsal` | `live` = OpenF1 WebSocket; `rehearsal` = Monaco script |
| `--speed` | `3.0` | Rehearsal playback multiplier |
| `--port` | `8000` | HTTP port |
| `--decode-backend` | `rules` | `rules`, `hybrid`, or `llm` |

### Deploy on Railway

`railway.toml` starts the app with:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set `PITWALL_MODE`, `DATABASE_URL`, and WhatsApp env vars in the Railway dashboard.

---

## See it in 60 seconds (dashboard)

No API key. No live race required.

```bash
pip install -r requirements.txt
python main.py --mode rehearsal --speed 3.0
```

What you will see:

- **Lap 37:** Ferrari pit intel surfaces with evidence before broadcast confirmation; amber gate until a human acknowledges.
- **Lap 38:** Norris tire complaint decoded as CRITICAL; sub-100ms on the default rules path.
- **Lap 40:** PUSH_MODE and pace-shift signal; Monaco track map with driver dots and event pins.

---

## How the live monitor works today

```
OpenF1 WebSocket  (/v1/team_radio)
        │
        ▼
  asyncio.Queue  ←── backpressure guard
        │
        ▼
Radio Intercept Decoder
  ├── rules path (default)     →  vector vote + pattern match
  └── optional LLM path      →  Pydantic AI + ChromaDB tools
        │
        ▼
  DecodedTransmission  (intent, signal, urgency, competitor intel)
        │
        ├──► FastAPI WebSocket  →  React dashboard
        └──► WhatsApp broadcast (foundation in place)
```

**Design principles**

- **Evidence, not instructions** — `evidence_summary` is observational, never “box now.”
- **Competitor intel requires a human gate** — `UNCONFIRMED → ACKNOWLEDGED → ACTED_ON`.
- **800ms is the contract** — decode latency is measured and surfaced on every transmission.

---

## Testing

```bash
# Pipeline + resilience (CI — no server, no LLM)
pytest tests/test_e2e.py tests/test_resilience.py tests/test_llm_contracts.py -v

# WebSocket fan-out (~90s, starts server subprocess)
pytest tests/test_ws_stress.py -v

# Latency benchmark → latency_report.json
python bench.py --runs 20 --backend rules
```

---

## Stack

| Layer | Technology |
|-------|------------|
| Agents | Pydantic AI (optional LLM), rules engine (default) |
| Vector store | ChromaDB + sentence-transformers |
| Live data | OpenF1 WebSocket |
| API | FastAPI + uvicorn |
| Dashboard | React 18 (CDN, no build step) |
| WhatsApp | Meta Cloud API |
| Subscribers | PostgreSQL + SQLAlchemy (async) |
| Secrets at rest | cryptography (Fernet) |

---

## Project status

| Component | Status |
|-----------|--------|
| Radio Intercept Decoder + dashboard | **Shipped** |
| WhatsApp webhook, commands, `send_message` | **Shipped** |
| Postgres subscriber schema + BYOK encryption | **Shipped** |
| Context Builder, Practice Analyst, Quali Strategist | Planned |
| Fantasy `TEAM` command + personalized picks | Planned |
| Scorer + season leaderboard | Planned |

This is a research preview moving toward full fantasy-weekend coverage. Contributions welcome — open an issue before starting a new agent.

---

## Contributing

New agents should follow the established contract: typed `AgentDependencies`, shared tools, Pydantic v2 outputs, and `asyncio`-native execution. The decoder fan-out pattern lets additional agents subscribe without modifying existing pipelines.

---

## License

MIT
