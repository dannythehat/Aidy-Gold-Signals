# Day 53 — Twelve Data Basic entitlement probe

This probe exists to settle one load-bearing question before any Twelve Data market-data adapter or Day 53 freeze break is allowed: does a real free Basic key have access to XAU/USD 1-minute OHLC?

## Hard gate

The probe passes only when both conditions are true:

1. `symbol_search?symbol=XAU/USD&show_plan=true` returns at least one exact `XAU/USD` match whose individual `access.plan` is `Basic`.
2. A real `time_series` request for `XAU/USD`, `interval=1min` succeeds on that same key and returns complete, valid, non-degenerate OHLC bars.

A marketing-page claim is not sufficient. Discovery without a successful time-series response is not sufficient. A successful time-series response with discovery reporting a higher plan is treated as inconsistent and does not pass this gate.

## Secret handling

The key is read only from the GitHub Actions secret `AIDY_TWELVE_DATA_API_KEY` and sent using Twelve Data's documented `Authorization: apikey ...` HTTP header. It is never accepted as a command-line argument, placed in a URL, written to the probe artifact, or printed by AIDY.

## Sequencing

This probe changes no runtime code, D1 state, cohort state, prompt, risk rule, trading rule, Telegram behavior, or execution boundary.

Order after a passing live probe:

1. Build the Twelve Data OHLC adapter and explicit timeframe completeness/session rules.
2. Prove historical backfill and live continuation without gaps or provenance ambiguity.
3. Run affected acceptance gates and remote smoke tests.
4. Only then close the current defective Day 53 cohort under `material_safety_or_data_integrity_defect` and create a replacement cohort bound to the new exact manifest.

Until the live probe passes, the current Day 53 system remains fail-closed and the adapter/freeze-break work is blocked.
