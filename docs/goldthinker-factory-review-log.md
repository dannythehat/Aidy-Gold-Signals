# GoldThinker factory review log

Status: pending the next Quant Reviewer pass. This file records findings and the commits that answered them. It is not a performance claim and not evidence that a terminal ran.

## Round 1 — head `06e95c7` — not pass

Quant Reviewer findings that were accepted and fixed in `21341c6`:

- Worst-trade share flipped sign on a losing year (`-100 / -50 = +2`), so the year could clear a minimum. Share is now defined only when yearly net is strictly positive.
- Equity drawdown was forced equal to the balance path, and the v1 field stored the balance figure. Equity and balance percents are now separate. Balance percent is recomputed from the ledger.
- The 13-column Deals header rejected reports that include Fee. Fee is accepted and included in net P&L and in the cost metric.
- v1 selection could emit `SELECTED_PENDING_INDEPENDENT_EVIDENCE` from highest net alone. v2 selection requires every metric gate to PASS. UNSET thresholds return `BLOCKED_THRESHOLDS_UNSET`.
- A nonzero residual hid an itemised mismatch as INCONCLUSIVE. Any itemised mismatch is now MISMATCH.
- Broker-server timestamps are converted to UTC only with an explicit GMT offset and DST rule.

## Round 2 — head `21341c6` — not pass

Quant Reviewer findings:

1. `source_kind` was not tied to evidence. A synthetic v2 bundle relabelled `REAL_MT5_TESTER` still validated its metrics and selection returned `SELECTED_PENDING_INDEPENDENT_EVIDENCE`. The repository test did that relabel on purpose.
2. Equity drawdown was copied from the report summary without a lower bound. Equity drawdown of 0 with balance drawdown of about 1% was admitted.

Fix in the commit that adds this round-2 section:

- `REAL_MT5_TESTER` selection requires the extractor receipt and the archived report and ledger bytes. The receipt binds `source_kind`, the v1 bundle digest, and each report and ledger SHA-256. Missing receipt, hash mismatch, and a `SYNTHETIC_FIXTURE` marker each return their own blocked status. The relabel test is now a negative test. A positive path exists only when that receipt matches the files. A matching receipt is still not authentication that a terminal wrote the file, and `real_mt5_evidence_authenticated` stays false.
- Equity relative percent must be at least the ledger balance relative percent, within half of the report's last displayed digit. Otherwise the year is FAILED and its bundle result fields stay null.

## Round 3 — ChatGPT review of PR #376, after `488625e`

The receipt-only binding is not treated as proof of a real terminal run.

- Provenance is a runner-signed attestation (`goldthinker.factory.mt5_runner_attestation.v1`) over the report bytes, deal ledger, EA, ini, strategy source, data manifest, runner id, terminal build, tester-log hash and process start/exit. The committed trust store has no runners and no keys, so verification fails closed. Fixture provenance is rejected whatever `source_kind` says. Synthetic bundles stay `RESEARCH_FIXTURE_ONLY` and cannot open packaging.
- The equity-versus-balance inequality is removed. Reported equity is kept. Without tester-attested equity or a hashed equity series, the year is `EQUITY_DD_UNVERIFIED` and selection does not advance. `conservative_drawdown_pct` is a separate max of the two figures.
- `research_packaging_allowed` requires MATCH, a verified runner attestation, and a strategy replay. Caller-supplied trades do not qualify.
- The S040 replay adapter is a stub that returns unavailable. See `docs/goldthinker-aidy-replay-adapter-design.md`.

## Quant Reviewer on `a3068f8` — not pass

No regressions were reported. Three gaps were:

1. The synthetic-marker check lived only in `real_evidence_block_reason`, which selection never calls. `verify_runner_attestation` did not look at the archived bytes. Relabelling a synthetic bundle to `REAL_MT5_TESTER` and signing it with a key placed in a populated trust store reached `SELECTED_PENDING_INDEPENDENT_EVIDENCE` for 2024.
2. Attestations used HMAC, so the signing secret would have had to live anywhere verification ran.
3. The signed body omitted `system_id`, a nonce, and `issued_at`, so one attestation could be reused for another system and a nonce could be repeated inside one selection.

Ed25519, the nonce, and `system_id` landed in `b9f1e24`. The ceiling below is `a0115e9`:

