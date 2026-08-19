# AIDY Gold Signals

Standalone AIDY Signals Gold trading intelligence and Telegram signal-provider project.

AIDY and Super Signals are separate systems. AIDY produces signals; Super Signals may later consume the AIDY Telegram group exactly like any other external provider.

## Permanent boundaries

- Separate repository and runtime from Super Signals.
- No Render dependency for AIDY. Render remains Super Signals infrastructure only.
- GitHub Actions is permitted for CI, tests, Cloudflare provisioning/migrations and deployment transport. AIDY runtime and trading intelligence execute on Cloudflare, not GitHub Actions.
- No direct MT5 execution from the AIDY intelligence layer.
- No live-money capability during build and paper testing.
- Point-in-time market evidence and decision auditability are mandatory.
- AIDY never reads broker/follower positions and never uses broker, MT5, MetaAPI, Vantage or Super Signals credentials for market-data capture.

## Locked AIDY data/runtime architecture

- **Cloudflare Workers** — AIDY serverless runtime and orchestration.
- **Cloudflare D1** — lightweight operational state and the evidence/archive outbox.
- **Cloudflare R2** — durable append-only raw and future Parquet historical Gold archive.
- **Google BigQuery** — historical analytics warehouse for regime research, feature studies, analogue retrieval, outcome analysis and evaluation datasets.
- **Telegram** — future provider publication boundary to Super Signals.

## Broker-free market-data architecture — 19 August 2026

AIDY's live reference-price recorder is deliberately independent of trading accounts.

- Primary live XAU/USD reference source: **Gold-API** (`https://api.gold-api.com/price/XAU`).
- Authentication: **none**. The live price endpoint is keyless.
- Runtime source identity: `AIDY_MARKET_DATA_SOURCE=gold_api`.
- Runtime provenance gate: `AIDY_MARKET_DATA_OWNERSHIP=public_independent`.
- AIDY stores the Gold reference price as `mid`; it does not invent bid, ask or spread when the upstream does not provide them.
- AIDY does not fabricate OHLC candles from one-minute price snapshots. Genuine OHLC and deeper historical research data remain a separate ingestion product.
- The old MetaAPI adapter is historical prototype code only and is not part of the active AIDY runtime path.

ChatGPT is a build tool, not an AIDY runtime dependency. The OpenAI API remains future trading intelligence and is unrelated to storage, broker access or the market-price source.

The earlier PostgreSQL/Alembic extraction from the prototype is preserved only as design/reference evidence. PostgreSQL and Render are not AIDY production dependencies.

## Day 1 Cloudflare test bootstrap

The repository carries an account-neutral Wrangler template and a Windows PowerShell bootstrap as a fallback for an authenticated development machine:

```powershell
.\scripts\bootstrap-cloudflare-test.ps1
```

The bootstrap path provisions the named Cloudflare test resources, applies `migrations/d1`, deploys `aidy-signals-test`, and verifies the D1 -> outbox -> R2 storage round trip.

`AIDY_CAPTURE_ENABLED` remains `false` in the checked-in test config. The live acceptance workflow deliberately turns it on only in the real test deployment after the public source and code gates pass.

Do not commit generated local Wrangler configs, `.dev.vars`, Cloudflare auth state, API tokens or account-specific resource IDs.

## Day 3 continuity gate

Day 3 adds a deterministic evidence-health auditor before any trading intelligence is allowed to trust the recorder. The test Worker exposes this read-only endpoint only when `AIDY_ENV=test`:

```text
GET /day3/continuity?minutes=10&archive_limit=40
```

For the broker-free Gold-API source, the endpoint returns HTTP `200` only when:

- capture is enabled;
- the configured source is `gold_api` and marked `public_independent`;
- every expected one-minute scheduled reference-price observation is present;
- quote timestamps are fresh;
- no partial or unavailable snapshots exist in the acceptance window;
- no upstream source errors are recorded;
- the archive outbox is caught up; and
- the bounded D1 archive sample exists in R2.

Any failed condition returns HTTP `503` with stable machine-readable failure reasons.

**Day 3 does not pretend that sparse reference-price observations are candles.** Candle integrity is evaluated only once a genuine OHLC research source has been ingested.
