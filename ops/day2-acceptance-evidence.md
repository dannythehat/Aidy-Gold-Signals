# Day 2 acceptance evidence

Status: Passed

- Acceptance commit: `74f6261b7e693f280dde863c28e76a071166530e`
- Acceptance run: https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/31999675627
- Genuine scheduled capture: `2026-08-17T05:57:43+00:00`
- Scheduler path: `aidy-signals-scheduler-test` Cron (`* * * * *`) -> `aidy-capture-test` Queue -> `aidy-signals-test` Python consumer
- Capture status: `complete`
- Position truth: `[]`
- Linked closed-candle timeframes: `1m, 5m, 15m, 1h, 4h, 1d`
- PIT Fed linkage: passed (`first_observed_at <= captured_at`)
- R2 objects verified: 8
- Archive outbox: pending 0, failed 0
- Queue backlog: 0
- Local verification of the exact deployed fix: 35 tests passed

The failed queue exception probe was not a consumer failure: it expected an exception object, but the corrected consumer completed successfully and therefore wrote no exception object. The succeeding consumer proof and final no-injection gate are the authoritative evidence.
