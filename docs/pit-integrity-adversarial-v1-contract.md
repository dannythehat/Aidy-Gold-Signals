# AIDY Day 19 — PIT Integrity Adversarial v1 Contract

## Purpose

Day 19 is a hard anti-hindsight gate over the complete AIDY historical-memory chain. It does not add trading intelligence. It attempts to make the existing intelligence cheat, and requires every known attack to fail before the future OpenAI Master Trader may consume AIDY memory.

Contract version: `aidy_pit_integrity_adversarial_v1`.

## Core invariant

At any decision/replay timestamp **T**, decision-context code may use only evidence that was genuinely knowable by **T** under its declared provenance contract. Later observations, later revisions, future outcome labels, retrospective-only research data and evaluation-only records must remain unavailable to decision/context/similarity paths.

A valid SHA-256 digest is necessary but not sufficient. Day 19 explicitly attacks packets after recomputing their digest/hash. Semantic provenance and future-data validation must still reject contamination.

## Real defect found and fixed on Day 19

Day 10 already required `aidy_gold_features_v1`, `mode=pit`, `provenance_class=pit_observed`, `pit_eligible=true`, an exact as-of timestamp and a valid feature digest. However, a hostile caller could inject a nested future/outcome field or retrospective lineage into an otherwise PIT-looking feature packet and recompute `feature_packet_digest`.

Day 19 moves that firewall to the earliest objective-context boundary. `context_packet._validate_feature_packet` now recursively rejects:

- future/outcome/evaluation field families inside the feature packet,
- `future_derived` unless it is explicitly `false`,
- `evaluation_only` unless it is explicitly `false`,
- nested `provenance_class=retrospective_history`, and
- nested `pit_eligible=false`.

This is a narrow hardening change. It does not alter valid Day 7/10 market-context semantics.

## Attack catalogue

The versioned catalogue contains 18 attacks:

1. later candle revision before `first_observed_at`
2. later macro revision before `first_observed_at`
3. future snapshot before `captured_at`
4. future cross-market observation/revision
5. retrospective candle injected into PIT features
6. future snapshot injected into PIT features
7. rehashed future field inside Gold feature packet
8. rehashed retrospective lineage inside Gold feature packet
9. future AIDY signal-lifecycle timestamp
10. rehashed hindsight field inside Day 11 regime context
11. evaluation-only future record masquerading as decision lifecycle state
12. rehashed hindsight inside Day 15 setup context
13. Day 15 regime from a different context hash
14. future field injected into Day 16 case input and rehashed
15. Day 17 analogue candidate at/after query time
16. Day 17 candidate whose outcome is not yet available at query time
17. changing a future outcome in an otherwise identical case
18. Day 18 selection tampering or a match claiming outcome-influenced similarity

Every attack has a stable `attack_id`, boundary and expected guard in `src/aidy/pit_integrity.py`.

## Boundary requirements

### Days 6–10 — observable truth

- `first_observed_at <= T` before revision ranking.
- `captured_at <= T` for snapshots.
- future Gold rows are excluded from PIT feature construction.
- retrospective research candles cannot masquerade as PIT features.
- official macro and cross-market evidence preserve first-observed knowability.
- Day 10 rejects semantically contaminated feature packets even after rehashing.

### Days 11 and 15 — descriptive intelligence

- regime and setup detection consume only valid objective Day 10 context.
- future/outcome fields are recursively rejected.
- setup detection requires a regime derived from the supplied context hash.

### Days 12–14 — future evaluation

These outputs intentionally use future data, but remain `evaluation_only=true`, `future_derived=true`, `pit_eligible=false` and `decision_input_allowed=false`. They cannot become decision lifecycle/context evidence.

### Day 16 — canonical memory

The historical case stores input and future evaluation together only behind a hard permission boundary. Future fields cannot enter `input_boundary`, including after the input digest is recomputed.

### Day 17 — analogue retrieval

Similarity/ranking uses the input boundary only. A candidate must precede the query timestamp and its future evaluation must already be available by the query timestamp. Changing future outcome content cannot alter similarity or selection.

### Day 18 — evidence grading

Day 18 validates the Day 17 retrieval digest, ranks, similarity digests and selection digest. It refuses evidence claiming outcomes affected similarity. Grading is downstream of selection and cannot repair or legitimize a contaminated retrieval.

## Decision-context storage isolation

Day 19 statically checks the Day 6–15 decision/context source files and Day 6 SQL contract for forbidden research-table names. Decision builders must not query:

- `research_candles`
- `research_move_labels`
- `research_trade_outcomes`
- `research_no_trade_counterfactuals`
- `research_gold_cases`

Day 16–18 research/evaluation code may use the research warehouse only under their explicit future-only contracts.

## Real-data acceptance

The acceptance workflow runs the full adversarial suite first, then performs a bounded read-only BigQuery probe against the accepted Day 16 `research_gold_cases` table through the frozen Day 17 retrieval contract.

For every real candidate returned by the candidate SQL:

- `case.as_of_utc < query.as_of_utc`
- `future_available_after_utc <= query.as_of_utc`
- returned matches have `outcome_used_for_similarity=false`
- retrieval has `outcomes_used_for_selection=false`

The probe creates no table and writes no analytical data.

## Non-goals

Day 19 does not tune setup thresholds, similarity weights, evidence grades, probability estimates or trading decisions. It does not touch Super Signals, MT5, broker state, Telegram or the OpenAI decision gateway.