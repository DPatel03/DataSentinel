-- Apply to existing TimescaleDB instances (already running from Week 1)
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
