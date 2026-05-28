# PitWallAI — Technical Reference

Developer-facing documentation for the radio intercept pipeline, WhatsApp integration, testing, and deployment. For the product overview, see [README.md](README.md).

---

## Implementation status

| Component | Status |
|-----------|--------|
| Radio Intercept Decoder + dashboard | Shipped |
| Monaco rehearsal scenario | Shipped |
| WhatsApp webhook, commands, `send_message` | Shipped |
| Postgres subscriber schema + Fernet BYOK | Shipped |
| Context Builder | Planned |
| Practice Analyst (full weekend scope) | Partial (decoder live) |
| Quali Strategist | Planned |
| Scorer + season leaderboard | Planned |
| `TEAM` fantasy setup command | Planned |

---

## Full pipeline (queue depths and fan-out)

*For strategists: radio in, structured intelligence out, under 800ms. For engineers: OpenF1 WebSocket → asyncio queue → rules-first decoder with ChromaDB retrieval (optional Pydantic AI escalation) → validated struct → FastAPI WebSocket → React dashboard → WhatsApp.*

```
OpenF1 WebSocket  (/v1/team_radio)
        │
        ▼
  asyncio.Queue  ←── backpressure guard (max depth 50)
        │
        ▼
Radio Intercept Decoder
  ├── rules path (default)     →  vector vote + pattern match  (~5–80ms)
  └── optional LLM path      →  Pydantic AI + provider tool calls
        ├── query_historical_context  →  ChromaDB  (sentence-transformers embeddings)
        ├── lookup_jargon             →  40-term F1 glossary
        └── get_driver_context        →  driver communication profiles
        │
        ▼
  DecodedTransmission  (Pydantic v2, frozen)
  ├── decoded_intent: RadioIntent
  ├── strategic_signal: StrategicSignal
  ├── urgency_level: UrgencyLevel
  ├── competitor_intel: CompetitorIntel | None  ← requires human confirmation
  ├── evidence_summary: str | None              ← observation, never instruction
  └── processing_latency_ms: float
        │
        ├──► FastAPI WebSocket  →  React dashboard
        └──► WhatsApp broadcast (subscriber fan-out foundation)
```

Per-message `AgentDependencies` are **not** mutated in the hot path — `dataclasses.replace()` passes an isolated `session_key` per decode to avoid races between producer and consumer coroutines.

---

## Design principles (expanded)

### Evidence, not instructions

The output field is called `evidence_summary`, not `recommended_action`. It is a factual observation connecting what the system heard to historical precedent: *"Transcript matches 3 of 4 pre-box indicators observed at Bahrain 2023 lap 31. Gap to leader is 2.1s and closing."* Never: *"Box Lando now."*

The strategist (or fan) decides. The system informs. Post-LLM, `_sanitise_evidence_summary()` strips directive language at the decoder boundary so schema-valid but badly worded model output cannot reach clients.

### Human confirmation gate

Any `CompetitorIntel` carries `ConfirmationState`: `UNCONFIRMED → ACKNOWLEDGED → ACTED_ON`. Unconfirmed intel renders behind an amber gate on the dashboard until acknowledged. Every intel card shows the evidence transcript and retrieval provenance (`context_doc_ids` on the decode).

### 800ms is the contract

The value of a decoded signal is in the window before the call is confirmed on broadcast. `exceeds_latency_target` is set when `processing_latency_ms > 800`. The dashboard latency gauge and `bench.py` stage breakdown (embedding, vector query, rules/LLM inference, validation) make regressions diagnosable.

**Targets:** P50 end-to-end &lt; 800ms, P95 &lt; 1200ms on the rules path (see `latency_report.json` from `python bench.py --runs 20 --backend rules`).

---

## For F1 data scientists

The system ingests from OpenF1's `/v1/team_radio` WebSocket endpoint. Rehearsal mode uses a hardcoded scenario with `session_key=9158` (Monaco 2024): 12 sequential events across laps 34–40. The vector store is ChromaDB in-memory, seeded with 22 hand-crafted historical transcripts. The intended production path is PostgreSQL + pgvector with real historical radio indexed from past sessions via FastF1.

Transcripts are embedded using `sentence-transformers` (`all-MiniLM-L6-v2`). On the default **rules** path, retrieval runs on every decode via vector similarity and weighted intent voting. On the optional **LLM** path, the agent calls `query_historical_context` as an explicit tool — retrieval sits inside the model's reasoning chain, not as a blind pre-fetch.

Set `PITWALL_DECODE_BACKEND=hybrid` to escalate only low-confidence decodes. Hard budget caps (`PITWALL_LLM_BUDGET_ACK`, per-session call limits, daily spend ceiling) prevent runaway API cost during a race.

**LLM providers** (same prompt and `DecodedTransmission` schema for all):

| Provider | Config | Default model |
|----------|--------|----------------|
| `gemini` | Vertex AI (ADC) or `PITWALL_GOOGLE_API_KEY` | `gemini-2.0-flash` |
| `claude` | `PITWALL_ANTHROPIC_API_KEY` | `claude-3-5-sonnet-latest` |
| `openai` | `PITWALL_OPENAI_API_KEY` | `gpt-4o-mini` |
| `ollama` | `PITWALL_OLLAMA_BASE_URL` | `llama3.2` |

