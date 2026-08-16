# AIDY Gold Signals — Locked Architecture

Decision date: 2026-08-16

## Product boundary

AIDY Signals is a standalone Gold signal provider. Super Signals is a downstream consumer only, through the AIDY Signals Telegram group.

AIDY does not share Super Signals code, database, runtime, risk engine, parser, broker execution layer, or deployment stack.

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

## Explicit exclusions

- No Render service, database, worker or deployment for AIDY unless the owner explicitly reverses this decision.
- No GitHub Actions.
- No direct follower-trade execution from AIDY.
- No live-money capability during build and paper evaluation.

## Superseded prototype

The PostgreSQL/Alembic extraction from the 15 August prototype is retained temporarily as reference for recorder semantics, append-only revisions and tests. It is not the target persistence implementation and must be refactored behind Cloudflare/BigQuery storage interfaces before Day 1 is closed.
