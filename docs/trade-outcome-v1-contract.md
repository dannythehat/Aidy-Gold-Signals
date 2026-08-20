# AIDY Day 13 trade-outcome contract

Decision date: 2026-08-20  
Version: `aidy_trade_outcome_v1`

## Purpose

Day 13 converts retrospective XAUUSD future paths into deterministic trade-specific evaluation facts for a proposed direction, entry, stop loss and one to three targets.

It answers questions such as:

- how far price moved favourably (MFE) and adversely (MAE);
- when the maximum favourable/adverse excursion occurred;
- whether and when each target or stop level was first touched;
- whether target evidence appeared before stop evidence, stop before target, or both first appeared in the same M1 bar;
- how the terminal close compared with entry;
- what Move Detective path class occurred over the same horizon.

It does **not** simulate broker execution, infer fills, calculate realized P&L, claim causality or decide whether the trade should have been taken.

## Hard future-information boundary

Every Day 13 outcome is:

- `evaluation_only = true`
- `future_derived = true`
- `pit_eligible = false`
- `decision_input_allowed = false`
- `realized_pnl_included = false`

`available_after_utc` equals the end of the evaluated horizon. A future-derived outcome cannot be treated as knowable at the anchor timestamp.

The Day 13 storage contract is `research_trade_outcomes`. It is separate from live/PIT tables and deliberately has no `first_observed_at` field.

`RESEARCH_TRADE_OUTCOMES` is a schema contract in code. Day 13 does not claim that a new BigQuery table has been provisioned unless a later explicit warehouse migration creates it.

## Accepted source evidence

Day 13 accepts only Day 5-style retrospective M1 research candles:

- symbol `XAUUSD`;
- timeframe `M1`;
- `provenance_class = retrospective_history`;
- `pit_eligible = false`;
- one explicitly selected research revision per timestamp;
- valid OHLC geometry;
- timezone-aware timestamps;
- `research_identity` provenance.

No interpolation or synthetic missing minutes are allowed. If a requested horizon is incomplete, the whole outcome fails closed to `coverage_state=incomplete`, `outcome_state=unknown`; partial level-hit or MFE/MAE claims are not emitted.

## Trade geometry

Supported directions are `long` and `short`.

Long:

- stop must be below entry;
- targets must be above entry;
- targets must be strictly increasing.

Short:

- stop must be above entry;
- targets must be below entry;
- targets must be strictly decreasing.

One to three unique targets are accepted. The normalized trade specification receives a deterministic digest.

## Excursion metrics

For a complete horizon, Day 13 records:

- MFE price distance;
- MAE price distance;
- MFE and MAE in basis points relative to entry;
- MFE and MAE in R relative to the entry-to-stop risk distance;
- time to MFE and MAE;
- terminal close;
- terminal favourable delta, bps and R, where positive means favourable to the supplied direction and negative means adverse.

These are path statistics, not realized P&L.

## Stop and target evidence

Each stop/target receives:

- hit/not-hit evidence;
- first hit minute;
- time to level;
- first-hit UTC timestamp.

First-hit evidence is grouped by M1 bar. If two or more previously unhit levels first appear in the same bar, `intrabar_order_state=ambiguous` and the levels remain grouped. The engine does not invent an order within that candle.

The stop-versus-first-target relation is one of:

- `neither`
- `target_only`
- `stop_only`
- `target_before_stop`
- `stop_before_any_target`
- `same_bar_order_unknown`

A target is counted as strictly before stop only when its first-hit minute is earlier than the stop first-hit minute. A target first seen in the same bar as stop is not credited as preceding stop.

## Path behaviour

For complete horizons, Day 13 reuses the accepted Day 12 Move Detective output at the same anchor, entry price and horizon. It carries the Day 12 label version/digest, path class and path statistics as descriptive path behaviour.

This does not turn a path class into a causal explanation or strategy verdict.

## Determinism and integrity

The same normalized trade specification and same research evidence must produce the same outcome and digest regardless of input row order.

Each horizon outcome and multi-horizon bundle is digest-bearing. Tampering invalidates storage/distribution acceptance.

## Historical acceptance probe

The Day 13 acceptance workflow uses a bounded, read-only sample from the already accepted `research_candles` BigQuery history. It evaluates a symmetric hypothetical research template in both directions at hourly anchors:

- risk distance: 25 bps from entry;
- target 1: 1R;
- target 2: 2R;
- horizon: 240 minutes.

This template exists only to exercise and summarize the generic outcome engine against real historical Gold paths. It is **not** a strategy, recommendation, backtest claim or profitability result.

The probe reports coverage, outcome-state counts, ambiguity counts and aggregate MFE/MAE R for complete outcomes. It writes no broker state and no realized P&L.

## Day 13 acceptance

Day 13 passes only if:

1. long/short geometry is validated and fail-closed;
2. MFE/MAE and terminal metrics are deterministic;
3. target/stop first-hit ordering works across distinct bars;
4. same-bar stop/target ordering remains explicitly unknown;
5. same-bar multi-target first hits remain intrabar-ambiguous;
6. incomplete horizons make no partial outcome claims;
7. input reordering does not change outputs/digests;
8. retrospective/PIT separation remains structural;
9. Day 13 bundles are rejected if supplied to Day 10 decision-time signal state;
10. tampered outcome digests are rejected;
11. the bounded real historical probe produces complete evaluation outcomes without broker data;
12. the full existing AIDY regression suite remains green.
