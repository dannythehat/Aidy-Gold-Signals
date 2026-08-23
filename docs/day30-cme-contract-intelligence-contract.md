# Day 30 — CME Gold settlement, open-interest and contract-state contract

Decision date: 2026-08-23  
Status at code review: implementation and warehouse acceptance candidate

## Scope and source boundary

Day 30 adds public CME Gold (`GC`) futures contract evidence to AIDY. It does not replace the
append-only evidence store, Day 19 point-in-time rules, Day 25 market-structure epochs, Day 26 price
structure, Day 28 revision rules, or Day 29 event intelligence.

The only live inputs are the free official CME Group daily settlement JSON, final per-month
volume/open-interest JSON, Metals Futures Daily Bulletin PDF fallback, and Gold Product Calendar XLS.
Redirects must remain on the CME HTTPS allowlist. Historical bulk settlement
or open-interest data from DataMine is outside this acceptance and is not silently licensed,
backfilled or fabricated. TAS is optional P2 and remains `unknown_not_ingested` in this version.

## Immutable daily contract records

`aidy_cme_gold_daily_settlement_oi_v1` stores, per trade date and contract month:

- official source and final URLs, raw PDF SHA-256 and extracted-text SHA-256;
- bulletin number, preliminary/final revision state and the first AIDY observation time;
- contract label, canonical month code, settlement, settlement change and change in basis points;
- daily open interest and daily open-interest change;
- a stable fact key and immutable record digest.

CME's final volume/open-interest JSON provides an explicit UTC update time, which is preserved as
`official_published_at`; `first_observed_at` remains the AIDY PIT boundary. If the JSON bundle is
unavailable and the official PDF fallback is used, `official_published_at` remains null.
Open interest is explicitly `daily_t_plus_1`; no intraday open interest is inferred. Preliminary and
final rows remain separate immutable revisions. Reconstruction at T excludes observations first seen
after T and chooses the highest revision then latest qualifying observation for each fact.

## Official contract calendar

`aidy_cme_gold_contract_calendar_v1` captures the public CME product-calendar document digest and
first-observed time with contract month, first-notice, last-trade and available delivery dates.
Contract code and month must agree. Missing required dates fail parsing rather than being derived from
informal calendar rules.

## Deterministic contract and roll state

`aidy_cme_gold_contract_intelligence_v1` names three different identities so they cannot be conflated:

- `front_month_contract`: nearest listed delivery in the observed bulletin;
- `second_listed_contract`: next listed delivery;
- `active_contract`: maximum daily open interest, with later contract month as deterministic tie-break.

It reports days from the bulletin trade date to the front month’s first-notice date in weekday
business days, front/second settlement basis, front/second OI ratio, the liquidity leader, source
digests and an explicit roll state. A missing PIT calendar returns `partial_unknown_calendar`; it is
never guessed. The state is context only and creates no trade gate.

## J6 preregistration

`aidy_j6_open_interest_persistence_v1` is descriptive only. Its independent unit is
`trade_date × contract_code`. It assigns non-neutral daily episodes to four fixed quadrants:

- price up / OI up;
- price down / OI up;
- price up / OI down;
- price down / OI down.

For next 1, 3 and 5 trading days it reports known sample count, return distribution and directional
persistence. Results are also stratified by predeclared trend state, while roll-state and
market-structure-epoch counts are retained. Each quadrant/horizon stays `insufficient` below 30 known
independent outcomes. Neutral price or OI changes are counted and excluded.

The first public forward capture has no matured next-1/3/5-day outcomes, so a sparse/null J6 is the
expected scientific result. Trade P/L, win rate, trader intent and Super Signals data are forbidden.
No predictive edge or trading gate may be claimed.

## Context integration

`aidy_market_context_v6_cme_contract_state` wraps the accepted Day 29 context packet. It requires the
verified CME state to share the same as-of T, records the source-contract version, embeds the complete
contract state and covers it with the deterministic context hash.

## Warehouse acceptance

Day 30 acceptance must:

1. pass Ruff, all focused tests and the full regression suite;
2. capture a real official CME bulletin and product calendar without authentication;
3. preserve source document digests, conservative first-observed timestamps and immutable revisions;
4. reconcile per-contract daily and calendar rows in BigQuery;
5. prove front, second, active, days-to-first-notice and roll state are deterministic and PIT-clean;
6. run the preregistered J6 quadrants and 1/3/5-day report, preserving insufficient/null outcomes;
7. emit deterministic evidence artifacts and exact digests;
8. show `intraday_open_interest_inferred=false`, `historical_bulk_backfilled=false`,
   `predictive_edge_claimed=false`, `trading_gate_created=false`,
   `accepted_prior_modules_modified=false` and `super_signals_modified=false`.
