# AIDY Evidence Grade v1 — Day 18 contract

## Purpose

Day 18 decides how much trust AIDY may place in the historical analogues returned by Day 17.

It does **not** choose neighbours, alter similarity, tune thresholds from outcomes, make a trade
decision or create a probability from a small sample. It consumes a completed Day 17 retrieval
only after selection is finished.

## Versions

- Evidence grade: `aidy_evidence_grade_v1`
- Evidence report: `aidy_analogue_evidence_report_v1`
- Evidence statistic: `aidy_evidence_statistic_v1`
- Source retrieval: `aidy_historical_analogue_retrieval_v1`
- Source similarity: `aidy_gold_similarity_features_v1`

All v1 thresholds are fixed engineering guardrails. They were not optimized against future
returns, win rates, PnL or any other outcome field.

## Semantic ladder

The only allowed dataset/statistic grades are:

1. `INSUFFICIENT`
2. `EXPLORATORY`
3. `MODERATE EVIDENCE`
4. `ESTABLISHED DATASET`

The grade can move upward only when **every** requirement for that level is satisfied.
A large sample alone is not enough.

### EXPLORATORY

Minimum requirements:

- n >= 10
- mean similarity >= 0.72
- 25th-percentile similarity >= 0.68
- mean similarity-component coverage >= 0.65
- mean Day 16 input-quality score >= 0.65
- complete 240-minute move outcome ratio >= 0.80
- temporal span >= 7 days
- at least 4 unique calendar days
- newest case no older than 365 days
- no single calendar day contributes more than 50% of the evidence

EXPLORATORY evidence is descriptive only. It cannot emit probability-like rates and cannot
receive decision weight.

### MODERATE EVIDENCE

Minimum requirements:

- n >= 30
- mean similarity >= 0.78
- 25th-percentile similarity >= 0.72
- mean component coverage >= 0.75
- mean Day 16 input-quality score >= 0.75
- complete 240-minute move outcome ratio >= 0.90
- temporal span >= 30 days
- at least 12 unique calendar days
- at least 2 unique calendar months
- newest case no older than 180 days
- no single day contributes more than 20%
- no single month contributes more than 80%

MODERATE EVIDENCE may expose descriptive empirical rates. It is still not eligible for automatic
decision weight and never creates a standalone trade instruction.

### ESTABLISHED DATASET

Minimum requirements:

- n >= 100
- mean similarity >= 0.82
- 25th-percentile similarity >= 0.76
- mean component coverage >= 0.82
- mean Day 16 input-quality score >= 0.85
- complete 240-minute move outcome ratio >= 0.95
- temporal span >= 180 days
- at least 45 unique calendar days
- at least 6 unique calendar months
- newest case no older than 90 days
- no single day contributes more than 10%
- no single month contributes more than 30%

ESTABLISHED DATASET evidence is eligible to receive decision weight in a later contract, but Day 18
does not define that weight and never makes a standalone trading decision.

## Day 16 quality mapping

The deterministic Day 16 input-quality grades map to a bounded score only for the purpose of
evidence completeness:

- `strong` = 1.00
- `moderate` = 0.80
- `limited` = 0.60
- `insufficient` = 0.00

Day 17 already excludes `insufficient` cases from retrieval.

## Outcome completeness versus outcome value

Day 18 may inspect whether a 240-minute future path is **complete** because evidence with missing
future observations is not equally usable for evaluation.

Day 18 must not use the value of that outcome to determine the dataset grade. Changing
`directional_up` to `spike_down_reverted`, for example, cannot alter the dataset grade when all
metadata and completeness are unchanged.

This distinction is mandatory:

- outcome **availability/completeness** may affect evidence quality;
- outcome **direction/result/value** may not affect the dataset grade.

## Hard ordering boundary

The sequence is fixed:

1. Day 16 builds canonical historical cases.
2. Day 17 performs PIT-safe analogue selection and ranking.
3. Day 18 grades the already-selected evidence.

Day 18 validates the Day 17 retrieval digest, similarity-score digests, ranks and selection digest.
The evidence report carries the original selection digest unchanged and states:

- `grading_applied_after_analogue_selection = true`
- `selection_mutated_by_grading = false`
- `outcomes_used_for_analogue_selection = false`

No Day 18 field may feed back into Day 17 similarity or ranking.

## Every statistic owns its own n and grade

A strong dataset grade does not automatically transfer to a thin sub-statistic.

Day 18 v1 emits six deterministic categorical statistics:

- move path class at 15 minutes
- move path class at 60 minutes
- move path class at 240 minutes
- trade outcome state at 15 minutes
- trade outcome state at 60 minutes
- trade outcome state at 240 minutes

Each statistic is graded again using only the matches that have a complete, known observation for
that exact statistic.

Example: a 30-case MODERATE EVIDENCE retrieval with only five valid trade outcomes produces a trade
statistic with `n=5` and grade `INSUFFICIENT`.

## Probability-like wording and weighting guards

For `INSUFFICIENT` and `EXPLORATORY` statistics:

- category counts may be shown;
- category rates are omitted entirely;
- probability-like wording is forbidden;
- decision weight is forbidden.

For `MODERATE EVIDENCE`:

- descriptive empirical rates may be shown;
- decision weight remains forbidden.

For `ESTABLISHED DATASET`:

- descriptive empirical rates may be shown;
- the statistic becomes eligible for a later decision-weight contract.

At every grade:

- causal claims are forbidden;
- standalone trade decisions are forbidden;
- realized PnL is not introduced;
- confidence is not manufactured from the evidence grade.

## Determinism

The same Day 17 retrieval produces the same:

- evidence metrics
- grade
- next-grade blockers
- statistic counts/rates
- grade/statistic/report digests

Reordering an equivalent set of matches cannot change the grade.

## Real acceptance probe

The Day 18 PR workflow:

1. runs Ruff and compile checks;
2. runs focused Day 18 tests;
3. runs the entire AIDY regression suite;
4. uses the existing Google Cloud credential;
5. queries the real Day 16 `research_gold_cases` table through the Day 17 retrieval contract;
6. grades the returned real evidence;
7. proves grading preserved the Day 17 selection digest;
8. proves low-n real evidence cannot emit probability-like rates or receive decision weight.

The current bounded Day 16/17 dataset is intentionally expected to remain conservative. A single
excellent neighbour is still one neighbour and therefore `INSUFFICIENT`.

## Explicit non-goals

Day 18 does not:

- tune similarity weights;
- lower Day 17 similarity thresholds to create more matches;
- infer a trading edge;
- claim profitability;
- create model confidence;
- size risk;
- access broker/follower/Super Signals state;
- call OpenAI;
- publish Telegram signals;
- execute trades.

Day 19 remains responsible for adversarial PIT-integrity and leakage tests across the research
stack.
