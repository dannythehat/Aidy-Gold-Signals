# Day 4 — Capture Freshness Watchdog Evidence — 2026-09-06

## Scope

AIDY operational-resilience hardening only. Day 4 closes the silent-capture-failure gap left by the process-level `/health` endpoint: a Worker can remain reachable and configuration-valid while the scheduler, queue, or scheduled Twelve Data capture path has stopped producing fresh evidence.

This change does not deploy or modify Worker capture/trading logic, does not write to D1, does not call Twelve Data from the watchdog, does not call MetaAPI/Vantage, and does not change formal-forward behaviour.

## Watchdog contract

The recurring watchdog:

- executes every 10 minutes at `3,13,23,33,43,53 * * * *`;
- performs one bounded, indexed read against production D1;
- reads only the latest successful `scheduled_capture` and latest scheduled request status;
- uses the canonical `aidy_gold_session_calendar_ny_v1` session semantics;
- treats Sunday 18:00 New York through Friday 17:00 New York as the trading week;
- respects the daily 17:00-18:00 New York maintenance break;
- uses a 900-second reopen grace;
- uses a 900-second stale threshold after the grace window;
- does not alert while the canonical gold session is closed;
- alerts after the grace window if no successful scheduled capture exists or the latest successful scheduled capture is older than 900 seconds;
- treats watchdog/D1 query failure as an alert condition after bounded retry;
- persists one JSON diagnostic artifact on every run;
- opens/comments one GitHub issue while stale;
- closes the open capture-freshness issue when the state recovers to `fresh`.

## D1 read-cost boundary

The heartbeat query uses existing covering indexes:

- `idx_twelve_data_request_ledger_completion_success`
- `idx_twelve_data_request_ledger_requested_at_credits`

The live production acceptance query reported:

- `rows_read: 4`
- `rows_written: 0`
- `changes: 0`
- `total_attempts: 1`

No new D1 migration is required.

## Acceptance run

Latest acceptance run:

- GitHub Actions run: `34026075398`
- job: `101467156274`
- candidate SHA: `01ddf67e9aea7ac81d10e16ebbb9cf6e8117854b`
- conclusion: `success`

Focused code gates:

- Ruff: PASS
- Day 4 focused tests: `18 passed`
- calendar equivalence tests include March DST, November DST, Sunday reopen, Friday close and the current Sunday closed session.

## Live production D1 proof

At the acceptance observation:

- latest scheduled request UTC: `2026-09-06T09:55:13.446000+00:00`
- latest scheduled request status: `succeeded`
- latest scheduled error code: `null`
- latest scheduled success UTC: `2026-09-06T09:55:13.684999+00:00`
- observed watchdog UTC: `2026-09-06T09:57:43.470222+00:00`
- success lag: `149` seconds
- canonical session state: `closed`
- watchdog status: `session_closed`
- alert: `false`

This proves both that the production scheduled-capture ledger is still updating and that an old/stale-looking timestamp will not produce a weekend false alarm when the canonical market is closed.

## Synthetic failure and recovery proofs

Open-session stale case:

- observed: `2026-09-07T12:00:00Z`
- latest success: `2026-09-07T11:44:00Z`
- success lag: `960` seconds
- latest request status: `failed`
- watchdog status: `stale`
- alert: `true`
- expected alert exit code: `2`
- result: PASS

Open-session fresh case:

- observed: `2026-09-07T12:00:00Z`
- latest success: `2026-09-07T11:54:00Z`
- success lag: `360` seconds
- watchdog status: `fresh`
- alert: `false`
- result: PASS

Sunday reopen grace case:

- observed: `2026-09-06T22:07:00Z`
- session opened: `2026-09-06T22:00:00Z`
- no scheduled success supplied
- watchdog status: `open_grace`
- alert: `false`
- result: PASS

## Notification proof

The GitHub issue notification channel was exercised with a synthetic Day 4 alert:

- test issue: `#86`
- issue created successfully
- issue closed immediately after proof
- result: PASS

## Acceptance artifact

- artifact ID: `9987087295`
- name: `day4-capture-freshness-34026075398`
- SHA-256: `935fd5ed30c571b6e5de273419dff270d0606ba2ba18812a6e8210f762633394`
- contains four Day 4 diagnostic JSON files

## Protected merge proof

PR `#87` passed both required protected checks:

- `Evidence Semantic Change Gate`: PASS
- `AIDY Day 53 Twelve Data OHLC Adapter / acceptance`: PASS
- full repository regression: PASS

PR `#87` merged to `main` at SHA `3cc699561d881203cfea712e8351fb98c19e76b6`.

## Final production gate — PASS

The merge-triggered production `AIDY Capture Freshness Watchdog` completed successfully from the exact merged `main` SHA:

- GitHub Actions run: `34026221990`
- job: `101467542665`
- `main` SHA: `3cc699561d881203cfea712e8351fb98c19e76b6`
- conclusion: `success`
- D1 query: PASS
- D1 query attempts: `1`
- latest scheduled request UTC: `2026-09-06T09:55:13.446000+00:00`
- latest scheduled request status: `succeeded`
- latest scheduled success UTC: `2026-09-06T09:55:13.684999+00:00`
- observed watchdog UTC: `2026-09-06T10:00:48.769903+00:00`
- success lag: `335` seconds
- canonical session state: `closed`
- watchdog status: `session_closed`
- alert: `false`
- alert-issue step: correctly skipped
- recovered-alert close step: correctly skipped because the market is closed rather than freshly recovered

Production diagnostic artifact:

- artifact ID: `9987127663`
- name: `aidy-capture-freshness-34026221990`
- SHA-256: `a6e61a5cd39f02a2de88b43b9fe2e1dabaf6de1f5cf6b3ca580592e14398b289`

**Day 4 production-hardening acceptance: GREEN.**
