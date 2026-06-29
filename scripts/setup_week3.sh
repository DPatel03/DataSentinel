#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

source .venv/bin/activate 2>/dev/null || { python3 -m venv .venv && source .venv/bin/activate && pip install -q -r requirements.txt; }
export PYTHONPATH=.

[[ -f .env ]] && set -a && source .env && set +a

echo "==> Week 2 + Week 3 DB migrations"
python scripts/migrate_week2.py
python scripts/migrate_week3.py

echo "==> Seed prompt registry"
python -c "
from agents.prompt_registry.registry import PromptRegistry
from validation.config import load_env
load_env()
PromptRegistry().seed_from_files()
print('Prompts seeded')
"

echo "==> Run tests"
python -m pytest tests/ -q

echo ""
echo "Week 3 ready. Run full pipeline:"
echo "  A: python -m validation.streaming_validator --from-beginning"
echo "  B: python -m ingestion.producer --file data/yellow_tripdata_2019-01_sample.parquet --max-records 100 --compression-factor 0"
echo "  C: python -m agents.triage_service --from-beginning --mock-llm --seed-prompts"
echo "  D: python scripts/query_week3.py"
