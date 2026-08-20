# AIDY Move Detective v1 contract

Decision date: 2026-08-20  
Day 12 implementation: 2026-08-20

## Purpose

Day 12 creates objective future-path labels for research and evaluation. It answers a narrow question: after an historical anchor timestamp, what did the subsequent XAUUSD path objectively do?

This contract does not explain why Gold moved, does not claim a setup existed, does not create a trading opinion and is never decision-time evidence.

## Versions

- Horizon label: `aidy_move_label_v1`
- Multi-horizon bundle: `aidy_move_bundle_v1`
- Distribution summary: `aidy_move_distribution_v1`
- Digest algorithm: SHA-256 over canonical JSON

## Physical evidence boundary

Move Detective consumes only Day 5 retrospective M1 research candles:

- `provenance_class=retrospective_history`
- `pit_eligible=false`
- symbol `XAUUSD`
- timeframe `M1`
- explicit `research_identity`

It never consumes live/PIT `market_candles` as future labels, and its outputs are structurally marked:

- `contract_class=research_future_path_label`
- `evaluation_only=true`
- `future_derived=true`
- `pit_eligible=false`
- `decision_input_allowed=false`
- `available_after_utc` equal to the end of the evaluated horizon

If labels are later persisted, their dedicated table contract is `research_move_labels`. It is not a PIT table and deliberately has no `first_observed_at` field.

Day 10 also rejects a Day 12 bundle when someone attempts to pass it through the AIDY signal-lifecycle input. This proves the future label cannot masquerade as valid as-of signal state.

## Default horizons

V1 defines three deterministic horizons:

- 15 minutes
- 60 minutes
- 240 minutes

Every label is explicitly horizon-tagged. The bundle's `available_after_utc` is the end of its longest requested horizon.

## Coverage rule

A horizon is complete only when every M1 timestamp from anchor +1 minute through the exact horizon end is present exactly once.

Move Detective never fills gaps or interpolates candles.

If any required minute is missing:

- `coverage_state=incomplete`
- `path_class=unknown`
- the missing minute offsets are recorded

If more than one retrospective research revision exists for the same M1 timestamp in the supplied input, evaluation fails closed. A caller must explicitly choose one revision before segmentation instead of allowing Move Detective to select a revision silently.

## Fixed descriptive thresholds

V1 uses fixed, versioned thresholds. They are not optimized from future profitability.

- quiet maximum excursion: `< 12 bps` on both sides
- meaningful excursion: `>= 25 bps`
- spike excursion: `>= 40 bps`
- directional terminal retention: `>= 0.50` of the qualifying excursion
- reverted-spike terminal retention: `<= 0.25` of the spike excursion

All basis-point calculations use the explicit anchor price as denominator.

## Path classes

### `quiet`
Neither upward nor downward maximum excursion reaches 12 bps.

### `subthreshold_chop`
The path is not quiet, but neither side reaches the 25 bps meaningful threshold.

### `directional_up` / `directional_down`
One side reaches the meaningful threshold, the opposite side does not, and the terminal close retains at least half of the qualifying excursion in the same direction.

### `spike_up_reverted` / `spike_down_reverted`
One side reaches the 40 bps spike threshold, the opposite side does not reach the meaningful threshold, and the terminal close retains no more than one quarter of the spike excursion.

### `reversal_up_to_down` / `reversal_down_to_up`
Both sides reach the meaningful threshold in different M1 bars. The label records which threshold was crossed first.

### `two_sided_intrabar_order_unknown`
The same M1 candle crosses both meaningful thresholds. OHLC bars do not reveal whether high or low occurred first, so AIDY explicitly refuses to invent a reversal order.

### `complex`
A complete path is objectively meaningful but does not meet one of the narrower deterministic classes above.

## Path statistics

For complete horizons the label records:

- maximum upward excursion in bps
- maximum downward excursion in bps
- terminal return in bps
- full high-low range in bps
- close-to-close path travel in bps
- close-path efficiency
- terminal retention ratios for each side
- time to maximum upward and downward excursion
- first meaningful upward and downward threshold-crossing times

These are descriptive path measurements only.

## Provenance

Each horizon label records the research identities used for that exact horizon through a deterministic digest, plus source/archive payload digests when present.

Input list order does not affect a label. Duplicate research timestamps are rejected rather than silently resolved.

## Leakage rules

Day 12 labels are future-derived by definition.

They may be used later for research questions such as "what tended to happen after contexts like this?" but they may never appear inside:

- a Day 6 PIT reconstruction
- a Day 7 PIT feature packet
- a Day 10 objective context packet
- a Day 11 regime packet
- a future Master Trader decision input as if they were known at the anchor timestamp

Later historical-case construction must keep decision-time inputs and future-derived outcome labels as separately typed sections.

## Distribution summary

`move_label_distribution` reports deterministic counts by horizon and path class plus coverage counts. It contains no causal claim and no profitability statistic.

The Day 12 live acceptance uses a bounded sample of the already accepted 2025 HistData M1 research history to produce a historical distribution summary. Fixture tests, not the live sample, are responsible for proving every important path-class edge case.

## Acceptance gate

Day 12 passes only when automated evidence proves:

1. quiet, directional, spike and reversal fixture paths classify reproducibly;
2. same-bar two-sided excursions remain intrabar-order unknown;
3. exact threshold boundaries behave deterministically;
4. missing M1 minutes fail closed instead of being interpolated;
5. reordered identical research evidence yields identical labels and digests;
6. every label is horizon/version tagged, future-derived, non-PIT and unavailable until horizon end;
7. retrospective rows with the wrong provenance or `pit_eligible=true` are rejected;
8. duplicate retrospective revisions require explicit caller selection;
9. `research_move_labels` is physically separate from PIT tables;
10. a Day 12 bundle cannot be accepted as Day 10 signal-lifecycle state;
11. distribution output is deterministic and contains no causal claim;
12. a bounded real historical distribution can be generated from accepted research history;
13. the full existing AIDY test suite remains green.

## Downstream boundary

Day 13 may build trade/setup outcome measurements such as favorable/adverse excursion using these future paths, but it must not weaken the evaluation-only boundary established here.
