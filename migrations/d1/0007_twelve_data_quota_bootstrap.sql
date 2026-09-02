-- Day 53 Twelve Data quota accounting and bootstrap/run separation.

CREATE TABLE IF NOT EXISTS twelve_data_request_ledger (
    id TEXT PRIMARY KEY,
    requested_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    endpoint TEXT NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    outputsize INTEGER,
    request_kind TEXT NOT NULL CHECK (request_kind IN ('scheduled_capture','bootstrap','manual_probe')),
    status TEXT NOT NULL CHECK (status IN ('started','succeeded','failed')),
    internal_accounted_credits INTEGER NOT NULL CHECK (internal_accounted_credits >= 1),
    provider_credits_request INTEGER,
    provider_minute_credits_used INTEGER,
    provider_minute_credits_left INTEGER,
    response_digest TEXT,
    error_code TEXT
);

CREATE INDEX IF NOT EXISTS idx_twelve_data_request_ledger_requested
ON twelve_data_request_ledger(requested_at_utc);

CREATE TABLE IF NOT EXISTS twelve_data_bootstrap_runs (
    id TEXT PRIMARY KEY,
    started_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    request_ledger_id TEXT NOT NULL,
    response_digest TEXT,
    vendor_closed_bars INTEGER,
    required_m1_minutes INTEGER,
    persisted_m1_minutes INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK (state IN ('started','ingesting','complete','failed')),
    decision_snapshot_created INTEGER NOT NULL DEFAULT 0 CHECK (decision_snapshot_created = 0),
    decision_ready INTEGER NOT NULL DEFAULT 0 CHECK (decision_ready = 0),
    failure_reason TEXT,
    FOREIGN KEY(request_ledger_id) REFERENCES twelve_data_request_ledger(id)
);

CREATE INDEX IF NOT EXISTS idx_twelve_data_bootstrap_runs_started
ON twelve_data_bootstrap_runs(started_at_utc);
