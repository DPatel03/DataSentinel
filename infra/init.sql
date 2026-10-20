-- TimescaleDB bootstrap for DataSentinel
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Contract breach history (Layer 2 — populated by the Spark validator later)
CREATE TABLE IF NOT EXISTS contract_breaches (
    time             TIMESTAMPTZ NOT NULL,
    rule_name        TEXT        NOT NULL,
    field_name       TEXT,
    contract_version TEXT        NOT NULL,
    failure_count    INT         NOT NULL DEFAULT 1,
    sample_record    JSONB
);

SELECT create_hypertable('contract_breaches', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_contract_breaches_rule
    ON contract_breaches (rule_name, time DESC);

CREATE INDEX IF NOT EXISTS idx_contract_breaches_field
    ON contract_breaches (field_name, time DESC);

-- AI triage + repair history
CREATE TABLE IF NOT EXISTS triage_events (
    time                   TIMESTAMPTZ NOT NULL,
    record_key             TEXT,
    rule_violated          TEXT        NOT NULL,
    failure_class          TEXT        NOT NULL,
    confidence             DOUBLE PRECISION NOT NULL,
    explanation            TEXT,
    affected_field         TEXT,
    requires_human_review  BOOLEAN     NOT NULL DEFAULT FALSE,
    classifier_source      TEXT        NOT NULL DEFAULT 'heuristic',
    raw_payload            JSONB
);

SELECT create_hypertable('triage_events', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_triage_events_class
    ON triage_events (failure_class, time DESC);

CREATE TABLE IF NOT EXISTS repair_attempts (
    time                   TIMESTAMPTZ NOT NULL,
    record_key             TEXT,
    original_record        JSONB,
    repaired_record        JSONB,
    field_repaired         TEXT,
    confidence             DOUBLE PRECISION,
    validation_passed      BOOLEAN     NOT NULL DEFAULT FALSE,
    routed_to_repaired     BOOLEAN     NOT NULL DEFAULT FALSE
);

SELECT create_hypertable('repair_attempts', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_repair_attempts_routed
    ON repair_attempts (routed_to_repaired, time DESC);

-- Anomaly patterns, review queue, schema evolution, prompt registry
CREATE TABLE IF NOT EXISTS anomaly_patterns (
    id              SERIAL PRIMARY KEY,
    pattern_name    TEXT UNIQUE NOT NULL,
    rule_violated   TEXT NOT NULL,
    field_name      TEXT,
    explanation     TEXT NOT NULL,
    severity        INT NOT NULL DEFAULT 3,
    suggested_action TEXT,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO anomaly_patterns (pattern_name, rule_violated, field_name, explanation, severity, suggested_action)
VALUES
    ('zero_distance_trip', 'trip_distance_range', 'trip_distance',
     'Zero-distance trip — known edge case (passenger cancel or meter reset).', 2, 'Monitor; do not auto-repair.'),
    ('extreme_distance', 'trip_distance_range', 'trip_distance',
     'Extreme trip distance — known long-haul or GPS error pattern.', 4, 'Flag for manual review.')
ON CONFLICT (pattern_name) DO NOTHING;

CREATE TABLE IF NOT EXISTS anomaly_history (
    time            TIMESTAMPTZ NOT NULL,
    record_key      TEXT,
    rule_violated   TEXT,
    pattern_name    TEXT,
    severity        INT,
    explanation     TEXT,
    record_payload  JSONB
);

SELECT create_hypertable('anomaly_history', 'time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS review_queue (
    id                      SERIAL PRIMARY KEY,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    record_key              TEXT,
    failure_class           TEXT NOT NULL,
    confidence              DOUBLE PRECISION,
    rule_violated           TEXT,
    summary                 TEXT NOT NULL,
    recommended_action      TEXT,
    status                  TEXT NOT NULL DEFAULT 'open',
    record_payload          JSONB,
    classification_payload  JSONB,
    resolved_at             TIMESTAMPTZ,
    resolved_by             TEXT
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue (status, created_at DESC);

CREATE TABLE IF NOT EXISTS schema_evolution_events (
    time                    TIMESTAMPTZ NOT NULL,
    record_key              TEXT,
    detected_schema_version TEXT,
    drift_description       TEXT,
    affected_fields         TEXT[],
    confidence              DOUBLE PRECISION,
    registry_updated        BOOLEAN DEFAULT FALSE,
    github_issue_url        TEXT,
    ge_suite_code           TEXT
);

SELECT create_hypertable('schema_evolution_events', 'time', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id              SERIAL PRIMARY KEY,
    prompt_id       TEXT UNIQUE NOT NULL,
    agent_name      TEXT NOT NULL,
    version         INT NOT NULL,
    prompt_text     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    accuracy        DOUBLE PRECISION,
    UNIQUE (agent_name, version)
);

CREATE INDEX IF NOT EXISTS idx_prompt_versions_active
    ON prompt_versions (agent_name, is_active);

CREATE TABLE IF NOT EXISTS prompt_eval_runs (
    time            TIMESTAMPTZ NOT NULL,
    agent_name      TEXT NOT NULL,
    prompt_id       TEXT NOT NULL,
    accuracy        DOUBLE PRECISION,
    passed          BOOLEAN NOT NULL
);

SELECT create_hypertable('prompt_eval_runs', 'time', if_not_exists => TRUE);

-- LLM trace tracking for dashboard
CREATE TABLE IF NOT EXISTS llm_traces (
    time            TIMESTAMPTZ NOT NULL,
    trace_id        TEXT,
    agent_name      TEXT NOT NULL,
    model           TEXT,
    prompt_version  TEXT,
    input_tokens    INT DEFAULT 0,
    output_tokens   INT DEFAULT 0,
    latency_ms      DOUBLE PRECISION,
    cost_usd        DOUBLE PRECISION DEFAULT 0,
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    input_preview   TEXT,
    output_preview  TEXT
);

SELECT create_hypertable('llm_traces', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_llm_traces_agent ON llm_traces (agent_name, time DESC);

-- Per-record validation samples for SLA (failure rate + p95 latency)
CREATE TABLE IF NOT EXISTS validation_events (
    time        TIMESTAMPTZ NOT NULL,
    is_valid    BOOLEAN     NOT NULL,
    latency_ms  DOUBLE PRECISION,
    rule_name   TEXT,
    record_key  TEXT
);

SELECT create_hypertable('validation_events', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_validation_events_valid
    ON validation_events (is_valid, time DESC);

ALTER TABLE contract_breaches ADD COLUMN IF NOT EXISTS record_key TEXT;
CREATE INDEX IF NOT EXISTS idx_contract_breaches_record_key
    ON contract_breaches (record_key, time DESC);

CREATE INDEX IF NOT EXISTS idx_triage_events_record_key
    ON triage_events (record_key, time DESC);

ALTER TABLE review_queue ADD COLUMN IF NOT EXISTS human_label TEXT;
ALTER TABLE review_queue ADD COLUMN IF NOT EXISTS human_note TEXT;

CREATE TABLE IF NOT EXISTS sla_alert_state (
    sla_name        TEXT PRIMARY KEY,
    last_status     TEXT NOT NULL,
    last_alerted_at TIMESTAMPTZ
);
