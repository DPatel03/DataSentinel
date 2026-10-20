#!/usr/bin/env bash
# One-command pipeline: infra + validator + triage + dashboard + sample producer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not running."
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

echo "==> Starting DataSentinel pipeline (infra + services)"
docker compose --profile pipeline up --build -d

echo ""
echo "Pipeline is up."
echo "  Dashboard:  http://localhost:8888"
echo "  Token:      DASHBOARD_AUTH_TOKEN (default: datasentinel-local) — local demo only"
echo "  Demo data:  seeded automatically (or: python scripts/seed_demo.py)"
echo "  AKHQ:       http://localhost:8080"
echo ""
echo "  Logs:       docker compose --profile pipeline logs -f validator triage dashboard"
echo "  Status:     python scripts/query_status.py   # from the host, after ./scripts/setup.sh"
echo "  Stop:       docker compose --profile pipeline down"
