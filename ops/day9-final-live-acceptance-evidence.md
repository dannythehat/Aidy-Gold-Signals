# Day 9 final runtime-authoritative acceptance evidence

- Trigger commit: f283dd6d639ca2d3a3dd88dc36baba89b54027e3
- Observed at UTC: 2026-08-19T16:45:02Z
- Dependencies: PASS
- Code gate: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Source/PIT structural boundary: PASS
- GitHub-side source probe: PASS
- Credentials: PASS
- D1 migration: PASS
- Worker deployed: PASS
- Gold boundary health: PASS
- Two successive Worker source pulls: PASS
- D1 reconciliation: PASS
- R2 reconciliation: PASS
- BigQuery dependency: PASS
- BigQuery double-export + PIT as-of: PASS

## ruff
```text
All checks passed!
```

## pytest
```text
........................................................................ [ 53%]
..............................................................           [100%]
134 passed in 0.81s
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
│ aidy/cross_market.py                            │ python │ 8.44 KiB   │
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
│ aidy/fed_h10_dollar.py                          │ python │ 4.23 KiB   │
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
│ aidy_gold_signals.egg-info/SOURCES.txt          │ text   │ 1.89 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/dependency_links.txt │ text   │ 0.00 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/requires.txt         │ text   │ 0.08 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ aidy_gold_signals.egg-info/top_level.txt        │ text   │ 0.00 KiB   │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ Vendored Modules                                │        │ 727.60 KiB │
├─────────────────────────────────────────────────┼────────┼────────────┤
│ Total (113 modules)                             │        │ 998.68 KiB │
└─────────────────────────────────────────────────┴────────┴────────────┘
Total Upload: 1008.60 KiB / gzip: 217.79 KiB
Worker Startup Time: 1439 ms
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

Uploaded aidy-signals-test (8.35 sec)
Deployed aidy-signals-test triggers (2.14 sec)
  https://aidy-signals-test.dannythehat2.workers.dev
  Consumer for aidy-capture-test
Current Version ID: 29ee2fea-40dd-4cbd-b458-d98d4bbf6a4b
```

## github-source-probe
```json
{"authentication": "none", "frequency": "daily_context", "observed_at": "2026-08-19T16:41:41.387090+00:00", "round_1": {"DTWEXBGS": {"observation_date": "2026-08-14", "payload_digest": "83588bcb13b6561f83786fcfcad182797b0c32b7a99ee316ada3bd27ff821486", "source": "federal_reserve_h10", "source_document_digest": "0eeaeae35787a8cabd504c69227e4d8bbc327cf35d3a8e57f8a24234f98134ca", "source_host": "www.federalreserve.gov", "unit": "index_jan_2006_100", "value": "118.9028"}, "UST_NOMINAL_10Y": {"observation_date": "2026-08-18", "payload_digest": "6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb", "source": "us_treasury", "source_document_digest": "07b00736796f8dbc130ec883764e13a44f0e894489536c9f55dfe857ca984a55", "source_host": "home.treasury.gov", "unit": "percent", "value": "4.71"}, "UST_NOMINAL_2Y": {"observation_date": "2026-08-18", "payload_digest": "a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677", "source": "us_treasury", "source_document_digest": "07b00736796f8dbc130ec883764e13a44f0e894489536c9f55dfe857ca984a55", "source_host": "home.treasury.gov", "unit": "percent", "value": "4.19"}, "UST_REAL_10Y": {"observation_date": "2026-08-18", "payload_digest": "5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f", "source": "us_treasury", "source_document_digest": "3d1627cfcb258048eda6fd2211a13a35f3d12e8268b38fa115daf5d3415667ba", "source_host": "home.treasury.gov", "unit": "percent", "value": "2.41"}}, "round_2": {"DTWEXBGS": {"observation_date": "2026-08-14", "payload_digest": "83588bcb13b6561f83786fcfcad182797b0c32b7a99ee316ada3bd27ff821486", "source": "federal_reserve_h10", "source_document_digest": "0edefd1ee079837b1b5b2999d0a3d5442f81975b9fc197696947a5f651781f00", "source_host": "www.federalreserve.gov", "unit": "index_jan_2006_100", "value": "118.9028"}, "UST_NOMINAL_10Y": {"observation_date": "2026-08-18", "payload_digest": "6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb", "source": "us_treasury", "source_document_digest": "07b00736796f8dbc130ec883764e13a44f0e894489536c9f55dfe857ca984a55", "source_host": "home.treasury.gov", "unit": "percent", "value": "4.71"}, "UST_NOMINAL_2Y": {"observation_date": "2026-08-18", "payload_digest": "a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677", "source": "us_treasury", "source_document_digest": "07b00736796f8dbc130ec883764e13a44f0e894489536c9f55dfe857ca984a55", "source_host": "home.treasury.gov", "unit": "percent", "value": "4.19"}, "UST_REAL_10Y": {"observation_date": "2026-08-18", "payload_digest": "5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f", "source": "us_treasury", "source_document_digest": "3d1627cfcb258048eda6fd2211a13a35f3d12e8268b38fa115daf5d3415667ba", "source_host": "home.treasury.gov", "unit": "percent", "value": "2.41"}}, "series": ["DTWEXBGS", "UST_NOMINAL_2Y", "UST_NOMINAL_10Y", "UST_REAL_10Y"], "status": "PASS"}

```

