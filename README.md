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
- **Cloudflare D1** — lightweight operational state such as decision/publication ledgers, watcher state and idempotency metadata.
- **Cloudflare R2** — durable append-only raw and Parquet historical Gold archive.
- **Google BigQuery** — historical analytics warehouse for regime research, feature studies, analogue retrieval, outcome analysis and evaluation datasets.
- **Telegram** — provider publication boundary to Super Signals.

The earlier PostgreSQL/Alembic extraction from the 15 August prototype is preserved only as design/reference evidence while its persistence layer is refactored. PostgreSQL and Render are not the target AIDY production data stack.
