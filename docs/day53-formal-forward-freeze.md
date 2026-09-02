# Day 53 — formal private forward paper evaluation freeze

Decision date: 1 September 2026  
Original Architecture V2 planning start: **20 September 2026**  
Immediate-start amendment effective floor: `2026-09-01T16:07:00+00:00`  
Accepted Day 52 base: `c2282d4cd6ab3eebc311e62004167a78d5ccee15`

## Purpose

Day 53 is the boundary between engineering/replay/shadow research and formal unseen forward paper evidence.

Architecture V2 originally planned the formal cohort for 20 September 2026. The accepted Day 53 immediate-start amendment superseded that calendar assumption ex ante on 1 September 2026 and created a new frozen manifest/cohort version rather than rewriting the old planning evidence.

That amendment does **not** make later evidence-semantic market-data changes automatically eligible for the already activated cohort. A new authoritative feed, source identity, session/candle semantic, or differently scaled decision surface follows the evidence-semantic change rule below and normally requires a new cohort/epoch after its own qualification passes.

No pre-activation evidence may be backfilled into any cohort.

## Frozen version manifest

A cohort is identified by an immutable manifest that binds the exact accepted code head and the relevant component identities:

- Day 52 end-to-end runtime
- OpenAI V2 gateway/model/prompt/config manifest
- k=3 falsifiable self-consistency manifest
- immutable decision ledger
- Day 45 selective-abstention layer, explicitly shadow-only
- Day 41 GC/XAU shadow spine
- Day 29 forward-only macro surprise contract
- authoritative market-data source identity and data-semantic qualification identity
- decision-context adapter qualification identity
- parameter-provenance audit identity

The manifest also freezes the Architecture V2 boundaries:

- no pre-activation performance backfill
- no forward-outcome tuning inside an active cohort
- no selective-layer trading/publication gate
- GC remains shadow rather than authoritative decision input
- no broker/account/follower/Super Signals state
- no live-money execution
- Day 54 inference requires at least 300 episode-independent decision episodes

## Preactivation data-semantic gates

A cohort cannot be treated as evidentially ready merely because the feed is reachable. Before a new cohort may accumulate formal evidence, the accepted code head must also carry contemporaneous qualification records for:

- the authoritative market-feed adapter and its source/price-basis identity
- the session calendar, DST policy and maintenance-gap semantics
- candle construction, aggregation and current-bucket completeness rules
- parameter provenance for every threshold, normalization scale, volatility band or tuned constant that can influence a decision
- the decision-context adapter, including point-in-time/as-of semantics, stale/missing fail-closed behavior and replay/live equivalence
- the analogue-retrieval source boundary, proving that live query features are not compared against a differently scaled historical instrument unless a deterministic equivalence/normalization contract has been accepted ex ante

Feed qualification and decision-context qualification are separate acceptance questions. Bootstrap/history population does not imply live decision readiness.

For the Twelve Data adapter introduced after the original Gold-API cohort, the reconciled source/session/candle differences are evidence-semantic. The Twelve Data decision surface therefore **must not inherit or continue the existing Gold-API cohort**. It requires a new cohort/epoch, and formal accumulation remains zero until the feed, parameter provenance, analogue boundary and decision-context adapter are all qualified under one accepted code head.

## Evidence-semantic change presumption

Changes touching any of the following are **presumed evidence-semantic**:

- feed/provider adapter or vendor symbol mapping
- price basis or source identity
- session calendar, timezone, DST or maintenance-gap logic
- candle construction, aggregation, bucket boundaries or completeness/readiness
- feature construction or source admission/provenance
- thresholds, numeric scales, volatility bands or analogue-retrieval geometry

The default consequence of an evidence-semantic change is a new cohort/epoch. Preserving an existing cohort is the exception and requires affirmative deterministic proof recorded **at PR time, before merge and before any post-change outcome is observed**.

A preservation proof must contain:

- base commit SHA
- proposed head commit SHA
- the exact protected-path diff
- a SHA-256 digest of that diff
- the deterministic invariants/fixtures used to establish semantic equivalence
- the test/evidence result for each invariant
- an explicit classification of the change as evidence-semantic or proven transport-only

Missing, late, ambiguous or retrospective proof means the change is evidence-semantic and the cohort resets. Cohort size, accumulated N, reset cost or observed performance cannot be used as evidence that a change was transport-only.

## Cohort lifecycle

A formal cohort has only three states:

1. `prepared`
2. `active`
3. `closed`

The historical 20 September planning date no longer blocks activation because the accepted immediate-start amendment superseded it. Activation is instead controlled by the applicable manifest/amendment plus the complete qualification state for that cohort's evidence semantics.

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

The Day 53 CI workflow proves the registry, immutability, freeze-break rules, J17/J20 logging structure, shadow boundaries and full repository regression for the accepted code head.

Passing a feed/bootstrap workflow means the adapter/readiness machinery is built. It does **not** activate a new evidence-semantic cohort and it does not make a mid-bucket bootstrap decision-ready.

For Twelve Data, formal evidence begins only after a new frozen manifest/cohort version is created under the evidence-semantic rule, the required qualifications are accepted, and a scheduler-generated tick independently satisfies live current-bucket readiness. A bootstrap request itself never creates or asserts decision readiness.

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