## smoke1
```json
{"ok": true, "capture": {"sources_checked": 3, "sources_failed": 0, "observations_seen": 4, "observations_added": 1}, "archive": {"attempted": 1, "archived": 1, "failed": 0, "pending": 0}, "latest": {"DTWEXBGS": {"id": "c81f6a18-1fc5-41cd-b1d7-4075eae3b103", "source": "federal_reserve_h10", "series_id": "DTWEXBGS", "observation_date": "2026-08-14", "value": "118.9028", "unit": "index_jan_2006_100", "first_observed_at": "2026-08-19T16:42:25.043000+00:00", "revision_index": 1, "payload_digest": "83588bcb13b6561f83786fcfcad182797b0c32b7a99ee316ada3bd27ff821486", "archive_key": "cross-market/2026/08/19/federal_reserve_h10/DTWEXBGS/2026-08-14-20260819T164225.043000Z-83588bcb13b6561f83786fcfcad182797b0c32b7a99ee316ada3bd27ff821486.json"}, "UST_NOMINAL_10Y": {"id": "96c8946c-cda3-46e9-b971-fecd6da548e7", "source": "us_treasury", "series_id": "UST_NOMINAL_10Y", "observation_date": "2026-08-18", "value": "4.71", "unit": "percent", "first_observed_at": "2026-08-19T16:02:15.659000+00:00", "revision_index": 1, "payload_digest": "6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb", "archive_key": "cross-market/2026/08/19/us_treasury/UST_NOMINAL_10Y/2026-08-18-20260819T160215.659000Z-6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb.json"}, "UST_NOMINAL_2Y": {"id": "a2b6ef41-fbac-45e1-b8b2-71b9a1d5bce4", "source": "us_treasury", "series_id": "UST_NOMINAL_2Y", "observation_date": "2026-08-18", "value": "4.19", "unit": "percent", "first_observed_at": "2026-08-19T16:02:15.659000+00:00", "revision_index": 1, "payload_digest": "a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677", "archive_key": "cross-market/2026/08/19/us_treasury/UST_NOMINAL_2Y/2026-08-18-20260819T160215.659000Z-a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677.json"}, "UST_REAL_10Y": {"id": "361c3ac8-8189-4fdd-8704-325e5a56fde2", "source": "us_treasury", "series_id": "UST_REAL_10Y", "observation_date": "2026-08-18", "value": "2.41", "unit": "percent", "first_observed_at": "2026-08-19T16:02:16.548999+00:00", "revision_index": 1, "payload_digest": "5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f", "archive_key": "cross-market/2026/08/19/us_treasury/UST_REAL_10Y/2026-08-18-20260819T160216.548999Z-5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f.json"}}}
```

