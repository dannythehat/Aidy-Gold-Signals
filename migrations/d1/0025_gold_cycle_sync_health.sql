-- Persistent health for the autonomous Gold cycle-learning sync.
-- Singleton row: this is operational diagnostics only, never trading evidence.

CREATE TABLE IF NOT EXISTS aidy_gold_cycle_sync_health (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    observed_at_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok','error')),
    creation_created INTEGER,
    creation_reason TEXT,
    view_direction TEXT,
    resolution_resolved INTEGER,
    backfill_views INTEGER,
    backfill_markers_scored INTEGER,
    error_type TEXT,
    error_message TEXT
);
