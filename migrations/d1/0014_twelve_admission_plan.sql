-- Day 53 follow-up: make the Twelve M1 admission view planner-stable.
-- Semantics are unchanged from v1; the scheduled and bootstrap branches are
-- separated so D1 can probe the request ledger first, then bootstrap evidence
-- by request_ledger_id instead of scanning succeeded bootstrap windows per candle.

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
           INDEXED BY idx_twelve_data_request_ledger_completion_success
      WHERE r.completed_at_utc=c.first_observed_at
        AND r.status='succeeded'
        AND r.request_kind='scheduled_capture'
        AND r.outputsize IS NOT NULL
        AND r.outputsize BETWEEN 1 AND 30
    )
    OR EXISTS (
      SELECT 1
      FROM twelve_data_request_ledger AS r
           INDEXED BY idx_twelve_data_request_ledger_completion_success
      WHERE r.completed_at_utc=c.first_observed_at
        AND r.status='succeeded'
        AND r.request_kind='bootstrap'
        AND EXISTS (
          SELECT 1
          FROM twelve_data_bootstrap_requests AS b
               INDEXED BY idx_twelve_data_bootstrap_requests_by_ledger_window
          WHERE b.request_ledger_id=r.id
            AND b.state='succeeded'
            AND c.open_time_utc>=b.window_start_utc
            AND c.open_time_utc<b.window_end_utc
        )
    )
  );
