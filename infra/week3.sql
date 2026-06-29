-- Week 3: anomaly patterns, review queue, schema evolution, prompt registry

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