- Selection scans the bundle document, the ledger text, the archived report bytes, and any supplied tester log, launch receipt, inputs, broker profile, and data source for `SYNTHETIC_FIXTURE` before it trusts a signature. The relabel-and-sign attack is a negative test: `tests/test_goldthinker_factory_metrics.py::test_signed_synthetic_relabel_is_blocked`.
- Signatures are Ed25519. The trust store holds `runner_id`, `key_id`, and the public key, plus `revoked_key_ids`. A revoked key id is rejected. The private key is generated on the Windows runner only. Procedure: `docs/goldthinker-factory-runner-keys.md`. No private key is committed. Tests use an ephemeral key and sign attacker documents locally.
- `sign_attestation` refuses `provenance_class` `RUNNER`. No factory path mints a runner attestation from a fixture or a CLI document.
- A runner document has to carry a launch/exit receipt and the SHA-256 of the tester journal, EA, ini, inputs, report, broker profile, and data source, plus the terminal build, timestamps, and year. The verifier requires the journal to name the same EA, ini, report, year, and build.
- A signature for a different `system_id` is rejected. A repeated nonce inside the selection is rejected.
- Nothing here observes a Windows runner. `verified` stays false. The best selection status is `RUNNER_SIGNED_SELF_REPORTED_PENDING_VERIFICATION` or `BLOCKED_REAL_MT5_PROVENANCE`. `SELECTED_PENDING_INDEPENDENT_EVIDENCE` is not returned. `test_real_selection_requires_a_matching_extractor_receipt` is a negative test: an authored report plus a valid test signature does not qualify.
- Reconciliation calls `verify_runner_attestation` for `runner_attestation_verified`. That flag stays false, so packaging stays closed. See `tests/test_goldthinker_factory_reconcile.py::test_packaging_calls_runner_verifier_and_stays_closed`.

## Quant Reviewer round 4 on `f21b49e` — not pass

1. A runner signature over the report's own equity-drawdown figure was labelled `TESTER_ATTESTED`. That figure is the report repeating itself. The status is now `RUNNER_SIGNED_SELF_REPORTED` unless a separate equity series hashes to the attestation and derives the same percent (`EQUITY_OBSERVATIONS_CHECKED`).
2. Accepted `(key_id, system_id, nonce)` values are stored in `config/goldthinker_factory_nonce_registry.json`. A later verifier instance rejects a repeat as `BLOCKED_ATTESTATION_NONCE_REPLAY`. `independent_runner_observed()` is true only when the committed trust store and an observation manifest both name a runner. Neither is configured, so `verified` stays false. Journal and launch-receipt checks parse `key=value` lines and require the EA, ini, report, year and build fields to match exactly.
3. `real_evidence_block_reason` now runs on the REAL selection path. A missing extractor receipt is `BLOCKED_EVIDENCE_RECEIPT_MISSING`.
4. The strategy-lab handoff no longer uses a shared HMAC secret. Review packets are Ed25519 signatures checked with a public key, and `independently_verified` stays false.

## Quant Reviewer round 5 on `524c011` — not pass

This is the last in-code verification round. Real MT5 provenance stays with the later D1 runner work.

- The nonce store is no longer a file in the repo. `GOLDTHINKER_NONCE_REGISTRY_PATH` must name a file outside the repository, created only by `init_nonce_registry`. A missing, unset, unreadable, or in-repo path returns `BLOCKED_ATTESTATION_NONCE_REGISTRY_UNAVAILABLE`. The file is append-only under `fcntl.flock`. A nonce is written only after the other checks pass. Evidence cannot supply a registry. Selection does not write into the repo.
- A self-supplied equity series, including one hashed into the signed body, stays `RUNNER_SIGNED_SELF_REPORTED`. It cannot become `EQUITY_OBSERVATIONS_CHECKED`.
- `independent_runner_observed()` is hard-coded `False`. There is no trust-store switch, observation manifest, or environment variable that turns it on. Verification does not return a verified attestation. `research_packaging_allowed` stays false while that function is false. `TODO(D1)` marks the runner work.

## Follow-ups deliberately left

- No offline AIDY strategy replay. Reconciliation still takes an explicit trade list.
- `in/out`, `out by`, and a position still open at year end stay fail-closed.
- DST rules other than `NONE` and `EU_LAST_SUNDAY_MAR_OCT` are refused.
- Committed fixtures remain synthetic. The real-report test stays skipped until a genuine Strategy Tester file is archived.
- A real Windows runner launch is not attached, so a self-reported signature cannot become independent evidence.
