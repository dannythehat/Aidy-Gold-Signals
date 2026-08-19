# AIDY Day 9 cross-market source audit

Decision date: 2026-08-19

## Outcome

Day 9 enables only free daily public/official context whose ownership and timing can be represented honestly. It does not add intraday cross-market prices, DXY, equities, ETFs, crypto or broker-derived proxies.

| Candidate | Decision | Source | Cost / auth | Frequency | PIT treatment |
|---|---|---|---|---|---|
| Broad USD index | ENABLE | Federal Reserve Board H.10 current release, Broad Dollar Index (`DTWEXBGS` semantic mapping) | Free, no key | Daily observations published in weekly H.10 release | source observation date + AIDY first-observed timestamp; revisions append-only |
| FRED CSV delivery of `DTWEXBGS` | NO-GO for forward Worker runtime | FRED public CSV | Free, no key | Daily | GitHub probe succeeded, but Cloudflare Worker live smoke failed repeatedly; do not depend on it in runtime |
| U.S. Treasury 2Y nominal | ENABLE | U.S. Treasury daily par yield XML | Free, no key | Daily | observation date + AIDY first-observed timestamp; revisions append-only |
| U.S. Treasury 10Y nominal | ENABLE | U.S. Treasury daily par yield XML | Free, no key | Daily | observation date + AIDY first-observed timestamp; revisions append-only |
| U.S. Treasury 10Y real | ENABLE | U.S. Treasury daily real par yield XML | Free, no key | Daily | observation date + AIDY first-observed timestamp; revisions append-only |
| DXY / ICE U.S. Dollar Index | NO-GO | Proprietary benchmark / no approved official free AIDY feed | Not approved | N/A | Remains unavailable; Fed broad dollar index is the approved context proxy |
| Intraday Treasury yields | NO-GO | No approved official free intraday feed | N/A | N/A | Daily Treasury evidence only; no synthetic interpolation |
| Equity/ETF/crypto proxies | NO-GO for Day 9 | Not needed to satisfy the current evidence question | N/A | N/A | Do not add noise before outcome research demonstrates incremental value |

## Why direct Federal Reserve H.10 is the runtime USD source

The Board of Governors publishes the H.10 Foreign Exchange Rates release and its Broad U.S. Dollar Index. The current H.10 page publishes the prior business week's daily dollar-index values on the Board's own `federalreserve.gov` domain.

AIDY maps the Board's `1) BROAD / JAN06=100` row to the established H.10 series semantic `DTWEXBGS`. The value remains daily context, but AIDY does **not** pretend it knew the value on the source observation date. `first_observed_at` is the later time when the Worker actually fetched the Board's H.10 release.

FRED remains a valid public distribution channel for the Board series, but Day 9 live acceptance found that the Cloudflare Worker could not fetch FRED reliably while GitHub Actions could. Because forward runtime continuity matters more than theoretical source availability, FRED is explicitly rejected for the Worker path rather than hidden behind a fallback.

## Why Treasury XML is acceptable

The U.S. Treasury documents the public daily interest-rate XML feed and the daily par nominal and real yield curves. AIDY reads the official Treasury endpoint directly. The enabled tenors are 2Y and 10Y nominal plus 10Y real.

## Timing semantics

These are daily context series, not intraday quotes.

- `observation_date` is the source's dated observation.
- `first_observed_at` is stamped only after AIDY's HTTP response has arrived and parsed successfully.
- AIDY never substitutes `observation_date` for `first_observed_at`.
- A value first captured today is unknown to AIDY in a replay from yesterday, even if its source observation date is older.
- If the same source/series/date later changes value, the logical identity stays fixed and D1 appends a higher revision.
- No Day 9 historical backfill is declared PIT-eligible.

## Storage

`cross_market_observations` is a dedicated D1 evidence class. It is not a Gold candle and not a macro event. Cross-market evidence has a dedicated retryable R2 outbox and immutable archive namespace, plus a dedicated BigQuery analytical table/export path.

## Runtime

The default poll interval is one hour because the enabled sources are daily. A source failure is isolated from Gold price capture, official macro capture and archive retries. No credential is required.
