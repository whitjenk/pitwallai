# PitWallAI — Technical Reference

Developer-facing documentation for the radio intercept pipeline, WhatsApp integration, testing, and deployment. For the product overview, see [README.md](README.md).

---

## Implementation status

| Component | Status |
|-----------|--------|
| Radio Intercept Decoder + dashboard | Shipped |
| Monaco rehearsal scenario | Shipped |
| WhatsApp webhook, command router, `send_message` | Shipped |
| Postgres subscriber schema + Fernet BYOK | Shipped |
| **3-agent weekend pipeline** (`PIPELINE_VERSION=3-agent-v1`) | Shipped |
| PicksAgent — context stage (Thursday) | Shipped |
| PicksAgent — practice stage (FP1/FP2 + anomalies) | Shipped |
| PicksAgent — quali stage (pre-lock picks + broadcast) | Shipped |
| RaceMonitor (Sunday live alerts) | Shipped |
| ScorerLearner (post-race scoring + signal quality) | Shipped |
| Pick generator (PATH A/B) + audit log | Shipped |
| `/api/picks` + scheduled picks job | Shipped |
| APScheduler race calendar + WhatsApp broadcast | Shipped |
| Screenshot team onboarding (Gemini Vision) | Shipped |
| `TEAM` / `UPDATE` fantasy setup commands | Shipped |
| App-review hygiene (vision caps, media validation, claim-then-process webhook, `PRIVACY.md`) | Shipped |

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

Weekend orchestration uses **three named agents** (`agents/__init__.py`, `agents/picks_agent.py`):

| Agent | Module(s) | Notes |
|-------|-----------|-------|
| **PicksAgent** | `context_builder.py`, `practice_analyst.py`, `quali_strategist.py` | Three **stages** (`PicksStage`: `context` → `practice` → `quali`), one versioned interface |
| **RaceMonitor** | `race_monitor.py` | Sunday live loop; separate 800ms decode contract |
| **ScorerLearner** | `scorer_learner.py` | Post-race scoring, season accuracy, signal-quality weights |

`LeadStrategist` (`orchestrator/lead_strategist.py`) coordinates all three. Bump `PIPELINE_VERSION` in `pitwallai/version.py` when topology or stage behaviour changes.

Radio decode uses typed `AgentDependencies`, `RunContext`-scoped tools, Pydantic v2 output, `asyncio` throughout. Additional consumers can subscribe to the decoder fan-out queue without modifying the consumer.

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
| WhatsApp | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | Meta Cloud API |
| Picks API | `PITWALL_PICKS_API_KEY` | Protects `/api/picks` (required for `?phone=` personalized access) |
| Security | `ENCRYPTION_KEY` | Fernet for BYOK keys at rest |
| Database | `DATABASE_URL` | Postgres (Railway injects in prod) |
| Vision caps | `PITWALL_VISION_MAX_PER_PHONE_HOUR`, `PITWALL_VISION_MAX_GLOBAL_DAY` | Screenshot / standings extractors |
| Dev webhook | `PITWALL_DEV_ONLY_SKIP_WEBHOOK_SIGNATURE` | Local only; ignored when `mode=live` |

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
- `POST /webhook` — returns 200 immediately; processes inbound messages in background. Requires `WHATSAPP_APP_SECRET` and valid `X-Hub-Signature-256` (HMAC-SHA256 of raw body). Set `PITWALL_DEV_ONLY_SKIP_WEBHOOK_SIGNATURE=1` for local dev only (legacy alias `PITWALL_WEBHOOK_SKIP_SIGNATURE`; ignored when `mode=live`). Logs a warning when signature verification is skipped.

**Idempotency:** claim-then-process via `claim_inbound_message()` → handler → `complete_inbound_message()` on `processed_inbound_messages` (`status=claimed` → `done`, stale reclaim after 5 min). Safe under Meta’s multi-day retries.

**Inbound images:** `whatsapp/inbound_image.py` — when `pending_screenshot_state` is set (DB-backed, TTL per kind), downloads media (`whatsapp/media.py`: magic-byte validation, 8 MiB reject, Meta CDN host allowlist), runs vision extractors under `intelligence/vision_budget.py` caps, saves team or league standings.

**Commands** — `whatsapp/inbound.py` (onboarding flows) + `whatsapp/command_router.py` (structured commands in `whatsapp/commands/`):

