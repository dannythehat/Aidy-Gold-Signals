# AIDY market-data boundary

Decision updated: 2026-08-19

## Locked decision

AIDY is an independent signal provider and market-intelligence system. It does not need a broker, MT5 account, MetaAPI account, execution account or follower-position state to observe Gold.

The systems meet only later through Telegram:

`AIDY evidence -> OpenAI decision -> AIDY Telegram -> Super Signals -> Vantage DEMO`

## Live reference-price source

AIDY's active forward price recorder uses the public Gold-API XAU endpoint:

`GET https://api.gold-api.com/price/XAU`

Runtime contract:

- `AIDY_MARKET_DATA_SOURCE=gold_api`
- `AIDY_MARKET_DATA_OWNERSHIP=public_independent`
- no market-data API key;
- no username/password;
- no broker account ID;
- no execution or position surface.

Gold-API is an indicative reference-price source. AIDY stores the supplied XAU/USD price as `mid`. Bid, ask and spread remain unknown when the upstream does not provide them.

## Candle and historical-data rule

AIDY must never manufacture OHLC bars from sparse one-minute snapshots. Genuine OHLC/tick history is a separate research ingestion product with its own provenance, timestamp and quality checks.

Day 3 therefore proves the live reference stream itself: expected one-minute scheduled observations, freshness, complete/unavailable states, source identity, archive backlog/retries and D1/R2 reconciliation.

Later historical/candle ingestion may use free/open sources where they provide genuine market observations, but those datasets do not create a trading-account dependency.

## Enforced in active code

- `GoldApiGateway` exposes only a keyless XAU/USD market-data read.
- `AidyReferencePriceRecorderService` writes no broker/follower position state.
- New snapshots keep `position_state_json=NULL` for historical schema compatibility.
- Bid, ask and spread are not fabricated.
- Candle IDs remain NULL until a genuine OHLC source is ingested.
- Checked-in Worker capture is disabled.
- Checked-in scheduler Cron is disabled.
- Enabled capture fails closed unless the source is `gold_api` and ownership is `public_independent`.
- The active runtime imports no MetaAPI adapter.

## Historical MetaAPI evidence

Day 2 used a temporary MetaAPI/Vantage path to prove the original Cloudflare capture plumbing. That evidence is retained as history only. A later provenance check proved the ambiguously named `AIDY_METAAPI_TOKEN` actually exposed the Super Signals owner demo on `VantageMarkets-Demo`, login ending `1913`.

That finding remains useful audit evidence, but MetaAPI is no longer an AIDY market-data option or runtime requirement.

## OpenAI clarification

ChatGPT is a build tool, not an AIDY runtime component. The OpenAI API is future trading/research intelligence only. It is not used for storage, market capture or broker execution.
