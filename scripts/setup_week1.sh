#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

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

echo "==> Starting Docker infra"
docker compose up -d

echo "==> Waiting for Schema Registry"
until curl -sf http://localhost:8081/subjects >/dev/null; do sleep 2; done

echo "==> Registering Avro schemas"
python ingestion/register_schemas.py --reset

echo "==> Generating sample Parquet (if missing)"
python scripts/generate_sample_parquet.py

echo ""
echo "Week 1 infra is ready. Next steps:"
echo "  source .venv/bin/activate"
echo "  export PYTHONPATH=."
echo ""
echo "  Terminal A: python -m validation.streaming_validator   # recommended"
echo "            (or: python -m validation.spark_job)        # needs Java 17"
echo "  Terminal B: python -m ingestion.producer --file data/yellow_tripdata_2019-01_sample.parquet --max-records 50 --compression-factor 0"
echo "  Terminal C: python scripts/query_breaches.py"
echo ""
echo "Note: use 'python' inside the venv (not system python3 without venv)."
