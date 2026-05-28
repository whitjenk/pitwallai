# PitWallAI

> The most useful thing an F1 fantasy fan has on race weekend.

PitWallAI is an open-source multi-agent intelligence system that delivers personalized F1 fantasy picks to your WhatsApp — budget-aware, circuit-adjusted, and powered by signals no pundit has access to.

*[Screenshot placeholder: WhatsApp message showing race picks]*

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://github.com/whitjenk/pitwallai/actions/workflows/ci.yml/badge.svg)](https://github.com/whitjenk/pitwallai/actions/workflows/ci.yml)
[![OpenF1](https://img.shields.io/badge/OpenF1-WebSocket-red)](https://openf1.org/)

---

## What it does

Three hours before race lock, you get a WhatsApp message. Not generic advice — picks filtered to your actual team, your remaining budget, and your available transfers. Backed by five agents that have been working since Thursday.

**Thursday** — Context Builder ingests circuit history, championship pressure per driver, weather forecast, and any FIA directives issued that week.

**Friday** — Practice Analyst processes FP1 and FP2. Extracts structured sentiment from team radio ("the rear feels loose in sector two") and flags statistical anomalies — a driver 0.8s off their FP1 pace on used rubber is a signal worth knowing about.

**Saturday night** — Quali Strategist takes your team, your budget, and the qualifying result. Models every legal transfer combination. Sends you the one swap that pencils out.

**Sunday during the race** — Live Race Monitor watches the OpenF1 stream. Safety car on lap 23? Your phone gets an alert before the commentators finish their sentence.

**Sunday night** — Scorer logs every pick against the actual result. The system gets measurably smarter each race.

---

## Subscribe

Text **SUBSCRIBE** to [number] on WhatsApp.  
Text **TEAM** to set up your fantasy team for personalized picks.  
Text **HELP** for all commands.

*Free. Open source. No app required.*

---

## Season GP pick hit rate

Picks are scored against **Grand Prix race results** using the official F1 Fantasy race points scale (not qualifying or sprint). Updated after every race.

[Link to live leaderboard]

---

## Run it yourself

No API key required for the Monaco rehearsal demo:

```bash
git clone https://github.com/whitjenk/pitwallai.git
cd pitwallai
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py --mode rehearsal --speed 3.0
# Dashboard → http://localhost:8000/dashboard
```

What you'll see: Lap 37, Ferrari boxes. Before it hits the broadcast, the competitor intel panel surfaces a 91% reliability signal. An amber gate holds it until a human acknowledges it. Lap 38, Norris reports his fronts are gone — CRITICAL tire complaint, decoded in under 100ms.

*The full rehearsal runs on local mock data. No live connection needed.*

---

## How it works

Five agents. One orchestrator. One shared context object passed across the race weekend.

```
Thursday     Friday        Saturday      Sunday        Post-Race
────────────────────────────────────────────────────────────────
Context   Practice      Quali         Live Race     Scorer +
Builder   Analyst       Strategist    Monitor       Learner
    │         │              │              │            │
    └─────────┴──────────────┴──────────────┴────────────┘
                          Orchestrator
                              │
                    WhatsApp → Fan
```

The radio intelligence pipeline (Practice Analyst / Live Race Monitor) extends the existing Radio Intercept Decoder — rules-first with optional LLM escalation, sub-100ms on the default path:

```
OpenF1 WebSocket → asyncio.Queue → RadioInterceptDecoder
  ├── rules path    ~5–80ms   vector vote + pattern match
  └── LLM path      ~300ms    Pydantic AI + ChromaDB retrieval
        │
        ▼
DecodedTransmission (Pydantic v2, frozen)
  ├── decoded_intent: RadioIntent
  ├── strategic_signal: StrategicSignal
  ├── evidence_summary: str     ← observation only, never directive
  └── processing_latency_ms: float
```

→ Deeper architecture, CLI, tests, and data-science notes: **[TECHNICAL.md](TECHNICAL.md)**

---

## Design principles

**Evidence, not instructions.** The output field is `evidence_summary`, not `recommended_action`. The system tells you what it heard and what history says about it. You decide. A fan who second-guesses their read because an AI gave a conflicting instruction has lost something. That is not a tool — that is a liability.

**Human confirmation gate.** Any CompetitorIntel object carries a ConfirmationState: UNCONFIRMED → ACKNOWLEDGED → ACTED_ON. The pipeline earns trust through provenance — every output shows the evidence that drove it.

**800ms is the contract.** The value of a decoded signal is in the window before it's confirmed on broadcast. After that, it's noise. Every DecodedTransmission carries an `exceeds_latency_target` flag. `bench.py` profiles each pipeline stage independently.

---

## Stack

| Layer | Technology |
|---|---|
| Agent orchestration | PydanticAI (model-agnostic) |
| Default LLM | Gemini 2.0 Flash via Vertex AI |
| BYOK | Claude / GPT-4o-mini / Ollama |
| Vector store | ChromaDB |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Live data | OpenF1 API (WebSocket + REST) |
| Async runtime | asyncio + websockets |
| API server | FastAPI + uvicorn |
| Database | Postgres (Railway) |
| Delivery | WhatsApp Cloud API |

---

## Contributing

Contributions are open. The five-agent architecture is the roadmap — see [TECHNICAL.md](TECHNICAL.md) for implementation contracts. New agents must follow the established pattern: typed `AgentDependencies`, `RunContext`-scoped tools, Pydantic v2 output model, asyncio-native throughout. Open an issue before starting a new agent.

## Disclaimer

PitWallAI is an independent open-source fan project. It is **not** affiliated with, endorsed by, or sponsored by Formula One Licensing B.V., the FIA, or the official [F1 Fantasy](https://fantasy.formula1.com/) game. F1, Formula 1, and related marks are trademarks of their respective owners.

**AI-generated intelligence.** Picks, recaps, radio decoding, and other outputs may use rules engines, statistical models, and large language models. They can be wrong, incomplete, or out of date — especially when data is missing, sessions change, or the official game applies penalties after the fact. PitWallAI is **not** financial or betting advice. You are responsible for your own fantasy decisions; always verify lineup, budget, transfers, and lock time in the official F1 Fantasy app.

Fantasy scoring and prices in this repo are simplified approximations of published game rules — always confirm transfers and points in the official app before lock.

Live timing and session data may be sourced from [OpenF1](https://openf1.org/) and other public APIs; see their terms for attribution and use.

WhatsApp is a trademark of Meta Platforms, Inc. Subscribers opt in via **SUBSCRIBE** and can opt out with **UNSUBSCRIBE**. Phone numbers and team data are stored to deliver picks; do not deploy without a privacy policy appropriate for your jurisdiction.

## License

MIT
