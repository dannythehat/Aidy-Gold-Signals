-- Day 53 Twelve Data free-tier read-budget repair.
-- Keep the admission EXISTS probes and quota accounting index-range driven.

CREATE INDEX IF NOT EXISTS idx_twelve_data_bootstrap_requests_by_ledger_window
ON twelve_data_bootstrap_requests(
    request_ledger_id,
    state,
    window_start_utc,
    window_end_utc
);

CREATE INDEX IF NOT EXISTS idx_twelve_data_request_ledger_completion_success
ON twelve_data_request_ledger(
    completed_at_utc,
    status,
    request_kind,
    outputsize,
    id
);

CREATE INDEX IF NOT EXISTS idx_twelve_data_request_ledger_requested_at_credits
ON twelve_data_request_ledger(
    requested_at_utc,
    internal_accounted_credits
);

CREATE INDEX IF NOT EXISTS idx_market_candles_twelve_private_forward_m1
ON market_candles(
    source,
    symbol,
    timeframe,
    open_time_utc,
    first_observed_at,
    revision_index,
    id
);
