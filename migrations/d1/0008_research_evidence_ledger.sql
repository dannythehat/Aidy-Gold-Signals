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
