# Day 4 BigQuery live-acceptance evidence

- Trigger commit: 2fd4a725ace3d20de19a02c26a9be74d7e2498aa
- Observed at UTC: 2026-08-19T11:25:02Z
- Dependencies: PASS
- Code gate: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Live-recorder/BigQuery import boundary: PASS
- Recorder health before export: PASS
- Credential preflight: PASS
- Genuine R2 snapshot retrieval: PASS
- BigQuery dependency: PASS
- R2 -> BigQuery repeated round-trip: PASS
- BigQuery-failure isolation from recorder: PASS
- R2 archive key: gold/snapshots/2026/08/19/20260819T112223.452999Z-ff131afc-45c9-4038-978a-69c3892fa611-c66e97aba2974c9bf9fe1ca44ee17ef699498a9aa5656cf1f4c75e0c9358d4f5.json
- R2 payload digest: c66e97aba2974c9bf9fe1ca44ee17ef699498a9aa5656cf1f4c75e0c9358d4f5
- R2 evidence ID: ff131afc-45c9-4038-978a-69c3892fa611

## ruff
```text
All checks passed!
```

## compile
```text
```

## pytest
```text
..............................................................           [100%]
62 passed in 0.57s
```

## expected-bigquery-failure
```text
DAY4_EXPORT_ERROR=RuntimeError:Missing AIDY_GCP_SERVICE_ACCOUNT_JSON.
Traceback (most recent call last):
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day4_export_r2_to_bigquery.py", line 471, in <module>
    raise SystemExit(main())
                     ~~~~^^
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day4_export_r2_to_bigquery.py", line 437, in main
    client = _client_from_env(args.project, args.location)
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day4_export_r2_to_bigquery.py", line 410, in _client_from_env
    raise RuntimeError("Missing AIDY_GCP_SERVICE_ACCOUNT_JSON.")
RuntimeError: Missing AIDY_GCP_SERVICE_ACCOUNT_JSON.
```

## health-before
```json
{"service": "aidy-signals", "status": "ok", "runtime": "cloudflare-workers", "environment": "test", "capture_enabled": true, "market_data_source": "gold_api", "market_data_ownership": "public_independent", "scheduler": "queue-consumer"}
```

## health-after-failure
```json
{"service": "aidy-signals", "status": "ok", "runtime": "cloudflare-workers", "environment": "test", "capture_enabled": true, "market_data_source": "gold_api", "market_data_ownership": "public_independent", "scheduler": "queue-consumer"}
```

## day4-export-first
```json
{"archive_keys": ["gold/snapshots/2026/08/19/20260819T112223.452999Z-ff131afc-45c9-4038-978a-69c3892fa611-c66e97aba2974c9bf9fe1ca44ee17ef699498a9aa5656cf1f4c75e0c9358d4f5.json"], "completed_at": "2026-08-19T11:24:34.778369+00:00", "dataset": "aidy_analytics_test", "load_identities": ["584cf33cabe983b15023548a977db9aa9a6a705e8a9347cbad8670b5647aa610"], "load_job_ids": ["bfe4fdc1-990f-4245-a040-e10a06b65d98", "b77d6583-4ec8-45d4-81ae-9f30dbcfd5ab"], "merge_job_ids": ["06d62f97-3509-4d27-9ad0-cbc73312b817", "01c4cf86-6652-447d-8817-b1141510a2b0"], "ok": true, "project": "aidy-signals", "query_bytes_processed": 1577, "reconciliation": {"export_manifest": {"expected": 1, "identities": 1, "rows": 1}, "market_snapshots": {"expected": 1, "identities": 1, "rows": 1}}, "records": 1, "run_id": "eb3d46c6-33f5-4dae-8469-015cfc254644", "source_files": ["/tmp/day4-r2-sample.json"], "started_at": "2026-08-19T11:24:04.544968+00:00"}

```

## day4-export-second
```json
{"archive_keys": ["gold/snapshots/2026/08/19/20260819T112223.452999Z-ff131afc-45c9-4038-978a-69c3892fa611-c66e97aba2974c9bf9fe1ca44ee17ef699498a9aa5656cf1f4c75e0c9358d4f5.json"], "completed_at": "2026-08-19T11:25:00.963681+00:00", "dataset": "aidy_analytics_test", "load_identities": ["584cf33cabe983b15023548a977db9aa9a6a705e8a9347cbad8670b5647aa610"], "load_job_ids": ["a744db2c-dc65-46c0-ae9f-5133708bbfc9", "0caf467a-0a16-43b3-acd0-0312d7fdaaaa"], "merge_job_ids": ["38511f23-79b6-42cb-ba5d-2404d9a4e295", "f2924ca6-7507-45b1-9242-5d57b622cbf6"], "ok": true, "project": "aidy-signals", "query_bytes_processed": 1709, "reconciliation": {"export_manifest": {"expected": 1, "identities": 1, "rows": 1}, "market_snapshots": {"expected": 1, "identities": 1, "rows": 1}}, "records": 1, "run_id": "5d39bbde-4d8d-483e-b2ff-4013feb7dc20", "source_files": ["/tmp/day4-r2-sample.json"], "started_at": "2026-08-19T11:24:37.990713+00:00"}

```
