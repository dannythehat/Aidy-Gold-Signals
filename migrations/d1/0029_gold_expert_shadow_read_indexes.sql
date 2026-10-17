-- AIDY Gold expert-shadow D1 read-amplification repair — 17 October 2026.
-- Additive indices ONLY; no market data, trading rules, old results or authority mutation.
-- Original ledger is one row per scope, immutable and already >40k records.
-- Existing index (subject_type,subject_id,subject_version,scope_key,resolved_at_utc)
-- cannot satisfy WHERE gate_id=? AND resolved_at_utc<? across every historical packet.
CREATE INDEX IF NOT EXISTS ix_aidy_gold_expert_outcome_gate_resolved
ON aidy_gold_expert_outcome_ledger(
    gate_id,resolved_at_utc,result_id,scope_key
);

-- Lookup of gate outcomes by subject kind and cutoff (PIT-safe).
CREATE INDEX IF NOT EXISTS ix_aidy_gold_expert_outcome_type_resolved
ON aidy_gold_expert_outcome_ledger(
    subject_type,resolved_at_utc,gate_id,result_id
);

-- The last non-null shadow cycle heartbeat must not scan a growing history
-- when every new row has latest_cycle_decided_at_utc=NULL.
CREATE INDEX IF NOT EXISTS ix_aidy_gold_expert_shadow_last_frozen
ON aidy_gold_expert_shadow_health_history(observed_at_utc DESC)
WHERE latest_cycle_decided_at_utc IS NOT NULL;
