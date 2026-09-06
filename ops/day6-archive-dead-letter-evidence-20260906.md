# Day 6 — Archive Dead-Letter Resilience — 2026-09-06

## Scope

AIDY production hardening only. Day 6 adds bounded retry, backoff and terminal dead-letter semantics to the D1 -> R2 archive outbox while preserving capture independence and the existing legacy `status` contract.

No Super Signals production files were touched. No real-money path changed. Formal-forward remains OFF.

## Runtime contract

For both `archive_outbox` and `cross_market_archive_outbox`:

- first R2 delivery failure -> `backoff`, retry due after 60 seconds;
- second due failure -> `backoff`, retry due after 300 seconds;
- third due failure -> `dead_letter`, no further automatic retry;
- a poison item never prevents later healthy items in the same flush from archiving;
- dead-letter rows remain visible through the legacy `status='pending'` surface, so existing continuity/watchdog checks continue to fail closed rather than hiding them;
- successful retry transitions to `archived`, clears `last_error` and `next_attempt_at`;
- new capture evidence can still commit while an old item is dead-lettered.

## Migration safety

Migration `0014_archive_delivery_state.sql` is additive:

- legacy `status` remains unchanged (`pending` / `archived`);
- new columns: `delivery_state`, `next_attempt_at`, `first_failed_at`, `dead_lettered_at`;
- existing archived rows map to `delivery_state='archived'`;
- existing pending rows map to `delivery_state='pending'`;
- due-selection indexes are added for both outbox tables.

Old Worker code ignores the new columns, so migration-first deployment is rollback-compatible.

## Pre-merge acceptance

Initial branch acceptance run: `34037789736`

Results:

- Ruff: PASS
- compileall: PASS
- focused archive/storage suite: **15 passed**
- full repository regression: **1199 passed**

Adversarial proof includes:

1. legacy-state migration mapping;
2. first failure enters backoff;
3. immediate retry is suppressed;
4. third due failure becomes dead-letter;
5. dead-letter is no longer selected for retry;
6. healthy item still archives after poison failure in the same flush;
7. successful retry clears error and archives;
8. cross-market outbox follows the same lifecycle;
9. new capture evidence still commits after a poison item reaches dead-letter.

PR `#92` passed:

- Evidence Semantic Change Gate: PASS
- AIDY Day 6 Archive Dead Letter Acceptance: PASS
- AIDY Day 53 Twelve Data OHLC Adapter / acceptance: PASS

PR `#92` merged Day 6 runtime/schema code to `main`.

## Rollout correction

The first merged-main rollout run `34038088226` stopped before migration/deploy because its config-build step used system Python and could not import the project package (`ModuleNotFoundError: aidy`). Production was not mutated.

PR `#93` changed project-importing rollout/rollback config validation to `uv run python`. All three protected checks passed again, and PR `#93` merged.

## Final production gate — PASS

Final merged `main` SHA deployed:

`ab13ce3b8d7e4a8e53b5e4ccb4162c7126f7833a`

Production rollout:

- workflow run: `34038324207`
- job: `101500376792`
- conclusion: **success**
- focused archive/storage suite on merged main: **15 passed**
- full repository regression on merged main: **1199 passed**
- migration `0014_archive_delivery_state.sql`: **applied successfully**
- migration commands executed: `13`
- Worker deployed: `aidy-signals-test`
- Worker version ID: `9b85ac4a-e9b0-49aa-8e36-361fa215bb35`
- queue consumer binding remained: `aidy-capture-test`
- capture enabled: `true`
- market data source: `twelve_data`
- market data ownership: `public_independent`
- market poll seconds: `300`
- formal-forward enabled: `false`
- Twelve bootstrap enabled: `false`
- health endpoint: **PASS**
- production gold pending archive states: `[]`
- production cross-market pending archive states: `[]`
- production dead-letter backlog: `0`
- pre-rollout scheduled-capture heartbeat: `2026-09-06T10:20:49.348999+00:00`, succeeded
- post-deploy fresh scheduled-capture heartbeat: `2026-09-06T14:11:52.774000+00:00`, succeeded
- heartbeat proof attempts: `2`
- D1 rows read at final gate: `881129`
- D1 alarm threshold: `3250000`
- rollback step: correctly skipped because all live gates passed

**Day 6: GREEN — merged, migrated, deployed and production-verified.**

## Next

Day 7 starts the intelligence-facing phase: provider identity, style and behavioural profile versioning, while keeping all learning forward-only and shadow-safe until later evidence gates authorize more.