Factory: `pitwallai/agents/radio_intercept/model_factory.py` → `get_model(provider, api_key)`.

New agents should use: typed `AgentDependencies`, `RunContext`-scoped tools, Pydantic v2 output, `asyncio` throughout. Additional agents can subscribe to the decoder fan-out queue without modifying the consumer.

---

## Prerequisites

- Python **3.11+** (3.9 will not work — uses modern typing and `datetime.UTC`)
- Optional: PostgreSQL `DATABASE_URL` for WhatsApp subscribers
- Optional: Meta WhatsApp Cloud API credentials
- No LLM API key for default `rules` decode

---

## Environment variables

Copy `.env.example` to `.env`.

| Group | Variables | Purpose |
|-------|-----------|---------|
| Decode | `PITWALL_DECODE_BACKEND` | `rules`, `hybrid`, `llm` |
| LLM | `PITWALL_LLM_PROVIDER`, `PITWALL_LLM_MODEL`, `PITWALL_LLM_USE_VERTEX`, `GOOGLE_CLOUD_PROJECT` | Vertex Gemini default |
| Budget | `PITWALL_LLM_BUDGET_ACK`, `PITWALL_LLM_MAX_*` | Spend guardrails |
| WhatsApp | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WEBHOOK_VERIFY_TOKEN` | Meta Cloud API |
| Security | `ENCRYPTION_KEY` | Fernet for BYOK keys at rest |
| Database | `DATABASE_URL` | Postgres (Railway injects in prod) |

Generate Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Settings load via `whatsapp/settings.py` (`WhatsAppSettings`, pydantic-settings) — nothing hardcoded.

---

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `rehearsal` | `live` = OpenF1 WebSocket; `rehearsal` = Monaco script |
| `--speed` | `3.0` | Rehearsal playback multiplier (`5.0` ≈ 90s total) |
| `--port` | `8000` | HTTP port |
| `--decode-backend` | `rules` | `rules`, `hybrid`, or `llm` |
| `--llm-model` | *(env)* | Override model name |
| `--bind-host` | `127.0.0.1` | HTTP bind address |

---

## WhatsApp integration

**Webhook** (registered on `main:app`):

- `GET /webhook` — Meta verify (`hub.mode`, `hub.verify_token`, `hub.challenge`)
- `POST /webhook` — returns 200 immediately; processes inbound messages in background

**Commands** (`whatsapp/commands.py`):

| Command | Behavior |
|---------|----------|
| `SUBSCRIBE` | Prompt for IANA timezone → create subscriber row |
| `UNSUBSCRIBE` | `active=False` (soft delete) |
| `HELP` | Command list (≤160 chars) |
| `SETTINGS` | Link to BYOK settings page |

**Outbound:** `whatsapp/sender.py` → `send_message(phone, text)` with exponential backoff on 429/5xx (max 3 retries).

Local verify:

```bash
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test123"
```

---

## The dashboard

Single HTML file (`dashboard.jsx`), no build step. Three columns:

- **Left** — live transmission feed (team colors, intent badges, jargon decode, latency)
- **Center** — strategic signals, competitor intel (amber gate until acknowledged), session timeline
- **Right** — Monaco track map, latency gauge, intent/urgency charts, rehearsal controls

---

## Testing

Three layers — run in order:

```bash
# No server, no LLM — async runtime + error isolation (~2s)
pytest tests/test_resilience.py -v

# Monaco pipeline contracts (~2s, rules backend)
pytest tests/test_e2e.py -v

# Mocked LLM provider contracts (~2s)
pytest tests/test_llm_contracts.py -v

# Requires running server — multi-client WebSocket fan-out (~90s)
pytest tests/test_ws_stress.py -v

# Stage timings → latency_report.json
python bench.py --runs 20 --backend rules
```

**CI** (`.github/workflows/ci.yml`): Python 3.11, `test_e2e` + `test_resilience` + `test_llm_contracts` only. `test_ws_stress` excluded (needs live server).

---

## Deploy on Railway

`railway.toml`:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set `DATABASE_URL`, WhatsApp vars, and `PITWALL_MODE` in the Railway dashboard. Tables are created on startup via `init_db()` when `DATABASE_URL` is present.

---

## Repository layout (core)

```
pitwallai/agents/radio_intercept/   # decode pipeline, agents, models
api/                                # FastAPI app factory, rehearsal engine
whatsapp/                           # webhook, commands, sender, settings
db/                                 # Subscriber ORM, async session, Fernet
main.py                             # ASGI entry (uvicorn main:app)
dashboard.jsx                       # strategist / demo UI
bench.py                            # latency benchmark
tests/                              # e2e, resilience, llm contracts, ws stress
```

---

## Contributing

Open an issue before starting a new agent. Follow the contracts above; see `tests/` for regression patterns.

## License

MIT
