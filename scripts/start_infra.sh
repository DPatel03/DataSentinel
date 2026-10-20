#!/usr/bin/env bash
# Start Docker infrastructure and wait until all services are ready.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not running."
  echo ""
  echo "  1. Open Docker Desktop"
  echo "  2. Wait until it says 'Docker is running'"
  echo "  3. Run this script again: ./scripts/start_infra.sh"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate 2>/dev/null || true
export PYTHONPATH=.

echo "==> Starting Docker services (Kafka, Schema Registry, TimescaleDB)..."
docker compose up -d

echo "==> Waiting for Schema Registry (port 8081)..."
for i in $(seq 1 60); do
  if curl -sf http://localhost:8081/subjects >/dev/null 2>&1; then
    echo "    Schema Registry ready."
    break
  fi
  if [[ $i -eq 60 ]]; then
    echo "ERROR: Schema Registry did not start in time."
    docker compose logs schema-registry --tail 20
    exit 1
  fi
  sleep 2
done

echo "==> Waiting for TimescaleDB (port 5433)..."
for i in $(seq 1 60); do
  if docker compose exec -T timescaledb pg_isready -U datasentinel -d datasentinel >/dev/null 2>&1; then
    echo "    TimescaleDB ready."
    break
  fi
  if [[ $i -eq 60 ]]; then
    echo "ERROR: TimescaleDB did not start in time."
    docker compose logs timescaledb --tail 20
    exit 1
  fi
  sleep 2
done

echo "==> Registering Avro schemas..."
python ingestion/register_schemas.py

echo "==> Running database migrations..."
python scripts/migrate.py

echo "==> Generating sample data (if missing)..."
python scripts/generate_sample_parquet.py

echo ""
echo "Infrastructure is ready."
echo ""
docker compose ps
echo ""
echo "Next — one-command pipeline:"
echo "  ./scripts/start_pipeline.sh"
echo ""
echo "Or run on the host in separate terminals:"
echo "  1. python -m validation.streaming_validator --from-beginning"
echo "  2. python -m ingestion.producer --file data/yellow_tripdata_2019-01_sample.parquet --max-records 50 --compression-factor 0"
echo "  3. python -m agents.triage_service --from-beginning --mock-llm --seed-prompts"
echo "  4. python scripts/query_status.py"
