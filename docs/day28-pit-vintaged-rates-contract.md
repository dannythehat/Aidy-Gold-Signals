# Day 28 — PIT-safe vintaged rates, inflation and revision intelligence

Frozen before any Day-28 real-data measurement.

Base SHA: `794ff67b52944f9a27e805c3b55beb363c199087`

## Purpose

Build a point-in-time rates/macro state that preserves what was actually knowable at T. The rates complex is a decomposition, not a stack of independent confirmations. Real-yield direction remains descriptive/provisional until J12.

## Official source family

Primary historical distribution: Federal Reserve Bank of St. Louis FRED/ALFRED.

Key-free ALFRED vintage endpoint:
`https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=<SERIES>&vintage_date=<YYYY-MM-DD>&cosd=<OBS_START>&coed=<OBS_END>`

Selected series:
- `DGS2` — 2-Year Treasury constant maturity, nominal.
- `DGS10` — 10-Year Treasury constant maturity, nominal.
- `DFII10` — 10-Year Treasury inflation-indexed constant maturity, real.
- `T10YIE` — official 10-Year breakeven inflation series, validation/reference only.
- `CPIAUCSL` — CPI all urban consumers, seasonally adjusted; revision-aware macro inflation series.

No paid market/news API is introduced. No FRED API key is required for the frozen Day-28 path.

## Timestamp semantics

ALFRED `vintage_date` is day-precision information, not an exact intraday release timestamp.

For every captured version AIDY stores:
- `observation_date`
- `publication_date` = first captured ALFRED vintage date on which that version is visible
- `vintage_date`
- `publication_time_precision = date_only`
- `pit_available_after_utc` = **00:00 UTC on the calendar day after `vintage_date`**

The next-day availability rule is deliberately conservative. AIDY never invents an exact release time from a date-only vintage. A same-day value therefore remains unavailable to intraday T unless a separate exact-timestamp source is later added.

`pit_reconstructable=true` only when the record has the required source identity, observation date, vintage/publication date and conservative availability boundary.

If an observation already exists in the first captured vintage, its true first-print date predates the frozen capture window and must be labelled `first_print_state=pre_window_unknown`; it must never be falsely called first print.

## Frozen historical acceptance window

Vintage dates: every calendar day from **2024-12-01 through 2025-01-08**, inclusive.

Observation window: **2024-10-01 through 2025-01-08**.

This window is frozen before Day-28 measurement and covers the existing Jan-6/7-2025 canonical historical cases while also containing the first publication of the CPI observation used by those cases.

## Version / revision rules

For each `(series_id, observation_date)`:
1. Walk captured vintages in chronological order.
2. First visible value after the capture-window start is `revision_index=0` only when it was absent in the immediately preceding captured vintage; otherwise its first-print state is unknown/pre-window.
3. A changed value creates a new immutable version with incremented `revision_index` and `revision_type=revision`.
4. Unchanged values across later vintages do not create duplicate versions.
5. Missing marker `.` stays missing; no fill/interpolation.
6. Later vintages can never enter an earlier as-of reconstruction.

## PIT reconstruction

For a requested T, a series version is eligible only when:
- `pit_reconstructable=true`
- `pit_available_after_utc <= T`
- `observation_date <= DATE(T)`

Select the latest eligible observation date, then the latest eligible version for that observation.

Missing evidence stays `unknown`.

## Deterministic rates decomposition

AIDY derives, rather than independently counts:
- `breakeven_10y = DGS10 - DFII10`
- `slope_2s10s = DGS10 - DGS2`

A derived value is known only when its required source legs are known **for the same observation date**. No stale-leg mixing.

`T10YIE` is retained as an official validation/reference series. It may be compared with the mechanically derived breakeven, but it contributes **zero additional independent-confirmation count**.

Model-facing family:
- `evidence_family = us_rates_decomposition`
- `independent_confirmation_units = 1`
- `components_not_independent = true`
- nominal, real, breakeven and curve shape are explanatory components of one rates state.

## Real-yield policy

`DFII10` is context/regime evidence only.

Day 28 must emit:
- `real_yield_role = context_regime_only`
- `directional_influence = provisional_unvalidated_j12`
- no bullish/bearish Gold rule based solely on the sign or change of real yield.

J12 on Day 44 owns the empirical regime-dependence test and may demote directional use after a null result.

## Inflation / revision intelligence

`CPIAUCSL` is reconstructed from vintages. The model-facing record may expose:
- latest PIT-known CPI level
- observation/publication/vintage metadata
- first-print state
- revision index/type
- prior version value and revision delta when genuinely observed in the captured vintage history

No revised modern CPI value may substitute for the value known at historical T.

## Context integration

Day 28 introduces a new context wrapper on top of accepted Day-26/27 context. It may add one `rates_macro_context` block only when its digest verifies and its as-of T matches the parent context.

The block must explicitly carry the one-family/non-independent decomposition labels above. It must not alter existing Gold, macro-event, price-structure, retrieval, evidence-grade, risk or safety gates.

## Acceptance

Day 28 passes only if:
- exact Day-27 base remains unchanged outside Day-28 files;
- source snapshots are archived/fingerprinted with source URL + SHA256;
- every emitted version carries observation/publication/vintage timing and `pit_reconstructable`;
- future vintage values are invisible at earlier T;
- same-day date-only vintages remain unavailable until the conservative next-day boundary;
- missing series/legs remain unknown;
- CPI revisions are append-only and first-print state is never invented;
- breakeven and 2s10s are deterministic and require same-date legs;
- official `T10YIE` is reference-only and never increases confirmation count;
- model-facing rates evidence reports exactly one rates-decomposition family;
- real-yield directional influence remains provisional/unvalidated;
- deterministic replay and reversed input order produce identical semantic output;
- no accepted prior trading/evidence/safety gate is weakened;
- no predictive edge or profitability claim is made.
