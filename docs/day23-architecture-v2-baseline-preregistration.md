# Day 23 Architecture V2 — J1 + baseline J16 pre-registration

Version: `aidy_day23_architecture_v2_baseline_v1`

Baseline commit: `4bc7269ee05f5596ac6555279e97e98556be9b96`

Day 23 is a measurement of the accepted Day 17 historical analogue retrieval and Day 18 evidence grading. It is not a retrieval-remediation day and it does not alter the existing retrieval or grading implementation.

## Frozen before results

The acceptance run must create and durably persist the complete query manifest **before** it evaluates any analogue result.

- Exactly 1,000 historical query states are required.
- Query anchors are the first 1,000 chronological, actually present HistData XAUUSD M1 hourly closed anchors at or after `2025-03-01T00:00:00Z`.
- No anchor may be removed, substituted, reordered or cherry-picked after seeing a result.
- Each query state is reconstructed with the existing Day 16 retrospective input builder and its 45-day context lookback.
- Retrieval is the accepted Day 17 implementation: `aidy_historical_analogue_retrieval_v1` / `aidy_gold_similarity_features_v1`.
- Similarity threshold remains `0.72`.
- Component-coverage threshold remains `0.65`.
- Candidate limit remains `2,000`.
- `max_results=200`, matching the accepted Day 18 evidence-grading probe baseline.
- Outcomes are forbidden from analogue selection.
- Day 23 does not tune feature weights, thresholds, cases, query states, setup definitions or grades.

The exact query payloads, query IDs, source input digests and source provenance are persisted in `research_day23_query_manifest` and in the acceptance artifact. The manifest has a deterministic digest.

## J1 — analogue independence

For every frozen query, Day 23 records:

- `candidate_raw_n`: rows admitted by the existing Day 17 BigQuery candidate SQL and candidate limit;
- `sufficient_match_n`: cases passing the existing Day 17 similarity and coverage thresholds;
- `selected_raw_n` / `raw_n`: cases returned to the existing Day 18 grader, before independence accounting;
- selected case IDs, case digests, input digests, ranks, similarities and component coverage;
- candidate-pool digest, selection digest and retrieval digest;
- effective independent sample size;
- effective-N / raw-N;
- number of independent market episodes;
- episode concentration (HHI and maximum episode share);
- same-episode and overlapping-path pair shares;
- temporal span and distinct calendar months;
- similarity and component-coverage distributions;
- near-top similarity concentration;
- explicit `NO_COMPARABLE_CASE` when the accepted Day 17 retrieval returns no sufficiently similar case.

### Frozen episode definition

A market episode is a connected component of overlapping 240-minute evaluation windows. If A overlaps B and B overlaps C, all three belong to the same episode even if A and C do not directly overlap. A new episode begins only when the next selected case's evaluation window starts at or after the prior connected component's end.

This definition is conservative by design: overlapping future Gold paths are not counted as independent observations merely because their case timestamps differ.

For episode sizes `n_i` and selected raw count `N`:

`effective_n = N^2 / sum(n_i^2)`

This is the Kish-equivalent episode count. The independence ratio is:

`effective_n / selected_raw_n`

`NO_COMPARABLE_CASE` is a coverage outcome and is **not** assigned a zero independence ratio. The stop-work median is therefore computed over legitimate comparable retrievals with `selected_raw_n > 0`, while `NO_COMPARABLE_CASE` and query-insufficient-quality rates are reported separately over all 1,000 frozen queries. This prevents low coverage from being falsely converted into low independence or vice versa.

### Pre-registered stop-work rule

If baseline median `effective_n / raw_n < 0.50`, the Day 23 result fires the stop-work branch. Normal roadmap progression is not permitted. Day 24 becomes the elastic memory-recovery programme and downstream dates may slip.

Schedule pressure cannot override this result.

The Day 24 recovery exit remains frozen at:

- exact same 1,000-query manifest;
- median `effective_n/raw_n >= 0.70` for legitimate comparable retrievals;
- median distinct independent episodes `>= 10`;
- separate reporting of candidate raw N, selected raw N, effective N and `NO_COMPARABLE_CASE` across all 1,000;
- complete affected evidence-store regrading on effective N;
- leakage and reproducibility reruns.

Missing any recovery criterion leaves Day 24 open.

`NO_COMPARABLE_CASE > 50%` is acceptable and does not relax the independence bar. Above 75%, historical memory is classified as `COVERAGE-LIMITED`; thresholds are not weakened to manufacture evidence.

## J16 — evidence-grade usefulness baseline

J16 applies the **existing** Day 18 grade to each frozen retrieval. Grading remains downstream of selection and its dataset grade does not use realised outcome values.

After grading, the research-only evaluation process measures realised 240-minute outcome dispersion using:

- population standard deviation of terminal return in basis points (primary);
- interquartile range of terminal return;
- median absolute deviation of terminal return;
- normalized entropy of the realised path-class distribution.

Day 23 reports sample counts and dispersion by observed Day 18 grade, plus descriptive rank ordering/correlation where there is sufficient grade variation. It reports no p-value and makes no independence-based inferential claim because the same near-duplicate episodes under investigation can create pseudo-replication.

A positive Day 23 relationship is **not** grading-system clearance. `validation_clearance=false` is hard-coded into the research contract. Only the post-hardening Day 38 J16 rerun may validate the grading architecture.

Queries that the existing Day 18 reporter cannot grade because the query itself is insufficient quality are retained as `not_graded`; they are not removed or silently relabelled.

## Persistence and reproducibility

The one acceptance run persists:

- `research_day23_query_manifest` — immutable frozen query payloads;
- `research_day23_j1_results` — one J1 result per frozen query;
- `research_day23_j16_results` — one descriptive J16 result per frozen query;
- `research_day23_summary` — deterministic experiment summary.

The GitHub Actions artifact also contains the pre-registration, exact query manifest, candidate-store identity snapshot, all J1 rows, all J16 rows and summary.

The candidate in-memory selector is required to match the accepted Day 17 BigQuery candidate SQL exactly on both the first and last frozen query before the 1,000-query measurement is accepted. This avoids 1,000 redundant warehouse SQL jobs without changing candidate semantics.

## Boundaries

Day 23 does not:

- edit Day 17 retrieval weights or thresholds;
- edit Day 18 evidence-grade rules;
- use future outcomes for query construction or analogue selection;
- import or modify Super Signals;
- read follower balances, positions, orders or risk state;
- use broker, MT5, MetaAPI or Vantage credentials;
- activate paid market data;
- add seasonality/month/quarter features;
- add psychological/round-number features;
- start Day 24.

The Architecture V2 reviewer amendments remain governing constraints. In particular, Day 53 formal forward paper begins on 20 September 2026, Day 54 remains the earliest review checkpoint on 8 October 2026, forward inference is sample-gated, intraday liquidity evidence later requires time-of-day × weekday normalization, the Day 40 market-data procurement decision is owner-gated, and the Day 53 forward freeze may only be broken for the three documented integrity/deprecation/market-structure reasons.
