# Day 6 — Archive Dead-Letter Resilience — 2026-09-06

## Scope

AIDY production hardening only. Day 6 adds bounded retry, backoff and terminal dead-letter semantics to the D1 -> R2 archive outbox while preserving capture independence and the existing legacy `status` contract.

No Super Signals production files are touched. No real-money path is changed. Formal-forward remains OFF.

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

Because old Worker code ignores the new columns, migration-first deployment is rollback-compatible. If the Day 6 Worker fails live acceptance, the rollout redeploys the previous main SHA while leaving the harmless additive schema in place.

## Pre-merge acceptance

Branch: `ops/day6-archive-dead-letter-20260906`

Acceptance run: `34037789736`

Candidate SHA at successful run: `c99ff4e7be3702c2f20853411a46b9df75ff2638`

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

## Production gate

Day 6 is not GREEN until protected PR checks pass, the merge-triggered rollback-ready rollout succeeds on exact merged `main`, production D1 shows the new schema, no unexpected dead-letter backlog exists, health remains capture-on / Twelve Data / public-independent / formal-forward OFF, a new scheduled-capture heartbeat advances after deploy, and D1 reads remain below the configured alarm.
