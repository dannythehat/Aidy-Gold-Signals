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

## Follow-ups deliberately left

- No offline AIDY strategy replay. Reconciliation still takes an explicit trade list.
- `in/out`, `out by`, and a position still open at year end stay fail-closed.
- DST rules other than `NONE` and `EU_LAST_SUNDAY_MAR_OCT` are refused.
- Committed fixtures remain synthetic. The real-report test stays skipped until a genuine Strategy Tester file is archived.
