-- AIDY Day 52 end-to-end orchestration journal.
-- Engineering/dry-run truth only; formal forward evidence starts Day 53.

CREATE TABLE IF NOT EXISTS aidy_end_to_end_cycles (
    cycle_id TEXT PRIMARY KEY,
    runtime_version TEXT NOT NULL,
    instruction_type TEXT NOT NULL CHECK (instruction_type IN ('market_evaluation','active_signal_management')),
    source_state TEXT NOT NULL CHECK (source_state IN ('live_admitted','dry_run','private_forward','shadow','replay')),
    subject_id TEXT NOT NULL,
    context_hash TEXT NOT NULL CHECK (length(context_hash) = 64),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    cycle_state TEXT NOT NULL CHECK (cycle_state IN (
        'registered','pre_model_blocked','model_failed','self_consistency_abstain',
        'no_trade','decision_admitted','paper_open','watcher_no_action',
        'management_admitted','publication_pending','publication_sent',
        'publication_uncertain','failed_closed'
    )),
    last_error_code TEXT,
    self_consistency_json TEXT,
    self_consistency_digest TEXT,
    ex_ante_json TEXT,
    ex_ante_digest TEXT,
    decision_id TEXT,
    paper_state_json TEXT,
    paper_state_digest TEXT,
    watcher_receipt_json TEXT,
    watcher_receipt_digest TEXT,
    management_action_json TEXT,
    management_action_digest TEXT,
    publication_id TEXT,
    formal_forward_evidence INTEGER NOT NULL DEFAULT 0 CHECK (formal_forward_evidence = 0),
    broker_state_used INTEGER NOT NULL DEFAULT 0 CHECK (broker_state_used = 0),
    follower_state_used INTEGER NOT NULL DEFAULT 0 CHECK (follower_state_used = 0),
    super_signals_used INTEGER NOT NULL DEFAULT 0 CHECK (super_signals_used = 0),
    UNIQUE(instruction_type, source_state, subject_id, context_hash),
    UNIQUE(decision_id),
    UNIQUE(publication_id)
);

CREATE INDEX IF NOT EXISTS ix_aidy_e2e_cycles_state_updated
    ON aidy_end_to_end_cycles(cycle_state, updated_at_utc);
CREATE INDEX IF NOT EXISTS ix_aidy_e2e_cycles_context
    ON aidy_end_to_end_cycles(context_hash, instruction_type);
