# AIDY BigQuery historical/export contract

Decision date: 2026-08-16

## Boundary

BigQuery is AIDY's analytical memory. It is not the recorder transaction store and must never be required to complete a live observation cycle.

The authoritative export source is the immutable R2 archive. D1 supplies operational manifests/status and archive pointers, not an alternative version of history.

## Idempotent export identity

Every exported row carries:

- `schema_version`
- `record_type`
- `evidence_id`
- `archive_key`
- `payload_digest`
- point-in-time timestamp (`first_observed_at` or `captured_at`)
- `revision_index` where revisions exist

An exporter treats `(archive_key, payload_digest)` as the immutable load identity. Re-running an export must not create a second analytical fact.

## Initial analytical tables

### `market_candles`

Core fields: evidence ID, symbol, timeframe, open time UTC, OHLC decimal strings/numerics, volume fields, source, revision index, payload digest, first-observed timestamp, archive key.

Partition by open date. Cluster by symbol, timeframe and source.

### `market_snapshots`

Core fields: evidence ID, capture timestamp, quote values/timestamp/age, session
code, data-availability object, linked event-observation IDs, latest candle IDs,
snapshot digest and archive key.

Broker/follower positions are deliberately excluded. AIDY's later watcher uses
its own versioned signal-lifecycle ledger; actual follower-account state remains
inside Super Signals.

Partition by capture date. Cluster by symbol, capture status and session code.

### `market_event_observations`

Core fields: evidence ID, source, external ID, event type, published timestamp when known, first-observed timestamp, revision index, headline, structured payload, raw archive pointer, payload digest.

Partition by first-observed date. Cluster by source and event type.

### Later tables

`decisions`, `outcomes`, `features`, `analogues` and counterfactual `no_trade` studies are later build-calendar work. Day 1 defines their provenance requirement but does not invent trading intelligence or outcome data early.

## Point-in-time research rule

Historical queries used for decisions must filter evidence by what AIDY could have known at the evaluation timestamp. A later event/candle revision may be studied as a later revision, but it must not replace the earlier version in a historical decision context.

Derived features must carry:

- `as_of_utc`
- source evidence IDs/digests
- feature definition/version
- query or pipeline version

This prevents hindsight leakage and makes research reproducible.

## Export manifest

The export process maintains a manifest with at least:

- archive key
- payload digest
- record type
- schema version
- export timestamp
- destination table
- load job/run identifier
- success/failure status

The exact Google Cloud project, dataset names and credentials are intentionally not hard-coded on Day 1; those are provisioned separately when authenticated Google Cloud access is available.
