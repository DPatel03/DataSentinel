#!/usr/bin/env bash
# Quick smoke test — no Docker required for pytest + dashboard API.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || {
  echo "FAIL: .venv not found. Run: ./scripts/setup.sh"
  exit 1
}
export PYTHONPATH=.

PASS=0
FAIL=0

check() {
  local name="$1"
  shift
  if "$@"; then
    echo "  OK  $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL $name"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== DataSentinel smoke test ==="
echo ""

echo "1. Unit tests"
check "pytest" pytest tests/ -q --tb=no

echo ""
echo "2. Eval harness"
check "eval runner" python eval/runner.py --no-adversarial --json >/dev/null

echo ""
echo "3. Dashboard API"
API_PID=""
cleanup() { [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true; }
trap cleanup EXIT

.venv/bin/python -m uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8888 >/dev/null 2>&1 &
API_PID=$!
sleep 2

check "API health" curl -sf http://127.0.0.1:8888/api/health >/dev/null
check "API overview" curl -sf http://127.0.0.1:8888/api/stats/overview >/dev/null

echo ""
echo "4. Docker (optional — needed for full pipeline)"
if docker info >/dev/null 2>&1; then
  check "docker compose" docker compose ps >/dev/null 2>&1
  if docker compose ps 2>/dev/null | grep -q "timescaledb.*Up"; then
    echo "  OK  TimescaleDB running"
    PASS=$((PASS + 1))
    check "DB migrate" python scripts/migrate.py
  else
    echo "  --  Docker installed but stack not up. Run: docker compose up -d"
  fi
else
  echo "  --  Docker not running (start Docker Desktop for Kafka pipeline)"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi

echo ""
echo "All checks passed. To run the full pipeline:"
echo ""
echo "  # 1. Start infrastructure"
echo "  docker compose up -d"
echo "  python scripts/migrate.py"
echo "  python ingestion/register_schemas.py"
echo ""
echo "  # 2. Four terminals (order matters)"
echo "  python -m validation.streaming_validator --from-beginning"
echo "  python -m ingestion.producer --file data/yellow_tripdata_2019-01_sample.parquet --max-records 50 --compression-factor 0"
echo "  python -m agents.triage_service --from-beginning --mock-llm --seed-prompts"
echo "  python scripts/query_status.py"
echo ""
echo "  # 3. Dashboard"
echo "  ./scripts/start_dashboard.sh"
echo "  # → http://localhost:3000"
