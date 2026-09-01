-- AIDY Day 53 formal private forward cohort registry.
-- This is append-only research evidence. It does not execute trades or access follower state.

CREATE TABLE IF NOT EXISTS aidy_forward_cohorts (
    cohort_id TEXT PRIMARY KEY,
    cohort_version TEXT NOT NULL,
    manifest_version TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    manifest_digest TEXT NOT NULL UNIQUE,
    accepted_code_head TEXT NOT NULL CHECK (length(accepted_code_head) = 40),
    earliest_start_utc TEXT NOT NULL,
    prepared_at_utc TEXT NOT NULL,
    activated_at_utc TEXT,
    closed_at_utc TEXT,
    state TEXT NOT NULL CHECK (state IN ('prepared','active','closed')),
    freeze_break_reason_code TEXT CHECK (
        freeze_break_reason_code IS NULL OR freeze_break_reason_code IN (
            'material_safety_or_data_integrity_defect',
            'forced_model_or_api_deprecation',
            'objective_market_structure_or_venue_rule_change'
        )
    ),
    freeze_break_evidence_json TEXT,
    freeze_break_evidence_digest TEXT,
    replacement_cohort_id TEXT,
    broker_or_account_state_allowed INTEGER NOT NULL DEFAULT 0 CHECK (broker_or_account_state_allowed = 0),
    follower_state_allowed INTEGER NOT NULL DEFAULT 0 CHECK (follower_state_allowed = 0),
    super_signals_dependency_allowed INTEGER NOT NULL DEFAULT 0 CHECK (super_signals_dependency_allowed = 0),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK (live_money_execution_allowed = 0),
    CHECK (
        (state = 'prepared' AND activated_at_utc IS NULL AND closed_at_utc IS NULL)
        OR (state = 'active' AND activated_at_utc IS NOT NULL AND closed_at_utc IS NULL)
        OR (state = 'closed' AND activated_at_utc IS NOT NULL AND closed_at_utc IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS aidy_forward_evaluations (
    record_id TEXT PRIMARY KEY,
    record_version TEXT NOT NULL,
    record_json TEXT NOT NULL,
    record_digest TEXT NOT NULL UNIQUE,
    cohort_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    instruction_type TEXT NOT NULL,
    source_state TEXT NOT NULL CHECK (source_state = 'private_forward'),
    evaluated_at_utc TEXT NOT NULL,
    context_hash TEXT NOT NULL CHECK (length(context_hash) = 64),
    disposition TEXT NOT NULL CHECK (disposition IN (
        'pre_model_blocked','model_failed','self_consistency_abstain','no_trade',
        'decision_admitted','management_admitted','failed_closed'
    )),
    data_quality_state TEXT NOT NULL CHECK (data_quality_state IN ('known_good','failure','unknown')),
    data_quality_reason_code TEXT,
    episode_id TEXT NOT NULL,
    decision_id TEXT,
    ex_ante_digest TEXT,
    self_consistency_digest TEXT,
    disagreement_digest TEXT NOT NULL,
    retrieval_effective_n INTEGER NOT NULL CHECK (retrieval_effective_n >= 0),
    gc_shadow_digest TEXT NOT NULL,
    gc_feed_health_digest TEXT NOT NULL,
    macro_surprise_digest TEXT NOT NULL,
    selective_shadow_digest TEXT NOT NULL,
    formal_forward_eligible INTEGER NOT NULL CHECK (formal_forward_eligible = 1),
    recorded_at_utc TEXT NOT NULL,
    broker_or_account_state_used INTEGER NOT NULL DEFAULT 0 CHECK (broker_or_account_state_used = 0),
    follower_state_used INTEGER NOT NULL DEFAULT 0 CHECK (follower_state_used = 0),
    super_signals_used INTEGER NOT NULL DEFAULT 0 CHECK (super_signals_used = 0),
    live_money_execution_used INTEGER NOT NULL DEFAULT 0 CHECK (live_money_execution_used = 0),
    FOREIGN KEY (cohort_id) REFERENCES aidy_forward_cohorts(cohort_id),
    UNIQUE(cohort_id, cycle_id)
);

CREATE TABLE IF NOT EXISTS aidy_forward_outcomes (
    attachment_id TEXT PRIMARY KEY,
    attachment_version TEXT NOT NULL,
    attachment_json TEXT NOT NULL,
    attachment_digest TEXT NOT NULL UNIQUE,
    cohort_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    outcome_type TEXT NOT NULL CHECK (outcome_type IN ('trade_outcome','no_trade_shadow')),
    attached_at_utc TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    active_cohort_tuning_allowed INTEGER NOT NULL DEFAULT 0 CHECK (active_cohort_tuning_allowed = 0),
    FOREIGN KEY (cohort_id) REFERENCES aidy_forward_cohorts(cohort_id),
    FOREIGN KEY (record_id) REFERENCES aidy_forward_evaluations(record_id),
    UNIQUE(record_id, outcome_type)
);

CREATE INDEX IF NOT EXISTS ix_aidy_forward_cohorts_state
    ON aidy_forward_cohorts(state, earliest_start_utc);
CREATE INDEX IF NOT EXISTS ix_aidy_forward_evaluations_cohort_time
    ON aidy_forward_evaluations(cohort_id, evaluated_at_utc);
CREATE INDEX IF NOT EXISTS ix_aidy_forward_evaluations_episode
    ON aidy_forward_evaluations(cohort_id, episode_id);