## smoke2
```json
{"ok": true, "capture": {"sources_checked": 3, "sources_failed": 0, "observations_seen": 4, "observations_added": 0}, "archive": {"attempted": 1, "archived": 1, "failed": 0, "pending": 0}, "latest": {"DTWEXBGS": {"id": "c81f6a18-1fc5-41cd-b1d7-4075eae3b103", "source": "federal_reserve_h10", "series_id": "DTWEXBGS", "observation_date": "2026-08-14", "value": "118.9028", "unit": "index_jan_2006_100", "first_observed_at": "2026-08-19T16:42:25.043000+00:00", "revision_index": 1, "payload_digest": "83588bcb13b6561f83786fcfcad182797b0c32b7a99ee316ada3bd27ff821486", "archive_key": "cross-market/2026/08/19/federal_reserve_h10/DTWEXBGS/2026-08-14-20260819T164225.043000Z-83588bcb13b6561f83786fcfcad182797b0c32b7a99ee316ada3bd27ff821486.json"}, "UST_NOMINAL_10Y": {"id": "96c8946c-cda3-46e9-b971-fecd6da548e7", "source": "us_treasury", "series_id": "UST_NOMINAL_10Y", "observation_date": "2026-08-18", "value": "4.71", "unit": "percent", "first_observed_at": "2026-08-19T16:02:15.659000+00:00", "revision_index": 1, "payload_digest": "6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb", "archive_key": "cross-market/2026/08/19/us_treasury/UST_NOMINAL_10Y/2026-08-18-20260819T160215.659000Z-6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb.json"}, "UST_NOMINAL_2Y": {"id": "a2b6ef41-fbac-45e1-b8b2-71b9a1d5bce4", "source": "us_treasury", "series_id": "UST_NOMINAL_2Y", "observation_date": "2026-08-18", "value": "4.19", "unit": "percent", "first_observed_at": "2026-08-19T16:02:15.659000+00:00", "revision_index": 1, "payload_digest": "a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677", "archive_key": "cross-market/2026/08/19/us_treasury/UST_NOMINAL_2Y/2026-08-18-20260819T160215.659000Z-a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677.json"}, "UST_REAL_10Y": {"id": "361c3ac8-8189-4fdd-8704-325e5a56fde2", "source": "us_treasury", "series_id": "UST_REAL_10Y", "observation_date": "2026-08-18", "value": "2.41", "unit": "percent", "first_observed_at": "2026-08-19T16:02:16.548999+00:00", "revision_index": 1, "payload_digest": "5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f", "archive_key": "cross-market/2026/08/19/us_treasury/UST_REAL_10Y/2026-08-18-20260819T160216.548999Z-5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f.json"}}}
```

## d1-groups
```json
[
  {
    "results": [
      {
        "source": "federal_reserve_h10",
        "series_id": "DTWEXBGS",
        "observation_date": "2026-08-14",
        "rows": 1,
        "payloads": 1,
        "max_revision": 1
      },
      {
        "source": "us_treasury",
        "series_id": "UST_NOMINAL_10Y",
        "observation_date": "2026-08-18",
        "rows": 1,
        "payloads": 1,
        "max_revision": 1
      },
      {
        "source": "us_treasury",
        "series_id": "UST_NOMINAL_2Y",
        "observation_date": "2026-08-18",
        "rows": 1,
        "payloads": 1,
        "max_revision": 1
      },
      {
        "source": "us_treasury",
        "series_id": "UST_REAL_10Y",
        "observation_date": "2026-08-18",
        "rows": 1,
        "payloads": 1,
        "max_revision": 1
      }
    ],
    "success": true,
    "meta": {
      "served_by": "v3-prod",
      "served_by_region": "WNAM",
      "served_by_colo": "SJC",
      "served_by_primary": true,
      "timings": {
        "sql_duration_ms": 0.8244
      },
      "duration": 0.8244,
      "changes": 0,
      "last_row_id": 3357,
      "changed_db": false,
      "size_after": 6860800,
      "rows_read": 8,
      "rows_written": 0,
      "total_attempts": 1
    }
  }
]

```

