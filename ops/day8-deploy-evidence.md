# Day 8 test Worker deployment evidence

- Trigger commit: 80dec7de222c9fe651c79508700473c28669f6b0
- Observed at UTC: 2026-08-19T15:27:27Z
- Acceptance preflight: PASS
- Live config: PASS
- Worker deployed: PASS
- Broker-free live health: PASS

## deploy
```text
Using CPython 3.13.15 interpreter at: /opt/hostedtoolcache/Python/3.13.15/x64/bin/python3.13
Creating virtual environment at: .venv-workers
Activate with: .venv-workers/bin/activate
Downloading pyodide-3.13.2-emscripten-wasm32-musl (download) (6.4MiB)
 Downloaded pyodide-3.13.2-emscripten-wasm32-musl (download)
Using CPython 3.13.2
Creating virtual environment at: .venv-workers/pyodide-venv
Activate with: .venv-workers/pyodide-venv/bin/activate
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
│ aidy/bigquery_exporter.py                       │ python │ 14.42 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/bls_calendar_parser.py                     │ python │ 5.70 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/cloudflare_storage.py                      │ python │ 24.43 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/config.py                                  │ python │ 3.95 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/continuity_auditor.py                      │ python │ 16.58 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/db.py                                      │ python │ 0.28 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/feature_engine.py                          │ python │ 19.78 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/fed_recorder.py                            │ python │ 4.13 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/fed_rss.py                                 │ python │ 8.35 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/fomc_calendar_parser.py                    │ python │ 2.44 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/gold_api_gateway.py                        │ python │ 3.61 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/historical_backfill.py                     │ python │ 26.11 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/macro_event_windows.py                     │ python │ 4.28 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/market_recorder.py                         │ python │ 16.18 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/market_repository.py                       │ python │ 8.60 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/market_sessions.py                         │ python │ 2.23 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/metaapi_read_gateway.py                    │ python │ 5.69 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/official_macro.py                          │ python │ 25.00 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/official_macro_recorder.py                 │ python │ 5.08 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/pit_reconstruction.py                      │ python │ 9.63 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/reference_continuity.py                    │ python │ 10.40 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/reference_price_recorder.py                │ python │ 6.74 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/runtime.py                                 │ python │ 4.42 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/storage_contracts.py                       │ python │ 4.97 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/SOURCES.txt          │ text   │ 1.69 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/dependency_links.txt │ text   │ 0.00 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/requires.txt         │ text   │ 0.08 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/top_level.txt        │ text   │ 0.00 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ Vendored Modules                                │        │ 727.60 KiB │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ Total (107 modules)                             │        │ 962.40 KiB │
└─────────────────────────────────────────────────┴────────┴────────────┘
Total Upload: 968.92 KiB / gzip: 209.19 KiB
Worker Startup Time: 1403 ms
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
env.AIDY_MACRO_POLL_SECONDS ("900")                                Environment Variable      

Uploaded aidy-signals-test (8.35 sec)
Deployed aidy-signals-test triggers (2.63 sec)
  https://aidy-signals-test.dannythehat2.workers.dev
  Consumer for aidy-capture-test
Current Version ID: 7a99c240-d574-4aa1-8f56-bad7687685f8

Cloudflare collects anonymous telemetry about your usage of Wrangler. Learn more at https://github.com/cloudflare/workers-sdk/tree/main/packages/wrangler/telemetry.md
```

## health
```json
{"service": "aidy-signals", "status": "ok", "runtime": "cloudflare-workers", "environment": "test", "capture_enabled": true, "market_data_source": "gold_api", "market_data_ownership": "public_independent", "scheduler": "queue-consumer"}
```
