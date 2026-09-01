# Day 41 — COMEX GC shadow observation spine and XAUUSD basis logger

Decision date: 2026-09-01

Authoritative base: `abe751749a20f9951b2456db9c7a048a8f60554f`

## Objective

Stand up a vendor-separable COMEX Gold futures observation spine using the Day 40 Databento historical adapter while retaining XAUUSD as the independent signal-expression/reference layer. GC remains shadow-only. This day creates architecture and genuine-source evidence; it does not create a venue switch, live-GC dependency, formal forward evidence, or trading permission.

## Free-first procurement decision

Day 40 selected a free-first path. Day 41 therefore does not activate Databento Standard, CME non-display licensing, or any recurring paid feed.

The Databento API credential is used only for licensed historical access covered by the account's free-credit entitlement. Databento's current free historical entitlement can lag the present UTC day. Day 41 must not relabel delayed historical data as live.

For genuine acceptance, the harness selects the last fully entitled UTC day and uses a bounded historical GC slice plus AIDY's already-accepted HistData XAUUSD M1 source for the same timestamp. That pair is explicitly marked `retrospective_history`, `pit_eligible=false`, and `formal_forward_evidence_eligible=false`.

## Databento acquisition boundary

- Dataset: `GLBX.MDP3`.
- Research symbol: OI-ranked continuous `GC.n.0`.
- Every accepted observation must resolve to an auditable raw GC contract identity such as `GCZ6`; the continuous alias is never accepted as a tradable contract identity.
- Contract identity is resolved through Databento symbology: `GC.n.0 -> instrument_id -> raw_symbol`, then bound to each OHLCV row through `hd.instrument_id`.
- Initial schema: `ohlcv-1m` only.
- Every request is quoted before download and quoted again immediately before transfer by the Day 40 adapter.
- The Day 41 genuine historical smoke adds a stricter `$0.25` maximum quote on top of Day 40's free-credit controls.
- No live Databento subscription is activated.
- No paid recurring service is activated.
- MBO/MBP-10 remain prohibited during the free-credit phase.
- No API key is written to logs or evidence.

## XAUUSD reference

AIDY's live XAUUSD reference remains the public Gold API and is not replaced by GC.

For the free historical Day 41 acceptance only, AIDY reuses the accepted Day 5 HistData Generic ASCII XAUUSD M1 history. HistData rows are retrospective bid-price candles and are never represented as point-in-time observed AIDY evidence. Their archive and payload digests are retained in the Day 41 evidence.

The historical acceptance pair therefore proves the GC/XAUUSD adapter, timestamp alignment, contract mapping, basis calculation and provenance boundaries without pretending the free Databento entitlement is a current live feed.

## Pair contract

A GC/XAUUSD pair binds:

- provider and dataset;
- continuous research symbol;
- mapped raw GC contract identity;
- GC observation timestamp and price;
- XAUUSD source identity, timestamp and price;
- XAUUSD provenance class and PIT eligibility;
- timestamp skew;
- basis in USD and basis points;
- source digests and pair digest;
- historical-versus-live research status;
- formal-forward-evidence eligibility;
- explicit no-substitution, no-broker and no-promotion flags.

If timestamps exceed the configured acceptance skew, no basis is fabricated. The row is `unpaired_timestamp_skew`. Missing contract identity also fails closed.

## Hindsight boundary

The genuine free historical pair is architecture/shadow evidence only.

It is explicitly:

- `historical_research_pair=true`;
- `retrospective_history` on the HistData leg;
- `pit_eligible=false` on the HistData leg;
- `formal_forward_evidence_eligible=false`;
- excluded from any future formal paper-performance claim.

A retrospective pair cannot be promoted into decision-time evidence merely because its timestamps align.

## Outage and substitution rule

Databento failure does not cause GC to be silently replaced by CME public data, broker data, XAUUSD, or another vendor. XAUUSD failure does not cause a broker feed to be inserted. Missing or stale observations remain missing/stale.

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
6. only after all offline gates pass, query Databento's genuine historical entitlement and select the last fully entitled UTC day;
7. quote and download one bounded `GC.n.0` `ohlcv-1m` slice under the `$0.25` cap;
8. resolve the downloaded rows to actual raw GC contracts using Databento symbology;
9. obtain matching XAUUSD M1 history from the accepted HistData source and require timestamp alignment within 60 seconds;
10. enforce retrospective/PIT-ineligible/no-forward-evidence flags and all paid/live/broker flags false;
11. upload the exact-head acceptance artifact.

If the Databento credential is absent, entitlement fails, no full historical UTC day is available, a raw GC contract cannot be resolved, the HistData source cannot provide the matching XAUUSD bar, the quote exceeds the cap, or the pair fails the timestamp gate, Day 41 fails closed rather than substituting a weak source.

## Live-GC status after Day 41

Live GC remains disabled and unapproved. The free historical spine may be used for architecture and research. A paid/current GC feed can be proposed later only if preregistered evidence demonstrates incremental value and the owner explicitly approves the spend.
