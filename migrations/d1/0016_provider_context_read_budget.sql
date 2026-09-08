-- Day 53 / operations: eliminate read amplification in the provider-context PIT lookup.
--
-- The provider-context API only accepts successful scheduled Twelve Data snapshots.
-- The previous general-purpose index still forced D1 to scan historical snapshots and
-- evaluate request_kind/request_ledger_status from JSON for every request.  This partial
-- index contains only rows that can ever satisfy that lookup, preserving the same
-- point-in-time semantics while making ORDER BY captured_at DESC LIMIT 1 index-driven.
--
-- Research/runtime authority is unchanged.  This migration does not create or alter
-- snapshots and does not enable formal-forward execution.
CREATE INDEX IF NOT EXISTS idx_market_snapshots_provider_context_scheduled_success
ON market_snapshots (
    symbol,
    captured_at DESC,
    id DESC
)
WHERE market_data_source = 'twelve_data'
  AND capture_status = 'complete'
  AND json_extract(data_availability_json, '$.request_kind') = 'scheduled_capture'
  AND json_extract(data_availability_json, '$.request_ledger_status') = 'succeeded';
