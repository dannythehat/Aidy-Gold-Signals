# Evidence-semantic PR proof records

Protected market-data/feature/retrieval changes are presumed evidence-semantic.

The PR gate computes the SHA-256 digest of the binary diff for the protected paths and requires a JSON record named:

`docs/evidence-semantic-proofs/<protected_diff_sha256>.json`

The proof must be recorded after the protected code change and before merge. If the protected diff changes after the proof is recorded, the old proof becomes invalid automatically.

## Evidence-semantic record

```json
{
  "record_version": "aidy_evidence_semantic_change_v1",
  "recorded_head_sha": "<40-char commit containing the protected change>",
  "base_sha": "<PR merge-base SHA>",
  "protected_diff_sha256": "<64-char protected diff SHA-256>",
  "classification": "evidence-semantic",
  "cohort_action": "new_epoch",
  "preserve_existing_cohort": false,
  "reason": "<why decision evidence semantics changed>"
}
```

## Transport-only preservation record

Preservation is the exception and needs affirmative deterministic proof.

```json
{
  "record_version": "aidy_evidence_semantic_change_v1",
  "recorded_head_sha": "<40-char commit containing the protected change>",
  "base_sha": "<PR merge-base SHA>",
  "protected_diff_sha256": "<64-char protected diff SHA-256>",
  "classification": "transport-only",
  "cohort_action": "preserve",
  "preserve_existing_cohort": true,
  "reason": "<why the change cannot alter admitted evidence or decision semantics>",
  "deterministic_equivalence_proof": {
    "invariants": [
      "<deterministic invariant 1>",
      "<deterministic invariant 2>"
    ],
    "test_commands": [
      "<exact command 1>",
      "<exact command 2>"
    ],
    "result": "pass",
    "evidence_digest": "<SHA-256 of preserved test/evidence payload>"
  }
}
```

Cohort size, accumulated N, reset cost or observed performance are never valid reasons to classify a protected change as transport-only.
