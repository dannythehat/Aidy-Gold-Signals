# AIDY Day 3 continuity-auditor contract

Decision date: 2026-08-17
Broker-free update: 2026-08-19

## Purpose

Rows in D1 do not prove that AIDY observed Gold continuously. Day 3 makes evidence quality explicit and machine-testable before feature engineering, historical memory or OpenAI reasoning can trust the stream.

## Active Day 3 source contract

The active forward source is the public keyless Gold-API XAU/USD reference-price endpoint.

For a fixed UTC window the active Day 3 auditor reads:

- D1 market snapshots and their capture status, quote age and availability map;
- the recorded source identity (`gold_api`);
- D1 archive-outbox status, retry count and stable R2 key;
- R2 object existence for a bounded reconciliation sample.

Broker positions, orders, account balances, MT5, MetaAPI and Super Signals state are outside the contract.

## Calculations

- expected versus observed one-minute scheduler cycles;
- missing-cycle ratio and longest missing run;
- complete, partial and unavailable snapshot counts;
- quote-age p50, p95, maximum and stale count;
- stable source-error-code counts from point-in-time availability maps;
- archive population/sample size, pending rows, retry attempts, failed rows, missing R2 objects and unverified rows.

## Genuine-candle rule

Gold-API supplies an indicative reference price, not the genuine OHLC contract needed for historical candle research. AIDY therefore does **not** manufacture M1/M5/H1 bars from one sample per minute.

The earlier general candle-continuity auditor remains useful when a genuine OHLC/tick research source is added. Candle gaps, revisions and timeframe continuity will then be evaluated against that source under its own provenance contract.

## Fail-closed Day 3 acceptance

The active broker-free report cannot pass when:

- capture is disabled;
- the source is not `gold_api` or provenance is not `public_independent`;
- an expected one-minute scheduler observation is missing;
- a complete snapshot has no quote age or any quote exceeds the stale limit;
- a partial/unavailable snapshot or source error exists;
- the archive outbox has backlog, retries/errors or a sampled R2 mismatch.

The strict zero-tolerance defaults are intentional for the Day 3 acceptance window. Later operational alert thresholds may be versioned, but missing evidence must never be silently converted into a healthy result.

## Test Worker endpoint

`GET /day3/continuity?minutes=10&archive_limit=40`

- Test environment only; production returns `404`.
- `minutes` must be between 5 and 1,440.
- `archive_limit` must be between 1 and 40.
- Healthy report: HTTP `200`, `ok=true`.
- Failed gate: HTTP `503`, `ok=false`, exact failure reasons retained.
- Invalid request/configuration: HTTP `400`.

Only aggregate evidence-health metrics are returned. No secret or raw market payload is included.
