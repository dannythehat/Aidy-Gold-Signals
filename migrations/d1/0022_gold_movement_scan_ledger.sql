-- Track every Provider-Context-eligible XAUUSD snapshot examined by the
-- Gold movement detector. Normal snapshots are recorded as well as abnormal ones
-- so the live scanner can advance through history deterministically without
-- re-reading the same normal snapshot forever.

CREATE TABLE IF NOT EXISTS aidy_gold_movement_scan_ledger (
    source_snapshot_id TEXT PRIMARY KEY,
    captured_at_utc TEXT NOT NULL,
    scanned_at_utc TEXT NOT NULL,
    capture_status TEXT NOT NULL,
    investigation_required INTEGER NOT NULL CHECK (investigation_required IN (0,1)),
    move_direction TEXT,
    attribution_state TEXT,
    triggered_by_json TEXT NOT NULL DEFAULT '[]',
    investigation_digest TEXT,
    episode_stored INTEGER NOT NULL DEFAULT 0 CHECK (episode_stored IN (0,1)),
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    future_values_used INTEGER NOT NULL DEFAULT 0 CHECK (future_values_used = 0),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_movement_scan_time
    ON aidy_gold_movement_scan_ledger(captured_at_utc, source_snapshot_id);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_movement_scan_trigger
    ON aidy_gold_movement_scan_ledger(investigation_required, captured_at_utc);
