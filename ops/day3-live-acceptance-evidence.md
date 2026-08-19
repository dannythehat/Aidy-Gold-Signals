# Day 3 broker-free live-acceptance evidence

- Trigger commit: 8d73b7e8fa192f4ac755048e16832eac7842a1bf
- Observed at UTC: 2026-08-19T09:55:01Z
- Public Gold API preflight: PASS
- Code gate: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Live config: PASS
- Live capture/scheduler deployed: PASS
- Live health: PASS
- Scheduled soak: PASS
- Day 3 continuity acceptance: PASS
- Failure rollback: NOT_NEEDED

## ruff
```text
All checks passed!
```

## compile
```text
```

## pytest-live
```text
.....................................................                    [100%]
53 passed in 0.60s
```

## live-worker-deploy
```text
INFO     Resolved 3 requirements from                                           
         /home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/pylock.toml.     
INFO     Installing packages into python_modules...                             
INFO     Packages installed in python_modules.                                  
INFO     Installing packages into .venv-workers...                              
INFO     Packages installed in .venv-workers.                                   
INFO     Passing command to npx wrangler: npx --yes wrangler deploy             

 ⛅️ wrangler 4.124.0
────────────────────
Attaching additional modules:
┌─────────────────────────────────────────────────┬────────┬────────────┐
│ Name                                            │ Type   │ Size       │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/__init__.py                                │ python │ 0.03 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/cloudflare_storage.py                      │ python │ 24.43 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/config.py                                  │ python │ 3.83 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/continuity_auditor.py                      │ python │ 16.58 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/db.py                                      │ python │ 0.28 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/fed_recorder.py                            │ python │ 3.50 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/fed_rss.py                                 │ python │ 8.35 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/gold_api_gateway.py                        │ python │ 3.61 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/market_recorder.py                         │ python │ 16.18 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/market_repository.py                       │ python │ 8.60 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/metaapi_read_gateway.py                    │ python │ 5.69 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/reference_continuity.py                    │ python │ 10.40 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/reference_price_recorder.py                │ python │ 7.01 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/runtime.py                                 │ python │ 3.73 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/storage_contracts.py                       │ python │ 4.97 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/SOURCES.txt          │ text   │ 1.09 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/dependency_links.txt │ text   │ 0.00 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/requires.txt         │ text   │ 0.08 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/top_level.txt        │ text   │ 0.00 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ Vendored Modules                                │        │ 727.10 KiB │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ Total (96 modules)                              │        │ 845.48 KiB │
└─────────────────────────────────────────────────┴────────┴────────────┘
Total Upload: 852.00 KiB / gzip: 183.39 KiB
Worker Startup Time: 1204 ms
Your Worker has access to the following bindings:
Binding                                                            Resource                  
env.AIDY_OPS (aidy-ops-test)                                       D1 Database               
env.AIDY_MEMORY (aidy-memory-test)                                 R2 Bucket                 
env.AIDY_ENV ("test")                                              Environment Variable      
env.AIDY_CAPTURE_ENABLED ("true")                                  Environment Variable      
env.AIDY_MARKET_DATA_SOURCE ("gold_api")                           Environment Variable      
env.AIDY_MARKET_DATA_OWNERSHIP ("public_independent")              Environment Variable      
env.AIDY_MARKET_POLL_SECONDS ("60")                                Environment Variable      
env.AIDY_SLOW_POLL_SECONDS ("300")                                 Environment Variable      
env.AIDY_MARKET_CLOSED_BACKOFF_SECONDS ("900")                     Environment Variable      
env.AIDY_MARKET_STALE_SECONDS ("300")                              Environment Variable      
env.AIDY_FED_RSS_POLL_SECONDS ("120")                              Environment Variable      
env.AIDY_ARCHIVE_FLUSH_LIMIT ("100")                               Environment Variable      

Uploaded aidy-signals-test (7.56 sec)
Deployed aidy-signals-test triggers (2.23 sec)
  https://aidy-signals-test.dannythehat2.workers.dev
  Consumer for aidy-capture-test
Current Version ID: 0fc96598-f998-4bc0-951e-b27d53b80e65

Cloudflare collects anonymous telemetry about your usage of Wrangler. Learn more at https://github.com/cloudflare/workers-sdk/tree/main/packages/wrangler/telemetry.md
```

## live-scheduler-deploy
```text

 ⛅️ wrangler 4.124.0
────────────────────
Total Upload: 0.31 KiB / gzip: 0.20 KiB
Worker Startup Time: 4 ms
Your Worker has access to the following bindings:
Binding                                 Resource      
env.AIDY_CAPTURE_QUEUE (inherited)      Queue         

Uploaded aidy-signals-scheduler-test (1.46 sec)
Deployed aidy-signals-scheduler-test triggers (0.73 sec)
  https://aidy-signals-scheduler-test.dannythehat2.workers.dev
  schedule: * * * * *
  Producer for aidy-capture-test
Current Version ID: 38c4fce8-7470-4a38-8af0-c038e3de5e1a
```

## Gold API preflight
```json
{"currency":"USD","currencySymbol":"$","exchangeRate":1.0,"name":"Gold","price":4360.600098,"symbol":"XAU","updatedAt":"2026-08-19T09:47:37Z","updatedAtReadable":"a few seconds ago"}
```

## Live health
```json
{"service": "aidy-signals", "status": "ok", "runtime": "cloudflare-workers", "environment": "test", "capture_enabled": true, "market_data_source": "gold_api", "market_data_ownership": "public_independent", "scheduler": "queue-consumer"}
```

## Continuity
HTTP 200
```json
{"ok": true, "report": {"window_start": "2026-08-19T09:50:00+00:00", "window_end": "2026-08-19T09:55:00+00:00", "passed": true, "failure_reasons": [], "expected_source": "gold_api", "observed_sources": ["gold_api"], "expected_cycles": 5, "observed_cycles": 5, "missing_cycles": 0, "missing_cycle_ratio": 0.0, "max_capture_gap_seconds": 0, "snapshots_complete": 5, "snapshots_partial": 0, "snapshots_unavailable": 0, "quote_age_p50_seconds": 16.4, "quote_age_p95_seconds": 18.171, "quote_age_max_seconds": 18.171, "stale_quote_count": 0, "source_error_counts": {}, "timeframe_audits": {}, "archive_population": 5, "archive_checked": 5, "archive_pending": 0, "archive_retry_attempts": 0, "archive_failed_rows": 0, "archive_missing_objects": 0, "archive_unverified_rows": 0}}
```
