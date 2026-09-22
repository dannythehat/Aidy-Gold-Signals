-- 0028: append-only Build-24 shadow health history.
--
-- aidy_gold_expert_shadow_sync_health (0027) is a singleton: every sync
-- overwrites the one row, so no record of a degradation survives. The
-- 2026-09-21 135-minute cycle gap had to be reconstructed from
-- market_snapshots because telemetry could not show it, and a raised
-- expert builder loses an entire shadow cycle leaving only a transient
-- error that the next successful sync erases.
--
-- This table is append-only and never updated in place. The singleton
-- remains the "current state" view; this is the durable trace.

CREATE TABLE IF NOT EXISTS aidy_gold_expert_shadow_health_history (
    observed_at_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok','error')),
    cycles_created INTEGER,
    cycles_scored INTEGER,
    latest_cycle_view_id TEXT,
    latest_cycle_decided_at_utc TEXT,
    latest_meta_direction TEXT,
    expected_gate_n INTEGER,
    known_gate_n INTEGER,
    explicit_unknown_gate_n INTEGER,
    -- Minutes since the previous recorded cycle. Makes a gap visible in the
    -- telemetry itself rather than only by reconstructing capture history.
    minutes_since_previous_cycle TEXT,
    error_type TEXT,
    error_message TEXT,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0),
    PRIMARY KEY(observed_at_utc)
);

CREATE INDEX IF NOT EXISTS idx_gold_expert_shadow_health_history_observed
    ON aidy_gold_expert_shadow_health_history(observed_at_utc DESC);

CREATE INDEX IF NOT EXISTS idx_gold_expert_shadow_health_history_status
    ON aidy_gold_expert_shadow_health_history(status,observed_at_utc DESC);
