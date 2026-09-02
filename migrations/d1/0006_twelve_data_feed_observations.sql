-- Day 53 Twelve Data feed-observation ledger.
-- Append-only request envelopes preserve PIT metadata, credit usage and observed latency.

CREATE TABLE IF NOT EXISTS twelve_data_feed_observations (
    id TEXT PRIMARY KEY,
    fetched_at_utc TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source='twelve_data'),
    symbol TEXT NOT NULL CHECK (symbol='XAU/USD'),
    interval TEXT NOT NULL CHECK (interval='1min'),
    meta_json TEXT NOT NULL CHECK (json_valid(meta_json)),
    credit_headers_json TEXT NOT NULL CHECK (json_valid(credit_headers_json)),
    raw_bar_count INTEGER NOT NULL CHECK (raw_bar_count >= 0),
    admitted_closed_bar_count INTEGER NOT NULL CHECK (admitted_closed_bar_count >= 0),
    forming_bar_count INTEGER NOT NULL CHECK (forming_bar_count >= 0),
    off_session_bar_count INTEGER NOT NULL CHECK (off_session_bar_count >= 0),
    latest_closed_bar_open_utc TEXT,
    latest_closed_bar_close_utc TEXT,
    observed_lag_seconds REAL,
    session_open_at_fetch INTEGER NOT NULL CHECK (session_open_at_fetch IN (0,1)),
    freshness_state TEXT NOT NULL CHECK (freshness_state IN ('fresh','stale','lag_unknown','session_closed')),
    response_digest TEXT NOT NULL CHECK (length(response_digest)=64)
);
CREATE INDEX IF NOT EXISTS ix_twelve_data_feed_observations_fetched
    ON twelve_data_feed_observations(fetched_at_utc);
CREATE INDEX IF NOT EXISTS ix_twelve_data_feed_observations_digest
    ON twelve_data_feed_observations(response_digest);
