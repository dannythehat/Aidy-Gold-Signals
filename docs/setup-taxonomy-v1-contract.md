# Day 15 — Gold setup taxonomy and candidate detector v1

## Purpose

Day 15 gives AIDY a fixed, human-auditable vocabulary for recognizing candidate Gold structures from evidence that was knowable at the evaluation timestamp.

It does **not** decide whether AIDY should trade.

The contract is deliberately split:

1. Day 10 `aidy_market_context_v1` provides objective PIT evidence.
2. Day 11 `aidy_gold_regime_v1` describes the current regime.
3. Day 15 `aidy_gold_setup_detector_v1` recognizes candidate setup structures.
4. Day 14's setup-eligibility adapter can consume Day 15 evidence for later no-trade counterfactual evaluation.
5. Day 16 will join these PIT inputs to later outcomes in historical case records while preserving the input/outcome boundary.

## Versions

- taxonomy: `aidy_gold_setup_taxonomy_v1`
- detector: `aidy_gold_setup_detector_v1`
- detection packet: `aidy_gold_setup_detection_v1`
- distribution: `aidy_gold_setup_distribution_v1`
- normalized research geometry: `aidy_atr_1r2r_normalized_geometry_v1`
- digest: SHA-256 over canonical JSON

## Hard boundary

Day 15 accepts only:

- XAUUSD
- a valid Day 10 context packet
- `objective_only=true`
- `retrospective_history_included=false`
- `broker_follower_state_included=false`
- Day 7 feature mode `pit`
- Day 7 provenance `pit_observed`
- `pit_eligible=true`
- a valid Day 11 regime packet derived from the exact supplied Day 10 context hash
- identical context/regime `as_of_utc`

The detector recursively rejects future/outcome material including future returns, Move Detective path classes, trade outcomes, MFE/MAE, P&L, counterfactual classifications and evaluation-only future bundles.

Day 12, Day 13 and Day 14 outputs are therefore not valid detector inputs.

## Detector states

`single`
: Exactly one setup definition is fully satisfied.

`multiple`
: Two or more setup definitions are fully satisfied. Every matching setup is preserved. The detector does not choose a winner.

`none`
: Every setup definition is falsified by known evidence.

`indeterminate`
: No setup is proven, but at least one definition cannot be resolved because required PIT evidence is unknown. Unknown is never silently converted to no setup.

## Frozen v1 taxonomy — 20 variants

Thresholds are fixed descriptive v1 rules. They were **not** selected by looking at future Day 12/13/14 outcomes.

| # | Setup ID | Family | Direction | Human meaning |
|---|---|---|---|---|
| 1 | `trend_pullback_long` | trend pullback | long | bullish higher-timeframe trend with M15 retracement |
| 2 | `trend_pullback_short` | trend pullback | short | bearish higher-timeframe trend with M15 retracement |
| 3 | `trend_momentum_long` | trend momentum | long | bullish trend with M15/H1 continuation and strong close |
| 4 | `trend_momentum_short` | trend momentum | short | bearish trend with M15/H1 continuation and weak close |
| 5 | `recent_high_pressure_long` | recent extreme pressure | long | bullish pressure in upper fifth of recent M15 range |
| 6 | `recent_low_pressure_short` | recent extreme pressure | short | bearish pressure in lower fifth of recent M15 range |
| 7 | `session_high_pressure_long` | session extreme pressure | long | positive momentum in top 15% of current session |
| 8 | `session_low_pressure_short` | session extreme pressure | short | negative momentum in bottom 15% of current session |
| 9 | `lower_extreme_rejection_long` | extreme rejection | long | bullish rejection from lower recent-range extreme |
| 10 | `upper_extreme_rejection_short` | extreme rejection | short | bearish rejection from upper recent-range extreme |
| 11 | `countertrend_reversal_long` | countertrend reversal | long | bullish reversal evidence inside bearish trend |
| 12 | `countertrend_reversal_short` | countertrend reversal | short | bearish reversal evidence inside bullish trend |
| 13 | `range_low_reversion_long` | range reversion | long | bullish rejection from lower quarter of classified range |
| 14 | `range_high_reversion_short` | range reversion | short | bearish rejection from upper quarter of classified range |
| 15 | `session_low_reversion_long` | session reversion | long | positive response from lower fifth of session |
| 16 | `session_high_reversion_short` | session reversion | short | negative response from upper fifth of session |
| 17 | `low_vol_break_pressure_long` | volatility transition | long | low H1 volatility plus bullish M15 expansion pressure |
| 18 | `low_vol_break_pressure_short` | volatility transition | short | low H1 volatility plus bearish M15 expansion pressure |
| 19 | `high_vol_recovery_long` | volatility recovery | long | bullish recovery from lower third in high H1 volatility |
| 20 | `high_vol_recovery_short` | volatility recovery | short | bearish recovery from upper third in high H1 volatility |

