# Day 44 — Policy-path and cross-asset J11–J14 contract

Decision date: 2026-09-01  
Authoritative base: `5d3c21077c918db0df789898fec3dacb762fb6b3`

## Purpose

Day 44 expands the shadow research sensor stack by economic mechanism, not by correlation mining. It adds explicit source contracts for policy-path futures, an intraday Treasury-futures proxy, the precious-metals complex, USD composition and risk-state observations, then preregisters J11–J14 under the accepted research-integrity framework.

This day does **not** make any cross-asset feature mandatory, create a trading gate, claim predictive edge, activate paid live market data or create formal forward evidence.

## Source contracts

Every Day 44 series has a machine-readable contract containing:

- source/provider and source authority;
- source locator/dataset identity;
- timestamp semantics;
- unit;
- provenance policy;
- mandatory PIT attestation;
- mandatory `first_observed_at`;
- mandatory quality and staleness state;
- `mandatory_for_trade=false`;
- `independent_vote=false`.

The frozen series are:

- `ZQ_FUT` — 30-Day Federal Funds futures, Databento/CME Group shadow research;
- `SR3_FUT` — Three-Month SOFR futures, Databento/CME Group shadow research;
- `ZN_FUT` — 10-Year Treasury Note futures, Databento/CME Group shadow research;
- `GC_FUT` — accepted Day 41/42 COMEX Gold baseline;
- `SI_FUT` — COMEX Silver futures, Databento/CME Group shadow research;
- `EURUSD_SPOT` — Federal Reserve H10 `DEXUSEU`;
- `USDJPY_SPOT` — Federal Reserve H10 `DEXJPUS`;
- `VIX_INDEX` — official Cboe VIX history/capture;
- `ES_FUT` — E-mini S&P 500 futures, Databento/CME Group shadow research;
- `DTWEXBGS` — accepted Federal Reserve H10 broad-dollar baseline;
- `DFII10` — accepted Day 28 ALFRED 10-year real-yield series.

Retrospective exchange history may be PIT-reconstructable for research but remains `evaluation_only=true` and cannot become a live decision input merely because it has an exchange timestamp.

## Mechanism separation

### Policy path

`ZQ_FUT` and `SR3_FUT` are one policy-path family. Their quoted prices are mechanically converted to contract-implied rates using `100 - price`, with contract-specific interpretation preserved. They count as **one** confirmation family, not two votes.

### Existing U.S. rates decomposition

Day 28 remains authoritative for DGS2, DGS10, DFII10, breakeven and 2s10s slope. Related rates remain one labelled decomposition with `independent_confirmation_units=1`.

### Intraday Treasury proxy

`ZN_FUT` is an intraday Treasury-futures price proxy. It is not silently converted into a cash yield and does not replace the Day 28 daily rates decomposition. J13 tests incremental information explicitly.

### Precious complex

Silver and the mechanically derived gold/silver ratio are shadow context only. Gold and silver timestamps must be aligned within the frozen 15-minute tolerance before a ratio is considered known. J11 is required before any incremental use can be considered.

### USD composition

EURUSD and USDJPY are tested as composition information beyond the accepted broad-dollar baseline. The broad-dollar index is a baseline, not another independent vote. J14 is the only registered test for this Day 44 question.

### Risk state

VIX and ES are risk-state observations. They are not treated as Gold proxies and cannot become mandatory from Day 44.

## J11–J14 preregistration

All four experiments require:

- Day 32 trial registration;
- Day 37 chronological split semantics;
- purge and embargo;
- episode-independent effective sample size;
- frozen predictors and effect field;
- no holdout tuning;
- no unregistered predictor search;
- no correlation mining;
- retention of null and insufficient results.

The frozen experiments are:

- **J11 — gold/silver mechanism:** test silver and gold/silver incremental information beyond Gold.
- **J12 — real-yield regime dependence:** test whether the real-yield directional relationship varies materially across preregistered regimes. A sufficient null may demote provisional directional influence. Insufficient evidence cannot demote or promote it.
- **J13 — intraday ZN vs daily yields:** test whether ZN adds timely information beyond the accepted daily rates decomposition.
- **J14 — USD composition beyond broad dollar:** test whether EURUSD/USDJPY composition adds information beyond `DTWEXBGS`.

The minimum Day 44 descriptive research threshold is 50 independent episodes. J12 additionally requires at least two preregistered regimes with at least 20 independent episodes each. These thresholds are fixed before any Day 44 result and are not a live-trading promotion threshold.

## Explicit exclusions

Crude (`CL`), copper (`HG`) and Bitcoin (`BTC`) remain prohibited as Gold proxies. Day 44 adds no calendar seasonality, psychological levels, retail positioning, sentiment, news/geopolitical labels, COT, ETF holdings or other unregistered cross-asset candidates.

## Acceptance interpretation

The acceptance harness includes deterministic architecture fixtures only to prove parsing, provenance, mechanism separation and fail-closed behavior. Fixture values are never outcome data.

If there is no accepted outcome-linked independent Day 44 cohort, J11–J14 must be recorded as `insufficient` with effective N = 0. That is a valid research result and must not be replaced with retrospective storytelling or relaxed thresholds.
