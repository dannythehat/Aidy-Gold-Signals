# Day 9 cross-market evidence live-acceptance evidence

- Trigger commit: 9aa697d77e9efb9399f9767b18fced8ec24938e4
- Observed at UTC: 2026-08-19T16:07:02Z
- Dependencies: PASS
- Code gate: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Source/PIT structural boundary: PASS
- Repeated live source probe: PASS
- Credential preflight: PASS
- Live config: PASS
- D1 migration: PASS
- Worker deployed: PASS
- Broker-free health: PASS
- Two real Worker samples: NOT_REACHED_OR_FAILED
- D1 identity reconciliation: NOT_REACHED_OR_FAILED
- R2 reconciliation: NOT_REACHED_OR_FAILED
- BigQuery dependency: NOT_REACHED_OR_FAILED
- BigQuery double-export + PIT as-of: NOT_REACHED_OR_FAILED

## ruff
```text
All checks passed!
```

## pytest
```text
........................................................................ [ 53%]
..............................................................           [100%]
134 passed in 0.77s
```

## migration
```text

 ⛅️ wrangler 4.124.0
────────────────────
Resource location: remote 

✅ No migrations to apply!
```

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

Cloudflare collects anonymous telemetry about your usage of Wrangler. Learn more at https://github.com/cloudflare/workers-sdk/tree/main/packages/wrangler/telemetry.md
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
│ aidy/config.py                                  │ python │ 4.11 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/continuity_auditor.py                      │ python │ 16.58 KiB  │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/cross_market.py                            │ python │ 8.81 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/cross_market_asof.py                       │ python │ 4.67 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/cross_market_bigquery.py                   │ python │ 5.04 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/cross_market_recorder.py                   │ python │ 2.54 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/cross_market_storage.py                    │ python │ 8.87 KiB   │
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
│ aidy/reference_price_recorder.py                │ python │ 6.75 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/runtime.py                                 │ python │ 5.34 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy/storage_contracts.py                       │ python │ 6.16 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/SOURCES.txt          │ text   │ 1.87 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/dependency_links.txt │ text   │ 0.00 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/requires.txt         │ text   │ 0.08 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/top_level.txt        │ text   │ 0.00 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ Vendored Modules                                │        │ 727.60 KiB │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ Total (112 modules)                             │        │ 994.79 KiB │
└─────────────────────────────────────────────────┴────────┴────────────┘
Total Upload: 1004.70 KiB / gzip: 216.42 KiB
Worker Startup Time: 1444 ms
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
env.AIDY_CROSS_MARKET_POLL_SECONDS ("3600")                        Environment Variable      

Uploaded aidy-signals-test (11.02 sec)
Deployed aidy-signals-test triggers (2.64 sec)
  https://aidy-signals-test.dannythehat2.workers.dev
  Consumer for aidy-capture-test
Current Version ID: cc490efc-3a57-4bba-97eb-494df1330b2f
```

## source-probe
```json
{"authentication": "none", "frequency": "daily_context", "observed_at": "2026-08-19T16:06:18.118934+00:00", "round_1": {"DTWEXBGS": {"observation_date": "2026-08-14", "payload_digest": "3a16cbaa00bf303b6ec7ad9db6237c7389ff3bff834a70d9fab09b11369adf69", "source": "fred_stlouisfed", "source_document_digest": "099b0ab4007d2060e319d5bef35d749a3bf397c5347c74703b8e9a626a99c2ae", "source_host": "fred.stlouisfed.org", "unit": "index_jan_2006_100", "value": "118.9028"}, "UST_NOMINAL_10Y": {"observation_date": "2026-08-18", "payload_digest": "6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb", "source": "us_treasury", "source_document_digest": "07b00736796f8dbc130ec883764e13a44f0e894489536c9f55dfe857ca984a55", "source_host": "home.treasury.gov", "unit": "percent", "value": "4.71"}, "UST_NOMINAL_2Y": {"observation_date": "2026-08-18", "payload_digest": "a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677", "source": "us_treasury", "source_document_digest": "07b00736796f8dbc130ec883764e13a44f0e894489536c9f55dfe857ca984a55", "source_host": "home.treasury.gov", "unit": "percent", "value": "4.19"}, "UST_REAL_10Y": {"observation_date": "2026-08-18", "payload_digest": "5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f", "source": "us_treasury", "source_document_digest": "3d1627cfcb258048eda6fd2211a13a35f3d12e8268b38fa115daf5d3415667ba", "source_host": "home.treasury.gov", "unit": "percent", "value": "2.41"}}, "round_2": {"DTWEXBGS": {"observation_date": "2026-08-14", "payload_digest": "3a16cbaa00bf303b6ec7ad9db6237c7389ff3bff834a70d9fab09b11369adf69", "source": "fred_stlouisfed", "source_document_digest": "099b0ab4007d2060e319d5bef35d749a3bf397c5347c74703b8e9a626a99c2ae", "source_host": "fred.stlouisfed.org", "unit": "index_jan_2006_100", "value": "118.9028"}, "UST_NOMINAL_10Y": {"observation_date": "2026-08-18", "payload_digest": "6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb", "source": "us_treasury", "source_document_digest": "07b00736796f8dbc130ec883764e13a44f0e894489536c9f55dfe857ca984a55", "source_host": "home.treasury.gov", "unit": "percent", "value": "4.71"}, "UST_NOMINAL_2Y": {"observation_date": "2026-08-18", "payload_digest": "a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677", "source": "us_treasury", "source_document_digest": "07b00736796f8dbc130ec883764e13a44f0e894489536c9f55dfe857ca984a55", "source_host": "home.treasury.gov", "unit": "percent", "value": "4.19"}, "UST_REAL_10Y": {"observation_date": "2026-08-18", "payload_digest": "5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f", "source": "us_treasury", "source_document_digest": "3d1627cfcb258048eda6fd2211a13a35f3d12e8268b38fa115daf5d3415667ba", "source_host": "home.treasury.gov", "unit": "percent", "value": "2.41"}}, "series": ["DTWEXBGS", "UST_NOMINAL_2Y", "UST_NOMINAL_10Y", "UST_REAL_10Y"], "status": "PASS"}

```

## health
```json
{"service": "aidy-signals", "status": "ok", "runtime": "cloudflare-workers", "environment": "test", "capture_enabled": true, "market_data_source": "gold_api", "market_data_ownership": "public_independent", "cross_market_source": "public_official_daily", "scheduler": "queue-consumer"}
```
