-- Build 24: live-forward shadow expert cycles and permanent scorecard.
-- Pre-outcome state is immutable and outcome scoring is stored separately.
-- Research-only. Formal-forward and live-money authority remain OFF.

CREATE TABLE IF NOT EXISTS aidy_gold_expert_shadow_cycles (
    cycle_view_id TEXT PRIMARY KEY,
    source_snapshot_id TEXT NOT NULL,
    decided_at_utc TEXT NOT NULL,
    window_start_utc TEXT NOT NULL,
    window_end_utc TEXT NOT NULL,
    environment_key TEXT NOT NULL,
    environment_version TEXT NOT NULL,
    expected_gate_n INTEGER NOT NULL,
    known_gate_n INTEGER NOT NULL,
    explicit_unknown_gate_n INTEGER NOT NULL,
    dependency_json TEXT NOT NULL CHECK (json_valid(dependency_json)),
    dependency_digest TEXT NOT NULL,
    selector_json TEXT NOT NULL CHECK (json_valid(selector_json)),
    selector_digest TEXT NOT NULL,
    meta_view_json TEXT NOT NULL CHECK (json_valid(meta_view_json)),
    meta_view_digest TEXT NOT NULL,
    bundle_digest TEXT NOT NULL UNIQUE,
    created_at_utc TEXT NOT NULL,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    future_values_used INTEGER NOT NULL DEFAULT 0 CHECK (future_values_used = 0),
    formal_forward_authority INTEGER NOT NULL DEFAULT 0 CHECK (formal_forward_authority = 0),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK (live_money_execution_allowed = 0),
    FOREIGN KEY(cycle_view_id) REFERENCES aidy_gold_cycle_views(cycle_view_id)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_expert_shadow_cycles_time
    ON aidy_gold_expert_shadow_cycles(decided_at_utc, cycle_view_id);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_expert_shadow_cycles_environment
    ON aidy_gold_expert_shadow_cycles(environment_key, decided_at_utc);

CREATE TABLE IF NOT EXISTS aidy_gold_expert_gate_snapshots (
    cycle_view_id TEXT NOT NULL,
    gate_id TEXT NOT NULL,
    gate_version TEXT NOT NULL,
    gate_mode TEXT NOT NULL CHECK (gate_mode IN ('directional','context_only')),
    dependency_family TEXT NOT NULL,
    conclusion TEXT NOT NULL,
    gate_scoreable INTEGER NOT NULL CHECK (gate_scoreable IN (0,1)),
    availability_state TEXT NOT NULL CHECK (
        availability_state IN ('available','explicit_unknown')
    ),
    packet_json TEXT NOT NULL CHECK (json_valid(packet_json)),
    packet_digest TEXT NOT NULL,
    trust_json TEXT NOT NULL CHECK (json_valid(trust_json)),
    trust_digest TEXT NOT NULL,
    trust_scopes_json TEXT NOT NULL CHECK (json_valid(trust_scopes_json)),
    selector_classification TEXT NOT NULL,
    trust_score TEXT NOT NULL,
    observation_weight TEXT NOT NULL,
    directional_authority_weight TEXT NOT NULL,
    mini_environment_digest TEXT NOT NULL,
    mini_environment_json TEXT NOT NULL CHECK (json_valid(mini_environment_json)),
    decided_at_utc TEXT NOT NULL,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    future_values_used INTEGER NOT NULL DEFAULT 0 CHECK (future_values_used = 0),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK (live_money_execution_allowed = 0),
    PRIMARY KEY(cycle_view_id, gate_id),
    FOREIGN KEY(cycle_view_id) REFERENCES aidy_gold_expert_shadow_cycles(cycle_view_id)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_expert_gate_history
    ON aidy_gold_expert_gate_snapshots(gate_id, decided_at_utc);

CREATE TABLE IF NOT EXISTS aidy_gold_expert_subcalculator_snapshots (
    cycle_view_id TEXT NOT NULL,
    gate_id TEXT NOT NULL,
    calculator_id TEXT NOT NULL,
    calculator_version TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('directional','context_only')),
    dependency_family TEXT NOT NULL,
    state TEXT NOT NULL,
    vote TEXT NOT NULL,
    strength TEXT,
    scoreable INTEGER NOT NULL CHECK (scoreable IN (0,1)),
    observation_json TEXT NOT NULL CHECK (json_valid(observation_json)),
    evidence_refs_json TEXT NOT NULL CHECK (json_valid(evidence_refs_json)),
    explanation TEXT NOT NULL,
    calculator_digest TEXT NOT NULL,
    decided_at_utc TEXT NOT NULL,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK (live_money_execution_allowed = 0),
    PRIMARY KEY(cycle_view_id, gate_id, calculator_id),
    FOREIGN KEY(cycle_view_id,gate_id)
      REFERENCES aidy_gold_expert_gate_snapshots(cycle_view_id,gate_id)
);

CREATE INDEX IF NOT EXISTS ix_aidy_gold_expert_subcalc_history
    ON aidy_gold_expert_subcalculator_snapshots(
        gate_id,calculator_id,decided_at_utc
    );

CREATE TABLE IF NOT EXISTS aidy_gold_meta_view_results (
    cycle_view_id TEXT PRIMARY KEY,
    resolved_at_utc TEXT NOT NULL,
    frozen_direction TEXT NOT NULL
      CHECK (frozen_direction IN ('bullish','bearish','neutral','abstain')),
    realised_direction TEXT NOT NULL
      CHECK (realised_direction IN ('bullish','bearish','neutral','unknown')),
    realised_return_bps TEXT,
    score INTEGER NOT NULL CHECK (score IN (-2,-1,0,1,2)),
    correct INTEGER CHECK (correct IS NULL OR correct IN (0,1)),
    result_digest TEXT NOT NULL UNIQUE,
    post_outcome_only INTEGER NOT NULL DEFAULT 1 CHECK (post_outcome_only = 1),
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    formal_forward_authority INTEGER NOT NULL DEFAULT 0 CHECK (formal_forward_authority = 0),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK (live_money_execution_allowed = 0),
    FOREIGN KEY(cycle_view_id) REFERENCES aidy_gold_expert_shadow_cycles(cycle_view_id)
);

CREATE TABLE IF NOT EXISTS aidy_gold_expert_shadow_sync_health (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    observed_at_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok','error')),
    cycles_created INTEGER,
    cycles_scored INTEGER,
    latest_cycle_view_id TEXT,
    latest_meta_direction TEXT,
    expected_gate_n INTEGER,
    known_gate_n INTEGER,
    explicit_unknown_gate_n INTEGER,
    error_type TEXT,
    error_message TEXT,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    live_money_execution_allowed INTEGER NOT NULL DEFAULT 0 CHECK (live_money_execution_allowed = 0)
);
