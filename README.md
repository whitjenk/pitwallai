# PitWallAI

> The most useful thing an F1 fantasy fan has on race weekend.

> **Independent fan project.** PitWallAI is not affiliated with, endorsed by, or connected to Formula 1, F1 Fantasy, ESPN, or any F1 team or constructor. All recommendations are informational only and intended for use within the F1 Fantasy game. Nothing here constitutes financial, betting, or investment advice.

PitWallAI is an open-source multi-agent intelligence system that delivers personalized F1 fantasy picks to your WhatsApp — budget-aware, circuit-adjusted, and powered by signals no pundit has access to.

*[Screenshot placeholder: WhatsApp message showing race picks]*

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CI](https://github.com/whitjenk/pitwallai/actions/workflows/ci.yml/badge.svg)](https://github.com/whitjenk/pitwallai/actions/workflows/ci.yml)
[![OpenF1](https://img.shields.io/badge/OpenF1-WebSocket-red)](https://openf1.org/)

---

## What it does

Three hours before race lock, you get a WhatsApp message. Not generic advice — picks filtered to your actual team, your remaining budget, and your available transfers. Backed by **three agents** that run across the weekend (the pre-lock pipeline is one agent with three stages).

**PicksAgent (Thursday → Saturday)** — three stages, one versioned pipeline:

- **Thursday (context)** — circuit history, championship pressure per driver, weather forecast, FIA directives.
- **Friday (practice)** — FP1/FP2 telemetry, team radio decode, statistical anomalies (e.g. a driver 0.8s off FP1 pace on used rubber).
- **Saturday (quali)** — your team, budget, and qualifying result; models legal transfer combinations and sends the swap that pencils out.

**Sunday (race)** — **RaceMonitor** watches the OpenF1 stream and timestamps every strategic moment as PitWallAI sees it: safety cars, retirements, pit windows, weather flips. The picks are already locked — the value here is *receipts*. Each call-out is saved with its source-signal time and our decode time so you can show your league chat afterward what we saw and when.

**Sunday night** — **ScorerLearner** logs every pick against the actual result and updates season accuracy + signal-quality weights. **CalledRecap** drops a forwardable summary of the weekend's call-outs to your WhatsApp with a shareable link (`/called/{token}`) — same idea as the season recap, but for live race intelligence.

---

## Subscribe

Text **SUBSCRIBE** to [number] on WhatsApp.  
Send a screenshot of your F1 Fantasy **My Team** screen (or text **TEAM**) to set up your squad.  
Text **HELP** for commands · **UNSUBSCRIBE** to stop messages · **DELETE** to erase your data ([PRIVACY.md](PRIVACY.md)).

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

What you'll see: Lap 37, Ferrari boxes. PitWallAI logs the pit-window event with two timestamps — the OpenF1 source signal and our decode time — so the Sunday-night recap can show your league chat exactly what we saw, when. Lap 38, Norris reports his fronts are gone — CRITICAL tire complaint, decoded by the rules path in milliseconds and added to the recap.

*The full rehearsal runs on local mock data. No live connection needed.*

---

## How it works

**Three agents.** One orchestrator (`LeadStrategist`). One shared `RaceContext` across the weekend.

`PicksAgent` owns Thursday–Saturday as three **stages** (`context` → `practice` → `quali`). Stage logic still lives in `agents/context_builder.py`, `practice_analyst.py`, and `quali_strategist.py` for testing — the consolidation is the *named interface*, not a merge of code paths.

```
Thursday–Saturday (PicksAgent)          Sunday              Post-race
────────────────────────────────────────────────────────────────────
 context → practice → quali      RaceMonitor        ScorerLearner
         │                              │                    │
         └──────────────┬───────────────┴────────────────────┘
                    LeadStrategist
                          │
                  WhatsApp → Fan
```

The radio pipeline (practice + live race) uses the **Radio Intercept Decoder** — rules-first with optional LLM escalation, sub-100ms on the default path:

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

Contributions are open. The **3-agent** topology (`PicksAgent`, `RaceMonitor`, `ScorerLearner`) is the current contract — see [TECHNICAL.md](TECHNICAL.md) for stage schedules, WhatsApp commands, and data models. New weekend logic should extend an existing stage or agent, not add a fourth top-level agent without discussion. Pattern: typed `AgentRunDependencies`, Pydantic v2 outputs, asyncio-native, `PIPELINE_VERSION` bump in [pitwallai/version.py](pitwallai/version.py) when behaviour changes.

## Disclaimer

PitWallAI is an independent open-source fan project. It is **not** affiliated with, endorsed by, or sponsored by Formula One Licensing B.V., the FIA, or the official [F1 Fantasy](https://fantasy.formula1.com/) game. F1, Formula 1, and related marks are trademarks of their respective owners.

**AI-generated intelligence.** Picks, recaps, radio decoding, and other outputs may use rules engines, statistical models, and large language models. They can be wrong, incomplete, or out of date — especially when data is missing, sessions change, or the official game applies penalties after the fact. PitWallAI is **not** financial or betting advice. You are responsible for your own fantasy decisions; always verify lineup, budget, transfers, and lock time in the official F1 Fantasy app.

Fantasy scoring and prices in this repo are simplified approximations of published game rules — always confirm transfers and points in the official app before lock.

Live timing and session data may be sourced from [OpenF1](https://openf1.org/) and other public APIs; see their terms for attribution and use.

WhatsApp is a trademark of Meta Platforms, Inc. Subscribers opt in via **SUBSCRIBE** and can opt out with **UNSUBSCRIBE** or erase all data with **DELETE**. See [PRIVACY.md](PRIVACY.md) for what we store and how deletion works.

## Legal

PitWallAI is an independent fan project not affiliated with Formula 1, F1 Fantasy, ESPN, or any F1 constructor. All picks are informational only. See [DISCLAIMER.md](DISCLAIMER.md) for full terms.

## License

MIT
