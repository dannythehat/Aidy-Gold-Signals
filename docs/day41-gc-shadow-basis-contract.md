# Day 41 — COMEX GC shadow observation spine and XAUUSD basis logger

Decision date: 2026-09-01

Authoritative base: `abe751749a20f9951b2456db9c7a048a8f60554f`

## Objective

Stand up a vendor-separable COMEX Gold futures observation spine using the Day 40 Databento historical adapter while retaining the existing public Gold-API XAUUSD recorder as the independent reference. GC is shadow-only. This day creates evidence, not a venue switch or trading permission.

## Databento acquisition boundary

- Dataset: `GLBX.MDP3`.
- Research symbol: OI-ranked continuous `GC.n.0`.
- Every accepted observation must resolve to an auditable raw GC contract identity such as `GCZ6`.
- Initial schema: `ohlcv-1m` only.
- Every request is quoted before download and quoted again immediately before transfer by the Day 40 adapter.
- The Day 41 genuine smoke adds a stricter `$0.25` maximum quote on top of Day 40's free-credit controls.
- No live Databento subscription is activated.
- No paid recurring service is activated.
- MBO/MBP-10 remain prohibited during the free-credit phase.
- No API key is written to logs or evidence.

## XAUUSD reference

The existing public Gold API remains the independent XAUUSD reference. It is broker-free and requires no account credential. Day 41 does not replace or retire this source.

## Pair contract

A GC/XAUUSD pair binds:

- provider and dataset;
- continuous research symbol;
- mapped raw GC contract identity;
- GC observation timestamp and price;
- XAUUSD source identity, timestamp and price;
- timestamp skew;
- basis in USD and basis points;
- source digests and pair digest;
- shadow/reference status;
- explicit no-substitution, no-broker and no-promotion flags.

If timestamps exceed the configured acceptance skew, no basis is fabricated. The row is `unpaired_timestamp_skew`. Missing contract identity also fails closed.

## Outage and substitution rule

Databento failure does not cause GC to be silently replaced by CME public data, broker data, XAUUSD, or another vendor. Gold-API failure does not cause XAUUSD to be replaced by broker data. Missing or stale observations remain missing/stale.

## Promotion policy frozen before results

The Day 41 policy requires, at minimum:

- 1,000 paired observations;
- four named session windows;
- ten distinct trading days;
- <=1% missing-pair rate;
- zero missing contract identities;
- p95 timestamp skew <=120 seconds;
- explicit roll-window annotation;
- basis distribution measured by session;
- outage-isolation test;
- XAUUSD parallel run retained;
- owner approval for any paid or live promotion.

Automatic promotion is forbidden. Performance improvement alone cannot promote the GC spine.

## Acceptance structure

CI runs in this order:

1. exact Day 40 base and bounded Day 41 surface check;
2. Ruff/compile checks;
3. focused Day 41 tests;
4. full repository regression;
5. deterministic architecture evidence twice, requiring byte-identical output;
6. only after all offline gates pass, one genuine bounded Databento request using `DATABENTO_API_KEY` and a public Gold-API read;
7. genuine evidence must contain a mapped raw GC contract, a paired XAUUSD observation, a quote <= `$0.25`, and all paid/live/broker flags false;
8. immutable workflow artifact upload.

If the Databento secret is absent, entitlement fails, no mapped GC observation is returned, the cost quote exceeds the cap, or the two sources cannot be paired within the acceptance skew, Day 41 fails rather than substituting another source.
