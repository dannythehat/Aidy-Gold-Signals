# AIDY Day 3 continuity-auditor contract

Decision date: 2026-08-17

## Purpose

Rows in D1 do not prove that AIDY observed the market continuously. Day 3 makes
evidence quality explicit and machine-testable before feature engineering,
historical memory or OpenAI reasoning can trust the stream.

## Inputs

For a fixed UTC window the auditor reads:

- D1 market snapshots and their capture status, quote age and availability map;
- D1 market candles, exact source, timeframe, open time and revision index;
- D1 archive-outbox status, retry count and stable R2 key;
- R2 object existence for a bounded reconciliation sample.

Broker positions, orders, account balances and Super Signals state are outside
the contract.

## Calculations

- expected versus observed one-minute scheduler cycles;
- missing-cycle ratio and longest missing run;
- complete, partial and unavailable snapshot counts;
- quote-age p50, p95, maximum and stale count;
- stable source-error-code counts from the point-in-time availability maps;
- per-timeframe unique candles, revision rows, gaps, missing intervals and
  maximum gap;
- archive population/sample size, pending rows, retry attempts, failed rows,
  missing R2 objects and unverified rows.

## Fail-closed acceptance

The report cannot pass when:

- capture is disabled or AIDY ownership is not explicitly confirmed;
- the observed candle source differs from the configured installed adapter;
- an expected scheduler cycle is missing;
- a complete snapshot has no quote age or any quote exceeds the stale limit;
- a partial/unavailable snapshot or source error exists;
- M1 or M5 evidence is absent, or any observed timeframe contains a gap;
- the archive outbox has backlog, retries/errors or a sampled R2 mismatch.

The strict zero-tolerance defaults are intentional for the Day 3 acceptance
window. Later operational alert thresholds may be versioned, but missing
evidence must never be silently converted into a healthy result.

## Test Worker endpoint

`GET /day3/continuity?minutes=10&archive_limit=40`

- Test environment only; production returns `404`.
- `minutes` must be between 5 and 1,440.
- `archive_limit` must be between 1 and 40.
- Healthy report: HTTP `200`, `ok=true`.
- Failed gate: HTTP `503`, `ok=false`, exact failure reasons retained.
- Invalid request/configuration: HTTP `400`.

Only aggregate evidence-health metrics are returned. No secret or raw market
payload is included.
