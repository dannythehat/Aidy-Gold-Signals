# Day 34 — Immutable decision ledger and reproducibility contract

Day 34 creates an append-only evidence layer for every AIDY evaluation. It does not promote the Day-33 V2 contract into the OpenAI gateway, create a trading gate, change risk, or touch Super Signals.

## Ex-ante row

Every evaluation receives a stable `evaluation_id` and `decision_id`, including:

- pre-model blocked cycles;
- model failures;
- post-model blocked cycles;
- accepted `no_trade` decisions;
- admitted actionable decisions.

The immutable ex-ante record stores the exact context snapshot/hash, safety receipts, non-secret gateway metadata, decision contract/digest when present, Day-33 falsifiable metadata when V2 is present, data-quality flags and a deterministic reproducibility bundle.

The reproducibility bundle preserves prompt/gateway/model identities when a model call occurred, strategy/config versions, explicit sampling/seed support state, regime/setup state, evidence grade/effective N, evidence-report identity, exact ranked analogue case IDs, analogue retrieval identity and selective-layer state when available.

The record rejects secrets, secret-like values, hidden reasoning traces, future/evaluation labels, MFE/MAE, realised P/L, trade outcomes and no-trade counterfactual results. Those fields cannot enter the pre-outcome digest.

## Immutable reconciliation

A repeated evaluation with the same identity is idempotent only when the canonical payload and digest are identical. Any changed ex-ante field under the same identity fails closed. There is no update/delete mutation path in the Day-34 warehouse acceptance.

## Outcome attachment

Later outcomes use a separate `aidy_decision_outcome_attachment_v1` record. An attachment references both the immutable evaluation identity and the original `ex_ante_digest`.

- `trade_outcome` can attach only to an admitted actionable decision.
- `shadow_outcome` can attach only to an accepted `no_trade` evaluation.
- attachments must occur after the ex-ante evaluation timestamp;
- identical duplicate attachments are idempotent;
- a conflicting payload under the same attachment identity fails closed;
- attaching an outcome never changes the ex-ante row.

Outcome payloads may contain future-derived result fields because they live outside the ex-ante boundary, but secrets and hidden reasoning remain forbidden.

## Reproducibility

`reconstruct_non_secret_decision_bundle()` reconstructs the exact non-secret input/identity bundle from one immutable ledger row: context snapshot, model/prompt/config identities, analogue identities, safety receipts, decision metadata and data-quality flags.

The BigQuery acceptance additionally performs one lookup by the immutable evaluation identity and reconstructs that same bundle from the stored `record_json`.

## Warehouse contract

Day 34 uses bounded test-dataset tables in `aidy-signals.aidy_analytics_test`:

- `research_day34_decision_ledger`;
- `research_day34_outcome_attachments`;
- `research_day34_summary`.

Persistence is insert-only and idempotent. Existing rows are reconciled by exact identity, digest and canonical payload. Missing rows may be inserted. Duplicate identities, identity-set drift, digest mismatch or payload mismatch fail acceptance. No delete/update fallback is permitted.

## Non-goals

Day 34 does not claim predictive edge, change accepted Day 0–33 scientific contracts, promote Context V7 into the live Master Trader, promote V2 into the gateway, alter sizing/risk, access broker/follower accounts, publish signals, or modify Super Signals.
