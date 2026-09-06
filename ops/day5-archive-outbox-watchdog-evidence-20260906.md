# Day 5 — Archive Outbox Durability Watchdog Evidence — 2026-09-06

## Scope

AIDY operational-resilience hardening only. Day 5 closes the observability gap between operational D1 evidence and durable R2 archival.

The existing archive flush already isolates one failing R2 item from later items in the same batch. Day 5 adds a production watchdog so an old or repeatedly failing pending item cannot remain invisible behind a healthy Worker/capture heartbeat.

No Worker capture/trading logic is changed. No D1 writes are performed by the watchdog. No Twelve Data, MetaAPI or Vantage calls are made by the watchdog. Formal-forward behaviour is unchanged.

## Watchdog contract

The production watchdog:

- runs every 10 minutes at `8,18,28,38,48,58 * * * *`;
- performs two bounded, index-driven D1 reads: Gold archive outbox and cross-market archive outbox;
- reads at most 25 pending rows from each outbox;
- fails closed if either bounded sample reaches its 25-row cap;
- reports pending/retrying/poison counts, maximum attempts, oldest pending age and up to five worst items;
- treats a pending item older than 900 seconds as stale;
- treats an item with 3 or more attempts as poison;
- allows recent pending/retrying items inside the 900-second grace without a false alert;
- uses bounded API retry for transient Cloudflare failures;
- saves one diagnostic JSON artifact on every run;
- opens/comments one GitHub issue while unhealthy;
- closes the issue once the outbox returns to fully healthy.

## Existing poison isolation proof

The repository-level `AidyMarketRepository.flush_archive_outbox()` catches an individual R2 write failure, records that failure and continues to the next item.

Day 5 acceptance explicitly injected two items:

1. `poison` -> synthetic R2 `RuntimeError`;
2. `healthy` -> successful archive write.

Result:

- attempted: `2`
- failed: `1`
- archived: `1`
- healthy item continued after poison: `true`
- result: PASS

## Focused tests

Acceptance run:

- GitHub Actions run: `34030028748`
- job: `101477737629`
- candidate SHA: `3aa8f3e57694256cb744720ae64f9371a1a83669`
- conclusion: `success`

Focused gates:

- Ruff: PASS
- Day 5 watchdog + existing storage-contract tests: `9 passed`
- poison isolation integration proof: PASS
- stale classification: PASS at `960` seconds
- poison classification: PASS at `3` attempts and only `120` seconds age
- recent retry classification: PASS at `180` seconds and `1` attempt
- notification channel: PASS

## Live production D1 proof

Live bounded production sample at `2026-09-06T11:22:06Z`:

Gold archive outbox:

- pending rows returned: `0`
- rows_read: `1`
- rows_written: `0`
- changes: `0`
- total_attempts: `1`

Cross-market archive outbox:

- pending rows returned: `0`
- rows_read: `1`
- rows_written: `0`
- changes: `0`
- total_attempts: `1`

Evaluator result:

- status: `healthy`
- alert: `false`
- pending sample count: `0`
- retrying count: `0`
- poison count: `0`
- max attempts: `0`
- sample_truncated: `false`

## Synthetic alert-path proofs

Stale item:

- age: `960s`
- attempts: `0`
- result: `stale`
- alert: `true`

Poison item:

- age: `120s`
- attempts: `3`
- result: `poison`
- alert: `true`

Recent retry:

- age: `180s`
- attempts: `1`
- result: `pending_recent`
- alert: `false`

Notification path:

- synthetic test issue: `#89`
- created successfully
- closed immediately after proof
- result: PASS

## Acceptance artifact

- artifact ID: `9988287136`
- name: `day5-archive-outbox-34030028748`
- SHA-256: `1988ad6c20c3663a6dcc990a20c8d7540a7336c41ee585ccbf1b0a36337d9346`
- contains four Day 5 diagnostic JSON files

## Safety boundary / deferred Day 6 change

Day 5 deliberately does not alter the live archive schema or retry scheduler before the Sunday gold open. The current flush is already fault-isolated; Day 5 makes persistent poison/backlog visible immediately.

Day 6 is the controlled runtime/schema improvement: bounded backoff and explicit dead-letter state so a permanently failing item is not retried forever. That change must preserve evidence truth, continuity-auditor semantics and capture independence.

## Final production gate

Day 5 is GREEN only after:

1. the one-off acceptance workflow is removed from the merge candidate;
2. protected checks and full repository regression pass;
3. the durable watchdog is merged to `main`;
4. the merge-triggered production archive watchdog succeeds from the merged SHA;
5. its diagnostic artifact exists;
6. no false issue is raised against the currently healthy outbox.
