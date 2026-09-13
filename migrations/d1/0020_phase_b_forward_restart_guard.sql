-- Phase B controlled forward-observer restart guard.
--
-- One campaign is allowed to activate once. The existing forward-cohort registry remains
-- authoritative. This table records the operational gate that permitted activation and
-- the first model-resolved evidence after restart.
-- Nothing here grants Telegram publication, broker/account access, follower state, a
-- Super Signals dependency, or live-money authority.

CREATE UNIQUE INDEX IF NOT EXISTS ux_aidy_forward_cohorts_one_active_version
    ON aidy_forward_cohorts(cohort_version)
    WHERE state='active';

CREATE TABLE IF NOT EXISTS aidy_forward_restart_runs (
    campaign_id TEXT PRIMARY KEY,
    restart_version TEXT NOT NULL,
    target_code_head TEXT NOT NULL CHECK (length(target_code_head) = 40),
    predecessor_cohort_id TEXT,
    activated_cohort_id TEXT NOT NULL UNIQUE,
    activated_at_utc TEXT NOT NULL,
    gate_json TEXT NOT NULL,
    gate_digest TEXT NOT NULL UNIQUE CHECK (length(gate_digest) = 64),
    market_data_source TEXT NOT NULL CHECK (market_data_source = 'twelve_data'),
    scheduler TEXT NOT NULL CHECK (scheduler = 'direct-cron'),
    session_open INTEGER NOT NULL CHECK (session_open = 1),
    data_health_fresh INTEGER NOT NULL CHECK (data_health_fresh = 1),
    consecutive_capture_successes INTEGER NOT NULL CHECK (consecutive_capture_successes >= 3),
    recent_complete_snapshots INTEGER NOT NULL CHECK (recent_complete_snapshots >= 2),
    model_gateway_configured INTEGER NOT NULL CHECK (model_gateway_configured = 1),
    acceptance_state TEXT NOT NULL DEFAULT 'activated'
        CHECK (acceptance_state IN ('activated','model_resolved')),
    first_forward_record_id TEXT,
    first_model_resolved_at_utc TEXT,
    acceptance_updated_at_utc TEXT NOT NULL,
    broker_or_account_state_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (broker_or_account_state_allowed = 0),
    follower_state_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (follower_state_allowed = 0),
    super_signals_dependency_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (super_signals_dependency_allowed = 0),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0),
    recorded_at_utc TEXT NOT NULL,
    FOREIGN KEY (predecessor_cohort_id) REFERENCES aidy_forward_cohorts(cohort_id),
    FOREIGN KEY (activated_cohort_id) REFERENCES aidy_forward_cohorts(cohort_id),
    FOREIGN KEY (first_forward_record_id) REFERENCES aidy_forward_evaluations(record_id),
    CHECK (
        (acceptance_state='activated' AND first_model_resolved_at_utc IS NULL)
        OR (acceptance_state='model_resolved' AND first_forward_record_id IS NOT NULL
            AND first_model_resolved_at_utc IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_aidy_forward_restart_runs_activated
    ON aidy_forward_restart_runs(activated_at_utc, campaign_id);
