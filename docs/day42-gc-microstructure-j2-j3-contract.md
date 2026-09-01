# Day 42 — Genuine GC microstructure, VWAP and shadow J2/J3

Decision date: 2026-09-01

Authoritative base: `8672ad19ba40ceaed2cf0f042c8e2af3694896a5`

## Objective

Add genuine COMEX Gold microstructure features to the Day 41 shadow observation spine and run the preregistered J2/J3 research contracts without promoting any feature into live decision authority.

Day 42 is a shadow research day. It does not create formal forward evidence, a trading gate, a broker dependency, a paid/live GC subscription, or any Super Signals integration.

## Source contract

The source is Databento `GLBX.MDP3` using the `tbbo` schema and OI-ranked continuous research symbol `GC.n.0`. Every accepted row must resolve to an auditable raw GC contract identity through Databento symbology.

The Day 40 free-first policy remains binding:

- `tbbo` is approved for bounded historical research;
- `mbo` and `mbp-10` remain prohibited;
- every genuine acceptance request is quoted before download and re-quoted before execution;
- the Day 42 smoke adds a strict `$0.25` request cap;
- no paid recurring service or live subscription is activated;
- the API key is never written to evidence or logs.

## Genuine features

Day 42 derives only features supported by genuine exchange observations:

- traded volume from genuine trade size;
- best bid/ask spread from genuine pre-trade BBO carried by TBBO;
- signed trade flow from the Databento aggressor-side field when side is known;
- unknown aggressor side remains unknown and is never imputed;
- minute VWAP from `sum(price × size) / sum(size)`;
- session-anchored VWAP from cumulative genuine price×volume within the deterministic AIDY session anchor;
- VWAP distance, spread, trade volume and signed-flow state.

Day 42 does **not** claim full depth, order-book imbalance, L2, L3 or MBO. Bid/ask sizes present in the TBBO top-of-book record do not authorize a depth claim.

## Frozen time-of-day × weekday normalization

Before any outcome analysis, the system freezes reference distributions by UTC weekday and 15-minute clock slot. The baseline is outcome-blind and carries its own digest.

The following features are normalized only against their matched weekday/clock bucket:

- genuine trade volume;
- BBO spread in basis points;
- signed trade imbalance when aggressor side is known;
- VWAP distance in basis points.

Ordinary London, New York, overlap, Asia or off-hours activity differences cannot count as alpha merely because absolute volume/spread levels differ by session.

Sparse buckets remain `insufficient`; they are not filled from neighboring clock periods or other weekdays.

## J2 — volume incremental information

Hypothesis: matched-clock genuine GC participation/flow features add incremental outcome information beyond the frozen baseline context.

Null: after frozen baseline controls, genuine GC volume/flow/VWAP features add no incremental outcome information.

J2 remains shadow-only. A null or insufficient result is retained as valid evidence. A single result cannot promote a gate.

## J3 — richer liquidity failure repeat

Hypothesis: matched-clock genuine GC spread/liquidity state is associated with setup failure after controlling for frozen volatility and clock/weekday context.

Null: after the frozen controls, genuine GC spread/liquidity state does not differentiate setup failure.

This is the richer-feed repeat of the accepted Day 27 J3 contract. It does not erase or rewrite Day 27 evidence.

## Trial/replay integrity

The complete J2/J3 experiment plan is frozen before the Day 42 result payloads are generated. Each result is bound to:

- the immutable experiment-plan digest;
- Day 32 monotonic trial-registry semantics;
- Day 37 chronological split identity;
- purge and embargo requirements;
- holdout-tuning prohibition;
- exact candidate code head.

The acceptance fixture is allowed to finish `insufficient` when no genuine outcome-linked independent cohort exists yet. The system must never invent observations, relax the independent-N floor, or turn ordinary session activity into a positive research result merely to make Day 42 look successful.

## Genuine acceptance evidence

After all offline checks pass, exact-head CI:

1. authenticates with the existing Databento credential;
2. verifies `GLBX.MDP3` and required schema entitlement;
3. selects the latest fully entitled weekday TBBO window;
4. quotes a five-minute `GC.n.0` TBBO request;
5. rejects the request if quoted cost exceeds `$0.25`;
6. downloads genuine TBBO history;
7. resolves instrument IDs to raw GC contracts;
8. parses genuine trade/BBO records;
9. derives genuine volume, spread, signed-flow and VWAP features;
10. freezes a matched weekday×clock baseline;
11. records J2/J3 as shadow evaluation results, including valid `insufficient` states;
12. enforces all no-promotion/no-live/no-broker/no-secret boundaries;
13. uploads exact-head evidence.

The genuine smoke is retrospective architecture/research evidence only: `pit_eligible=false` and `formal_forward_evidence_created=false`.

## Acceptance boundary

Day 42 passes only when:

- the bounded five-file surface is exact;
- static checks pass;
- focused adversarial tests pass;
- the full repository regression passes;
- deterministic acceptance is byte-identical across two runs;
- genuine Databento TBBO evidence passes on the exact head;
- volume is proven to come from genuine trades;
- spread is proven to come from genuine BBO quotes;
- VWAP is proven to be price×volume based;
- unknown trade side is never imputed;
- weekday×clock normalization is frozen before outcomes;
- J2/J3 retain null/insufficient results and use the Day 32/37 integrity contracts;
- no depth/order-book claim, broker mutation, publication, paid/live subscription, feature promotion or formal-forward result is created.
