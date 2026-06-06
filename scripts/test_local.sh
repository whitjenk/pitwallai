#!/usr/bin/env bash
# One-shot local test: live OpenF1 + live F1 Fantasy prices + BYO-LLM insights.
#
# Ensures Ollama is running, confirms the model is pulled, then launches the
# interactive WhatsApp simulator. Reads config from .env (DATABASE_URL,
# PITWALL_SIM_LIVE, PITWALL_PRICES_VERIFIED, PITWALL_LLM_MODE=byo, model).
#
# Usage:
#   ./scripts/test_local.sh           # BYO LLM (default, from .env)
#   PITWALL_LLM_MODE=free ./scripts/test_local.sh   # rules only, no LLM
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 1) Activate venv.
if [[ -f .venv314/bin/activate ]]; then
  source .venv314/bin/activate
elif [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi

# 2) Load .env so we know the configured mode/model.
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

MODE="${PITWALL_LLM_MODE:-free}"
MODEL="${PITWALL_LLM_MODEL:-llama3.1:8b}"

# 3) If BYO mode, make sure Ollama is serving and the model is present.
if [[ "$MODE" == "byo" && "${PITWALL_LLM_PROVIDER:-ollama}" == "ollama" ]]; then
  if ! command -v ollama >/dev/null 2>&1; then
    echo "⚠️  Ollama not installed. Install: brew install --cask ollama-app"
    echo "    (or run in free mode: PITWALL_LLM_MODE=free ./scripts/test_local.sh)"
    exit 1
  fi
  if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "⏳ Starting Ollama server..."
    (ollama serve >/tmp/ollama_serve.log 2>&1 &)
    for _ in 1 2 3 4 5 6 7 8; do
      curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && break
      sleep 1
    done
  fi
  if ! ollama list 2>/dev/null | grep -q "${MODEL%%:*}"; then
    echo "⬇️  Pulling model $MODEL (one-time)..."
    ollama pull "$MODEL"
  fi
  echo "✅ Ollama ready — BYO LLM: $MODEL (local, free)"
else
  echo "ℹ️  LLM mode: free (rules only, no LLM)"
fi

echo ""
echo "Onboard your team when prompted, e.g.:"
echo "  SUBSCRIBE → TEAM → 0.3 → ANT,HUL,COL,OCO,BOR → MCL,MER → 2 → YES"
echo "Then try:  PICKS · WHY HAM · should i play a chip? · BUDGET · quit"
echo ""

# 4) Launch the simulator.
exec python scripts/whatsapp_chat.py --practice
