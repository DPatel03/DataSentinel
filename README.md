# DataSentinel

Agentic data quality platform — NYC taxi trip streaming ingestion, validation, and AI triage.

## Week 1 checklist

| Item | Status |
|---|---|
| `docker compose up` runs Kafka, Schema Registry, TimescaleDB | Done |
| Two Avro schemas registered with compatibility enforced | Done |
| Producer replays Parquet to `taxi.rides.raw` | Done |
| YAML data contract versioned in Git | Done |
| Great Expectations suite | Done |
| Spark job routes valid → `validated`, invalid → `dead-letter` | Done |
| DLQ message has record, rule, contract_version, timestamp, 5 good samples | Done |
| Breach history queryable in TimescaleDB | Done |

## Week 2 checklist

| Item | Status |
|---|---|
| Coordinator routes DLQ failures to classifier | Done |
| Classifier returns Pydantic-validated JSON (5 failure classes) | Done |
| Heuristic pre-classifier with LLM fallback (< 0.7 confidence) | Done |
| Repair agent fixes `data_entry_error` and re-validates | Done |
| Repaired records routed to `taxi.rides.repaired` | Done |
| Triage + repair history in TimescaleDB | Done |
| Mock mode works without OpenAI API key | Done |

## Week 3 checklist

| Item | Status |
|---|---|
| Schema Evolution agent (`schema_drift`) | Done |
| Anomaly Enrichment agent (`genuine_anomaly` → `taxi.rides.anomaly`) | Done |
| Known pattern matching → `known_edge_case` | Done |
| Human Escalation agent (`requires_human_review`) | Done |
| Slack webhook + `review_queue` table | Done |
| GitHub issue on schema drift (optional) | Done |
| Prompt version registry in PostgreSQL | Done |
| Prompt eval + auto-rollback on accuracy regression | Done |

---

## Architecture (Week 1–3)

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

---

## Quick start

### 1. Prerequisites

- Docker Desktop
- Python 3.11+

### 2. One-time setup

```bash
cd DataSentinel
chmod +x scripts/setup_week1.sh
./scripts/setup_week1.sh
```

Or manually:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d
python ingestion/register_schemas.py
python scripts/generate_sample_parquet.py
```

### 3. Run the pipeline (3 terminals)

**Terminal A — validator** (start first):

```bash
source .venv/bin/activate
export PYTHONPATH=.

# Recommended locally — no Java required
python -m validation.streaming_validator --from-beginning

# Or PySpark (auto-uses Java 17 on macOS if default Java is 24+)
python -m validation.spark_job
```

**Terminal B — Producer** (replay sample data):

```bash
source .venv/bin/activate
export PYTHONPATH=.
python -m ingestion.producer \
  --file data/yellow_tripdata_2019-01_sample.parquet \
  --max-records 100 \
  --compression-factor 0
