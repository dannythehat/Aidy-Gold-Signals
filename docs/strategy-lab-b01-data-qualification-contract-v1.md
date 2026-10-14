# B01 Day 04 — Frozen gold historical-data qualification contract v1
Date: 2026-10-14 | Research-only / isolated; NOT a declaration that all gold candles are qualified.

## Day 04 deliverables
- Source identity, clock, source hashes, timeframe and quote price-basis are explicit and required.
- Native XAUUSD M1 OHLC bars require UTC minute-aligned aware timestamps, finite positive prices, correct high/low containment, strictly increasing unique time and no implicit candle creation.
- Every inter-bar gap is labelled UNCLASSIFIED until a verified market-hours calendar with holidays, maintenance sessions and broker/source DST rules exists. Weekend guesses must never silently mark an outage as legitimate.
- Closed higher-timeframe candle information is forbidden to a strategy before that candle's ending timestamp; source-aligned aggregations need a qualified clock and completeness test.
- Fingerprinting freezes input contract and bar inputs for reproducibility.
- Historical backfill is retrospective with `pit_eligible=false`: use historical prices for testing, never assert that AIDY observed them at the time.

## Caveats carried to B01 Days 05–07
- This module validates supplied bars; the 709,543 real BigQuery rows were previously checked for uniqueness and nulls only. This is **NOT** a full dataset-quality result or measured classification of 598 historical gaps.
- Actual vendor sessions including short closures, DST, special holidays and adjusted broker sessions need their own source-grounded calendar fixtures.
- HistData's fixed EST clock is **not** Vantage's server clock. No broker session equivalence is claimed.
- No true ask-price inference from bid bars. No synthetic bid/ask estimates masquerading as observed prices.
- High-timeframe source-clock grouping, half-open interval membership and incomplete-bucket exclusions require tested implementation before higher-timeframe strategy testing.
- Source licensing for commercial reporting not yet approved.

## Acceptance (Day04 scope)
1. Stable frozen contract with exact fail-closed semantics.
2. Unit tests for valid bars, gaps, duplicates, timestamp handling, OHLC validity, nonfinite prices, provenance and time availability.
3. No production worker, brokerage, GoldThinker or other existing AIDY module modified.
4. CI verification and commit/artefact evidence recorded before calling Day04 PASSED.

## Next
Day 05: run quality audit on complete historical M1 partitions, measure all gaps and actual OHLC invalid values using bounded read-only BigQuery; preserve partition provenance and input hashes.