| Command | Behavior |
|---------|----------|
| `SUBSCRIBE` | Infer timezone from country code; unknown codes get IANA prompt (`pending_timezone_state`, 24h TTL) |
| `TIMEZONE Europe/London` | Override timezone explicitly |
| `UNSUBSCRIBE` | `active=False` (soft delete); mentions `DELETE` |
| `DELETE` | Hard-delete all subscriber-linked rows — see [PRIVACY.md](PRIVACY.md) |
| `TEAM` / screenshot | Progressive fantasy team setup (text or vision) |
| `HELP` | Command list |
| `PICKS`, `HISTORY`, `STREAK`, driver codes, `SHARE`, `LIVE ON/OFF`, … | See `whatsapp/commands/` |

**Outbound:** `whatsapp/sender.py` → `send_message(phone, text)` with exponential backoff on 429/5xx (max 3 retries). Phone numbers masked in logs via `mask_phone()`.

**Local simulator:** `python scripts/whatsapp_chat.py` (patches `send_message` to stdout).

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

## Fantasy picks API

Endpoints (included on the main FastAPI app):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/picks` | Return picks for the active weekend (`?refresh=true` to regenerate) |
| `POST` | `/api/picks/generate` | Force an immediate pipeline run |
| `GET` | `/api/picks/status` | Scheduler config and last run metadata |

Query parameters: `phone` (personalized PATH A), `circuit_key`, `year`, `refresh`.

**Auth:** Set `PITWALL_PICKS_API_KEY` and pass `X-PitWall-API-Key: <key>` (or `Authorization: Bearer <key>`) on every `/api/picks` request. Requests fail with 503 until the server key is configured.

**Operational retention:** security tracking tables are pruned periodically in-process:
- processed inbound webhook IDs: ~7 days
- live alert delivery logs: ~14 days

The pipeline (`intelligence/picks_pipeline.py`) runs FP1/FP2 practice analysis → qualifying/weather fetch → pick generation → append-only `picks` audit log.

**Scheduler** (background asyncio task on startup when `PITWALL_PICKS_AUTO=true`, default on in `live` mode):

- `PITWALL_PICKS_INTERVAL_SECONDS` — default `1800` (30 min)
- `PITWALL_CIRCUIT_KEY` — force a circuit (e.g. `monaco` in rehearsal)
- `PITWALL_RACE_YEAR` — default `2026`

Active weekend detection uses OpenF1 Race sessions nearest to “now”, unless `PITWALL_CIRCUIT_KEY` is set.

---

## Race weekend delivery (Phase 4)

**Calendar** — `scheduler/calendar.py` hard-codes 22 confirmed 2026 rounds (Bahrain/Jeddah cancelled). All times UTC; `fantasy_lock_utc` = race − 1hr. `race_key` format: `2026_monaco`.

**F1 Fantasy rules** — `fantasy/rules.py` centralizes official game logic ([game rules](https://fantasy.formula1.com/en/game-rules)): $100M cap (5 drivers + 2 constructors), $3M price floor, 2 free transfers/week (bank +1 → max 3), −10 pts per extra transfer, driver race points 25–1 (P1–P10), DNF/NC −20 (sprint −10), quali NC −5, constructor quali progression (Q2/Q3), constructor race pit-stop tiers (+5 fastest / +15 world record), and six 2026 chips. Pick generation, quali strategist, post-race scoring, and `TEAM` onboarding import from here. Asset prices are approximate placeholders until synced from in-game values.

**APScheduler** — `scheduler/jobs.py` + `scheduler/runtime.py`:

| Job | Trigger | Action |
|-----|---------|--------|
| `thursday_context` | race − 72h | PicksAgent `context` stage (+ sprint/banked-transfer broadcasts) |
| `practice_analysis` | FP2 + 90min | PicksAgent `practice` stage |
| `quali_broadcast` | fantasy_lock − 3h | PicksAgent `quali` stage → `broadcast_race_picks()` |
| `race_monitor_start` | race − 5min | **RaceMonitor** |
| `post_race_scorer` | race + 3h | **ScorerLearner** → recap broadcast |

Jobs persist in Postgres table `apscheduler_jobs` (same `DATABASE_URL`, sync driver). Stable IDs `{race_key}:{job}` + `replace_existing=True` prevent duplicates on Railway restart.

**WhatsApp broadcast** — `whatsapp/broadcast.py` + `whatsapp/message_format.py` (mandatory char assertions: 400 / 350 / 300). Subscriber timezone used only at send time for “hrs to lock”.

**Scoring** — `agents/scorer_learner.py` (**ScorerLearner**) scores driver picks vs **Grand Prix race results** only (official race points scale; see `recap_metrics.PICK_SCORING_SCOPE`). Rolls up `season_accuracy` (GP pick hit rate) and writes `signal_quality` weights. User-facing copy says “GP hit rate”, not generic “accuracy”.

**Orchestration** — `orchestrator/lead_strategist.py` holds immutable `RaceContext` (`evolve_race_context()` / `model_copy`). Scheduler jobs call `LeadStrategist` methods, which delegate to `PicksAgent.run_stage()`, `run_race_monitor()`, or `run_scorer_and_learner()`:

| Agent | Stage / role | Module | Trigger |
|-------|----------------|--------|---------|
| **PicksAgent** | `context` | `agents/context_builder.py` | Thursday |
| **PicksAgent** | `practice` | `agents/practice_analyst.py` | FP2 + 90min |
| **PicksAgent** | `quali` | `agents/quali_strategist.py` | Pre-lock |
| **RaceMonitor** | — | `agents/race_monitor.py` | Race − 5min (long-lived) |
| **ScorerLearner** | — | `agents/scorer_learner.py` | Race + 3h |

Stage functions remain separately testable; `PicksAgent` is the named, versioned interface (`agents/picks_agent.py`). Logs and `run_meta()` carry `pipeline_version` + stage tags for calibration attribution.

**Durable onboarding state** (Postgres, multi-worker safe):

| Table | Purpose | TTL |
|-------|---------|-----|
| `pending_screenshot_state` | Awaiting team / locked-team / standings image | 48h / 36h / 72h |
| `pending_timezone_state` | Awaiting manual IANA timezone | 24h |
| `vision_call_log` | Per-phone hourly + global daily vision caps | Rolling |

Subscriber prefs: `live_alerts`, `cadence_preference` (`FULL` / `RACE_DAY_ONLY`). Commands: `LIVE ON/OFF`, `CADENCE FULL/RACEDAY`.

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

Set `DATABASE_URL`, WhatsApp vars, and `PITWALL_MODE` in the Railway dashboard. On startup, `init_db()` runs `db/migrate.upgrade_schema()`: `create_all` for new tables plus `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for additive Phase 7 columns (`pick_status`, `rehearsal_complete`, etc.). No separate Alembic step required.

