-- Day 53 canonical Twelve Data M1 admission boundary.
-- Raw evidence remains immutable in market_candles. Decision readers may use only
-- rows tied to a successful scheduled capture or a successful bootstrap window.
-- Manual probes and legacy/unledgered rows are intentionally excluded.

DROP VIEW IF EXISTS twelve_data_decision_admitted_m1_v1;

CREATE VIEW twelve_data_decision_admitted_m1_v1 AS
SELECT c.*
FROM market_candles c
WHERE c.source='twelve_data_vendor_m1_v1'
  AND c.symbol='XAUUSD'
  AND c.timeframe='1m'
  AND EXISTS (
    SELECT 1
    FROM twelve_data_request_ledger r
    WHERE r.completed_at_utc=c.first_observed_at
      AND r.status='succeeded'
      AND (
        (
          r.request_kind='scheduled_capture'
          AND r.outputsize IS NOT NULL
          AND r.outputsize BETWEEN 1 AND 30
        )
        OR
        (
          r.request_kind='bootstrap'
          AND EXISTS (
            SELECT 1
            FROM twelve_data_bootstrap_requests b
            WHERE b.request_ledger_id=r.id
              AND b.state='succeeded'
              AND c.open_time_utc>=b.window_start_utc
              AND c.open_time_utc<b.window_end_utc
          )
        )
      )
  );
