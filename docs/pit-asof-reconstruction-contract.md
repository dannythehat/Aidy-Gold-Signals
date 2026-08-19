# AIDY point-in-time as-of reconstruction contract

Decision date: 2026-08-19  
Day 6 implementation: 2026-08-19

## Purpose

Day 6 defines one canonical answer to the question: **What exactly could AIDY have known at evaluation timestamp T?**

This contract is for honest replay, research, later feature generation and historical case retrieval. It is not a trading-decision engine.

## Eligible evidence only

The PIT reconstruction surface reads only:

- `market_candles`
- `market_event_observations`
- `market_snapshots`

It does not read `research_candles` or any other retrospective-only Day 5 table. Retrospective historical price data is useful for research but is structurally ineligible to represent AIDY's historical knowledge state.

The output bundle always declares:

- `query_version = aidy_pit_asof_v1`
- `as_of_utc`
- `retrospective_history_included = false`
- deterministic query IDs
- immutable evidence provenance for each selected fact.

## Canonical temporal rule

Filtering by knowability happens **before** revision ranking.

A later revision must never be selected first and then projected backwards.

### Candles

A candle is eligible only when both:

- `open_time_utc <= as_of_utc`
- `first_observed_at <= as_of_utc`

For each logical candle `(source, symbol, timeframe, open_time_utc)`, select the latest eligible revision by:

1. `first_observed_at DESC`
2. `revision_index DESC`
3. `load_identity DESC` as deterministic tie-breaker.

Then, for the current as-of market state, select the latest eligible logical candle for each `(source, timeframe)` by open time and the same deterministic revision ordering.

### Events

An event revision is eligible only when `first_observed_at <= as_of_utc`.

For each logical event `(source, external_id)`, select the latest eligible revision using first-observed time, revision index and immutable load identity. `published_at` does not determine knowability: a scheduled future event may legitimately be known in advance, while a later revision cannot be known before AIDY actually observed it.

### Snapshot, quote and availability

Select the latest snapshot for the requested symbol with `captured_at <= as_of_utc`.

The snapshot supplies the quote fields, capture status, session state, linked evidence IDs and the exact `data_availability` object AIDY recorded at that time. No later snapshot is allowed to fill an earlier availability gap.

If no eligible snapshot exists, snapshot state and availability state are both explicitly `unknown`. Unknown is never converted to zero, false, empty-market or another fabricated state.

## Provenance bundle

Every known selected fact carries:

- `load_identity`
- `evidence_id`
- `archive_key`
- `payload_digest`
- `record_type`
- `schema_version`

The bundle also carries deterministic query IDs derived from the query version, query kind and exact SQL text. Later derived features can therefore record the exact reconstruction/query version that produced their source state.

## Query/runtime boundary

`src/aidy/pit_reconstruction.py` contains the deterministic selection logic and SQL contract and imports no Google Cloud client.

`scripts/day6_reconstruct_asof.py` is the separate BigQuery adapter. Google libraries are imported lazily only when the analytical reconstruction runner is invoked. The live recorder remains independent of BigQuery availability.

## Leakage tests

Day 6 must prove at minimum:

1. before a candle revision's `first_observed_at`, the earlier revision is returned;
2. at/after the later candle revision's `first_observed_at`, the later revision is returned;
3. the same pre/post rule holds for event revisions;
4. evidence first observed after T is absent, not backfilled;
5. a future-dated candle cannot appear before its open time even if malformed source metadata says it was observed early;
6. no snapshot before the first capture produces explicit unknown quote/availability state;
7. deterministic tie-breaking is stable for equal observation times;
8. PIT query SQL contains no reference to `research_candles` or retrospective-history provenance;
9. a real BigQuery reconstruction carries immutable archive/evidence provenance;
10. real Day 5 retrospective facts exist but remain absent from the PIT reconstruction bundle.

## Acceptance

The Day 6 bounded acceptance gate must pass the full project test suite and then use the real `aidy_analytics_test` warehouse to produce representative bundles around genuine AIDY snapshot evidence.

The gate must demonstrate an as-of timestamp before the first real snapshot returns explicit unknown snapshot/availability state, while an as-of timestamp at a real capture returns that snapshot with its evidence ID, archive key and payload digest intact. It must also prove `research_candles` contains retrospective rows while the Day 6 query surface and output bundle include none of them.

GitHub Actions may transport this bounded acceptance only. No recurring reconstruction runtime or trading scheduler is introduced on Day 6.