**Subscriber rehearsal:** After first `TEAM` confirm (next race >5 days away), `onboarding/rehearsal.py` sends a compressed Monaco 2024 weekend using OpenF1 session `9158` and the same message formatters as production. Set `PITWALL_REHEARSAL_FAST=1` for ~25s spacing in dev. Texting any command pauses rehearsal pacing so replies take priority.

**PICKS command:** Resolved via `whatsapp/app_runtime.get_pick_runtime()` — registered FastAPI app first, then scheduler context, then rules-only lazy runtime if embeddings are available.

---

## Repository layout (core)

```
agents/                             # PicksAgent, RaceMonitor, ScorerLearner (+ stage modules)
pitwallai/agents/radio_intercept/   # Radio Intercept Decoder (separate from weekend agents)
orchestrator/                       # LeadStrategist, RaceContext store
intelligence/                       # pick generator, vision extractors, repository, cache health
openf1/                             # REST client + Postgres cache
circuits/                           # static circuit profiles (startup-injected)
api/                                # FastAPI app factory, picks router, rehearsal
whatsapp/                           # webhook, inbound, command_router, sender, media
db/                                 # ORM models, migrate, Fernet
scheduler/                          # APScheduler jobs → LeadStrategist
main.py                             # ASGI entry (uvicorn main:app)
dashboard.jsx                       # strategist / demo UI
bench.py                            # latency benchmark
scripts/whatsapp_chat.py            # terminal command simulator
tests/                              # e2e, resilience, integration image flow, erase audit
PRIVACY.md                          # data handling + DELETE scope (app review)
```

---

## Contributing

The weekend surface is **three agents** — extend an existing `PicksStage` or agent before proposing a fourth top-level agent. Follow typed `AgentRunDependencies`, Pydantic v2 outputs, and bump `PROMPT_VERSION` / `PIPELINE_VERSION` in `pitwallai/version.py` when user-facing or pipeline behaviour changes. See `tests/` for regression patterns (`test_integration_image_flow.py`, `test_erase_subscriber.py`, `test_mask_phone_audit.py`).

## License

MIT
