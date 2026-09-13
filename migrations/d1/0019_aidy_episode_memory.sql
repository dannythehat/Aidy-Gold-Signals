-- Phase B: permanent point-in-time AIDY decision memory.
--
-- Ex-ante episodes are immutable and contain no future outcome fields. Outcomes are
-- append-only attachments. Learning cards are deterministic derivatives that become
-- available only at/after the outcome timestamp, so later retrieval can remain PIT-safe.

CREATE TABLE IF NOT EXISTS aidy_memory_episodes (
    memory_episode_id TEXT PRIMARY KEY,
    memory_version TEXT NOT NULL,
    source_cycle_id TEXT NOT NULL UNIQUE,
    source_state TEXT NOT NULL,
    forward_record_id TEXT UNIQUE,
    cohort_id TEXT,
    evaluation_id TEXT NOT NULL UNIQUE,
    decision_id TEXT NOT NULL,
    ex_ante_digest TEXT NOT NULL UNIQUE,
    evaluated_at_utc TEXT NOT NULL,
    context_hash TEXT NOT NULL CHECK (length(context_hash) = 64),
    disposition TEXT NOT NULL,
    decision_action TEXT,
    direction TEXT,
    expected_horizon_minutes INTEGER,
    thesis_text TEXT,
    episode_json TEXT NOT NULL,
    episode_digest TEXT NOT NULL UNIQUE,
    recorded_at_utc TEXT NOT NULL,
    future_outcome_fields_present INTEGER NOT NULL DEFAULT 0
        CHECK (future_outcome_fields_present = 0),
    broker_or_account_state_used INTEGER NOT NULL DEFAULT 0
        CHECK (broker_or_account_state_used = 0),
    follower_state_used INTEGER NOT NULL DEFAULT 0
        CHECK (follower_state_used = 0),
    super_signals_used INTEGER NOT NULL DEFAULT 0
        CHECK (super_signals_used = 0),
    live_money_execution_used INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_used = 0)
);

CREATE TABLE IF NOT EXISTS aidy_memory_outcomes (
    memory_outcome_id TEXT PRIMARY KEY,
    outcome_version TEXT NOT NULL,
    memory_episode_id TEXT NOT NULL,
    source_attachment_id TEXT NOT NULL UNIQUE,
    source_outcome_type TEXT NOT NULL CHECK (source_outcome_type IN ('trade_outcome','no_trade_shadow')),
    outcome_state TEXT NOT NULL,
    score_eligible INTEGER NOT NULL CHECK (score_eligible IN (0,1)),
    attached_at_utc TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    outcome_digest TEXT NOT NULL UNIQUE,
    recorded_at_utc TEXT NOT NULL,
    FOREIGN KEY (memory_episode_id) REFERENCES aidy_memory_episodes(memory_episode_id),
    UNIQUE(memory_episode_id, source_outcome_type)
);

CREATE TABLE IF NOT EXISTS aidy_learning_cards (
    card_id TEXT PRIMARY KEY,
    learning_version TEXT NOT NULL,
    memory_episode_id TEXT NOT NULL,
    memory_outcome_id TEXT NOT NULL UNIQUE,
    available_at_utc TEXT NOT NULL,
    outcome_class TEXT NOT NULL,
    thesis_class TEXT NOT NULL,
    realized_r TEXT,
    tags_json TEXT NOT NULL,
    card_json TEXT NOT NULL,
    card_digest TEXT NOT NULL UNIQUE,
    score_eligible INTEGER NOT NULL CHECK (score_eligible IN (0,1)),
    hidden_reasoning_stored INTEGER NOT NULL DEFAULT 0 CHECK (hidden_reasoning_stored = 0),
    same_episode_retrieval_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (same_episode_retrieval_allowed = 0),
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (memory_episode_id) REFERENCES aidy_memory_episodes(memory_episode_id),
    FOREIGN KEY (memory_outcome_id) REFERENCES aidy_memory_outcomes(memory_outcome_id)
);

CREATE INDEX IF NOT EXISTS ix_aidy_memory_episodes_time
    ON aidy_memory_episodes(evaluated_at_utc, memory_episode_id);
CREATE INDEX IF NOT EXISTS ix_aidy_memory_episodes_forward
    ON aidy_memory_episodes(forward_record_id, ex_ante_digest);
CREATE INDEX IF NOT EXISTS ix_aidy_memory_outcomes_episode_time
    ON aidy_memory_outcomes(memory_episode_id, attached_at_utc);
CREATE INDEX IF NOT EXISTS ix_aidy_learning_cards_available
    ON aidy_learning_cards(available_at_utc, score_eligible, card_id);
