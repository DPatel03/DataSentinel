# DataSentinel

An agentic data quality platform for streaming data. It replays NYC taxi trips through Kafka, validates every record against a versioned data contract, and sends the failures to a set of LLM agents that decide what to do with each one: repair it, flag it as a real anomaly, propose a schema change, or hand it to a human. A dashboard shows breaches, triage results, and a review queue.

Everything runs without an API key. A heuristic classifier handles the obvious cases and the LLM is only called when confidence is low, so you can try the whole pipeline locally with `--mock-llm`.

## Architecture

```
Parquet → Producer → taxi.rides.raw → Validator → taxi.rides.validated
                                           │
                                           └──► taxi.rides.dead-letter
                                                    │
                                                    ▼
                                              Coordinator
                                                    │
                    ┌───────────────┬───────────────┼───────────────┬──────────────┐
                    ▼               ▼               ▼               ▼              ▼
              Classifier      Repair Agent   Schema Evolution  Anomaly Enrich  Escalation
                    │          (data_entry)   (schema_drift)   (genuine_anom)  (human review)
                    ▼               │               │               │              │
              triage_events   taxi.rides.     schema_evolution  taxi.rides.   review_queue
                              repaired        events + GitHub    anomaly       + Slack
```

## Features

| Layer | What it does |
|---|---|
| **Streaming ingestion** | Replays NYC TLC Parquet via Kafka with Avro + Schema Registry (pre/post-2020 schema drift) |
| **Validation** | YAML data contracts (Python streaming default) → `validated` or `dead-letter` with 5 good-record samples |
| **AI triage** | Coordinator routes failures to Classifier, Repair, Schema Evolution, Anomaly, Escalation agents |
| **Prompt registry** | Versioned prompts in PostgreSQL with eval + auto-rollback on accuracy regression |
| **Eval harness** | 300-record labeled dataset, adversarial suite, MLflow metrics |
| **Dashboard** | FastAPI + React — breaches, triage, repairs, LLM traces, review queue |

---

## Quick start

### Prerequisites

- Docker Desktop
- Python 3.11+ (optional — only needed for host-side tests / 4-terminal mode)
- Node.js 18+ (optional, for dashboard frontend hot-reload)

### One-command pipeline

Starts Kafka, Schema Registry, TimescaleDB, validator, triage, dashboard, and a sample producer:

```bash
chmod +x scripts/start_pipeline.sh
./scripts/start_pipeline.sh
```

Or:

```bash
docker compose --profile pipeline up --build -d
```

Open http://localhost:8888 — token is `DASHBOARD_AUTH_TOKEN` (default `datasentinel-local`, local demo only). Demo rows are seeded automatically so the dashboard is not empty. Click a breach or review row for the raw record, good samples, and repair diff. Accept or reject stores a human label.

To re-seed later: `python scripts/seed_demo.py`

### Host setup (tests + 4-terminal workflow)

```bash
cd DataSentinel
chmod +x scripts/setup.sh
./scripts/setup.sh
```

This starts Docker infra, registers schemas, runs migrations, generates sample data, seeds prompts, and runs tests.

### Run the full pipeline on the host (4 terminals)

**Terminal A — Validator** (start first):

```bash
source .venv/bin/activate
export PYTHONPATH=.
python -m validation.streaming_validator --from-beginning
```

**Terminal B — Producer**:

```bash
python -m ingestion.producer \
  --file data/yellow_tripdata_2019-01_sample.parquet \
  --max-records 100 \
  --compression-factor 0
```

**Terminal C — Triage service**:

```bash
python -m agents.triage_service --from-beginning --mock-llm
```

Use real GPT-4o-mini by setting `OPENAI_API_KEY` in `.env` and omitting `--mock-llm`. New classifier prompts are eval'd on a held-out LLM slice when the key is set, and only activated if accuracy stays above the threshold.

**Terminal D — Verify**:

```bash
python scripts/query_status.py
```

### Dashboard (host)

**Terminal A — API** (port 8888):

```bash
source .venv/bin/activate
export PYTHONPATH=.
npm run dashboard:api
```

**Terminal B — UI** (port 3000):

```bash
npm run dashboard:dev
```

Open http://localhost:3000

Or run both together:

```bash
npm install   # once, installs concurrently
npm run dashboard
```

