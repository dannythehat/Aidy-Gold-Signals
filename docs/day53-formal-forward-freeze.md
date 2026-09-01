# Day 53 — formal private forward paper evaluation freeze

Decision date: 1 September 2026  
Architecture V2 earliest formal cohort start: **20 September 2026**  
Accepted Day 52 base: `c2282d4cd6ab3eebc311e62004167a78d5ccee15`

## Purpose

Day 53 is the boundary between engineering/replay/shadow research and formal unseen forward paper evidence.

This change prepares the machinery now, but it does **not** backdate or start formal evidence before the Architecture V2 earliest date. The formal cohort can activate only at or after `2026-09-20T00:00:00+00:00`.

Everything before that boundary remains engineering, replay, shadow or readiness evidence.

## Frozen version manifest

A cohort is identified by an immutable manifest that binds the exact accepted code head and the relevant component identities:

- Day 52 end-to-end runtime
- OpenAI V2 gateway/model/prompt/config manifest
- k=3 falsifiable self-consistency manifest
- immutable decision ledger
- Day 45 selective-abstention layer, explicitly shadow-only
- Day 41 GC/XAU shadow spine
- Day 29 forward-only macro surprise contract

The manifest also freezes the Architecture V2 boundaries:

- no pre-Day53 performance backfill
- no forward-outcome tuning inside an active cohort
- no selective-layer trading/publication gate
- GC remains shadow rather than authoritative decision input
- no broker/account/follower/Super Signals state
- no live-money execution
- Day 54 inference requires at least 300 episode-independent decision episodes

## Cohort lifecycle

A formal cohort has only three states:

1. `prepared`
2. `active`
3. `closed`

Preparation can occur before 20 September. Activation cannot.

A closed cohort cannot be reopened or patched in place.

## Formal evaluation record

Every formal evaluation, including `no_trade`, is stored as a separate immutable forward record.

The record includes:

- cohort and frozen-manifest identity
- exact Day 52 cycle identity
- context hash
- disposition
- explicit data-quality state
- episode identity
- decision/ex-ante identities when present
- exact k=3 disagreement metrics for J17
- analogue retrieval effective N
- GC shadow observation and feed-health snapshot
- macro consensus/surprise snapshot, including explicit unknown state
- Day 45 selective shadow snapshot
- a formal-forward eligibility flag

Data-quality failures are structurally distinct from genuine `no_trade`. A failed or unknown data-quality state cannot be recorded as a genuine no-trade decision.

Raw decision count and `COUNT(DISTINCT episode_id)` are both accumulated. Raw bursts cannot substitute for episode-independent N.

## Outcomes stay separate

Trade outcomes and no-trade shadow outcomes attach later through a separate immutable table.

Outcome attachments:

- occur after the ex-ante evaluation
- do not mutate the forward evaluation
- cannot tune an active cohort
- preserve `no_trade` as a first-class evaluated decision

## Freeze-break rule

The active cohort may be closed only for one of the three Architecture V2 machine-readable reasons:

- `material_safety_or_data_integrity_defect`
- `forced_model_or_api_deprecation`
- `objective_market_structure_or_venue_rule_change`

Performance improvement is never a valid freeze-break reason.

A valid break requires machine-readable evidence and irreversibly closes the old cohort. A replacement cohort must use a new version/epoch and rerun affected acceptance before its evidence can count.

## GC and selective-layer boundaries

GC/XAU remains a shadow observation layer. Its own Day 41 records continue to say `formal_forward_evidence_eligible=false`; Day 53 records the shadow observation and its health for later analysis without silently promoting it to the decision surface.

The Day 45 selective/conformal layer is logged for later risk-coverage work but remains unable to block the Master Trader or publication.

## Formal start versus readiness acceptance

The Day 53 CI workflow proves the registry, date gate, immutability, freeze-break rules, J17/J20 logging structure, shadow boundaries and full repository regression.

Passing that workflow means **Day 53 readiness is built**.

It does **not** mean the formal cohort has started on 1 September. The cohort starts only when the frozen manifest is activated on or after 20 September 2026.

## No downstream execution

Day 53 is private paper evaluation only.

It does not import or access:

- MetaAPI
- MT5
- Vantage
- broker accounts
- follower accounts
- Super Signals execution state

No live-money execution is enabled.
