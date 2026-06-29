#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || { python3 -m venv .venv && source .venv/bin/activate && pip install -q -r requirements.txt; }
export PYTHONPATH=.

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "==> Applying Week 2 DB migration"
python scripts/migrate_week2.py

echo "==> Running agent unit tests"
python -m pytest tests/test_agents.py -q

echo ""
echo "Week 2 ready. Full pipeline (4 terminals):"
echo ""
echo "  Terminal A: python -m validation.streaming_validator --from-beginning"
echo "  Terminal B: python -m ingestion.producer --file data/yellow_tripdata_2019-01_sample.parquet --max-records 100 --compression-factor 0"
echo "  Terminal C: python -m agents.triage_service --from-beginning --mock-llm"
echo "  Terminal D: python scripts/query_triage.py"
echo ""
echo "Set OPENAI_API_KEY in .env to use real GPT-4o-mini (omit --mock-llm)."
