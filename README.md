# AIDY Gold Signals

Standalone AIDY Signals Gold trading intelligence and Telegram signal-provider project.

AIDY and Super Signals are separate systems. AIDY produces signals; Super Signals may later consume the AIDY Telegram group exactly like any other external provider.

## Permanent boundaries

- Separate repository and runtime from Super Signals.
- No Render dependency for AIDY. Render remains Super Signals infrastructure only.
- GitHub Actions is permitted only for CI, automated tests, Cloudflare provisioning/migrations and deployment. AIDY runtime and trading intelligence never execute in GitHub Actions.
- No direct MT5 execution from the AIDY intelligence layer.
- No live-money capability during build and paper testing.
- Point-in-time market evidence and decision auditability are mandatory.
- AIDY never reads broker/follower positions and never uses Super Signals'
  Vantage/MetaAPI credentials. Market-data credentials must be AIDY-owned.

## Locked AIDY data/runtime architecture

- **Cloudflare Workers** — AIDY serverless runtime and orchestration.
- **Cloudflare D1** — lightweight operational state and the evidence/archive outbox.
- **Cloudflare R2** — durable append-only raw and Parquet historical Gold archive.
- **Google BigQuery** — historical analytics warehouse for regime research, feature studies, analogue retrieval, outcome analysis and evaluation datasets.
- **Telegram** — provider publication boundary to Super Signals.

## Market-data boundary correction — 17 August 2026

AIDY needs independent XAUUSD quotes and closed candles. It does not need a
broker execution account or follower-position state. The retained MetaAPI
adapter is now market-only, contains no positions endpoint, and is disabled in
the checked-in Cloudflare test configuration until an AIDY-dedicated source is
explicitly approved. `AIDY_MARKET_DATA_OWNERSHIP=aidy_dedicated` is a fail-closed
runtime gate; it must never be set for credentials owned or shared by Super
Signals.

ChatGPT is a build tool, not an AIDY runtime dependency. The OpenAI API remains
future Day 21 trading intelligence and is unrelated to storage or broker access.

The earlier PostgreSQL/Alembic extraction from the 15 August prototype is preserved only as design/reference evidence. PostgreSQL and Render are not AIDY production dependencies.

## Day 1 Cloudflare test bootstrap

GitHub Actions is the browser/cloud-only deployment bridge for the Day 1 test gate. It may run tests, provision the named Cloudflare test resources, apply D1 migrations, deploy the test Worker and execute the storage smoke test. It is not an AIDY runtime.

The repository also carries an account-neutral Wrangler template and a Windows PowerShell bootstrap as a fallback for an authenticated development machine:

```powershell
.\scripts\bootstrap-cloudflare-test.ps1
```

The bootstrap path:

1. checks Cloudflare CLI authentication and opens browser login when required;
2. copies `wrangler.test.example.jsonc` to ignored `wrangler.test.local.jsonc`;
3. deploys `aidy-signals-test` and provisions its test D1/R2 bindings;
4. applies `migrations/d1` to the real test D1 database;
5. calls `POST /day1/storage-smoke` and requires a real D1 -> outbox -> R2 round trip.

`AIDY_CAPTURE_ENABLED` remains `false` in the checked-in test config. The
scheduler Cron is also disabled in source until the independent AIDY market-data
boundary is accepted.

Do not commit generated local Wrangler configs, `.dev.vars`, Cloudflare auth state, API tokens or account-specific resource IDs.
