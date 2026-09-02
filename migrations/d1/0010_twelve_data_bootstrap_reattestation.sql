-- Day 53 bootstrap re-attestation boundary.
--
-- Candle evidence is immutable and deduplicated by source/symbol/timeframe/open/payload.
-- A successful bootstrap may therefore re-observe an identical historical candle
-- without creating a new market_candles row or changing its original first_observed_at.
-- Decision admission must bind that existing immutable row to the successful,
-- bounded bootstrap window rather than require its original observation timestamp
-- to equal the bootstrap request completion timestamp.
--
-- Scheduled-capture admission remains unchanged and manual probes remain excluded.

DROP VIEW IF EXISTS twelve_data_decision_admitted_m1_v1;

CREATE VIEW twelve_data_decision_admitted_m1_v1 AS
SELECT c.*
FROM market_candles c
WHERE c.source='twelve_data_vendor_m1_v1'
  AND c.symbol='XAUUSD'
  AND c.timeframe='1m'
  AND (
    EXISTS (
      SELECT 1
      FROM twelve_data_request_ledger r
      WHERE r.completed_at_utc=c.first_observed_at
        AND r.status='succeeded'
        AND r.request_kind='scheduled_capture'
        AND r.outputsize IS NOT NULL
        AND r.outputsize BETWEEN 1 AND 30
    )
    OR
    EXISTS (
      SELECT 1
      FROM twelve_data_bootstrap_requests b
      JOIN twelve_data_request_ledger r ON r.id=b.request_ledger_id
      WHERE r.status='succeeded'
        AND r.request_kind='bootstrap'
        AND b.state='succeeded'
        AND c.open_time_utc>=b.window_start_utc
        AND c.open_time_utc<b.window_end_utc
    )
  );
