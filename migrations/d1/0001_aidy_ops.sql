-- AIDY Day 1 operational schema for Cloudflare D1.
-- Permanent raw evidence is archived to R2 through archive_outbox.

CREATE TABLE IF NOT EXISTS revision_counters (
    logical_key TEXT PRIMARY KEY,
    next_revision INTEGER NOT NULL CHECK (next_revision >= 2)
);

CREATE TABLE IF NOT EXISTS market_candles (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL CHECK (timeframe IN ('1m','5m','15m','1h','4h','1d')),
    open_time_utc TEXT NOT NULL,
    broker_open_time TEXT,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    tick_volume INTEGER,
    spread TEXT,
    volume TEXT,
    source TEXT NOT NULL DEFAULT 'metaapi',
    revision_index INTEGER NOT NULL CHECK (revision_index >= 1),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    first_observed_at TEXT NOT NULL,
    archive_key TEXT NOT NULL,
    UNIQUE(source,symbol,timeframe,open_time_utc,revision_index),
    UNIQUE(source,symbol,timeframe,open_time_utc,payload_digest)
);
CREATE INDEX IF NOT EXISTS ix_market_candles_symbol_timeframe_open
    ON market_candles(symbol,timeframe,open_time_utc);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id TEXT PRIMARY KEY,
    captured_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    capture_status TEXT NOT NULL CHECK (capture_status IN ('complete','partial','unavailable')),
    bid TEXT,
    ask TEXT,
    mid TEXT,
    spread TEXT,
    quote_time TEXT,
    quote_age_seconds REAL,
    session_code TEXT NOT NULL,
    position_state_json TEXT CHECK (position_state_json IS NULL OR json_valid(position_state_json)),
    data_availability_json TEXT NOT NULL CHECK (json_valid(data_availability_json)),
    event_observation_ids_json TEXT NOT NULL CHECK (json_valid(event_observation_ids_json)),
    latest_m1_id TEXT,
    latest_m5_id TEXT,
    latest_m15_id TEXT,
    latest_h1_id TEXT,
    latest_h4_id TEXT,
    latest_d1_id TEXT,
    snapshot_digest TEXT NOT NULL CHECK (length(snapshot_digest) = 64),
    archive_key TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_market_snapshots_symbol_captured
    ON market_snapshots(symbol,captured_at);

CREATE TABLE IF NOT EXISTS market_event_observations (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    published_at TEXT,
    first_observed_at TEXT NOT NULL,
    revision_index INTEGER NOT NULL CHECK (revision_index >= 1),
    headline TEXT,
    structured_data_json TEXT NOT NULL CHECK (json_valid(structured_data_json)),
    raw_payload_json TEXT CHECK (raw_payload_json IS NULL OR json_valid(raw_payload_json)),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    archive_key TEXT NOT NULL,
    UNIQUE(source,external_id,revision_index),
    UNIQUE(source,external_id,payload_digest)
);
CREATE INDEX IF NOT EXISTS ix_market_event_observations_first_observed
    ON market_event_observations(first_observed_at);

CREATE TABLE IF NOT EXISTS storage_smoke_probes (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    archive_key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS archive_outbox (
    id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL CHECK (record_type IN ('candle','snapshot','event','storage_smoke')),
    evidence_id TEXT NOT NULL,
    archive_key TEXT NOT NULL UNIQUE,
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','archived')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_archive_outbox_pending
    ON archive_outbox(status,created_at);
