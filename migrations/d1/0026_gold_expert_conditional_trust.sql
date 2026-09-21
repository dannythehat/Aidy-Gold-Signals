-- Build 3: environment-conditional trust for future expert gates.
-- Raw per-scope outcome ledger preserves PIT reconstruction; aggregate scorebooks
-- support fast pre-decision lookup. Research-only. No execution authority.

CREATE TABLE IF NOT EXISTS aidy_gold_expert_outcome_ledger (
    result_id TEXT NOT NULL,
    packet_digest TEXT NOT NULL,
    gate_id TEXT NOT NULL,
    gate_version TEXT NOT NULL,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('gate','subcalculator')),
    subject_id TEXT NOT NULL,
    subject_version TEXT NOT NULL,
    target_horizon_minutes INTEGER NOT NULL CHECK (target_horizon_minutes > 0),
    scope_key TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    resolved_at_utc TEXT NOT NULL,
    realised_direction TEXT NOT NULL
        CHECK (realised_direction IN ('bullish','bearish','neutral','unknown')),
    realised_return_bps TEXT,
    score INTEGER NOT NULL CHECK (score IN (-2,-1,0,1,2)),
    correct INTEGER CHECK (correct IS NULL OR correct IN (0,1)),
    impact_class TEXT NOT NULL
        CHECK (impact_class IN ('large','normal','unscoreable','outcome_unknown')),
    result_digest TEXT NOT NULL,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0),
    PRIMARY KEY(result_id,scope_key)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_expert_outcome_history
    ON aidy_gold_expert_outcome_ledger(
        subject_type,subject_id,subject_version,scope_key,resolved_at_utc
    );

CREATE INDEX IF NOT EXISTS ix_aidy_gold_expert_outcome_packet
    ON aidy_gold_expert_outcome_ledger(packet_digest,gate_id,resolved_at_utc);

CREATE TABLE IF NOT EXISTS aidy_gold_expert_context_scores (
    subject_type TEXT NOT NULL CHECK (subject_type IN ('gate','subcalculator')),
    subject_id TEXT NOT NULL,
    subject_version TEXT NOT NULL,
    gate_id TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    horizon_minutes INTEGER NOT NULL CHECK (horizon_minutes > 0),
    sample_n INTEGER NOT NULL DEFAULT 0,
    correct_n INTEGER NOT NULL DEFAULT 0,
    incorrect_n INTEGER NOT NULL DEFAULT 0,
    unscoreable_n INTEGER NOT NULL DEFAULT 0,
    net_score INTEGER NOT NULL DEFAULT 0,
    score_mean TEXT,
    accuracy TEXT,
    recent_window INTEGER NOT NULL DEFAULT 20,
    recent_sample_n INTEGER NOT NULL DEFAULT 0,
    recent_correct_n INTEGER NOT NULL DEFAULT 0,
    recent_net_score INTEGER NOT NULL DEFAULT 0,
    recent_accuracy TEXT,
    first_resolved_at_utc TEXT,
    last_resolved_at_utc TEXT,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0),
    PRIMARY KEY(
        subject_type,subject_id,subject_version,scope_key,horizon_minutes
    )
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_expert_context_lookup
    ON aidy_gold_expert_context_scores(
        gate_id,subject_type,subject_id,subject_version,
        horizon_minutes,scope_type,sample_n
    );
