# AIDY BigQuery historical/export contract

Decision date: 2026-08-16
Day 4 implementation: 2026-08-19

## Boundary

BigQuery is AIDY's analytical memory. It is not the recorder transaction store and must never be required to complete a live observation cycle.

The authoritative export source is the immutable R2 archive. D1 supplies operational manifests/status and archive pointers, not an alternative version of history.

Day 4 keeps the exporter as a separate batch component. The live Gold recorder imports no BigQuery or Google Cloud client and remains healthy if the exporter or BigQuery is unavailable. GitHub Actions may execute the bounded Day 4 acceptance/provisioning run, but it is not the permanent AIDY export scheduler.

## Day 4 test warehouse

- Dataset: `aidy_analytics_test`
- Default location: `EU`
- Source of truth: immutable R2 objects only
- Export identity: `(archive_key, payload_digest)`
- Fact writes: insert-only BigQuery `MERGE`; an existing immutable identity is never updated or duplicated
- Prices/volumes: source decimal representations are retained as strings so analytical loading cannot change source precision
- Large raw event payloads: remain in R2; BigQuery stores structured event data plus the immutable R2 archive pointer
- Staging tables: transient transport only, keyed separately by `_export_run_id`; staging is never analytical truth

The Google Cloud project ID and service-account credential are environment/secret values and are never hard-coded or written into evidence files as credential material.

## Idempotent export identity

Every exported row carries:

- `schema_version`
- `record_type`
- `evidence_id`
- `archive_key`
- `payload_digest`
- point-in-time timestamp (`first_observed_at` or `captured_at`)
- `revision_index` where revisions exist
- deterministic `load_identity = sha256(archive_key + NUL + payload_digest)`

An exporter treats `(archive_key, payload_digest)` as the immutable load identity. Re-running an export must not create a second analytical fact. The Day 4 live gate exports the same real R2 object twice and requires the fact and manifest counts to remain one identity/one row.

## Initial analytical tables

### `market_candles`

Core fields: load identity, evidence ID, symbol, timeframe, open time UTC, exact OHLC decimal strings, volume fields, source, revision index, payload digest, first-observed timestamp, archive key.

Partition by `open_time_utc` day. Cluster by symbol, timeframe and source.

### `market_snapshots`

Core fields: load identity, evidence ID, capture timestamp, quote values/timestamp/age, session code, market-data source, data-availability JSON, linked event-observation IDs, latest candle IDs, snapshot digest and archive key.

Broker/follower positions are deliberately excluded. AIDY's later watcher uses its own versioned signal-lifecycle ledger; actual follower-account state remains inside Super Signals.

Partition by `captured_at` day. Cluster by symbol, capture status and session code.

### `market_event_observations`

Core fields: load identity, evidence ID, source, external ID, event type, published timestamp when known, first-observed timestamp, revision index, headline, structured payload, raw archive pointer and payload digest.

The raw event body remains in immutable R2 rather than being copied into BigQuery.

Partition by `first_observed_at` day. Cluster by source and event type.

### `export_manifest`

Each successful immutable load identity records:

- archive key and payload digest
- evidence ID, record type and schema version
- export timestamp
- destination table
- load/merge job identifiers
- exporter run ID
- success status

Partition by `exported_at` day. Cluster by record type, status and destination table.

### Later tables

`decisions`, `outcomes`, `features`, `analogues` and counterfactual `no_trade` studies are later build-calendar work. Day 4 does not invent trading intelligence or outcome data early.

## Point-in-time research rule

Historical queries used for decisions must filter evidence by what AIDY could have known at the evaluation timestamp. A later event/candle revision may be studied as a later revision, but it must not replace the earlier version in a historical decision context.

Derived features must carry:

- `as_of_utc`
- source evidence IDs/digests
- feature definition/version
- query or pipeline version

This prevents hindsight leakage and makes research reproducible.

## Export manifest and acceptance

The Day 4 acceptance requires all of the following:

1. test dataset and four analytical tables exist with the exact schema, partition and clustering contract;
2. one genuine archived R2 Gold snapshot is retrieved and its archive key, digest and evidence ID reconcile to D1;
3. the R2 object loads into `market_snapshots` with provenance intact;
4. the same object is exported a second time and the destination still contains exactly one fact and one manifest identity;
5. load/merge job IDs and query-byte usage are retained in acceptance evidence;
6. a deliberately unavailable BigQuery credential path fails outside the recorder while the live Gold `/health` endpoint remains healthy.

No recurring BigQuery job is introduced on GitHub Actions. Forward scheduling belongs to a later approved runtime path after this data contract is proven.
