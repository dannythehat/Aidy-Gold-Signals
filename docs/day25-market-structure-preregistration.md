# Day 25 pre-registration — market-structure epochs, named windows and J5

Status: **frozen before Day 25 measurement**

Base commit: `9c2d0e33177c40bbc123f380bce68ffe2430f504`

## Purpose

Day 25 adds deterministic structural context without weakening any accepted Day 24 retrieval rule. The Day 24 minimum similarity (`0.72`), component coverage (`0.65`), 240-minute embargo, 240-minute episode definition, outcome separation and effective-independent-N grading remain unchanged.

The new context must distinguish structural market mechanics that make otherwise similar price patterns non-comparable. It is descriptive context, not a new source of alpha by assertion.

## Frozen structural boundaries

### Architecture regime boundary — 24 February 2022

Architecture V2 pre-registers a post-February-2022 structural regime. This is an **AIDY architecture boundary**, not a claim that CME or LBMA changed Gold venue rules on that exact timestamp. It is therefore labelled as such in provenance and is never represented as an exchange rule change.

Boundary: `2022-02-24T00:00:00Z`.

### CME 1-Ounce Gold 24/7 boundary — 24 July 2026

CME SER-9766 announced that 1-Ounce Gold futures would become Globex-only and expand to 24/7 trading effective Friday 24 July 2026. CME's subsequent July 13 Globex notice specified a special first-Friday maintenance period ending at 4:30 p.m. Chicago time before the first weekend session. Day 25 therefore uses `2026-07-24T21:30:00Z` as the exact boundary at which the first weekend-capable 24/7 regime became operational, while also retaining the official effective date `2026-07-24` in provenance.

This boundary applies to the 1-Ounce Gold contract market-structure context. It does **not** assert that XAUUSD itself suddenly became a different venue. AIDY uses it as a documented Gold-market structural epoch boundary for analogue compatibility.

## Named-window policy

Named windows are deterministic clock/calendar context, not independent confirmations of a trade thesis.

The frozen Day 25 set includes:

- AIDY broad Asia/London/New York liquidity windows, preserving the accepted Day-0–24 session semantics.
- LBMA Gold Price AM auction at 10:30 Europe/London.
- LBMA Gold Price PM auction at 15:00 Europe/London.
- legacy COMEX/New York Gold open-liquidity reference at 08:20 America/New_York. This is explicitly labelled **legacy open-outcry reference**, not modern electronic Globex open.
- Gold futures daily settlement observation window at 13:29–13:30 America/New_York.
- regular Gold Globex daily maintenance/close-reopen reference around 16:00–17:00 America/Chicago.
- post-boundary 1-Ounce Gold maintenance: Monday–Friday 16:00–16:02 America/Chicago and Saturday 02:00–04:00 America/Chicago.
- contract-specific CME Gold options-expiry windows only when supplied by a versioned official-schedule record that was known by the context timestamp.

DST is resolved with IANA time zones (`Europe/London`, `America/New_York`, `America/Chicago`, `Asia/Tokyo`) rather than hard-coded offsets.

## Calendar / PIT rule

A scheduled-event record may enter context at timestamp T only when `known_at_utc <= T`.

Exact exchange holiday/half-day/special-close hours are not inferred from a future schedule. CME states that holiday trading hours are subject to change and are typically finalized approximately two weeks before the holiday. Therefore:

- deterministic public holiday dates may be labelled as calendar dates;
- exact half-day, early-close, maintenance or options-expiry overrides require a supplied official record with a `known_at_utc` no later than T;
- a record whose publication/known timestamp is after T is ignored;
- missing exact hours remain `unknown`, not silently converted to normal hours.

## Retrieval integration

Accepted Day 24 `analogue_retrieval_v2` remains unchanged.

Day 25 enriches the query and candidate input boundary with canonical `market_structure_epoch`, recomputes input/query/case identities, and then delegates selection to the unchanged Day 24 retriever. With a known query epoch:

- missing candidate epoch fails closed;
- epoch mismatch fails the existing Day 24 hard gate;
- no pre-Day25 epoch relaxation is permitted for a Day 25-enriched query;
- no outcome value is used to assign an epoch, session, calendar state or select an analogue.

## J5 — market-structure epoch effect

### Hypothesis

Within otherwise matched regime/setup strata, same-epoch historical observations may have lower 240-minute outcome dispersion than cross-epoch observations.

This is a **descriptive test**, not a causal claim and not an optimization objective.

### Frozen cohort

Use the exact accepted Day 23/24 historical candidate-store snapshot:

`bd3c81b54ec05b2150e6e6ecbdffbc3c1e4f943c6a23c9a8ee4977c1dc1c3a88`

No case may be added, removed or replaced for this Day 25 acceptance measurement.

### Matching stratum

Pairs are formed only after grouping on decision-time/input-boundary fields:

1. `trend_structure`
2. `volatility_band`
3. sorted `candidate_setup_ids`

No future outcome is used to create the stratum or assign the epoch.

### Episode independence

Within each matching stratum, cases with overlapping complete 240-minute outcome windows are collapsed into connected temporal episodes before pair construction. The deterministic representative is the lexicographically smallest `case_id`; outcomes do not choose the representative. J5 reports both raw eligible-case counts and independent representative counts. This prevents clustered timestamps from manufacturing pair count.

### Outcome

Only a complete Move Detective 240-minute label is eligible. The frozen descriptive outcome is `path_stats.terminal_return_bps`.

For every eligible **episode-independent representative** pair within a stratum calculate:

`abs(terminal_return_bps_a - terminal_return_bps_b)`

Pairs are then classified as:

- `same_epoch`
- `cross_epoch`

### Frozen descriptive statistics

Report separately for same-epoch and cross-epoch pairs:

- pair count
- minimum
- p25
- median
- mean
- p75
- maximum absolute terminal-return difference in bps

Also report raw source-case counts, complete-240m case counts and independent episode-representative counts by epoch.

### Frozen conclusion rule

Minimum **episode-independent pair count** per comparison class: **10**.

- If either same-epoch or cross-epoch has fewer than 10 matched pairs: `INSUFFICIENT`.
- If both have at least 10 pairs and same-epoch median absolute difference is lower than cross-epoch median: `SUPPORTS_LOWER_SAME_EPOCH_DISPERSION`.
- If both have at least 10 pairs and that ordering is not present: `DOES_NOT_SUPPORT_LOWER_SAME_EPOCH_DISPERSION`.

The new post-24-Jul-2026 1-Ounce 24/7 epoch is separately considered `INSUFFICIENT` unless it has at least **10 complete independent historical episode representatives**. Day 25 acceptance explicitly allows this result.

No threshold, structural boundary, stratum definition, independence rule, outcome field or conclusion rule may be changed after observing J5.

## Acceptance invariants

Day 25 passes only if:

- epoch assignment is deterministic and versioned;
- UTC/DST and weekend tests pass;
- official named windows reproduce correctly across DST;
- future-known calendar records cannot leak into T;
- historical cases and live/PIT context can carry the same structural-context contract;
- Day 25 retrieval delegates to unchanged Day 24 selection and keeps all Day 24 numerical gates;
- known-epoch retrieval cannot emit `market_structure_epoch_unavailable_pre_day25`;
- J5 is produced exactly from the frozen cohort and rules above;
- `INSUFFICIENT` is accepted where sample counts do not earn a conclusion;
- no future outcome enters context construction or retrieval selection.
