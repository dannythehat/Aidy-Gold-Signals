-- AIDY Gold 15-minute cycle-learning memory.
-- This is research-only and additive to the Gold-first intelligence system.
-- Views are frozen before their target window; outcomes are attached separately
-- after the target window is complete so hindsight cannot rewrite the ex-ante view.

CREATE TABLE IF NOT EXISTS aidy_gold_cycle_views (
    cycle_view_id TEXT PRIMARY KEY,
    window_start_utc TEXT NOT NULL UNIQUE,
    window_end_utc TEXT NOT NULL,
    decided_at_utc TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL,
    source_snapshot_at_utc TEXT NOT NULL,
    session_code TEXT NOT NULL,
    observed_state TEXT NOT NULL CHECK (observed_state IN ('bullish','bearish','neutral','unknown')),
    view_direction TEXT NOT NULL CHECK (view_direction IN ('bullish','bearish','neutral','unknown')),
    view_confidence TEXT NOT NULL,
    cycle_signature TEXT NOT NULL,
    reasoning_summary TEXT NOT NULL,
    supporting_reasons_json TEXT NOT NULL CHECK (json_valid(supporting_reasons_json)),
    contradicting_reasons_json TEXT NOT NULL CHECK (json_valid(contradicting_reasons_json)),
    unavailable_evidence_json TEXT NOT NULL CHECK (json_valid(unavailable_evidence_json)),
    evidence_json TEXT NOT NULL CHECK (json_valid(evidence_json)),
    toolbox_manifest_digest TEXT NOT NULL,
    toolbox_considered_json TEXT NOT NULL CHECK (json_valid(toolbox_considered_json)),
    toolbox_used_json TEXT NOT NULL CHECK (json_valid(toolbox_used_json)),
    analogue_summary_json TEXT NOT NULL CHECK (json_valid(analogue_summary_json)),
    view_digest TEXT NOT NULL UNIQUE,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    future_values_used INTEGER NOT NULL DEFAULT 0 CHECK (future_values_used = 0),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_cycle_views_window
    ON aidy_gold_cycle_views(window_start_utc, cycle_view_id);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_cycle_views_session_state
    ON aidy_gold_cycle_views(session_code, observed_state, view_direction, window_start_utc);

CREATE TABLE IF NOT EXISTS aidy_gold_cycle_outcomes (
    cycle_view_id TEXT PRIMARY KEY,
    resolved_at_utc TEXT NOT NULL,
    realised_direction TEXT NOT NULL
        CHECK (realised_direction IN ('bullish','bearish','neutral','unknown')),
    return_bps TEXT,
    mfe_bps TEXT,
    mae_bps TEXT,
    m1_bars_observed INTEGER NOT NULL,
    exact_direction_correct INTEGER
        CHECK (exact_direction_correct IS NULL OR exact_direction_correct IN (0,1)),
    reasoning_review_json TEXT NOT NULL CHECK (json_valid(reasoning_review_json)),
    outcome_json TEXT NOT NULL CHECK (json_valid(outcome_json)),
    outcome_digest TEXT NOT NULL UNIQUE,
    post_outcome_only INTEGER NOT NULL DEFAULT 1 CHECK (post_outcome_only = 1),
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0),
    FOREIGN KEY(cycle_view_id) REFERENCES aidy_gold_cycle_views(cycle_view_id)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_cycle_outcomes_resolved
    ON aidy_gold_cycle_outcomes(resolved_at_utc, cycle_view_id);

-- Retrospective cycle analogues are deliberately non-PIT research evidence.
-- A one-time historical seed job can populate this from BigQuery research_candles.
CREATE TABLE IF NOT EXISTS aidy_gold_cycle_historical (
    historical_cycle_id TEXT PRIMARY KEY,
    window_start_utc TEXT NOT NULL,
    session_code TEXT NOT NULL,
    time_slot_utc TEXT NOT NULL,
    observed_state TEXT NOT NULL CHECK (observed_state IN ('bullish','bearish','neutral')),
    prior_sequence_signature TEXT NOT NULL,
    next_state TEXT NOT NULL CHECK (next_state IN ('bullish','bearish','neutral')),
    next_return_bps TEXT NOT NULL,
    state_run_length_windows INTEGER NOT NULL CHECK (state_run_length_windows >= 1),
    source_provenance TEXT NOT NULL DEFAULT 'retrospective_history',
    pit_eligible INTEGER NOT NULL DEFAULT 0 CHECK (pit_eligible = 0),
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_cycle_hist_lookup
    ON aidy_gold_cycle_historical(
        session_code,time_slot_utc,observed_state,prior_sequence_signature,window_start_utc
    );
