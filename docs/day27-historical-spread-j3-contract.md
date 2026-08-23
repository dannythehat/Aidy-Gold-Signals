# Day 27 contract — historical XAUUSD bid/ask and J3 spread/liquidity failure risk

Status: **frozen before real Day 27 source measurement and outcome analysis**

Base commit: `cab78a26acfbabdec6b3d2b5969eb3cf3b4831b3`

## Purpose

Day 27 adds a truthful historical bid/ask dimension to AIDY research and runs Architecture V2 experiment J3. It does not add a trading gate, predictive model, execution rule, broker-position proxy, exchange-depth claim or order-flow claim.

The experiment asks a narrow question: after controlling for normal weekday/time-of-day spread behaviour and input-side volatility, do historical setup outcomes differ across normalized spread stress terciles?

## Source choice

Day 27 uses HistData Generic ASCII tick data for XAUUSD rather than introducing a second historical vendor.

Reasons:

- HistData is already AIDY's accepted Day-5 retrospective price source.
- HistData's Generic ASCII tick specification provides timestamp, Bid and Ask for each tick.
- HistData states its free historical data is intended for strategy/backtest research.
- Day 27 ignores the supplied volume field entirely. No broker volume, true exchange volume, depth or order flow is inferred.

Source-use scope for AIDY Day 27 is internal research/backtesting with raw vendor data not redistributed. This contract does not assert a broader redistribution or commercial market-data licence. Any future use outside that scope requires a fresh source/licensing check rather than silently inheriting this acceptance.

## Frozen source period

The canonical Day-16/23/24/25 research case set contains 36 hourly XAUUSD cases from 2025-01-06 through 2025-01-07 UTC. Day 27 therefore freezes the source archive to **HistData XAUUSD Generic ASCII tick January 2025**.

No month is selected after looking at J3 outcomes.

The original ZIP and CSV payload are identified by SHA-256. Analytical rows retain both digests, source file name, source dataset and source timezone.

## Time and provenance

HistData Generic ASCII timestamps are interpreted using the source's documented fixed EST basis (`UTC-05:00`, without DST adjustment), then converted to UTC.

Every accepted tick must have:

- a parseable source timestamp;
- finite positive Bid and Ask;
- `Ask >= Bid`;
- monotonic source ordering inside the archive.

Malformed price geometry fails closed.

All Day-27 quote data is `retrospective_history` and `pit_eligible=false`. It is research evidence, not a claim that AIDY observed those quotes live in January 2025.

## Canonical quote reduction

To avoid storing millions of redundant ticks while preserving genuine bid/ask evidence, Day 27 deterministically materializes **the last genuine source tick in each UTC minute**.

Each materialized row preserves:

- UTC minute;
- exact source tick timestamp;
- raw Bid;
- raw Ask;
- derived midpoint;
- derived absolute spread;
- derived spread in basis points of midpoint;
- source archive and payload SHA-256;
- deterministic quote identity.

No synthetic interpolation is allowed. Missing minutes remain missing.

The HistData volume column is deliberately ignored and is not stored in the Day-27 analytical quote contract.

## Anchor spread state

For historical case timestamp `T`, the anchor quote is the latest canonical minute quote whose source tick timestamp is `<= T` and no more than **120 seconds** old.

If no such quote exists, anchor spread state is `unknown`.

Future ticks may never backfill a missing quote at `T`.

Spread is:

`spread = ask - bid`

`mid = (bid + ask) / 2`

`spread_bps = spread / mid * 10000`

## Frozen weekday × time-of-day baseline

The spread baseline is frozen **before future outcome analysis**.

Clock normalization:

- timezone: UTC;
- weekday: Monday=0 through Sunday=6;
- time bucket: 15-minute clock slot, 0–95;
- observations: canonical per-minute genuine bid/ask quotes from the frozen January-2025 source archive;
- minimum bucket sample: 20 minute quotes;
- baseline center: arithmetic mean spread bps;
- baseline scale: sample standard deviation spread bps.

A bucket with fewer than 20 observations or zero standard deviation is `insufficient`.

For a known anchor:

`spread_z = (anchor_spread_bps - matched_bucket_mean) / matched_bucket_std`

This is explicitly designed so ordinary New-York-vs-Asia activity is normalized rather than rediscovered and mislabeled as alpha.

The full baseline has a deterministic SHA-256 digest and `outcome_fields_used=false`.

## Frozen J3 input strata

J3 strata are built before reading `future_evaluation`.

Eligible cases require:

- known normalized spread-z;
- known input-side H1 ATR(14) bps already present in the accepted historical-case input boundary;
- deterministic normalized trade geometry already present on the input side.

Spread terciles are deterministic rank terciles of normalized `spread_z` (`low`, `mid`, `high`).

Volatility terciles are deterministic rank terciles of **input-side H1 ATR(14) bps** (`low`, `mid`, `high`).

Ties are ordered by case ID only for deterministic assignment. No outcome value participates in either ranking.

The complete case assignment manifest is frozen with a digest before J3 reads outcomes.

## J3 outcome analysis

J3 reads the accepted Day-13 trade-outcome bundle only after the baseline and strata digests are frozen.

For each available complete horizon, outcomes are reported separately for:

- 15 minutes;
- 60 minutes;
- 240 minutes.

Horizons are never pooled as independent observations.

Within each `(horizon, volatility_tercile, spread_tercile)` cell, J3 reports distributions for:

- MFE in R;
- MAE in R;
- sample n;
- p25;
- median;
- p75;
- deterministic sorted sample values.

The result also reports session mix by normalized spread tercile as a diagnostic against accidentally rediscovering ordinary session activity.

## Evidence threshold and gate rule

Pre-registered descriptive sample floor for even considering a future gate review: **minimum n=10 in every observed J3 cell**.

If that floor is not met, the experiment result is `descriptive_only_insufficient_for_gate`.

Even if the floor is met, Day 27 still does **not** create a trading gate. The strongest allowed state on Day 27 is `descriptive_sample_floor_met_gate_still_provisional`.

Any future gate requires a separate evidence decision and cannot be inferred merely from Day-27 tercile separation.

## Explicit non-claims

Day 27 never claims or fabricates:

- true exchange volume;
- market depth;
- order flow;
- broker/client positioning;
- executable liquidity;
- causal spread effect;
- profitability;
- predictive alpha;
- a trading gate.

A result that mainly rediscovers ordinary time-of-day/session activity is a failed experiment, not alpha.

## Acceptance

Day 27 passes only if all of the following hold:

- genuine historical Bid and Ask are ingested from the frozen source archive;
- source ZIP and CSV payload SHA-256 are preserved;
- source timestamps, Bid, Ask and derived spread are retained on canonical quote rows;
- Ask below Bid fails closed;
- no volume/depth/order-flow field is promoted into Day-27 evidence;
- anchor joins never use later ticks;
- missing quote periods remain unknown;
- weekday × 15-minute baseline is frozen before outcome analysis;
- spread-z uses only the matched weekday/clock bucket;
- J3 spread and volatility terciles are frozen from input-side fields before outcomes;
- J3 reports MAE/MFE distributions by spread tercile within volatility tercile, per horizon;
- session mix is reported as a confounding diagnostic;
- any Day-27 trading gate remains null/provisional;
- no predictive-edge claim is made;
- accepted Day 0–26 runtime/scientific modules are not modified;
- focused tests and full regression pass;
- real source + BigQuery acceptance evidence is preserved with exact base/head SHAs and deterministic digests.
