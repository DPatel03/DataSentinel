#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> DataSentinel setup"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
fi
set -a
# shellcheck disable=SC1091
source .env
set +a
export PYTHONPATH=.

echo "==> Starting Docker infrastructure"
docker compose up -d

echo "==> Waiting for Schema Registry"
until curl -sf http://localhost:8081/subjects >/dev/null; do sleep 2; done

echo "==> Registering Avro schemas"
python ingestion/register_schemas.py --reset

echo "==> Applying database migrations"
python scripts/migrate.py

echo "==> Seeding demo dashboard data"
python scripts/seed_demo.py

echo "==> Generating sample Parquet (if missing)"
python scripts/generate_sample_parquet.py

echo "==> Generating eval dataset (if missing)"
if [[ ! -f eval/dataset/full_dataset.json ]]; then
  python eval/dataset/generate_dataset.py
fi

echo "==> Seeding prompt registry"
python -c "
from agents.prompt_registry.registry import PromptRegistry
PromptRegistry().seed_from_files()
print('Prompts seeded')
"

echo "==> Building dashboard frontend (if Node.js available)"
if command -v npm >/dev/null 2>&1; then
  (cd dashboard/frontend && npm install --silent && npm run build --silent) || echo "  (frontend build skipped — run manually: cd dashboard/frontend && npm install && npm run build)"
else
  echo "  (npm not found — skip frontend build)"
fi

echo "==> Running tests"
python -m pytest tests/ -q

echo ""
echo "DataSentinel is ready."
echo ""
echo "  One-command pipeline:"
echo "    ./scripts/start_pipeline.sh"
echo "    Dashboard: http://localhost:8888  (token: datasentinel-local unless DASHBOARD_AUTH_TOKEN is set)"
echo ""
echo "  Host pipeline (4 terminals):"
echo "    A: python -m validation.streaming_validator --from-beginning"
echo "    B: python -m ingestion.producer --file data/yellow_tripdata_2019-01_sample.parquet --max-records 100 --compression-factor 0"
echo "    C: python -m agents.triage_service --from-beginning --mock-llm"
echo "    D: python scripts/query_status.py"
echo ""
echo "  Dashboard (host):  npm run dashboard"
echo "  Eval:              python eval/runner.py"
echo "  AKHQ UI:           http://localhost:8080"
