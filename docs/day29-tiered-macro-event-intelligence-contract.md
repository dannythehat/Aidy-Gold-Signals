# Day 29 — tiered scheduled macro-event and forward-surprise contract

Decision date: 2026-08-23  
Status at code review: implementation and warehouse acceptance candidate

## Scope

Day 29 extends the accepted Day 8 official macro-event evidence layer. It does not replace the
append-only event store, the Day 19 point-in-time boundary, Day 25 market-session handling, Day 26
price structure, or Day 28 first-print/revision rules.

The added event classes are:

- `initial_jobless_claims`
- `ism_manufacturing`
- `ism_services`
- `retail_sales`
- `fed_speech`
- `fed_chair_testimony`
- `fomc_minutes`
- `treasury_auction`
- `ecb_decision`
- `boj_decision`
- `boe_decision`

This remains macro timing and volatility context. Day 29 makes no predictive-edge claim and creates
no trading gate.

## Free authoritative source boundary

The source registry is strict and versioned. It permits only HTTPS observations from:

- U.S. Department of Labor / Employment and Training Administration for weekly claims;
- Institute for Supply Management for Manufacturing and Services release schedules;
- U.S. Census Bureau for advance retail-sales schedules and releases;
- Federal Reserve Board for speeches, Chair testimony and FOMC Minutes;
- U.S. Treasury Fiscal Data for announced and upcoming auctions;
- European Central Bank, Bank of Japan and Bank of England for policy-decision schedules.

No paid calendar, news, consensus, broker or Super Signals dependency is introduced. Redirects off
the registered official host fail acceptance.

## Schedule and timezone rules

`aidy_macro_event_intelligence_v2` stores the official local date, local time, IANA timezone,
derived UTC time, precision, source URL, first-observed time, provenance and digest.

- Minute-precision schedules require an explicit IANA timezone.
- UTC conversion uses the timezone database, including DST transitions.
- Nonexistent local wall times are rejected by a UTC round-trip check.
- If the official source exposes a date but no reliable release clock, `scheduled_at` stays null and
  precision is `date_only`; AIDY never invents a time.
- PIT schedule revisions are selected only when `first_observed_at <= T`.
- Retrospective official schedules are research-only and are excluded from live as-of selection.

## J4/J15 severity-tier preregistration

`aidy_j4_j15_event_tiers_v1` is descriptive only. The independent unit is an event episode, keyed by
event class and independent episode identity. Duplicate identities with conflicting values fail.

Per class, the study reports:

- independent episode count;
- minimum, median and maximum post-event absolute return;
- minimum, median and maximum post-event realized volatility;
- minimum, median and maximum signed outcome return;
- assigned tier state and its descriptive timing window.

The tier metric is fixed before warehouse execution:

`median(post-event absolute return bps) + median(post-event realized volatility bps)`

The preregistered thresholds are:

- tier 3: metric at least 30 bps;
- tier 2: metric at least 15 bps and below 30 bps;
- tier 1: metric below 15 bps.

No class receives a numeric tier until it has at least 20 independent episodes. Sparse classes remain
`unclassified_insufficient_evidence`. That null/pruning result is valid and must not be overridden by
judgment, trade P/L, win rate or later trade outcomes.

Tier windows are descriptive metadata:

| Tier | Minutes before | Minutes after |
|---|---:|---:|
| tier 1 | 30 | 90 |
| tier 2 | 60 | 180 |
| tier 3 | 90 | 240 |

An unclassified event within four hours produces `unknown_severity_nearby`. It does not silently fall
back to the old one-size window and does not itself authorize or block a trade.

## PIT-safe pre-event price structure

`aidy_pre_event_structure_v1` uses only AIDY-owned accepted XAUUSD M1 research rows whose nominal
close time is no later than both the requested as-of time and scheduled release time.

It calculates:

- 60-minute pre-event drift;
- 60-minute high-low range;
- 60-minute realized volatility;
- preceding 240-minute realized-volatility baseline;
- recent-to-baseline volatility-compression ratio.

Both windows require at least 80% minute coverage. Incomplete evidence returns
`unknown_insufficient_pre_event_coverage`. Rows at or after the release cannot influence the packet.

## Forward consensus, actual and surprise capture

`aidy_forward_macro_surprise_v1` starts the immutable forward observation contract.

- Consensus is accepted only from an explicitly approved HTTPS source with a timestamped immutable
  capture no later than the scheduled release.
- Historical consensus is never inferred or backfilled from an overwritten calendar.
- If no qualifying source exists, consensus and surprise remain `UNKNOWN`.
- Official actuals retain `first_observed_at`, optional official `published_at`, units, source URL,
  revision index and previous value.
- Revision index 0 is the first print. Later actuals remain revisions and cannot replace the first
  print used for surprise.
- Surprise is computed only when PIT-known consensus and first print use the same unit.

Day 29 deliberately accepts `UNKNOWN` consensus/surprise because no free qualifying consensus source
has been approved. This is the scientific result, not an implementation gap to fill with hindsight.

## Context integration

`aidy_market_context_v5_tiered_macro_events` adds the verified Day 29 event-intelligence state to the
accepted Day 28 context packet. It marks the legacy `event_risk` field as superseded, while preserving
it for compatibility. The new packet and event state must share the same as-of timestamp and both are
covered by the deterministic context hash.

## Warehouse acceptance

Day 29 acceptance must:

1. pass Ruff, all focused tests and the full regression suite;
2. retrieve or reuse cached bodies from all eight registered official source families;
3. prove each response stays on its official host and contains source-specific contract markers;
4. prove the source registry covers every Day 29 event class;
5. build a real bounded HistData pre-event feature and post-event descriptive episode;
6. preserve the sparse J4/J15 result instead of promoting it to a tier;
7. keep forward consensus/surprise unknown when no qualifying observation exists;
8. reconcile immutable source, class, feature and summary rows in BigQuery;
9. emit deterministic evidence artifacts and exact digests;
10. show `predictive_edge_claimed=false`, `trading_gate_created=false`,
    `accepted_prior_modules_modified=false` and `super_signals_modified=false`.

The acceptance script writes only source body digests and bounded source metadata to evidence. It does
not write credentials, environment values or secret material.
