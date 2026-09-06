# Day 3 — Production Hardening Evidence — 2026-09-06

## Scope

AIDY operational-resilience hardening only. This work did not deploy the Cloudflare Worker, write to D1, call MetaAPI/Vantage, or change formal-forward trading behavior.

## Exact 24-hour Cloudflare D1 rows-read audit

Requested half-open UTC window:

- start: `2026-09-05T05:59:00Z`
- end: `2026-09-06T05:59:00Z`
- database: `3588d82a-d686-4430-872d-d4c0e62c3d5d`
- dataset: `d1AnalyticsAdaptiveGroups`
- start filter: `datetime_geq`
- end filter: `datetime_lt`

Authenticated Cloudflare GraphQL schema introspection proved the dataset accepts sub-day datetime filters. The exact query returned:

- **rows_read: `2,456,668`**

Evidence:

- GitHub Actions run: `34022557047`
- job: `101457668896`
- conclusion: `success`

## Durable D1 budget monitor hardening

The recurring D1 budget monitor was refactored into `scripts/aidy_d1_budget_monitor.py` and the production workflow `.github/workflows/aidy-d1-row-budget-alert.yml` now calls it.

Hardening added:

- maximum 3 query attempts;
- bounded exponential backoff;
- retry only for transport errors, HTTP 429/5xx, and recognized transient Cloudflare GraphQL errors;
- no retry loop for permanent GraphQL/schema failures;
- deterministic UTC-day aggregation;
- durable JSON diagnostic on both success and failure;
- diagnostic artifact uploaded on every workflow execution;
- existing 3,250,000 rows-read warning threshold retained;
- existing GitHub issue alert channel retained.

## Acceptance evidence

Acceptance run:

- GitHub Actions run: `34022768672`
- job: `101458270101`
- conclusion: `success`

Passed gates:

1. monitor compiles;
2. bounded retry/backoff proof: two synthetic transient failures followed by success on attempt 3, with backoff `0.25s`, `0.5s`;
3. schedule proof: `17 * * * *`, UTC day aggregation;
4. authenticated current Cloudflare D1 query succeeded on attempt 1;
5. forced connection failure exhausted exactly 3 attempts and preserved an error diagnostic;
6. synthetic alert threshold (`1`) set `alert=true` using a real Cloudflare analytics read;
7. configured GitHub issue notification path created and immediately closed test issue `#82`;
8. three JSON diagnostic files were preserved as an Actions artifact.

Acceptance snapshot during the run:

- UTC day: `2026-09-06`
- rows_read at query time: `661,380`
- production warning threshold: `3,250,000`
- free-tier reference ceiling: `5,000,000`
- alert at production threshold: `false`

Acceptance artifact:

- artifact ID: `9986046938`
- name: `day3-operational-hardening-34022768672`
- SHA-256: `82673952ed23ddd4a13b332e5ce0c626c5cf30096c529dce19c23f7544d916a2`

## Safety boundary

The one-off exact-window and synthetic acceptance workflows were removed from the merge candidate after successful proof. Only the durable production monitor hardening and this evidence record were merged to `main`.

## Final production gate — PASS

PR `#83` merged to `main` at SHA `9540a3e24e63af29cffac4b9c7585b2f8e9ec260`.

The merge-triggered production `AIDY D1 Row Budget Alert` workflow completed successfully:

- GitHub Actions run: `34022918687`
- job: `101458680273`
- conclusion: `success`
- UTC day: `2026-09-06`
- real Cloudflare rows_read at query time: `661,473`
- configured warning threshold: `3,250,000`
- alert: `false`
- attempts: `1`
- alert-issue step: correctly skipped
- production diagnostic artifact ID: `9986094184`
- artifact name: `aidy-d1-budget-diagnostic-34022918687`
- artifact SHA-256: `3124ebddfee80d3e4a938ea4c48813ef84a196ff3af420a2779556981ab9cc83`

**Day 3 production-hardening acceptance: GREEN.**
