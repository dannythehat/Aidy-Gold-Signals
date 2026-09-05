-- Day 53 D1 free-tier hot-path repair.
-- Keep live quote/candle reads index-driven and make archived hot evidence pruneable.

ALTER TABLE market_snapshots ADD COLUMN market_data_source TEXT;

UPDATE market_snapshots
SET market_data_source = COALESCE(
    NULLIF(TRIM(CAST(json_extract(data_availability_json,'$.market_data_source') AS TEXT)), ''),
    'unknown'
)
WHERE market_data_source IS NULL;

CREATE INDEX IF NOT EXISTS ix_market_snapshots_quote_history
ON market_snapshots(
    symbol,
    market_data_source,
    capture_status,
    quote_time,
    captured_at,
    id
);

CREATE INDEX IF NOT EXISTS ix_market_candles_source_symbol_timeframe_latest
ON market_candles(
    source,
    symbol,
    timeframe,
    open_time_utc DESC,
    revision_index DESC,
    id
);

CREATE INDEX IF NOT EXISTS ix_archive_outbox_created_at
ON archive_outbox(created_at);

ALTER TABLE archive_outbox ADD COLUMN hot_pruned_at TEXT;

CREATE INDEX IF NOT EXISTS ix_archive_outbox_hot_prune
ON archive_outbox(
    record_type,
    status,
    hot_pruned_at,
    archived_at,
    id,
    evidence_id
);
