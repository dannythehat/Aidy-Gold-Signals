# AIDY deterministic Gold regime v1 contract

Decision date: 2026-08-20
Day 11 implementation: 2026-08-20

## Purpose

Day 11 turns the accepted Day 10 objective observation packet into a small, versioned set of descriptive Gold regime labels. The classifier exists so later AIDY research can compare like with like without asking a model to invent a vague market regime.

The regime layer is descriptive only. It is not a trade setup, recommendation, confidence score, causal explanation, future-return label or outcome label.

## Version and input boundary

- Regime definition: `aidy_gold_regime_v1`
- Source context: `aidy_market_context_v1`
- Supported symbol: `XAUUSD` only
- Regime digest: SHA-256 over canonical JSON excluding only the top-level `regime_digest`

A Day 11 classifier accepts only a valid Day 10 packet whose context hash verifies and which explicitly states:

- `objective_only=true`
- `retrospective_history_included=false`
- `broker_follower_state_included=false`

A tampered Day 10 context, retrospective packet, broker/follower-bearing packet, unsupported context version or non-Gold symbol is rejected.

## Regime labels

The canonical Day 11 output contains five descriptive labels.

### 1. Trend structure

Source features: `M15`, `H1` and `H4` `return_5_direction` from the accepted Day 7 feature engine inside the Day 10 Gold packet.

Rules:

- Fewer than two known votes -> `unknown`.
- At least two bullish votes and no bearish vote -> `bullish_trend`.
- At least two bearish votes and no bullish vote -> `bearish_trend`.
- At least two flat votes and no bullish or bearish vote -> `range`.
- Every other sufficiently observed combination -> `mixed`.

The classifier deliberately does not call conflicting directional evidence a range. `mixed` remains its own observable state.

### 2. Volatility band

Source feature: H1 `atr_14_bps`.

V1 fixed descriptive thresholds:

- `< 20 bps` -> `low`
- `>= 20 bps and < 50 bps` -> `normal`
- `>= 50 bps` -> `high`
- unavailable H1 ATR -> `unknown`

These thresholds are versioned descriptive buckets for Gold. They are not optimized on future returns and are not trading gates. Any later threshold change requires a new regime-definition version rather than silently changing historical labels.

### 3. Session

Source: Day 10 deterministic `session.computed_session_code`.

Accepted labels are the existing AIDY session codes: `asia`, `london`, `new_york`, `london_new_york_overlap`, `off_hours`, `weekend`, or `unknown` if the value is unavailable/unrecognized.

### 4. Quote/spread condition

Source: Day 10 data-quality facts only.

Labels:

- unavailable quote/freshness -> `unknown`
- stale quote -> `stale_quote`
- fresh quote + known spread -> `fresh_quote_spread_known`
- fresh quote + unavailable spread -> `fresh_quote_spread_unknown`

This label intentionally avoids words such as tight, wide, liquid or illiquid. Current Gold-API evidence does not provide bid/ask/spread, so a fresh mid with unknown spread must remain `fresh_quote_spread_unknown`.

### 5. Event timing

Source: Day 10 high-impact official macro/Fed timing context.

Labels are carried only when macro evidence itself is known:

- `inside_high_impact_window`
- `clear_current_window`
- `unknown`

The regime layer does not infer event surprise, direction, impact magnitude or causality.

## Compound regime key

The output includes one deterministic compound key in fixed label order:

`trend_structure | volatility_band | session | quote_spread_condition | event_timing`

The key is a grouping identity for later research. It is not a score and has no embedded preference for one regime over another.

## Explainability

Every packet includes `rule_evidence` that records the exact source fields and rule inputs used for each label:

- M15/H1/H4 direction votes;
- H1 ATR value and v1 volatility thresholds;
- computed session;
- quote state/freshness/spread state;
- macro evidence/timing state.

The output also preserves the source Day 10 context hash so every regime assignment can be traced back to its exact factual observation packet.

## Null and boundary semantics

Unknown evidence stays unknown. The classifier does not fill missing values, use neighbouring periods, interpolate unsupported spread, or borrow retrospective history.

Boundary values are explicit:

- `19.999999` ATR bps is `low`;
- exactly `20` is `normal`;
- `49.999999` is `normal`;
- exactly `50` is `high`.

Trend classification requires at least two known M15/H1/H4 votes. Conflicting bullish/bearish evidence is `mixed`, not a guessed trend or range.

## No hindsight contract

Day 11 output explicitly declares:

- `objective_only=true`
- `causal_claims_included=false`
- `hindsight_outcomes_included=false`

No regime label may contain profit/loss, win/loss, future-return, target-hit, stop-hit or subsequent-price information. Later outcome analysis may group results by this regime packet, but outcomes must remain in a separate downstream dataset.

## Determinism and integrity

The regime packet is canonical and digest-bearing. Identical validated Day 10 context produces an identical Day 11 regime packet and digest. A changed source context hash produces a changed regime digest even if the coarse labels happen to remain the same, preserving exact reconstruction identity.

## Distribution report

`regime_distribution()` provides deterministic counts by each descriptive label and by compound regime key. It validates every regime digest before counting and explicitly declares `outcome_statistics_included=false`.

This distribution utility exists to inspect coverage and regime prevalence. It does not calculate win rate, PnL, expectancy or any other future-outcome statistic.

## Acceptance gate

Day 11 passes only when automated tests prove:

1. trend/range/mixed assignments are deterministic and null-aware;
2. exact volatility boundaries behave as documented;
3. integrated classifications use only valid Day 10 objective context;
4. missing features remain `unknown` rather than becoming guesses;
5. unsupported spread remains explicit even when the quote is fresh;
6. identical context produces identical regime packet/digest;
7. changed context changes regime reconstruction identity;
8. tampered/retrospective/non-objective inputs are rejected;
9. distribution counts are deterministic and reject tampered regime packets;
10. output contains no hindsight outcome semantics;
11. the full existing project regression suite remains green.

## Downstream contract

Later analogue retrieval, outcome statistics and case building may condition on `aidy_gold_regime_v1`, but they must preserve the source context hash and regime digest. A later intelligence layer may reason about why a regime matters; Day 11 itself makes no causal or predictive claim.
