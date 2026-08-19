-- AIDY Day 9: independent/public cross-market evidence.
-- Kept separate from macro events and Gold candles so semantics cannot leak.

CREATE TABLE IF NOT EXISTS cross_market_observations (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    series_id TEXT NOT NULL,
    observation_date TEXT NOT NULL,
    value TEXT NOT NULL,
    unit TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_document_digest TEXT NOT NULL CHECK (length(source_document_digest) = 64),
    first_observed_at TEXT NOT NULL,
    revision_index INTEGER NOT NULL CHECK (revision_index >= 1),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    archive_key TEXT NOT NULL,
    UNIQUE(source,series_id,observation_date,revision_index),
    UNIQUE(source,series_id,observation_date,payload_digest)
);
CREATE INDEX IF NOT EXISTS ix_cross_market_series_date
    ON cross_market_observations(series_id,observation_date,first_observed_at);

-- Separate outbox avoids mutating the proven Day 1 archive_outbox CHECK contract.
CREATE TABLE IF NOT EXISTS cross_market_archive_outbox (
    id TEXT PRIMARY KEY,
    evidence_id TEXT NOT NULL,
    archive_key TEXT NOT NULL UNIQUE,
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','archived')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_cross_market_archive_outbox_pending
    ON cross_market_archive_outbox(status,created_at);
