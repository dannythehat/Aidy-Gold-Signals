# Day 3 safe-deploy evidence

- Trigger commit: ba85c202439184420b16cefd00ffba4de1c1c412
- Observed at UTC: 2026-08-19T08:56:48Z
- Dependencies: PASS
- Cloudflare credentials present: PASS
- Ruff/compile/tests: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Safe-off config built: PASS
- D1 migrations: PASS
- Worker safe-off deploy: PASS
- Scheduler safe-off deploy: PASS
- Health + continuity fail-closed proof: PASS

## ruff output
```text
All checks passed!
```

## compile output
```text
```

## pytest output
```text
...............................................                          [100%]
47 passed in 0.56s
```

## worker-deploy output
```text
┌─────────────────────────────────────────────────┬────────┬────────────┐
│ Name                                            │ Type   │ Size       │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/__init__.py                                │ python │ 0.03 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/cloudflare_storage.py                      │ python │ 24.43 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/config.py                                  │ python │ 4.51 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/continuity_auditor.py                      │ python │ 16.58 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/db.py                                      │ python │ 0.28 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/fed_recorder.py                            │ python │ 3.50 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/fed_rss.py                                 │ python │ 8.35 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/market_recorder.py                         │ python │ 16.18 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/market_repository.py                       │ python │ 8.60 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/metaapi_read_gateway.py                    │ python │ 5.69 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/runtime.py                                 │ python │ 4.25 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/storage_contracts.py                       │ python │ 4.97 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/SOURCES.txt          │ text   │ 0.93 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/dependency_links.txt │ text   │ 0.00 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/requires.txt         │ text   │ 0.08 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/top_level.txt        │ text   │ 0.00 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ Vendored Modules                                │        │ 727.10 KiB │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ Total (93 modules)                              │        │ 825.50 KiB │
└─────────────────────────────────────────────────┴────────┴────────────┘
Total Upload: 832.23 KiB / gzip: 179.14 KiB
Worker Startup Time: 1241 ms
Your Worker has access to the following bindings:
Binding                                                        Resource                  
env.AIDY_OPS (aidy-ops-test)                                   D1 Database               
env.AIDY_MEMORY (aidy-memory-test)                             R2 Bucket                 
env.AIDY_ENV ("test")                                          Environment Variable      
env.AIDY_CAPTURE_ENABLED ("false")                             Environment Variable      
env.AIDY_MARKET_DATA_SOURCE ("metaapi")                        Environment Variable      
env.AIDY_MARKET_POLL_SECONDS ("60")                            Environment Variable      
env.AIDY_SLOW_POLL_SECONDS ("300")                             Environment Variable      
env.AIDY_MARKET_CLOSED_BACKOFF_SECONDS ("900")                 Environment Variable      
env.AIDY_MARKET_STALE_SECONDS ("300")                          Environment Variable      
env.AIDY_FED_RSS_POLL_SECONDS ("120")                          Environment Variable      
env.AIDY_ARCHIVE_FLUSH_LIMIT ("100")                           Environment Variable      

Uploaded aidy-signals-test (8.26 sec)
Deployed aidy-signals-test triggers (1.98 sec)
  https://aidy-signals-test.dannythehat2.workers.dev
  Consumer for aidy-capture-test
Current Version ID: c8ebe7c8-b4b5-4a61-aa8e-5f6ab7e75476
```

## scheduler-deploy output
```text

 ⛅️ wrangler 4.124.0
────────────────────
Total Upload: 0.31 KiB / gzip: 0.20 KiB
Worker Startup Time: 5 ms
Your Worker has access to the following bindings:
Binding                                 Resource      
env.AIDY_CAPTURE_QUEUE (inherited)      Queue         

Uploaded aidy-signals-scheduler-test (1.29 sec)
Deployed aidy-signals-scheduler-test triggers (0.57 sec)
  https://aidy-signals-scheduler-test.dannythehat2.workers.dev
  Producer for aidy-capture-test
Current Version ID: f5a9137b-ad69-46d3-a015-366d1cf3c9d8
```

## Health
```json
{"service": "aidy-signals", "status": "ok", "runtime": "cloudflare-workers", "environment": "test", "capture_enabled": false, "scheduler": "queue-consumer"}
```

## Safe-off continuity response
HTTP 503
```json
{"ok": false, "report": {"window_start": "2026-08-19T08:51:00+00:00", "window_end": "2026-08-19T08:56:00+00:00", "passed": false, "failure_reasons": ["capture_disabled", "market_data_ownership_unconfirmed", "unexpected_or_missing_market_data_source", "material_capture_cycles_missing", "stale_quotes_present", "partial_snapshots_present", "unavailable_snapshots_present", "required_timeframe_missing"], "expected_source": "metaapi", "observed_sources": [], "expected_cycles": 5, "observed_cycles": 0, "missing_cycles": 5, "missing_cycle_ratio": 1.0, "max_capture_gap_seconds": 300, "snapshots_complete": 0, "snapshots_partial": 0, "snapshots_unavailable": 0, "quote_age_p50_seconds": null, "quote_age_p95_seconds": null, "quote_age_max_seconds": null, "stale_quote_count": 0, "source_error_counts": {}, "timeframe_audits": {"1m": {"observed_candles": 0, "revision_rows": 0, "gap_count": 0, "missing_intervals": 0, "max_gap_seconds": 0}, "5m": {"observed_candles": 0, "revision_rows": 0, "gap_count": 0, "missing_intervals": 0, "max_gap_seconds": 0}, "15m": {"observed_candles": 0, "revision_rows": 0, "gap_count": 0, "missing_intervals": 0, "max_gap_seconds": 0}, "1h": {"observed_candles": 0, "revision_rows": 0, "gap_count": 0, "missing_intervals": 0, "max_gap_seconds": 0}, "4h": {"observed_candles": 0, "revision_rows": 0, "gap_count": 0, "missing_intervals": 0, "max_gap_seconds": 0}, "1d": {"observed_candles": 0, "revision_rows": 0, "gap_count": 0, "missing_intervals": 0, "max_gap_seconds": 0}}, "archive_population": 0, "archive_checked": 0, "archive_pending": 0, "archive_retry_attempts": 0, "archive_failed_rows": 0, "archive_missing_objects": 0, "archive_unverified_rows": 0}}
```

## Remaining live gate
Enable capture only with an independently owned AIDY market-data source, restore the one-minute Cloudflare scheduler, then require a clean 5+ minute /day3/continuity window with D1/R2 reconciliation.
