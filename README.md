# AIDY Gold Signals

Standalone AIDY Signals Gold trading intelligence and Telegram signal-provider project.

AIDY and Super Signals are separate systems. AIDY produces signals; Super Signals may later consume the AIDY Telegram group exactly like any other external provider.

## Permanent boundaries

- Separate repository and runtime from Super Signals.
- No Render dependency for AIDY. Render remains Super Signals infrastructure only.
- No GitHub Actions.
- No direct MT5 execution from the AIDY intelligence layer.
- No live-money capability during build and paper testing.
- Point-in-time market evidence and decision auditability are mandatory.

## Locked AIDY data/runtime architecture

- **Cloudflare Workers** — AIDY serverless runtime and orchestration.
- **Cloudflare D1** — lightweight operational state and the evidence/archive outbox.
- **Cloudflare R2** — durable append-only raw and Parquet historical Gold archive.
- **Google BigQuery** — historical analytics warehouse for regime research, feature studies, analogue retrieval, outcome analysis and evaluation datasets.
- **Telegram** — provider publication boundary to Super Signals.

The earlier PostgreSQL/Alembic extraction from the 15 August prototype is preserved only as design/reference evidence. PostgreSQL and Render are not AIDY production dependencies.

## Day 1 Cloudflare test bootstrap

The ChatGPT Cloudflare connector is not required. The repository carries an account-neutral Wrangler template and a Windows PowerShell bootstrap.

From the repository root on an authenticated development machine:

```powershell
.\scripts\bootstrap-cloudflare-test.ps1
```

The script:

1. checks Cloudflare CLI authentication and opens browser login when required;
2. copies `wrangler.test.example.jsonc` to ignored `wrangler.test.local.jsonc`;
3. deploys `aidy-signals-test` and lets Wrangler provision its draft D1/R2 bindings;
4. applies `migrations/d1` to the real test D1 database;
5. calls `POST /day1/storage-smoke` and requires a real D1 -> outbox -> R2 round trip.

`AIDY_CAPTURE_ENABLED` remains `false` in the Day 1 test config, so this proof does not call MetaAPI or start live recording.

Do not commit the generated local Wrangler config, `.dev.vars`, Cloudflare auth state, API tokens or account-specific resource IDs.