## d1-latest
```json
[
  {
    "results": [
      {
        "source": "federal_reserve_h10",
        "series_id": "DTWEXBGS",
        "observation_date": "2026-08-14",
        "value": "118.9028",
        "unit": "index_jan_2006_100",
        "first_observed_at": "2026-08-19T16:42:25.043000+00:00",
        "revision_index": 1,
        "payload_digest": "83588bcb13b6561f83786fcfcad182797b0c32b7a99ee316ada3bd27ff821486",
        "archive_key": "cross-market/2026/08/19/federal_reserve_h10/DTWEXBGS/2026-08-14-20260819T164225.043000Z-83588bcb13b6561f83786fcfcad182797b0c32b7a99ee316ada3bd27ff821486.json"
      },
      {
        "source": "us_treasury",
        "series_id": "UST_NOMINAL_10Y",
        "observation_date": "2026-08-18",
        "value": "4.71",
        "unit": "percent",
        "first_observed_at": "2026-08-19T16:02:15.659000+00:00",
        "revision_index": 1,
        "payload_digest": "6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb",
        "archive_key": "cross-market/2026/08/19/us_treasury/UST_NOMINAL_10Y/2026-08-18-20260819T160215.659000Z-6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb.json"
      },
      {
        "source": "us_treasury",
        "series_id": "UST_NOMINAL_2Y",
        "observation_date": "2026-08-18",
        "value": "4.19",
        "unit": "percent",
        "first_observed_at": "2026-08-19T16:02:15.659000+00:00",
        "revision_index": 1,
        "payload_digest": "a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677",
        "archive_key": "cross-market/2026/08/19/us_treasury/UST_NOMINAL_2Y/2026-08-18-20260819T160215.659000Z-a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677.json"
      },
      {
        "source": "us_treasury",
        "series_id": "UST_REAL_10Y",
        "observation_date": "2026-08-18",
        "value": "2.41",
        "unit": "percent",
        "first_observed_at": "2026-08-19T16:02:16.548999+00:00",
        "revision_index": 1,
        "payload_digest": "5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f",
        "archive_key": "cross-market/2026/08/19/us_treasury/UST_REAL_10Y/2026-08-18-20260819T160216.548999Z-5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f.json"
      }
    ],
    "success": true,
    "meta": {
      "served_by": "v3-prod",
      "served_by_region": "WNAM",
      "served_by_colo": "SJC",
      "served_by_primary": true,
      "timings": {
        "sql_duration_ms": 0.6641
      },
      "duration": 0.6641,
      "changes": 0,
      "last_row_id": 3357,
      "changed_db": false,
      "size_after": 6860800,
      "rows_read": 25,
      "rows_written": 0,
      "total_attempts": 1
    }
  }
]

```