If `DASHBOARD_AUTH_TOKEN` is set, the UI will ask for it. Leave it empty to disable auth on the host.

### Tests

```bash
source .venv/bin/activate
export PYTHONPATH=.
pytest tests -q
```

The suite (40 tests) runs without Docker or an API key.

### Eval harness

```bash
python eval/dataset/generate_dataset.py   # 300 labeled records
python eval/runner.py                     # metrics → mlruns/
```

The dataset has 300 labeled records generated with a fixed seed, and 50 of them are adversarial (hallucination injection, ambiguous cases, edge cases, repair cases). With no API key the runner scores the heuristic classifier only, and on a fresh run it reported 100% classification accuracy, 97.1% repair accuracy, and 0% hallucination. The labels come from the same rules the generator uses, so read that as a regression check on the plumbing, not as a measure of LLM accuracy. Pass `--coordinator` to run the full agent pipeline instead of the heuristic classifier alone.

---

## Configuration (`.env`)

```bash
# Required for real LLM (optional — heuristics work without it)
OPENAI_API_KEY=sk-...

# Optional integrations
GITHUB_TOKEN=ghp_...
GITHUB_REPO=your-org/DataSentinel
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
```

Copy from `.env.example` if you don't have a `.env` yet.

---

## Troubleshooting

### `python: command not found`

Activate the venv first — it provides `python`:

```bash
source .venv/bin/activate
```

### `role "datasentinel" does not exist`

Local PostgreSQL may be on port 5432. DataSentinel uses **port 5433**:

```bash
docker compose down && docker compose up -d
python scripts/migrate.py
python scripts/query_status.py
```

### Schema registration failed

```bash
source .venv/bin/activate && export PYTHONPATH=.
python ingestion/register_schemas.py
```

### Spark fails with Java errors

The default validator is pure Python (no Java). Spark is optional:

```bash
pip install -r requirements-spark.txt
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
python -m validation.spark_job
```

Or just use:

```bash
python -m validation.streaming_validator
```

### Correct run order

**Compose pipeline:** `docker compose --profile pipeline up --build -d`

**Host:**

1. `docker compose up -d`
2. `python scripts/migrate.py`
3. `python ingestion/register_schemas.py`
4. **Validator first**, then **producer**, then **triage**
5. `python scripts/query_status.py`

---

## Connection strings

| Service | URL |
|---|---|
| Kafka | `localhost:9092` |
| Schema Registry | `http://localhost:8081` |
| TimescaleDB | `postgresql://datasentinel:datasentinel@127.0.0.1:5433/datasentinel` (local demo only) |
| AKHQ (Kafka UI) | `http://localhost:8080` |
| Dashboard (Compose) | `http://localhost:8888` |
| Dashboard UI (host) | `http://localhost:3000` |
| Dashboard API (host) | `http://localhost:8888` |

---

## Real NYC TLC data

Download from [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page):

```bash
mkdir -p data
curl -L -o data/yellow_tripdata_2019-01.parquet \
  https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2019-01.parquet
curl -L -o data/yellow_tripdata_2021-01.parquet \
  https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2021-01.parquet
```

---

## Project layout

```
DataSentinel/
├── Dockerfile                # App image (validator / triage / dashboard / producer)
├── docker-compose.yml        # Infra always; --profile pipeline for services
├── requirements.txt
├── requirements-app.txt      # Slim runtime deps for Docker
├── requirements-spark.txt    # Optional PySpark validator
├── infra/
│   ├── init.sql
│   └── migrations.sql
├── ingestion/                # Kafka producer + Avro schemas + ride keys
├── validation/               # YAML contracts + Python streaming validator
├── agents/                   # Multi-agent AI triage
├── eval/                     # Eval harness + 300-record dataset
├── dashboard/                # FastAPI + React
├── dags/                     # Optional Airflow prompt eval
├── tests/
├── scripts/
│   ├── setup.sh
│   ├── start_pipeline.sh
│   ├── migrate.py
│   └── query_status.py
└── data/
```

---

## Optional: Airflow eval DAG

```bash
docker compose -f docker-compose.yml -f docker-compose.airflow.yml up -d
# UI: http://localhost:8085 (admin / admin)
# Trigger: datasentinel_prompt_eval
```

