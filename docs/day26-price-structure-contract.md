# Day 26 contract — free price structure and feed health

Status: **frozen before Day 26 warehouse acceptance**

Base commit: `262bf436dcd948d0dabe554f93d64edb82726121`

## Purpose

Day 26 extends AIDY's deterministic Gold context using only observations AIDY already owns. It does not add a new vendor, predictive model, technical-indicator family, setup, risk rule or trade gate. The accepted Day 0–25 modules remain unchanged.

The output is descriptive market structure and feed telemetry. Nothing in this contract is asserted to be alpha merely because it is measured.

## Point-in-time rule

A candle is eligible for Day 26 structure only when its entire nominal interval has completed by T:

`open_time_utc + timeframe_duration <= T`

Durations are fixed: M1=60s, M5=300s, M15=900s, H1=3600s, H4=14400s, D1=86400s.

The existing Day-7 PIT provenance rules still apply first. A PIT observation whose `first_observed_at > T` is not visible. Retrospective-only rows cannot enter a PIT packet. Duplicate logical candles fail closed.

A forming candle never contributes to a Day-26 level. Missing history stays `unknown`; it is never imputed from future data or from a different source.

## Prior-period references

Prior-period references use completed D1 observations only.

- `prior_day`: the latest completed trading-day D1 observation strictly before the current UTC date.
- `prior_week`: all completed D1 observations belonging to the latest ISO week strictly before the current ISO week.
- `prior_month`: all completed D1 observations belonging to the latest calendar month strictly before the current calendar month.

Each reference reports high, low and close, observation count and source identities. A period with no eligible observations is `unknown`.

## Overnight range

`asia_overnight_range` uses the accepted Day-25 Asia liquidity window: 09:00–18:00 `Asia/Tokyo` for the relevant Tokyo local date.

The range is emitted only after the full window has elapsed. Before the end it is `not_started` or `forming` and high/low remain null. Missing M1 coverage after the window is `incomplete`, not silently treated as a valid range.

## Opening ranges

Opening ranges use the accepted Day-25 broad liquidity-window opens, not a newly invented market-open definition:

- Asia: 09:00 `Asia/Tokyo`
- London: 08:00 `Europe/London`
- New York: 08:00 `America/New_York`

For each session, 15m, 30m and 60m opening ranges are defined. A range becomes usable only after the complete interval has elapsed and every expected completed M1 bar is present. Before completion, its state is `not_started` or `forming` and its high/low are null. After completion with missing bars, state is `incomplete` and high/low remain null.

DST is resolved through IANA time zones.

## Session extremes

Asia, London and New York session high/low are reported from completed M1 bars observed so far inside each accepted Day-25 liquidity window. They may be `observed_so_far`, `complete`, `partial`, `not_started` or `unknown`. The payload reports expected and observed bar counts so feed gaps cannot masquerade as a complete session range.

No future session bar is ever used.

## UTC-day gap state

The Day-26 gap is deliberately mechanical and narrowly named: `utc_day_gap`.

- reference close: `prior_day.close`
- current open: the first completed M1 candle open on the current UTC date
- gap bps: `(current_open - prior_close) / prior_close * 10000`
- direction: `up`, `down`, or `flat`

A non-flat gap is `filled` once an eligible completed M1 range touches/crosses the prior close; otherwise it is `unfilled` using observations available so far. If either boundary is missing, state is `unknown`.

This is not claimed to be a venue-open gap or predictive edge.

## Trend persistence and acceleration

Day 26 adds no moving average or oscillator. It uses the last five completed M15 closes (four close-to-close intervals):

- net direction across the four intervals
- `persistence_ratio`: fraction of the four interval returns whose sign agrees with the net direction
- first-half two-interval return in bps
- second-half two-interval return in bps
- `absolute_acceleration_bps`: absolute second-half move minus absolute first-half move

With fewer than five completed M15 bars, state is `insufficient`.

## Prior-day breakout / failed-break state

Breakout context is referenced only to the completed prior-day high and low.

For current-UTC-day completed M1 observations:

- upside penetration exists when any high is above prior-day high
- downside penetration exists when any low is below prior-day low
- penetration magnitude is reported in bps
- `reverted_inside` is true when penetration occurred but the latest completed close is back inside the prior-day boundary

The combined state is mechanical (`none`, `upside_hold`, `upside_failed`, `downside_hold`, `downside_failed`, or `two_sided`). It does not claim trader intent.

## Wick footprint

The latest completed M15 candle reports body, upper-wick, lower-wick and total-range bps plus close location. No candlestick name or psychological interpretation is assigned.

## Swing-extreme penetration with reversion

The only allowed name is `swing_extreme_penetration_with_reversion`.

A confirmed M15 swing uses wing=2 and therefore requires two completed bars on both sides. Penetration is evaluated only on completed bars after the confirmation bars:

- high-side event: a later high exceeds the confirmed swing high and latest completed close is at/below that swing high
- low-side event: a later low falls below the confirmed swing low and latest completed close is at/above that swing low

The payload reports the swing identity, maximum penetration bps and reversion boolean. It does not infer orders, stops, liquidity-provider intent or institutional intent.

## Feed-health telemetry

Feed health is descriptive telemetry, not a threshold-based trading gate on Day 26.

Per timeframe it reports, where observable:

- latest completed bar end
- age of the latest completed observation at T
- expected interval seconds
- count of inter-bar gaps larger than the expected interval in the recent completed sample
- maximum inter-bar gap seconds
- recent sample size
- PIT-only `first_observed_delay_from_open_seconds` distribution when `first_observed_at` exists

For retrospective history, arrival-delay telemetry is `unknown`; it is never fabricated as zero or healthy.

Quote telemetry preserves the existing snapshot state and quote age where a PIT snapshot exists. Without a PIT snapshot, quote feed-health state is `unknown`.

Day 27 owns historical bid/ask spread/liquidity inference and time-of-day × weekday normalization. Day 26 must not pre-empt that work.

## Determinism and replay

The packet has two hashes:

- full packet digest, including provenance and feed telemetry
- `structure_semantic_digest`, computed from value semantics with source identities removed

Equivalent OHLC observations at the same T must reproduce the same structure semantic digest in PIT and retrospective modes even though provenance and observable arrival telemetry differ.

Input ordering must not change either digest for the same logical observations.

## Explicitly prohibited additions

Day 26 does not introduce RSI, MACD, Stochastics, Bollinger Bands, Ichimoku, new moving-average families, calendar seasonality, standalone round-number levels, sentiment, broker positioning, or intent-laden market-microstructure labels.

No Day-24/25 analogue threshold, embargo, episode rule, evidence grade or safety gate may be changed by this work.

## Acceptance

Day 26 passes only if:

- completed-bar filtering is explicit and tested at exact interval boundaries;
- future/unobserved PIT rows cannot alter a packet at T;
- prior day/week/month HLC is deterministic and missing periods remain unknown;
- opening ranges never expose levels while forming or when coverage is incomplete;
- session extremes use only elapsed completed bars;
- gap, trend, breakout, wick and swing-reversion definitions match this frozen contract;
- missing feed telemetry remains unknown;
- equivalent PIT/retrospective OHLC produces the same structure semantic digest;
- reversed input ordering is deterministic;
- the accepted Day 0–25 modules remain untouched;
- focused and full regression tests pass;
- real BigQuery retrospective-case and PIT probes pass and are preserved as immutable evidence;
- no prohibited indicator or intent vocabulary is added to the Day-26 runtime source.