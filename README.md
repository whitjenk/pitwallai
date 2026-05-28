On a modern F1 pit wall, a strategist is processing two driver radios, live timing, tire models, weather, and race control simultaneously. PitWallAI decodes competitor team radio in real time and surfaces structured tactical intelligence — intent, strategic signal, historical precedent — before the rival team confirms their call on the broadcast feed.

![CI](https://github.com/whitjenk/f1-tactical-intelligence-hive/actions/workflows/ci.yml/badge.svg) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![License: MIT](https://img.shields.io/badge/license-MIT-green) ![Status: Research Preview](https://img.shields.io/badge/status-research%20preview-orange) ![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688) ![Pydantic AI](https://img.shields.io/badge/Pydantic%20AI-0.0.13%2B-violet) ![OpenF1](https://img.shields.io/badge/OpenF1-WebSocket-red)

*For strategists: a live intelligence feed that informs without directing. For engineers: an async multi-agent pipeline built on OpenF1, vector retrieval, optional Pydantic AI, and ChromaDB.*

## See it in 60 seconds

There is a built-in Monaco Grand Prix rehearsal scenario — 12 radio events across laps 34–40, four teams, one strategic battle. No API key is required for the default path. Run it with three commands:

```bash
git clone https://github.com/your-handle/pitwallai.git && cd pitwallai
pip install -r requirements.txt
python main.py --mode rehearsal --speed 3.0
# Dashboard → http://localhost:8000/dashboard
```

What you will see on the dashboard:

- Lap 37: Ferrari boxes. Before it hits the broadcast, the competitor intel panel surfaces a 91% reliability signal with the evidence transcript. An amber gate holds it until a human acknowledges it.
- Lap 38: Norris reports his fronts are gone. The system decodes CRITICAL tire complaint, fires a TIRE_DEGRADATION_HIGH strategic signal, and the latency gauge shows end-to-end decode in real time (typically sub-100ms on the default rules path).
- Lap 40: After the pit stop, PUSH_MODE decoded, pace shift signal confirmed. The Monaco track map updates with driver positions and event pins at the sector where each call originated.

*No live race connection required. The rehearsal runs entirely on local mock data.*

## The problem it solves

During a live grand prix, a strategist tracking competitor radio manually is always behind. By the time a pit call is confirmed on the FOM broadcast, the window for a reactive undercut is already closing. The radio transmission that precedes a pit call — the tire complaint three laps earlier, the gap query, the engineer's carefully worded non-answer — contains the signal. Getting to it structured, grounded in historical precedent, and in front of the right person before it resolves is the entire value proposition.

The second problem is cognitive load. A race strategist in a live stint is managing too many parallel streams to manually pattern-match against historical race data in real time. PitWallAI does not replace that judgement. It compresses the information surface — extracting intent, translating jargon, surfacing relevant historical outcomes — so the strategist spends their cognitive budget on decisions, not data triage.

## How it works

*For strategists: radio in, structured intelligence out, under 800ms. For engineers: OpenF1 WebSocket → asyncio queue → rules-first decoder with ChromaDB retrieval (optional Pydantic AI escalation) → validated struct → FastAPI WebSocket → React dashboard.*

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
        ▼
  FastAPI WebSocket  →  React dashboard
```

| Agent | Status | Responsibility |
|---|---|---|
| Radio Intercept Decoder | Built | Decodes competitor radio, extracts tactical intent |
| Race Control & Regulations | Planned | Analyses steward updates, penalty risk assessment |
| Telemetry Verification | Planned | Validates human claims against live sensor data |
| Lead Strategist Orchestrator | Planned | Synthesises all agents into a single briefing stream |

## Design principles

**Evidence, not instructions**

The output field is called `evidence_summary`, not `recommended_action`. It is a factual observation connecting what the system heard to historical precedent: *"Transcript matches 3 of 4 pre-box indicators observed at Bahrain 2023 lap 31. Gap to leader is 2.1s and closing."* Never: *"Box Lando now."* The strategist decides. The system informs. A strategist who second-guesses their own read because an AI gave a conflicting instruction has introduced hesitation into a decision that costs tenths of a second. That is not a tool — that is a liability.

**Competitor intel requires a human gate**

Any `CompetitorIntel` object carries a `ConfirmationState`: `UNCONFIRMED → ACKNOWLEDGED → ACTED_ON`. Unconfirmed competitor intel renders behind a visual gate on the dashboard — a pulsing amber border, an explicit acknowledgement button. A mis-decoded competitor signal acted on directly is not just a missed opportunity. In a close fight, it is a lost race. The pipeline earns trust through provenance: every intel output shows the evidence transcript that drove it and the historical documents it matched against.

**800ms is the contract, not a target**

The value of a decoded radio intercept is in the window before the call is confirmed on broadcast. After that, it is noise. The `exceeds_latency_target` flag on every `DecodedTransmission` and the live latency gauge on the dashboard make this constraint visible in real time. The benchmark script (`bench.py`) profiles each pipeline stage independently — embedding, vector retrieval, LLM inference, validation — so latency regressions are diagnosable, not just observable.

## The dashboard

A single HTML file, no build step, opens in any browser after `python main.py`. Designed to feel like mission control, not a side project.

Left column — a live scrolling feed of decoded transmissions. Each card shows the driver in their team color, the raw transcript, the decoded intent as a color-coded badge (gray through red by urgency), jargon translated into plain English, and the processing latency in the corner. New cards slide in from the bottom.

Center column — the strategic intelligence board. Active strategic signals at the top. Below that, the competitor intel panel: the feature that earns the most attention in any demo. Unconfirmed intel cards pulse amber until a human acknowledges them. Acknowledged intel turns solid blue. Acted-on intel moves to a session timeline at the bottom of the column.

Right column — the Monaco circuit map showing live driver positions and sector event pins, a latency gauge, an intent distribution chart, and urgency counters. In rehearsal mode, this column also shows scenario progress and speed controls.

## For F1 data scientists

The system ingests from OpenF1's `/v1/team_radio` WebSocket endpoint. Rehearsal mode uses a hardcoded scenario with `session_key=9158` (Monaco 2024): 12 sequential events across laps 34–40. The vector store is ChromaDB in-memory, seeded with 22 hand-crafted historical transcripts. The intended production path is PostgreSQL + pgvector with real historical radio indexed from past sessions via FastF1.

Transcripts are embedded using `sentence-transformers` (`all-MiniLM-L6-v2`). On the default rules path, retrieval runs on every decode via vector similarity and weighted intent voting. On the optional LLM path, the agent calls `query_historical_context` as an explicit tool — retrieval sits inside the model's reasoning chain, not as a blind pre-fetch. Each `DecodedTransmission` includes `context_doc_ids` for full retrieval provenance. Set `PITWALL_DECODE_BACKEND=hybrid` to escalate only low-confidence decodes to an LLM; hard budget caps (`PITWALL_LLM_BUDGET_ACK`, per-session call limits, daily spend ceiling) prevent runaway API cost during a race.

New agents follow the same contract: a typed `AgentDependencies` dataclass, `RunContext`-scoped tools, a Pydantic v2 output model, and `asyncio`-native execution. The `RadioInterceptDecoder` fan-out pattern means additional agents can subscribe to the output queue without modifying existing code. The most immediately useful extension is a Telemetry Verification Agent that cross-references decoded radio claims against live sector times from `/v1/car_data`.

## Quickstart

### Prerequisites

Python 3.11+ (3.9 will not work — the codebase uses `match` and modern typing). pip. An LLM provider API key is optional and only required if you enable `hybrid` or `llm` decode backends.

### Install and run

```bash
git clone https://github.com/your-handle/pitwallai.git
cd pitwallai
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py --mode rehearsal --speed 3.0
```

*Open `http://localhost:8000/dashboard`. The Monaco scenario runs automatically.*

Optional LLM escalation (not required for the demo):

```bash
export PITWALL_LLM_BUDGET_ACK=1
export PITWALL_LLM_MODEL=openai:gpt-4o-mini
python main.py --mode rehearsal --decode-backend hybrid
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--mode` | `rehearsal` | `live` connects to OpenF1 WebSocket; `rehearsal` replays the Monaco scenario |
| `--speed` | `3.0` | Rehearsal playback multiplier. `1.0` is real time, `5.0` completes in ~90 seconds |
| `--port` | `8000` | FastAPI server port |
| `--decode-backend` | `rules` | `rules` (no API, default), `hybrid` (rules + LLM on low confidence), or `llm` |
| `--llm-model` | *(none)* | Pydantic AI model id, e.g. `openai:gpt-4o-mini` or `anthropic:claude-3-5-sonnet-20241022` |
| `--bind-host` | `127.0.0.1` | HTTP bind address |

## Testing

Three layers — deterministic, pipeline contracts, full system. Run them in order.

```bash
# No LLM calls — tests async runtime, error isolation, sentinel handling (~10s)
pytest tests/test_resilience.py -v

# Pipeline contracts — Monaco scenario decode assertions (~10s, rules backend)
pytest tests/test_e2e.py -v

# Requires server running — tests multi-client WebSocket fan-out (~90s)
pytest tests/test_ws_stress.py -v --timeout=120

# Profiles each pipeline stage, writes latency_report.json
python bench.py --runs 20
```

## Stack

| Layer | Technology |
|---|---|
| Agent orchestration | Pydantic AI (optional LLM path) |
| Decode (default) | Rules engine + ChromaDB vector vote |
| LLM (optional) | Provider-agnostic via Pydantic AI (OpenAI, Anthropic, etc.) |
| Data validation | Pydantic v2 |
| Vector store | ChromaDB (in-memory) |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| Live data | OpenF1 API (WebSocket + REST) |
| Async runtime | Python `asyncio` + `websockets` |
| API server | FastAPI + uvicorn |
| Dashboard | React 18 + Recharts + Tailwind CSS (CDN) |
| Logging | loguru |

## Project status

This repository contains Agent 1 of a planned four-agent system. The current implementation is a research preview — the pipeline is functional and the Monaco rehearsal demo is stable on the default rules path without any API spend, but live race deployment would require production-grade vector storage (PostgreSQL + pgvector), latency validation against real OpenF1 stream conditions, and a formal review process for competitor intel before it reaches a strategist. The three remaining agents are scoped and the contribution path is open.

## Contributing

Contributions are open. The architecture table in the previous section is the most direct signal of what is most useful to build next. New agents must follow the established contract: typed `AgentDependencies`, `RunContext`-scoped tools, structured Pydantic output, `asyncio`-native execution throughout. Open an issue before starting work on a new agent so the scope can be aligned.

## License

MIT
