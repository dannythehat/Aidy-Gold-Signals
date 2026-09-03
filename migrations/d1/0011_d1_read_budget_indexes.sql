-- Day 53 D1 read-budget hardening.
-- These indexes do not change evidence admission semantics. They support the exact
-- predicates already used by the Twelve decision-admission view and final proof.

CREATE INDEX IF NOT EXISTS idx_twelve_data_request_ledger_admission
ON twelve_data_request_ledger(completed_at_utc,request_kind,status,outputsize);

CREATE INDEX IF NOT EXISTS idx_twelve_data_bootstrap_requests_admission_window
ON twelve_data_bootstrap_requests(state,window_start_utc,window_end_utc,request_ledger_id);

CREATE INDEX IF NOT EXISTS ix_aidy_forward_evaluations_proof_poll
ON aidy_forward_evaluations(cohort_id,evaluated_at_utc,disposition,data_quality_state);