```

Use `--compression-factor 4320` for real time compression (~30 days in 10 min).

**Terminal C — Verify breaches**:

```bash
source .venv/bin/activate
python scripts/query_breaches.py
```

### 4. Inspect in AKHQ

Open http://localhost:8080 — browse `taxi.rides.raw`, `taxi.rides.validated`, `taxi.rides.dead-letter`, `taxi.rides.repaired`.

---

## Week 2 — AI Triage (Classifier + Repair)

### Setup

```bash
chmod +x scripts/setup_week2.sh
./scripts/setup_week2.sh
```

This applies DB migrations (`triage_events`, `repair_attempts`) and runs unit tests.

### Run the full pipeline (4 terminals)

**Terminal A — Validator** (same as Week 1):

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

**Terminal C — Triage service** (start after DLQ has messages):

```bash
python -m agents.triage_service --from-beginning --mock-llm
```

Use real GPT-4o-mini by setting `OPENAI_API_KEY` in `.env` and omitting `--mock-llm`.

**Terminal D — Verify**:

```bash
python scripts/query_triage.py
python scripts/query_breaches.py
```

### What Week 2 adds

| Component | What it does |
|---|---|
| **Coordinator** | Receives DLQ payload, orchestrates classify → repair |
| **Classifier** | Heuristic first; LLM if confidence < 0.7; 3s timeout + retry |
| **Repair** | Fixes `data_entry_error` (negative fare, swapped datetimes); re-validates |
| **`taxi.rides.repaired`** | Kafka topic for successfully repaired records |
| **`triage_events`** | TimescaleDB hypertable — failure class, confidence, explanation |
| **`repair_attempts`** | TimescaleDB hypertable — repair confidence, validation result |

### Classification output (Pydantic)

```json
{
  "failure_class": "data_entry_error",
  "confidence": 0.92,
  "explanation": "Negative fare is almost certainly a sign-entry error.",
  "affected_field": "fare_amount",
  "suggested_fix": "Use absolute value: 14.5",
  "requires_human_review": false,
  "source": "heuristic"
}
```

### Enable real LLM

Add to `.env`:

```
OPENAI_API_KEY=sk-...
```

Then run triage without `--mock-llm`.

---

## Week 3 — Advanced Agents + Prompt Registry

### Setup

```bash
chmod +x scripts/setup_week3.sh
./scripts/setup_week3.sh
```

### Run pipeline (same 4 terminals, updated triage command)

**Terminal C — Triage service (Week 3):**

```bash
python -m agents.triage_service --from-beginning --mock-llm --seed-prompts
```

**Terminal D — Verify Week 3:**

```bash
python scripts/query_week3.py
python scripts/query_triage.py
```

### What Week 3 adds

| Agent | Triggers on | What it does |
|---|---|---|
| **Schema Evolution** | `schema_drift` | Detects v1/v2, generates GE suite code, opens GitHub issue, updates Schema Registry if confidence ≥ 0.85 |
| **Anomaly Enrichment** | `genuine_anomaly` | LLM explanation, severity 1–5, routes to `taxi.rides.anomaly` |
| **Known patterns** | matching history | Reclassifies to `known_edge_case` (e.g. extreme distance) |
| **Human Escalation** | `requires_human_review` | Summary → `review_queue` + Slack webhook |
| **Prompt Registry** | all agents | Versioned prompts in DB, eval on change, auto-rollback if accuracy < 85% |

### Optional integrations (`.env`)

```bash
GITHUB_TOKEN=ghp_...          # Opens issues on schema drift
GITHUB_REPO=your-org/DataSentinel
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
OPENAI_API_KEY=sk-...         # Real LLM (omit --mock-llm)
```

### Prompt registry CLI

```bash
# Seed prompts from agents/prompts/*.txt
python -c "from agents.prompt_registry.registry import PromptRegistry; PromptRegistry().seed_from_files()"

# List versions
python -c "from agents.prompt_registry.registry import PromptRegistry; print(PromptRegistry().list_versions('classifier'))"
```

---

## Troubleshooting

### `python: command not found`

macOS often only has `python3`. Activate the venv first — it provides `python`:

```bash
source .venv/bin/activate
```

### `role "datasentinel" does not exist`

Your Mac likely has **local PostgreSQL on port 5432**. DataSentinel TimescaleDB uses **port 5433**.

```bash
docker compose down && docker compose up -d
docker compose exec timescaledb psql -U datasentinel -d datasentinel -c '\dt'
python scripts/query_breaches.py
```

### Schema registration failed

Re-run after the fix:

```bash
source .venv/bin/activate && export PYTHONPATH=.
python ingestion/register_schemas.py
```

### Spark fails with `getSubject is not supported`

Your default Java is **24** — PySpark 3.5 only supports up to Java 21.

**Option A (easiest):** use the Python validator:

```bash
python -m validation.streaming_validator
```

**Option B:** PySpark auto-switches to Java 17. Or set manually:

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
python -m validation.spark_job
```

### Spark validator slow to start

First run downloads Spark Kafka JARs (~30s). Wait 10–20s for imports — don't Ctrl+C immediately.

