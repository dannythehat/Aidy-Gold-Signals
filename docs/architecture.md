# AIDY Gold Signals — Locked Architecture

Decision date: 2026-08-16

## Product boundary

AIDY Signals is a standalone Gold signal provider. Super Signals is a downstream consumer only, through the AIDY Signals Telegram group.

AIDY does not share Super Signals code, database, runtime, risk engine, parser, broker execution layer, or deployment stack.

## Market-data boundary

AIDY requires XAUUSD quotes and closed candles, not a broker execution account.

- AIDY never reads broker/follower positions, orders or account state.
- Vantage execution and actual position reconciliation belong only to Super Signals.
- Super Signals MetaAPI/Vantage credentials must never be copied into AIDY.
- Any enabled AIDY market-data connection must be separately owned, separately
  credentialed and explicitly confirmed with
  `AIDY_MARKET_DATA_OWNERSHIP=aidy_dedicated`.
- The MetaAPI adapter retained from Day 2 is a disabled market-only adapter, not
  the permanent production-source decision.

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

ChatGPT is not part of the AIDY runtime. OpenAI API reasoning is planned for Day
21 as AIDY's trading intelligence. It does not store evidence and does not access
Vantage or Super Signals.

## Explicit exclusions

- No Render service, database, worker or deployment for AIDY unless the owner explicitly reverses this decision.
- No GitHub Actions runtime. Actions may be used only as explicitly approved CI
  or deployment transport.
- No direct follower-trade execution from AIDY.
- No live-money capability during build and paper evaluation.

## Day 3 evidence-health boundary

The continuity auditor is deterministic and runs against D1/R2 bindings. It
does not ask OpenAI whether the evidence is healthy. It calculates expected
versus observed scheduler cycles, quote age, snapshot status, M1/M5 candle
gaps, revision counts, source errors, archive backlog/retries and D1-to-R2
object existence. A material unknown or mismatch fails closed.

The live Day 3 gate additionally requires `AIDY_CAPTURE_ENABLED=true`,
`AIDY_MARKET_DATA_OWNERSHIP=aidy_dedicated`, and an installed adapter whose
name matches `AIDY_MARKET_DATA_SOURCE`. Super Signals credentials can never
satisfy this gate.

## Superseded prototype

The PostgreSQL/Alembic extraction from the 15 August prototype is retained temporarily as reference for recorder semantics, append-only revisions and tests. It is not the target persistence implementation and must be refactored behind Cloudflare/BigQuery storage interfaces before Day 1 is closed.
