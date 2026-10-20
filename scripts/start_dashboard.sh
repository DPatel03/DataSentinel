#!/usr/bin/env bash
# Start dashboard API (8888) + UI (3000) in one terminal.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Run ./scripts/setup.sh first"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH=.

npm install --silent 2>/dev/null || npm install

echo "Starting dashboard..."
echo "  API: http://localhost:8888/api/health"
echo "  UI:  http://localhost:3000"
echo ""

npx concurrently -k -n api,ui -c blue,green \
  ".venv/bin/python -m uvicorn dashboard.api.main:app --reload --host 127.0.0.1 --port 8888" \
  "npm run dev --prefix dashboard/frontend"
