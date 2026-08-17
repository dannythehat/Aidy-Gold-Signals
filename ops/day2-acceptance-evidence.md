# Day 2 acceptance evidence

Status: Passed

- Acceptance commit: `74f6261b7e693f280dde863c28e76a071166530e`
- Acceptance run: https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/31999675627
- Genuine scheduled capture: `2026-08-17T05:57:43+00:00`
- Scheduler path: `aidy-signals-scheduler-test` Cron (`* * * * *`) -> `aidy-capture-test` Queue -> `aidy-signals-test` Python consumer
- Capture status: `complete`
- Historical Day 2 position observation: `[]` (superseded as an AIDY requirement
  by the 17 August market-data boundary correction; no new captures may read or
  store broker positions)
- Linked closed-candle timeframes: `1m, 5m, 15m, 1h, 4h, 1d`
- PIT Fed linkage: passed (`first_observed_at <= captured_at`)
- R2 objects verified: 8
- Archive outbox: pending 0, failed 0
- Queue backlog: 0
- Local verification of the exact deployed fix: 35 tests passed

The failed queue exception probe was not a consumer failure: it expected an exception object, but the corrected consumer completed successfully and therefore wrote no exception object. The succeeding consumer proof and final no-injection gate are the authoritative evidence.

Day 2 remains valid proof of the scheduled Cloudflare capture and D1/R2 archive
pipeline. It is not approval to share Super Signals credentials or to keep
broker-account state in AIDY. Checked-in capture and Cron configs are now safe-off
until an independently owned AIDY market-data source is approved.
