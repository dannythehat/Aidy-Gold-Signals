# AIDY Gold Signals — Locked Architecture

Decision date: 2026-08-16
Market-data update: 2026-08-19

## Product boundary

AIDY Signals is a standalone Gold signal provider. Super Signals is a downstream consumer only, through the AIDY Signals Telegram group.

AIDY does not share Super Signals code, database, runtime, risk engine, parser, broker execution layer or deployment stack.

## Market-data boundary

AIDY does not require a broker execution account to observe Gold.

- Active live XAU/USD reference source: public keyless Gold-API.
- AIDY never reads broker/follower positions, orders or account state.
- Vantage execution and position reconciliation belong only to Super Signals.
- No MetaAPI, MT5, Vantage or Super Signals credential belongs in the AIDY live market-data path.
- Enabled forward capture must identify `AIDY_MARKET_DATA_SOURCE=gold_api` and `AIDY_MARKET_DATA_OWNERSHIP=public_independent`.
- The live reference source provides an indicative Gold price. AIDY stores it as `mid` and leaves unsupported bid/ask/spread values unknown.
- Genuine OHLC/tick history is a separate research ingestion product. AIDY never invents candles from sparse snapshots.

## Runtime and data layer

### Cloudflare Workers
Serverless runtime and orchestration for recorder jobs, ingestion, state transitions, publication workflows and controlled API endpoints.

### Cloudflare D1
Lightweight operational state only. Intended examples:
- decision-cycle ledger
- publication/idempotency state
- active watcher state
- current trade-management metadata
- evidence manifests and archive pointers

D1 is not the permanent raw market-history warehouse.

### Cloudflare R2
Durable append-only raw and historical archive. Prefer compact immutable files and Parquet for analytical datasets.

Example partitioning:
- `gold/candles/YYYY/MM/DD/...`
- `gold/snapshots/YYYY/MM/DD/...`
- `gold/events/YYYY/MM/DD/...`
- `gold/decisions/YYYY/MM/DD/...`
- `gold/outcomes/YYYY/MM/DD/...`

Point-in-time truth must be preserved. Unknown data must never be rewritten as known-empty data.

### Google BigQuery
Analytical warehouse for:
- historical feature research
- regime analysis
- analogue retrieval
- decision/outcome evaluation
- MAE/MFE and expectancy studies
- counterfactual NO TRADE analysis
- large historical queries used to prepare compact evidence for the OpenAI trader

BigQuery is analytical memory, not the low-latency operational transaction store.

## Telegram boundary

AIDY publishes provider-style trade and management messages to the private AIDY Signals Telegram group. Super Signals may later onboard that group exactly like any other approved external provider.

## Intelligence boundary

ChatGPT is not part of the AIDY runtime. OpenAI API reasoning is planned for the later intelligence phase. It does not store evidence and does not access Vantage or Super Signals.

## Explicit exclusions

- No Render service, database, worker or deployment for AIDY unless the owner explicitly reverses this decision.
- No GitHub Actions trading/runtime scheduler. Actions may be used for CI, tests, provisioning, migrations and deployment transport.
- No direct follower-trade execution from AIDY.
- No live-money capability during build and paper evaluation.

## Day 3 evidence-health boundary

The Day 3 reference continuity auditor is deterministic and runs against D1/R2 bindings. For the active Gold-API feed it measures expected versus observed one-minute scheduler cycles, quote age, complete/partial/unavailable snapshot state, source identity, source errors, archive backlog/retries and D1-to-R2 object existence.

The live Day 3 gate requires:

- `AIDY_CAPTURE_ENABLED=true`;
- `AIDY_MARKET_DATA_SOURCE=gold_api`;
- `AIDY_MARKET_DATA_OWNERSHIP=public_independent`;
- zero hidden missing capture cycles in the acceptance window;
- no stale/partial/unavailable observations;
- no archive mismatch.

Candle continuity is not claimed by this feed. Candle integrity is assessed only when a genuine OHLC research source has been loaded.

## Historical prototype

The earlier MetaAPI and PostgreSQL/Alembic recorder code is historical reference material only. It is not the active market-data or persistence architecture.
