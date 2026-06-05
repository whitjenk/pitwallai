#!/usr/bin/env bash
# Interactive PitWallAI WhatsApp simulator — use your Postgres FP1/FP2 data via .env
#
# Usage:
#   ./scripts/start_simulator.sh
#   PITWALL_SIM_RACE_KEY=2026_montreal ./scripts/start_simulator.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .venv314/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv314/bin/activate
elif [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

export EXPLANATION_CARDS_ENABLED="${EXPLANATION_CARDS_ENABLED:-true}"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "⚠️  DATABASE_URL not set — simulator uses ephemeral SQLite (no prod FP1/FP2)."
  echo "   Add DATABASE_URL to .env to test with your stored practice signals."
  echo ""
fi

exec python scripts/whatsapp_chat.py --practice
