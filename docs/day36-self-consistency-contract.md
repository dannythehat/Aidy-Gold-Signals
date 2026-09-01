# Day 36 — Master Trader k=3 self-consistency contract

Decision date: 2026-09-01

Authoritative base: `619923f813c3f6527f4c765174b91e272a4dd8a3`

## Objective

Run exactly three independent Master Trader evaluations against the same frozen evidence/configuration and use deterministic infrastructure voting to measure judgement stability. The layer must abstain safely when repeated samples do not produce a safe majority.

## Sampling contract

- `k = 3` exactly.
- Every sample receives a defensive copy of the same frozen evidence bundle.
- Every sample is governed by the same accepted OpenAI gateway configuration identity.
- One sample never receives another sample's output.
- No bull/bear/judge architecture, debate, critique, persuasion or model tie-breaker exists.
- Provider retry bounds remain the accepted gateway bounds: maximum 2 attempts per sample, therefore maximum 6 provider attempts for the k=3 cycle.

## Independent validation

Each sample must independently satisfy:

1. bounded gateway metadata;
2. accepted gateway status;
3. the Day-20 Master Trader V1 semantic contract;
4. exact gateway decision-digest identity;
5. a valid Day-22 post-model safety receipt;
6. `decision_admitted=true` and matching action identity.

A failed, malformed, blocked or over-budget sample has no vote.

## Vote identity

The majority identity includes the fields that determine the external action, not confidence or prose rationale.

- `new_trade`: action, direction, setup codes, entry type, market reference price, stop loss and targets;
- `manage_trade`: action, target decision ID, management instruction, new stop and new targets;
- `close_trade`: action, target decision ID and close scope;
- `no_trade`: action.

This is intentionally stricter than voting on direction alone. Two samples that say `long` but disagree on actionable geometry do not form a safe trade majority.

## Consensus and disagreement

A safe majority requires at least two independently vote-eligible samples with the same action-semantic identity.

- safe actionable majority → deterministic representative from the earliest winning sample;
- safe `no_trade` majority → `no_trade`;
- fewer than two valid votes → infrastructure `no_trade` with `insufficient_valid_samples`;
- valid 1/1/1 disagreement → infrastructure `no_trade` with `no_safe_majority`;
- inconsistent request identity → infrastructure `no_trade` with `frozen_request_identity_mismatch`.

The disagreement score is deterministic: `(3 - majority_count) / 3`, reported to six decimal places. Invalid/blocked samples therefore increase observed instability rather than disappearing from the denominator.

## Ledger integration

All three sample decision digests, vote identities, eligibility states, gateway statuses, post-model safety states, disagreement metrics, consensus result, token usage, attempt counts, latency and estimated cost are exposed through a non-secret `selective_layer_state` payload compatible with the accepted Day-34 reproducibility bundle.

## Boundaries

Day 36 does not weaken Day-20 or Day-22 validation, grant confidence any sizing/safety authority, access broker/account/follower state, modify Super Signals, create model debate, or claim predictive edge.

## Acceptance

Before merge:

1. changed-file Ruff passes;
2. focused Day-36 adversarial tests pass;
3. full repository regression passes;
4. two exact-head acceptance artifacts are byte-identical;
5. accepted PR head is merged only with expected-head protection.
