-- Gold-first causal learning: permanent memory for abnormal XAUUSD movements.
--
-- These records are independent of provider signals. An investigation is frozen at the
-- point the abnormal movement is detected. A learning card is attached only after the
-- forward observation window has matured, so future path can never rewrite the diagnosis.

CREATE TABLE IF NOT EXISTS aidy_gold_movement_investigations (
    movement_episode_id TEXT PRIMARY KEY,
    investigator_version TEXT NOT NULL,
    source_snapshot_id TEXT NOT NULL UNIQUE,
    trigger_at_utc TEXT NOT NULL,
    move_direction TEXT NOT NULL,
    attribution_state TEXT NOT NULL,
    triggered_by_json TEXT NOT NULL,
    investigation_json TEXT NOT NULL,
    investigation_digest TEXT NOT NULL UNIQUE CHECK (length(investigation_digest) = 64),
    recorded_at_utc TEXT NOT NULL,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    future_values_used INTEGER NOT NULL DEFAULT 0 CHECK (future_values_used = 0),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0)
);

CREATE TABLE IF NOT EXISTS aidy_gold_movement_learning_cards (
    movement_card_id TEXT PRIMARY KEY,
    learning_card_version TEXT NOT NULL,
    movement_episode_id TEXT NOT NULL UNIQUE,
    available_at_utc TEXT NOT NULL,
    path_class TEXT NOT NULL,
    initial_move_direction TEXT NOT NULL,
    attribution_state TEXT NOT NULL,
    card_json TEXT NOT NULL,
    learning_card_digest TEXT NOT NULL UNIQUE CHECK (length(learning_card_digest) = 64),
    recorded_at_utc TEXT NOT NULL,
    same_episode_retrieval_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (same_episode_retrieval_allowed = 0),
    active_cohort_tuning_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (active_cohort_tuning_allowed = 0),
    predictive_rule_created INTEGER NOT NULL DEFAULT 0
        CHECK (predictive_rule_created = 0),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0),
    FOREIGN KEY (movement_episode_id)
        REFERENCES aidy_gold_movement_investigations(movement_episode_id)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_movement_investigations_time
    ON aidy_gold_movement_investigations(trigger_at_utc, movement_episode_id);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_movement_cards_available
    ON aidy_gold_movement_learning_cards(available_at_utc, path_class, movement_card_id);
