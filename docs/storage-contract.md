# AIDY Cloudflare storage contract

Decision date: 2026-08-16

## Purpose

Day 1 replaces the PostgreSQL production dependency without weakening the recorder's point-in-time truth rules.

- D1 is the operational transaction store.
- R2 is the permanent append-only evidence archive.
- BigQuery is downstream analytical memory, not an operational dependency.

## Atomic evidence + outbox rule

Every new candle, snapshot, event observation or storage-smoke probe is committed to D1 together with an `archive_outbox` row in the same D1 batch/transaction.

The recorder does **not** require R2 to be healthy before operational evidence can be committed. If R2 is unavailable, the outbox row stays `pending`. A later Worker invocation retries it. R2 failure therefore cannot silently convert a successful observation into missing evidence.

## Point-in-time rules retained

- Candle revisions are append-only and keyed by source + symbol + timeframe + open time.
- Event revisions are append-only and keyed by source + external ID.
- Identical payload digests are idempotent and do not create a new revision.
- Event lookups use only observations whose `first_observed_at` was known at the requested capture time.
- `position_state_json = "[]"` is persisted only when the MetaAPI positions read explicitly succeeded.
- Failed or unattempted position reads persist as SQL `NULL`, meaning unknown.

## D1 tables

- `market_candles`
- `market_snapshots`
- `market_event_observations`
- `revision_counters`
- `archive_outbox`
- `storage_smoke_probes` (Day 1 infrastructure proof only; never trading evidence)

Prices are stored as text in D1 so decimal string truth is not changed by binary floating-point conversion.

## R2 archive keys

Permanent objects use immutable digest-bearing keys:

- `gold/candles/YYYY/MM/DD/<symbol>/<timeframe>/<timestamp>-<sha256>.json`
- `gold/snapshots/YYYY/MM/DD/<timestamp>-<evidence-id>-<sha256>.json`
- `gold/events/YYYY/MM/DD/<event-type>/<timestamp>-<sha256>.json`
- `day1/storage-smoke/YYYY/MM/DD/<probe-id>-<sha256>.json`

The R2 writer performs `head()` first. If the deterministic object already exists, the retry is treated as complete; it is never overwritten.

## Archive completion

After a successful R2 write, D1 marks the outbox row `archived`. For Fed/event evidence, the potentially large `raw_payload_json` may then be cleared from D1 because the immutable R2 object is the permanent raw copy. The D1 event row retains its identifiers, structured fields, revision, digest and archive pointer.

## Day 1 real-environment proof

The test Worker exposes `POST /day1/storage-smoke` only when `AIDY_ENV=test`. A successful response requires all of the following in one invocation:

1. a D1 smoke-probe row is committed with an outbox row;
2. the outbox is flushed to R2;
3. the D1 outbox state becomes `archived`;
4. `R2.head(archive_key)` confirms the object exists.

Mocks and local SQLite tests are useful preflight evidence but are not sufficient to mark Day 1 Passed.
