# AIDY retrospective XAUUSD historical-backfill contract

Decision date: 2026-08-19  
Day 5 implementation: 2026-08-19

## Purpose

Day 5 gives AIDY a bounded body of historical XAUUSD price structure for research without pretending that AIDY observed those historical candles in real time.

The source is HistData Generic ASCII XAU/USD M1 history. The source rows are bid-price OHLC bars. HistData timestamps are interpreted exactly as documented by the source: fixed Eastern Standard Time (UTC-05:00) with no daylight-saving adjustment, then normalized to UTC by AIDY.

This is research data, not historical knowledge-state evidence.

## Hard provenance boundary

Retrospective historical candles are stored in `research_candles`, never in the live/PIT `market_candles` table.

Every research row carries:

- `provenance_class = retrospective_history`
- `pit_eligible = false`
- source and source-dataset identifiers
- source archive and payload SHA-256 digests
- source timezone interpretation
- deterministic derivation version
- deterministic candle and research identities
- ingest/run provenance

`research_candles` deliberately has no `first_observed_at` field. A retrospective source timestamp is not an observation timestamp.

Any future as-of/PIT reconstruction must use PIT evidence tables only. Day 6 explicitly tests that retrospective rows cannot contaminate an as-of reconstruction.

## Source contract

- Source: `histdata`
- Source dataset: `generic_ascii_m1`
- Symbol: `XAUUSD`
- Price basis: bid OHLC
- Native timeframe: M1
- Source time zone: fixed EST / UTC-05:00, no DST adjustment
- AIDY normalized timestamp: UTC
- Source archives: immutable-by-digest inputs for a given backfill run

AIDY does not use any Super Signals, MetaAPI, Vantage, MT5 or broker credential for Day 5.

## Parsing and fail-closed rules

The parser:

1. accepts the documented `YYYYMMDD HHMMSS;Open;High;Low;Close;...` Generic ASCII M1 shape;
2. requires minute-aligned timestamps;
3. rejects malformed/non-finite prices;
4. rejects impossible OHLC relationships;
5. counts source rows that move backward relative to the preceding raw row, then deterministically canonicalizes the accepted rows by source timestamp;
6. removes exact candle duplicates while counting them;
7. rejects conflicting duplicates for the same source timestamp;
8. measures every source discontinuity greater than one minute and retains count/max-gap evidence.

The immutable ZIP and CSV hashes remain the source-of-truth provenance even when the vendor archive contains ordering anomalies. `out_of_order_rows` is persisted in the backfill manifest so canonicalization is auditable rather than hidden.

A gap is evidence, not permission to fabricate a missing candle. No interpolation or synthetic M1 bars are created.

## Deterministic timeframe derivation

M5, M15, H1, H4 and D1 candles are derived only from accepted source M1 rows. Bucket boundaries are aligned in the source's fixed-EST clock before the bucket timestamp is normalized to UTC. This prevents UTC conversion from silently changing H4/D1 session boundaries.

Each derived row records:

- `derived_from_timeframe = M1`
- `derivation_version = aidy_histdata_source_aligned_v1`
- `input_rows`

No source gap is filled merely to complete an aggregate bucket.

## BigQuery tables

### `research_candles`

Partition: `open_time_utc` day  
Cluster: symbol, timeframe, source, provenance class

`research_identity` is deterministic from candle identity, source digests, OHLC values, input-row count and derivation version. Re-running the same immutable source produces the same research identities.

`candle_key` identifies the logical source/timeframe/open-time candle independently of source revision. If a source archive is later deliberately refreshed and changes, the revised source can be retained as a distinct research identity instead of silently overwriting history.

### `research_backfill_manifest`

Partition: `ingested_at` day  
Cluster: source, symbol, status

One successful manifest identity records the source period, request signature, source digests, requested timeframes, first/last UTC timestamps, M1 row count, duplicate/gap/order-anomaly evidence, derived timeframe counts and run ID.

The manifest is the resumable checkpoint. A completed source period with the same request signature and derivation version is skipped on a normal rerun. `--force-process` bypasses the checkpoint but still uses insert-only BigQuery MERGE semantics, so the same source cannot duplicate facts.

## Idempotency and recovery

Day 5 processes source periods independently.

For each period:

1. check the successful manifest checkpoint;
2. download/cache and validate the source ZIP;
3. hash ZIP and CSV payload;
4. parse, validate and audibly canonicalize M1 source order;
5. derive requested timeframes;
6. stage rows under a unique `_backfill_run_id`;
7. insert-only MERGE facts by `research_identity`;
8. reconcile rows and provenance in BigQuery;
9. insert-only MERGE the successful manifest by `backfill_identity`;
10. remove transient staging rows.

If execution stops after fact MERGE but before the manifest is written, rerunning the period safely reuses the same research identities and then completes the manifest checkpoint.

The warehouse bootstrap permits only additive nullable metadata fields for this contract. Any destructive or incompatible schema drift still fails closed.

## Day 5 acceptance

The bounded live gate must prove all of the following with real HistData XAUUSD archives and the real `aidy_analytics_test` BigQuery dataset:

1. source download and ZIP/CSV validation succeeds;
2. parser, UTC normalization and deterministic aggregation tests pass;
3. at least two complete historical annual periods are loaded and range/count/gap/order-anomaly evidence is recorded;
4. every loaded research row is `retrospective_history` and `pit_eligible = false`;
5. no retrospective row is written to `market_candles`;
6. a forced repeat of an accepted source period leaves research fact/manifest identity counts unchanged;
7. a normal rerun recognizes the successful manifest checkpoint and skips already-complete work;
8. source periods and requested timeframe counts reconcile to the generated/load counts;
9. no Super Signals or broker credential is used.

GitHub Actions may transport this bounded acceptance, but no recurring historical-download runtime is created there.
