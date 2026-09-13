-- 2026-09-13 production recovery: keep Provider Lab M1 admission PIT-safe
-- without forcing a specific SQLite/D1 query plan from inside the view.
--
-- Semantics are intentionally unchanged from 0014:
--   * only canonical Twelve Data XAUUSD M1 candles;
--   * only evidence first observed by the requested cut-off;
--   * scheduled captures must be succeeded and bounded outputsize <= 30;
--   * bootstrap evidence remains admitted only through a succeeded bootstrap window.
--
-- The supporting indexes are retained/created explicitly.  D1 is allowed to choose
-- among them rather than failing the endpoint if a forced INDEXED BY plan becomes
-- unavailable or incompatible after a schema/runtime change.

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

DROP VIEW IF EXISTS twelve_data_decision_admitted_m1_v1;

CREATE VIEW twelve_data_decision_admitted_m1_v1 AS
SELECT c.*
FROM market_candles AS c
WHERE c.source='twelve_data_vendor_m1_v1'
  AND c.symbol='XAUUSD'
  AND c.timeframe='1m'
  AND (
    EXISTS (
      SELECT 1
      FROM twelve_data_request_ledger AS r
      WHERE r.completed_at_utc=c.first_observed_at
        AND r.status='succeeded'
        AND r.request_kind='scheduled_capture'
        AND r.outputsize IS NOT NULL
        AND r.outputsize BETWEEN 1 AND 30
    )
    OR EXISTS (
      SELECT 1
      FROM twelve_data_request_ledger AS r
      WHERE r.completed_at_utc=c.first_observed_at
        AND r.status='succeeded'
        AND r.request_kind='bootstrap'
        AND EXISTS (
          SELECT 1
          FROM twelve_data_bootstrap_requests AS b
          WHERE b.request_ledger_id=r.id
            AND b.state='succeeded'
            AND c.open_time_utc>=b.window_start_utc
            AND c.open_time_utc<b.window_end_utc
        )
    )
  );