Every setup definition contains its exact clauses in code and receives a deterministic definition digest.

## Observation vocabulary used in v1

The detector reads only existing deterministic Day 7/Day 11 observations:

- Day 11 trend structure
- Day 11 volatility band
- M1 one-bar return
- M15 one-bar return
- M15 five-bar direction
- H1 five-bar direction
- H4 five-bar direction
- M15 candle body in bps
- M15 close location inside the bar
- M15 20-bar range position
- M15 range / M15 ATR ratio
- active-session range position

No RSI, MACD, moving-average crossover or other indicator is silently invented in Day 15. New observations require a later explicit feature/taxonomy version.

## Multiple setups are information, not an error

A single market state can satisfy multiple human descriptions. For example, bullish trend momentum can occur simultaneously with recent-high pressure and session-high pressure.

Day 15 preserves all of them and emits `detector_state=multiple`.

It does not rank, score or choose between them. When adapted to Day 14, multiple candidates become `setup_state=ambiguous`, because Day 14 must not pretend one setup was the contemporaneous trade thesis when several were present.

## Unknown stays unknown

A definition is:

- `matched` only if every clause is true
- `not_matched` if any known clause is false
- `unresolved` if no clause is false but at least one required observation is unknown

If there are no matched candidates but one or more unresolved definitions, the overall state is `indeterminate`, not `none`.

## Research-normalized structural geometry

Day 15 includes an adapter to Day 14's `aidy_no_trade_setup_eligibility_v1` contract.

This adapter exists so later research can ask a consistent counterfactual question when exactly one setup was present.

For a single setup only, if a contemporaneous reference price and positive H1 ATR(14) are known, the adapter can produce:

- market entry at the observed reference price
- stop distance = 1.0 × H1 ATR(14) in bps
- target 1 = 1R
- target 2 = 2R

This geometry is versioned as `aidy_atr_1r2r_normalized_geometry_v1`.

It is **not** claimed to be optimal, profitable or the final AIDY trading rule. It is a deterministic research normalization that lets Day 13/14 compare candidate setups on the same risk scale without future tuning.

If ATR/reference price is unknown, risk remains `unknown` and no trade geometry is fabricated.

If multiple setups are present, risk/direction/trade geometry remain unresolved in the Day 14 adapter.

## Reference-price rule

For normalized geometry the detector records one contemporaneous reference price:

1. fresh quote `mid`, when available
2. otherwise latest known M1 close
3. otherwise unknown

The Day 14 adapter requires the supplied anchor price to equal the price preserved in the Day 15 detection packet. Callers cannot substitute a more convenient later price.

## Output contract

Every detection packet includes:

- taxonomy/detector/detection versions
- taxonomy digest
- PIT and no-future markers
- exact `as_of_utc`
- source context hash
- source regime digest
- detector state
- all candidate setup IDs and directions
- unresolved setup IDs
- candidate definition digests
- normalized observation snapshot + digest
- explicit research risk basis
- per-rule evaluation states
- full detection digest
- `trading_decision_made=false`
- `trade_recommendation_made=false`

## Storage contract

`RESEARCH_SETUP_DETECTIONS` defines a `research_setup_detections` analytical schema contract.

Day 15 does **not** claim a physical BigQuery table has been provisioned. Day 16 owns the canonical historical-case storage design.

The schema stores PIT setup detection evidence, not future outcomes.

## Distribution helper

`setup_detection_distribution()` may count:

- detector states
- candidate setup IDs
- candidate families
- candidate directions

It explicitly contains `outcome_statistics_included=false`.

Day 15 does not calculate setup win rates, expectancy, target rates or future returns. Those belong after the Day 16 input/outcome boundary is built.

## Acceptance invariants

Day 15 passes only if tests prove:

1. exactly 20 unique versioned setup variants exist
2. bullish and bearish single candidates are deterministic
3. multiple candidates are preserved
4. a true no-setup state is explicit
5. missing evidence produces indeterminate, not fake absence
6. bad context/regime hashes fail closed
7. regime must originate from the exact context
8. retrospective features fail closed
9. future/outcome injection fails closed
10. detection output is PIT-safe and makes no trading decision
11. single detection can adapt to Day 14 without future data
12. missing structural risk remains unknown
13. multiple detection maps conservatively to Day 14 ambiguity
14. none maps to Day 14 absence
15. detection and storage digests reject tampering
16. distributions contain prevalence only, never outcomes

## Day 16 boundary

Day 16 may use Day 15 detections as the setup component of a canonical historical case.

Day 16 must still keep the following physically/logically separate:

**decision-time inputs**
: context + regime + setup detection + data-quality evidence

**future evaluation**
: Day 12 move labels + Day 13 trade outcomes + Day 14 no-trade counterfactuals

AIDY must never rebuild Day 15 setup presence from the future path.