## bigquery-export
```json
{"fact_identities": 1, "fact_rows": 1, "load_identity": "6da05d0534453ddc1e32f8670b7bb9a1a245f3b2d6de15a6a9c1c1ccf470ed6e", "load_job_id": "c24fc00e-9564-4236-b74d-55056137d073", "manifest_identities": 1, "manifest_load_job_id": "c6f43f3f-4329-4ea4-95f0-b500fe0b9260", "manifest_rows": 1, "observation_date": "2026-08-14", "ok": true, "series_id": "DTWEXBGS"}
{"fact_identities": 1, "fact_rows": 1, "load_identity": "6da05d0534453ddc1e32f8670b7bb9a1a245f3b2d6de15a6a9c1c1ccf470ed6e", "load_job_id": "6a49952f-4c53-42b6-853e-85db2c9e7e19", "manifest_identities": 1, "manifest_load_job_id": "e63fa1c5-0a8d-4c1a-b139-0c435c1c2ff2", "manifest_rows": 1, "observation_date": "2026-08-14", "ok": true, "series_id": "DTWEXBGS"}
{"fact_identities": 1, "fact_rows": 1, "load_identity": "05dd8e1e48433a63628375587c37a9eb4243d8b664b8277bd77bb7aced13184f", "load_job_id": "7eecca9c-8f87-48b6-b692-3da5138ea494", "manifest_identities": 1, "manifest_load_job_id": "6bfcd169-db72-42f5-91b9-58f87b290093", "manifest_rows": 1, "observation_date": "2026-08-18", "ok": true, "series_id": "UST_NOMINAL_10Y"}
{"fact_identities": 1, "fact_rows": 1, "load_identity": "05dd8e1e48433a63628375587c37a9eb4243d8b664b8277bd77bb7aced13184f", "load_job_id": "656ab338-2592-49b5-9142-19d39cecebe4", "manifest_identities": 1, "manifest_load_job_id": "56575d0f-a6db-44d8-a34d-bb77680ed246", "manifest_rows": 1, "observation_date": "2026-08-18", "ok": true, "series_id": "UST_NOMINAL_10Y"}
{"fact_identities": 1, "fact_rows": 1, "load_identity": "7c92ff5e86368ba382df7f5ec3611d60e7afb9b0997492d5cee2d791e9645df6", "load_job_id": "fe8ea451-949c-48aa-835a-7445be64d105", "manifest_identities": 1, "manifest_load_job_id": "bf5a3e37-15de-48f3-8f8b-941d0b7d90b6", "manifest_rows": 1, "observation_date": "2026-08-18", "ok": true, "series_id": "UST_NOMINAL_2Y"}
{"fact_identities": 1, "fact_rows": 1, "load_identity": "7c92ff5e86368ba382df7f5ec3611d60e7afb9b0997492d5cee2d791e9645df6", "load_job_id": "e6a21a05-1137-4369-94e7-3bfb0476fbd3", "manifest_identities": 1, "manifest_load_job_id": "0efa3990-2913-4886-b052-1748e1eacf11", "manifest_rows": 1, "observation_date": "2026-08-18", "ok": true, "series_id": "UST_NOMINAL_2Y"}
{"fact_identities": 1, "fact_rows": 1, "load_identity": "f80d3f50ea396eb05be9f512ca10045eebecd5e0d2e0939c0b98b2482ace5958", "load_job_id": "d0bde983-0101-4797-b251-ff4f821a0600", "manifest_identities": 1, "manifest_load_job_id": "1e4b6130-7a86-4845-85fa-fc3dce5bb476", "manifest_rows": 1, "observation_date": "2026-08-18", "ok": true, "series_id": "UST_REAL_10Y"}
{"fact_identities": 1, "fact_rows": 1, "load_identity": "f80d3f50ea396eb05be9f512ca10045eebecd5e0d2e0939c0b98b2482ace5958", "load_job_id": "f2897de1-9e4d-4a5c-8585-dcb0cd7eab7d", "manifest_identities": 1, "manifest_load_job_id": "aa8b93ad-f625-420b-b00d-8c7ca5a4df6d", "manifest_rows": 1, "observation_date": "2026-08-18", "ok": true, "series_id": "UST_REAL_10Y"}

```

