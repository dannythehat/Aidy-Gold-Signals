# AIDY deterministic Gold feature engine v1

Decision date: 2026-08-19  
Feature definition: `aidy_gold_features_v1`

## Purpose

Day 7 converts approved XAUUSD evidence into stable, reproducible descriptors for later research and OpenAI reasoning. The feature engine does not make trade decisions, assign confidence or infer causes.

## Two explicit packet classes

### PIT packet

- `mode=pit`
- `provenance_class=pit_observed`
- `pit_eligible=true`
- candle rows must have been first observed on or before `as_of_utc`
- candle open time must be on or before `as_of_utc`
- retrospective Day 5 rows are rejected, not silently ignored
- quote/session context may use the latest PIT snapshot captured on or before `as_of_utc`
- the read-only BigQuery adapter admits only the active broker-free `gold_api` candle source; old MetaAPI candle history is not resurrected

The active Gold-API recorder currently captures indicative reference-price snapshots but does not fabricate OHLC candles. Therefore current PIT packets are expected to have real quote/session context while technical candle features remain explicit unknown until a genuine broker-free candle feed exists.

### Retrospective research packet

- `mode=retrospective`
- `provenance_class=retrospective_history`
- `pit_eligible=false`
- every input row must be a Day 5 `research_candles` row with `pit_eligible=false`
- a PIT snapshot cannot be mixed into a retrospective packet

This packet exists for historical pattern/analogue research. It must never masquerade as AIDY's historical knowledge state.

## Numeric determinism

Source OHLC values are parsed with Python `Decimal`. Computed numeric features are rounded with `ROUND_HALF_EVEN` to six decimal places and serialized as decimal strings. Packet JSON is canonicalized with sorted keys and compact separators; `feature_packet_digest` is SHA-256 of the packet before the digest field is added.

Input row order does not affect the output. Duplicate logical candles fail closed.

## Timeframe normalization

Accepted aliases are normalized to:

- `M1`
- `M5`
- `M15`
- `H1`
- `H4`
- `D1`

PIT aliases such as `1m`, `5m`, `15m`, `1h`, `4h`, `1d` map to the same canonical names.

## Per-timeframe features

For each timeframe the v1 packet exposes:

- state and bars available
- latest candle time and close
- one-bar return in basis points
- five-bar return in basis points and direction
- current candle body in basis points
- current candle range in basis points
- close location within the current candle range
- 14-period ATR-style true-range average in basis points (requires 15 observed bars)
- 20-return realized volatility in basis points using population standard deviation (requires 21 observed bars)
- 20-bar recent high and low
- distance to recent high / from recent low in basis points
- position within the 20-bar range
- latest confirmed two-bars-each-side swing high and swing low
- seconds elapsed since the previous observed bar
- exact source identities used by the rolling technical window

Insufficient history produces null/unknown values. Missing bars are not fabricated. Elapsed seconds are exposed so downstream research can distinguish tightly spaced observations from gaps.

## Session and range context

Day 7 introduces one portable session clock for forward and research use. It uses explicit modern London and New York DST rules plus Tokyo local hours and therefore does not depend on host tzdata.

Session labels are:

- `asia`
- `london`
- `new_york`
- `london_new_york_overlap`
- `off_hours`
- `weekend`

M1 evidence supplies current UTC-day and current contiguous-session high/low/range-position context. Those range features carry the exact source identities used.

The active broker-free recorder now delegates future session labels to this shared clock. No deployment is implied merely by merging Day 7; the existing Cloudflare recorder remains independently scheduled and healthy.

## Quote and spread context

A PIT snapshot exposes:

- capture status
- upstream quote state exactly as recorded in `data_availability`
- quote age seconds
- quote timestamp
- bid, ask, mid and spread exactly as present
- recorded session code
- Day 7 computed session code and consistency flag
- snapshot load identity

Unknown spread remains null. A stale quote remains stale. The feature engine does not invent a spread, recalculate recorder freshness thresholds or turn missing values into zero.

Retrospective packets have quote context `unknown`; current/future PIT snapshots cannot be projected backwards into historical research packets.

## Multi-timeframe alignment

The v1 alignment descriptor compares the sign of each timeframe's five-bar return. It records each direction, counts bullish/bearish/flat known timeframes and labels the aggregate as:

- `all_bullish`
- `all_bearish`
- `all_flat`
- `mixed`
- `insufficient`

This is a deterministic descriptor, not a trade signal.

## Source-link audit

Every packet carries source identities by timeframe. PIT source links carry immutable load/evidence/archive/digest provenance. Retrospective links carry research identity, source ZIP/payload hashes and derivation version. Day/session range contexts separately list all M1 identities used in those range calculations.

## BigQuery adapter

`scripts/day7_build_feature_packet.py` is read-only and imports Google libraries lazily.

- PIT mode queries only canonical revisions known by `as_of_utc`, restricted to source `gold_api`, plus the latest eligible snapshot.
- Retrospective mode queries only `research_candles` rows where `provenance_class=retrospective_history` and `pit_eligible=false`.
- At most 2,048 recent rows per timeframe are loaded into one packet.
- Day 7 creates no recurring GitHub runtime and no trading scheduler.

## Acceptance

Day 7 passes only when:

1. the full project suite, Ruff and compile gate pass;
2. identical evidence produces an identical packet and digest across reruns and input order;
3. missing candles, stale quotes, null spread, invalid OHLC and London/New York DST boundaries are covered by tests;
4. retrospective evidence is rejected from PIT mode and PIT snapshots are rejected from retrospective mode;
5. a real BigQuery retrospective packet contains non-null technical features, source links and `pit_eligible=false`;
6. the same real retrospective packet built twice has the same digest;
7. a real PIT packet uses the genuine AIDY snapshot, preserves quote/session provenance and contains no retrospective rows;
8. current absence of broker-free live OHLC remains explicit unknown rather than being filled from MetaAPI or Day 5 history.
