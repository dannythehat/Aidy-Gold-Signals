-- Contextual marker learning for AIDY's 15-minute Gold cycle brain.
-- Every marker is frozen with the environment that existed at decision time.
-- Resolved outcomes score each marker +1/-1/0 and update multiple contextual
-- scorebooks. This remains research-only and cannot create live-money authority.

CREATE TABLE IF NOT EXISTS aidy_gold_cycle_environments (
    cycle_view_id TEXT PRIMARY KEY,
    environment_key TEXT NOT NULL,
    environment_json TEXT NOT NULL CHECK (json_valid(environment_json)),
    scope_keys_json TEXT NOT NULL CHECK (json_valid(scope_keys_json)),
    environment_version TEXT NOT NULL,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0),
    FOREIGN KEY(cycle_view_id) REFERENCES aidy_gold_cycle_views(cycle_view_id)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_cycle_environment_key
    ON aidy_gold_cycle_environments(environment_key, cycle_view_id);

CREATE TABLE IF NOT EXISTS aidy_gold_cycle_marker_observations (
    cycle_view_id TEXT NOT NULL,
    marker_id TEXT NOT NULL,
    surface TEXT NOT NULL,
    vote TEXT NOT NULL CHECK (vote IN ('bullish','bearish','neutral')),
    source_path TEXT NOT NULL,
    base_weight TEXT NOT NULL,
    learned_multiplier TEXT NOT NULL,
    effective_weight TEXT NOT NULL,
    selected_score_scope TEXT NOT NULL,
    selected_score_sample_n INTEGER NOT NULL DEFAULT 0,
    selected_score_net INTEGER NOT NULL DEFAULT 0,
    selected_score_accuracy TEXT,
    observation_digest TEXT NOT NULL,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0),
    PRIMARY KEY(cycle_view_id, marker_id),
    FOREIGN KEY(cycle_view_id) REFERENCES aidy_gold_cycle_views(cycle_view_id)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_cycle_marker_surface
    ON aidy_gold_cycle_marker_observations(surface, cycle_view_id);

CREATE TABLE IF NOT EXISTS aidy_gold_cycle_marker_results (
    cycle_view_id TEXT NOT NULL,
    marker_id TEXT NOT NULL,
    resolved_at_utc TEXT NOT NULL,
    realised_direction TEXT NOT NULL
        CHECK (realised_direction IN ('bullish','bearish','neutral','unknown')),
    marker_score INTEGER NOT NULL CHECK (marker_score IN (-2,-1,0,1,2)),
    marker_correct INTEGER CHECK (marker_correct IS NULL OR marker_correct IN (0,1)),
    result_digest TEXT NOT NULL,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0),
    PRIMARY KEY(cycle_view_id, marker_id),
    FOREIGN KEY(cycle_view_id,marker_id)
      REFERENCES aidy_gold_cycle_marker_observations(cycle_view_id,marker_id)
);

CREATE TABLE IF NOT EXISTS aidy_gold_marker_context_scores (
    scope_key TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    marker_id TEXT NOT NULL,
    surface TEXT NOT NULL,
    source_path TEXT NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    sample_n INTEGER NOT NULL DEFAULT 0,
    correct_n INTEGER NOT NULL DEFAULT 0,
    incorrect_n INTEGER NOT NULL DEFAULT 0,
    neutral_n INTEGER NOT NULL DEFAULT 0,
    net_score INTEGER NOT NULL DEFAULT 0,
    score_mean TEXT NOT NULL DEFAULT '0.000000',
    accuracy TEXT,
    last_resolved_at_utc TEXT NOT NULL,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0
        CHECK (live_money_execution_allowed = 0),
    PRIMARY KEY(scope_key,marker_id,horizon_minutes)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_marker_context_lookup
    ON aidy_gold_marker_context_scores(marker_id,surface,horizon_minutes,scope_type,sample_n);