## bigquery-asof
```json
{"as_of_utc": "2026-08-19T16:45:01.524673+00:00", "frequency": "daily_context", "query_version": "aidy_cross_market_asof_v1", "series": {"DTWEXBGS": {"fact": {"first_observed_at": "2026-08-19T16:42:25.043000+00:00", "observation_date": "2026-08-14", "revision_index": 1, "series_id": "DTWEXBGS", "source": "federal_reserve_h10", "source_url": "https://www.federalreserve.gov/releases/h10/current/default.htm", "unit": "index_jan_2006_100", "value": "118.9028"}, "observation_age_days": 5, "provenance": {"archive_key": "cross-market/2026/08/19/federal_reserve_h10/DTWEXBGS/2026-08-14-20260819T164225.043000Z-83588bcb13b6561f83786fcfcad182797b0c32b7a99ee316ada3bd27ff821486.json", "evidence_id": "c81f6a18-1fc5-41cd-b1d7-4075eae3b103", "load_identity": "6da05d0534453ddc1e32f8670b7bb9a1a245f3b2d6de15a6a9c1c1ccf470ed6e", "payload_digest": "83588bcb13b6561f83786fcfcad182797b0c32b7a99ee316ada3bd27ff821486", "source_document_digest": "5898de30a9bd29fde0ba70c34581e8c18ce37b2015c0f9c3c39fb1cbf6cfb1ee"}, "state": "known"}, "UST_NOMINAL_10Y": {"fact": {"first_observed_at": "2026-08-19T16:02:15.659000+00:00", "observation_date": "2026-08-18", "revision_index": 1, "series_id": "UST_NOMINAL_10Y", "source": "us_treasury", "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2026", "unit": "percent", "value": "4.71"}, "observation_age_days": 1, "provenance": {"archive_key": "cross-market/2026/08/19/us_treasury/UST_NOMINAL_10Y/2026-08-18-20260819T160215.659000Z-6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb.json", "evidence_id": "96c8946c-cda3-46e9-b971-fecd6da548e7", "load_identity": "05dd8e1e48433a63628375587c37a9eb4243d8b664b8277bd77bb7aced13184f", "payload_digest": "6deab068c787fa7da437432c40b875d430e81068bd26015636bb3702cb9d58bb", "source_document_digest": "07b00736796f8dbc130ec883764e13a44f0e894489536c9f55dfe857ca984a55"}, "state": "known"}, "UST_NOMINAL_2Y": {"fact": {"first_observed_at": "2026-08-19T16:02:15.659000+00:00", "observation_date": "2026-08-18", "revision_index": 1, "series_id": "UST_NOMINAL_2Y", "source": "us_treasury", "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2026", "unit": "percent", "value": "4.19"}, "observation_age_days": 1, "provenance": {"archive_key": "cross-market/2026/08/19/us_treasury/UST_NOMINAL_2Y/2026-08-18-20260819T160215.659000Z-a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677.json", "evidence_id": "a2b6ef41-fbac-45e1-b8b2-71b9a1d5bce4", "load_identity": "7c92ff5e86368ba382df7f5ec3611d60e7afb9b0997492d5cee2d791e9645df6", "payload_digest": "a0a8d755673c7658b77c1f1751862053aa9e52beb47f8d4592a7724512c7a677", "source_document_digest": "07b00736796f8dbc130ec883764e13a44f0e894489536c9f55dfe857ca984a55"}, "state": "known"}, "UST_REAL_10Y": {"fact": {"first_observed_at": "2026-08-19T16:02:16.548999+00:00", "observation_date": "2026-08-18", "revision_index": 1, "series_id": "UST_REAL_10Y", "source": "us_treasury", "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_real_yield_curve&field_tdr_date_value=2026", "unit": "percent", "value": "2.41"}, "observation_age_days": 1, "provenance": {"archive_key": "cross-market/2026/08/19/us_treasury/UST_REAL_10Y/2026-08-18-20260819T160216.548999Z-5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f.json", "evidence_id": "361c3ac8-8189-4fdd-8704-325e5a56fde2", "load_identity": "f80d3f50ea396eb05be9f512ca10045eebecd5e0d2e0939c0b98b2482ace5958", "payload_digest": "5b87f43bc3a9c2a1da91bfd5ec4e22e867dd67a2487f3c0c9799e60902d9a49f", "source_document_digest": "3d1627cfcb258048eda6fd2211a13a35f3d12e8268b38fa115daf5d3415667ba"}, "state": "known"}}}

```

## health
```json
{"service": "aidy-signals", "status": "ok", "runtime": "cloudflare-workers", "environment": "test", "capture_enabled": true, "market_data_source": "gold_api", "market_data_ownership": "public_independent", "cross_market_source": "public_official_daily", "scheduler": "queue-consumer"}
```