### Correct run order

1. `docker compose up -d`
2. `python ingestion/register_schemas.py`
3. **Validator first:** `python -m validation.streaming_validator`
4. **Then producer:** `python -m ingestion.producer ...`
5. `python scripts/query_breaches.py`

---

## What each component does

### Avro schemas (`ingestion/schemas/`)

| File | Purpose |
|---|---|
| `taxi-ride-v1.avsc` | Pre-2020 NYC taxi format (no `congestion_surcharge`) |
| `taxi-ride-v2.avsc` | Post-2020 format (adds `congestion_surcharge`) |

Registered in Schema Registry with **BACKWARD** compatibility on subject `taxi.rides.raw-value`. Breaking schema changes are rejected at the registry.

### Producer (`ingestion/producer/`)

- Reads TLC Parquet row-by-row
- Maps PascalCase columns → Avro snake_case fields
- Auto-detects v1 vs v2 from pickup year (or `--schema-version`)
- Publishes Confluent Avro-encoded messages to `taxi.rides.raw`
- Time compression via `--compression-factor`

### Data contract (`validation/contracts/v1.0.0.yaml`)

Versioned YAML defining expected types, null thresholds, value ranges, and SLAs. Both v1 and v2 schema versions are covered.

### Great Expectations (`validation/expectations/`)

- **Per-record validation** — used by the Spark streaming job
- **Batch GE suite** — `run_static_validation.py` for testing against Parquet before streaming

```bash
export PYTHONPATH=.
python validation/expectations/run_static_validation.py \
  --file data/yellow_tripdata_2019-01_sample.parquet
```

### Spark validator (`validation/spark_job/`)

PySpark Structured Streaming job that:

1. Consumes `taxi.rides.raw`
2. Deserializes Avro via Schema Registry
3. Validates each record against the YAML contract + GE rules
4. Routes **valid** → `taxi.rides.validated` (JSON)
5. Routes **invalid** → `taxi.rides.dead-letter` with structured payload:

```json
{
  "record": { "...": "..." },
  "rule_violated": "fare_amount_range",
  "contract_version": "1.0.0",
  "timestamp": "2026-06-16T...",
  "sample_good_records": [ "...5 nearest valid records by pickup time..." ]
}
```

6. Writes breach rows to TimescaleDB `contract_breaches` hypertable

### TimescaleDB (`infra/init.sql`)

`contract_breaches` hypertable stores rule violations over time for querying and dashboards.

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

Then run the producer against those files.

---

## Connection strings

| Service | URL |
|---|---|
| Kafka | `localhost:9092` |
| Schema Registry | `http://localhost:8081` |
| TimescaleDB | `postgresql://datasentinel:datasentinel@127.0.0.1:5433/datasentinel` |
| AKHQ UI | `http://localhost:8080` |

---

## Project layout

```
DataSentinel/
├── docker-compose.yml
├── requirements.txt
├── infra/
│   ├── init.sql
│   └── week2.sql
├── ingestion/
│   ├── schemas/
│   ├── register_schemas.py
│   └── producer/
├── validation/
│   ├── contracts/
│   ├── expectations/
│   ├── streaming_validator/
│   └── spark_job/
├── agents/
│   ├── coordinator.py
│   ├── classifier.py
│   ├── repair.py
│   ├── schema_evolution.py      # Week 3
│   ├── anomaly_enrichment.py    # Week 3
│   ├── escalation.py            # Week 3
│   ├── prompt_registry/         # Week 3
│   ├── prompts/
│   └── triage_service/
├── tests/
│   ├── test_agents.py
│   └── test_week3.py
├── scripts/
│   ├── setup_week1.sh
│   ├── setup_week2.sh
│   ├── setup_week3.sh
│   ├── migrate_week2.py
│   ├── migrate_week3.py
│   ├── query_triage.py
│   ├── query_week3.py
│   └── query_breaches.py
└── data/
```
