# Day 31 — GVZ and Gold volatility-state intelligence contract

Decision date: 2026-08-23  
Status at code review: implementation and warehouse acceptance candidate

## Scope and source boundary

Day 31 adds a free official Cboe GVZ channel and a small, preregistered volatility-state
foundation. GVZ is the Cboe estimate of expected 30-day volatility in SPDR Gold Shares ETF
(`GLD`) returns. It is a forward-looking options-market proxy, not direct XAUUSD or COMEX Gold
implied volatility.

The only new live input is Cboe's public `GVZ_History.csv` endpoint. The Cboe GVZ dashboard and
official volatility-index methodology notice establish the index meaning and calculation lineage.
Cboe DataShop, CME CVOL and any paid options feed remain outside Day 31. CVOL stays deferred until
GVZ demonstrates information value and the owner explicitly approves procurement.

## Immutable GVZ observations

`aidy_cboe_gvz_observation_v1` preserves:

- observation date and the official daily GVZ value in annualised percent;
- the explicit 30-calendar-day horizon and GLD underlying proxy;
- requested and final official URLs, full CSV SHA-256 and HTTP Last-Modified when supplied;
- AIDY `first_observed_at`, conservative PIT boundary and immutable record digest;
- explicit no-auth/no-paid-source state.

An observation date is not treated as a historical AIDY publication timestamp. Cboe's current
history file does not provide a historical per-row release timestamp. Therefore no row may appear in
a counterfactual PIT query before the snapshot's `first_observed_at`. This is conservative by design.

## Realised-volatility term structure

XAUUSD realised volatility uses close-to-close log returns at fixed 5, 10 and 21 trading-day
horizons. Each value is annualised as the root mean square return multiplied by the square root of
252, then expressed as a percentage. Missing history remains unknown.

The IV-minus-RV field compares GVZ's 30-calendar-day GLD proxy with 21-trading-day XAUUSD realised
volatility. It always carries both the horizon mismatch and cross-instrument proxy warning. The
spread is descriptive and makes no mispricing, direction or trade claim.

## Jump, continuous variation and vol-of-vol

For each sufficiently covered UTC day, one-minute XAUUSD log returns produce realised variation.
Continuous variation is the lesser of realised variation and bipower variation. Jump variation is
the non-negative residual; jump share is jump variation divided by realised variation. Days with
fewer than 300 qualifying consecutive one-minute returns are excluded rather than extrapolated.

Vol-of-vol is the 21-day sample standard deviation of annualised daily realised volatility. Missing
days or incomplete windows remain unknown. These fields are deterministic research descriptors, not
additional cosmetic indicators.

## Provenance separation

PIT mode rejects retrospective candles. Retrospective HistData calculations are always marked
`evaluation_only=true`, `decision_input_allowed=false`, `pit_reconstructable=false` and
`retrospective_history_included=true`. They may support a frozen Day 43 experiment but can never enter
a live context packet.

`aidy_market_context_v7_volatility_state` accepts only a verified decision-eligible PIT volatility
state sharing the exact context timestamp. It covers the complete state with the deterministic
context hash. A valid packet may contain known GVZ and unknown realised/jump evidence.

## J7/J8 boundary

`aidy_j7_j8_volatility_foundation_v1` freezes the inputs and null hypotheses only:

- J7: GVZ state adds no outcome-dispersion information beyond frozen realised-volatility state.
- J8: jump-dominant and continuous-dominant states do not differ in later outcome dispersion after
  frozen controls.

Day 31 does not run either formal test. Day 43 owns the chronological, episode-independent comparison.
Null or insufficient results are accepted. Evaluation-set threshold tuning is forbidden.

## Acceptance

Day 31 must:

1. pass changed-file Ruff, focused tests and the full regression suite;
2. capture and validate the official public Cboe GVZ history without authentication;
3. prove unknown-before-first-observation and immutable-digest behaviour;
4. compute deterministic 5/10/21-day RV, jump/continuous variation and 21-day vol-of-vol;
5. keep the current state null-aware when PIT XAUUSD candles are unavailable;
6. compute a bounded retrospective research state without making it decision-eligible;
7. reconcile GVZ, volatility-state, J7/J8 foundation and summary evidence in BigQuery;
8. show no paid source, CVOL commitment, predictive edge, trading gate, prior-module mutation or
   Super Signals dependency.
