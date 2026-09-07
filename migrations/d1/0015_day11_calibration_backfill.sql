-- Day 11 calibration-only historical Twelve Data M1 evidence.
-- This schema is deliberately separate from market_candles and all decision-admitted views.
-- Rows here are retrospective research evidence only and can never be PIT eligible.

CREATE TABLE IF NOT EXISTS provider_calibration_backfill_windows (
    window_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL CHECK (symbol = 'XAUUSD'),
    timeframe TEXT NOT NULL CHECK (timeframe = '1m'),
    window_from TEXT NOT NULL,
    window_to TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind = 'calibration_backfill'),
    source_provider TEXT NOT NULL CHECK (source_provider = 'twelve_data'),
    pit_eligible INTEGER NOT NULL DEFAULT 0 CHECK (pit_eligible = 0),
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK (live_money_execution_allowed = 0),
    expected_row_count INTEGER NOT NULL DEFAULT 0 CHECK (expected_row_count >= 0),
    observed_row_count INTEGER NOT NULL DEFAULT 0 CHECK (observed_row_count >= 0),
    missing_row_count INTEGER NOT NULL DEFAULT 0 CHECK (missing_row_count >= 0),
    status TEXT NOT NULL CHECK (status IN ('COMPLETE', 'INCOMPLETE')),
    fetched_at_utc TEXT NOT NULL,
    response_digest TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_calibration_m1_backfill (
    open_time_utc TEXT PRIMARY KEY,
    symbol TEXT NOT NULL CHECK (symbol = 'XAUUSD'),
    timeframe TEXT NOT NULL CHECK (timeframe = '1m'),
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind = 'calibration_backfill'),
    source_provider TEXT NOT NULL CHECK (source_provider = 'twelve_data'),
    pit_eligible INTEGER NOT NULL DEFAULT 0 CHECK (pit_eligible = 0),
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK (live_money_execution_allowed = 0),
    first_observed_at TEXT NOT NULL,
    payload_digest TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_provider_calibration_m1_time
ON provider_calibration_m1_backfill(open_time_utc);
