# AIDY Historical Analogue Retrieval v1 Contract

## Purpose

Day 17 turns Day 16 historical Gold cases into usable, point-in-time-safe memory.

The retrieval question is deliberately narrow:

> Given what was knowable at query time, which earlier AIDY Gold cases were genuinely similar enough to inspect?

This layer does not decide whether to trade, estimate a probability of winning, or grade the strength of the evidence. Day 18 owns evidence grades and sample-size semantics.

## Versions

- Query: `aidy_historical_analogue_query_v1`
- Similarity features: `aidy_gold_similarity_features_v1`
- Retrieval: `aidy_historical_analogue_retrieval_v1`
- Required case input: `aidy_historical_case_input_v1`
- Required historical case: `aidy_historical_gold_case_v1`

All hashes are deterministic canonical JSON SHA-256 digests.

## Input boundary

The query is built from Day 16 `input_boundary` only.

Required input properties include:

- `future_derived=false`
- `analogue_match_allowed=true`
- a valid Day 16 `input_digest`
- current frozen Day 7 feature version
- current frozen Day 11 regime version
- current frozen Day 15 taxonomy/detector versions
- versioned `analogue_features`
- explicit data-quality state
- explicit provenance

Future/outcome keys are recursively forbidden from the query even if an attacker recomputes the outer input digest.

The query can therefore be created before the current case has any future outcome.

## Historical availability rule

For a query at time **T**, a candidate may be retrieved only when:

1. candidate `as_of_utc < T`
2. candidate `future_available_after_utc <= T`
3. candidate provenance is explicitly allowed
4. candidate quality is retrieval-eligible
5. feature/regime/setup versions are compatible

This is stricter than simply asking whether the candidate case itself occurred before T.

A historical case from 10:00 whose 4-hour outcome becomes available at 14:00 must not tell a replay running at 12:00 what happened after 10:00.

For a live current query, old historical cases naturally satisfy this rule once their outcomes are complete.

## Provenance

Supported candidate provenance remains explicit:

- `retrospective_history`
- `pit_observed`

The default Day 17 historical search allows `retrospective_history`.

Other provenance classes must be deliberately requested. Results retain their provenance label. The system never silently promotes retrospective HistData reconstruction into genuinely observed live evidence.

## Similarity dimensions

Similarity v1 uses 15 human-auditable components.

### Regime

- trend structure
- volatility band
- session
- official-event timing state when available
- quote/spread condition when available

### Multi-timeframe structure

- M15 direction
- H1 direction
- H4 direction

### Numeric market state

- H1 ATR(14)
- M15 realized volatility
- M15 recent-range position
- M15 close location
- active-session range position

### Setup context

- Day 15 detector state
- Day 15 candidate setup IDs

Weights and numeric comparison scales are frozen in `similarity_manifest()`.

They are descriptive engineering choices, not thresholds calibrated from Day 12/13/14 outcomes.

## Missing evidence

Missing values do not become zeros and do not become matches.

A component is `unavailable` when either side lacks a comparable observation. Similarity is calculated across actually comparable weight, and the result separately reports `component_coverage`.

Default v1 gates:

- minimum similarity score: `0.72`
- minimum component coverage: `0.65`

A candidate that fails either gate is not returned.

This is the Day 17 anti-fake-match rule.

Day 18 will add evidence grades and sample-size semantics on top. Day 17 must not use a low match count to manufacture probability-like confidence.

## Numeric comparison

For each numeric component:

`component_similarity = max(0, 1 - absolute_difference / fixed_scale)`

The fixed scales are versioned in the manifest.

Categorical values compare exactly.

Setup IDs use Jaccard overlap when both detector states make setup identity meaningful. Indeterminate setup states do not pretend an empty candidate list is comparable evidence.

## Ranking

Candidates that pass hard eligibility and similarity/coverage gates are ranked by:

1. higher similarity score
2. higher component coverage
3. deterministic `case_id` tie-break

Recency is not secretly used as a tie-break or weight in Day 17. Day 18 owns recency/stability evidence semantics.

Every returned match exposes:

- rank
- `case_id`
- case timestamp
- provenance
- data-quality grade
- regime
- setup detector state
- candidate setup IDs
- overall similarity
- component coverage
- every individual similarity component
- future evaluation, attached only after ranking

## Outcome firewall

Future evaluation is intentionally returned with a selected historical analogue because the point of memory is to inspect what later happened.

However:

- outcome fields never enter the query
- outcome fields never enter similarity scoring
- outcome fields never enter ranking
- a candidate outcome must have been available by query time
- `outcomes_used_for_selection=false` is explicit in every retrieval result

Changing a candidate's future outcome while preserving its input identity cannot change its similarity, rank, or selection digest.

The full retrieval digest may change because the returned evaluation payload changed. The separate `selection_digest` must remain stable.

## Query identity

`query_id` is deterministic over:

- query/retrieval/similarity versions
- query timestamp
- source input digest
- optional source case exclusion
- allowed candidate provenance
- result limit
- similarity and coverage thresholds
- frozen feature versions
- query data-quality state
- query analogue features

The same query produces the same ID.

## BigQuery contract

Day 17 searches the physical Day 16 table:

`aidy_analytics_test.research_gold_cases`

The BigQuery candidate query applies hard filters before Python similarity scoring:

- XAUUSD only
- candidate before query time
- candidate outcome available by query time
- allowed provenance only
- non-insufficient quality
- exact feature/regime/setup versions
- bounded candidate limit

Similarity is then calculated deterministically in Python from `input_boundary.analogue_features`.

Future evaluation is selected from storage but is never read by the scoring function.

## No-evidence semantics

Retrieval states are:

- `matches_found`
- `no_sufficient_similarity`
- `query_insufficient_quality`

`no_sufficient_similarity` is a successful, truthful retrieval result.

It is preferable to returning weak neighbours simply to fill a list.

Day 17 contains no probability claims and no profitability claims.

## Security and separation

Day 17 does not use:

- Super Signals
- broker/follower account state
- MT5 execution
- Telegram publication
- OpenAI trading decisions
- future outcomes for ranking

It remains a research/intelligence memory-retrieval layer.
