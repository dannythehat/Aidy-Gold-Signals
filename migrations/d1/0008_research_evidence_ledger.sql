-- Day 53 Step 0: append-only research evidence ledger.
-- Every governance, research-family, trial, qualification and amendment event is a new row.
-- UPDATE/DELETE are rejected at the database boundary.

CREATE TABLE IF NOT EXISTS research_evidence_ledger (
  sequence INTEGER PRIMARY KEY CHECK (sequence >= 0),
  record_digest TEXT NOT NULL UNIQUE CHECK (length(record_digest) = 64),
  previous_digest TEXT CHECK (previous_digest IS NULL OR length(previous_digest) = 64),
  ledger_version TEXT NOT NULL,
  record_type TEXT NOT NULL,
  recorded_at_utc TEXT NOT NULL,
  code_head_sha TEXT NOT NULL CHECK (length(code_head_sha) = 40),
  initiated_by TEXT NOT NULL CHECK (
    initiated_by IN ('human','agent','scheduled_system','registered_search_engine')
  ),
  payload_json TEXT NOT NULL CHECK (json_valid(payload_json))
);

CREATE INDEX IF NOT EXISTS idx_research_evidence_type_sequence
  ON research_evidence_ledger(record_type, sequence);

CREATE TRIGGER IF NOT EXISTS research_evidence_ledger_no_update
BEFORE UPDATE ON research_evidence_ledger
BEGIN
  SELECT RAISE(ABORT, 'research_evidence_ledger is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS research_evidence_ledger_no_delete
BEFORE DELETE ON research_evidence_ledger
BEGIN
  SELECT RAISE(ABORT, 'research_evidence_ledger is append-only: DELETE forbidden');
END;

INSERT INTO research_evidence_ledger (
  sequence,record_digest,previous_digest,ledger_version,record_type,
  recorded_at_utc,code_head_sha,initiated_by,payload_json
) VALUES (
  0,
  'daa8478ee4932bb5fabd83396abc29cdc38fca2e5b913fb78a0e4e2c80458406',
  NULL,
  'aidy_research_ledger_v1',
  'governance_genesis',
  '2026-09-02T07:22:24+00:00',
  'ede6e5cbfd9c7a1b449cb1c8314449d1fd0ec5d3',
  'human',
  '{"governance_version":"aidy_research_governance_v1","mutation_policy":{"amendment_must_reference_superseded_digest":true,"amendment_requires_new_record":true,"delete_allowed":false,"update_allowed":false},"no_edge_rule":"AIDY is permitted to conclude that no actionable edge exists. No research, qualification, accumulation or promotion rule may be changed solely because the evidence is approaching or has reached an unfavourable conclusion.","permitted_final_states":["positive_edge","no_economically_useful_edge","harm","insufficient_evidence"],"qualification_policy":{"default_state":"insufficient_evidence","fail_allows_inheritance":false,"insufficient_evidence_allows_inheritance":false,"pass_requires_affirmative_preregistered_acceptance":true},"selection_policy":{"agent_self_report_is_not_proof":true,"mechanical_origin_requires_ex_ante_parameter_space_proof":true,"unknown_origin_defaults_to":"post_result_unknown"},"trial_count_policy":{"effective_trial_count_requires_preregistered_versioned_method":true,"raw_attempted_trials_can_decrease":false,"reports_must_expose_raw_and_effective_counts":true}}'
);
