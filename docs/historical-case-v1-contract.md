# Historical Gold case v1 contract

## Purpose

Day 16 turns AIDY's separate context, regime, setup and future-evaluation tools into one canonical historical memory record without allowing later outcomes to contaminate the information that was available at the case timestamp.

The full record is `aidy_historical_gold_case_v1`. The input side is `aidy_historical_case_input_v1` and the Day 17-safe projection is `aidy_historical_analogue_input_v1`.

## Two provenance classes are deliberate

AIDY must never pretend retrospective research was genuinely observed live.

### `pit_observed`

A genuinely observed case built from an exact Day 10 `aidy_market_context_v1`, Day 11 `aidy_gold_regime_v1` and Day 15 `aidy_gold_setup_detection_v1` hash chain.

These cases preserve the original context hash, regime digest and setup-detection digest.

### `retrospective_history`

A research replay built from accepted Day 5 HistData candles. It uses the same Day 7 feature definition, Day 11 regime rules and Day 15 setup taxonomy/detector rules, but it remains explicitly retrospective and PIT-ineligible.

A retrospective case is useful historical evidence. It is not proof that AIDY actually observed those facts live at that historical timestamp.

## Closed-candle replay rule

Retrospective replay may use a candle only after that candle would have closed:

- M1: `open_time + 1 minute <= as_of`
- M5: `open_time + 5 minutes <= as_of`
- M15: `open_time + 15 minutes <= as_of`
- H1: `open_time + 60 minutes <= as_of`
- H4: `open_time + 240 minutes <= as_of`
- D1: `open_time + 1440 minutes <= as_of`

This rule is stricter than merely checking `open_time <= as_of`. It prevents the retrospective replay from reading a candle close, high or low that was not yet knowable at the case timestamp.

For a retrospective case the evaluation anchor is the last closed M1 bar. The future path starts with the next minute. This keeps the input side causal while remaining compatible with the Day 12/13 research-label anchor convention.

## Input boundary

`input_boundary` is the only part of a historical case that Day 17 analogue matching may use.

It contains:

- exact case `as_of_utc`
- provenance class
- Day 7 feature version and feature packet digest
- bounded multi-timeframe feature summary
- Day 11 regime version/rule replay and compound regime key
- Day 15 setup taxonomy/detector versions and deterministic setup replay
- setup candidate IDs and detector state
- case data-quality grade
- versioned analogue feature vector
- source-identity/source-link digests
- evaluation anchor metadata
- deterministic `input_digest`

It is always:

- `future_derived=false`
- `analogue_match_allowed=true`
- free of outcome/path/MFE/MAE/PnL/counterfactual fields

A retrospective input is also `live_decision_input_allowed=false`. A genuine PIT-observed input may be `live_decision_input_allowed=true`, but the completed case record itself is never a direct decision input because it also contains future outcomes.

## Regime replay

Retrospective cases use `aidy_gold_regime_replay_v1` while preserving `source_regime_definition_version=aidy_gold_regime_v1`.

The replay applies the same deterministic Day 11 trend and H1 ATR volatility rules. Session is computed from the case timestamp. Quote/spread and event timing remain `unknown` because the old HistData candle source cannot retrospectively manufacture evidence that was never collected.

No causal claim is made.

## Setup replay

Retrospective cases use `aidy_gold_setup_replay_v1` while preserving:

- `source_detection_version=aidy_gold_setup_detection_v1`
- `source_taxonomy_version=aidy_gold_setup_taxonomy_v1`
- `source_detector_version=aidy_gold_setup_detector_v1`
- the frozen Day 15 taxonomy digest

The exact Day 15 setup definitions are evaluated only against the closed-candle retrospective feature state and replayed regime state.

The detector still returns `single`, `multiple`, `none` or `indeterminate`. It still makes no trading decision and no trade recommendation.

If exactly one candidate is present and H1 ATR/reference price are available, Day 16 may derive the same `aidy_atr_1r2r_normalized_geometry_v1` research geometry used by Day 15. It remains a standardized evaluation ruler, not a strategy or recommendation.

## Data quality

`aidy_historical_case_quality_v1` grades whether a case is suitable for later retrieval.

For retrospective history the grade primarily measures price-structure completeness. Quote, event and cross-market evidence are explicitly marked `unavailable_by_retrospective_provenance`; they are not silently treated as known or false.

Grades are `strong`, `moderate`, `limited` and `insufficient`. `insufficient` cases are retained as evidence but are marked `retrieval_eligible=false`.

PIT-observed cases grade the actual Day 10 data-quality state, including core Gold timeframes, quote freshness, macro evidence and cross-market gaps.

## Future evaluation boundary

`future_evaluation` is physically separate from `input_boundary` and is always:

- `evaluation_only=true`
- `future_derived=true`
- `pit_eligible=false`
- `decision_input_allowed=false`
- `analogue_match_allowed=false`

It may contain:

1. Day 12 `aidy_move_bundle_v1`
2. Day 13 `aidy_trade_outcome_bundle_v1` when a deterministic normalized trade geometry exists
3. Day 14 `aidy_no_trade_counterfactual_v1` only for a genuinely `pit_observed` case

A retrospective replay can never attach a Day 14 counterfactual and claim a historical missed opportunity. Day 14 requires contemporaneous setup evidence that was genuinely known at the decision timestamp.

## Day 17 analogue projection

`analogue_input_view(case)` validates the full case digest, validates the input digest, then returns only versioned input-side fields.

The projection contains no future outcome object, no path class, no MFE/MAE, no target/stop state and no case digest derived from outcomes. Its identity is based on the input-side case ID/input digest.

A key Day 16 acceptance test constructs two cases with identical historical input but different future prices. The future case digests differ while the analogue input views remain exactly identical.

## Case identity

`case_id` is deterministic from:

- case version
- symbol
- case as-of timestamp
- provenance class
- input digest

Therefore future outcomes do not change the identity of the historical situation.

`case_digest` covers the completed record including future evaluation. If future evaluation changes, the case digest changes while the case ID remains tied to the same input situation.

## BigQuery contract

Canonical table: `research_gold_cases`.

Partition: `as_of_utc`.

Cluster fields:

- `symbol`
- `provenance_class`
- `data_quality_grade`
- `detector_state`

The table stores scalar retrieval/version fields plus two separate JSON columns:

- `input_boundary`
- `future_evaluation`

Day 16 materializes a bounded real retrospective sample with insert-only deterministic reconciliation by `case_id`. If an existing case ID ever has a different deterministic case digest under the same frozen versions/source data, the probe fails rather than silently updating history.

## What Day 16 does not claim

Day 16 does not claim:

- profitability
- predictive power
- setup quality
- causal relationships
- historical live observation where only retrospective data exists
- that missing macro/cross-market/quote evidence was known
- that Day 14 missed-opportunity classifications exist for retrospective cases

Day 16 creates trustworthy structured memories. Day 17 is responsible for retrieving genuinely similar memories. Day 18 is responsible for deciding whether the retrieved sample constitutes meaningful evidence.
